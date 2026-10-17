"""
box_client.py — thin wrapper over the Box API used by the agent tools.

Design goals:
  * Credentials come from the environment (see .env.example). Nothing secret
    is hard-coded, and the module imports cleanly even with no keys set, so the
    rest of the scaffold can be built/tested before keys are dropped in.
  * One place to swap between the real Box SDK and a local fallback. When the
    `boxsdk` package and credentials are present we use the real API; otherwise
    calls raise a clear, actionable error (or use the local manifest in dev).

Primary operations the agent needs:
  * list_contracts()                 -> [BoxFile]
  * download_text(file_id)           -> str          (contract text)
  * extract_metadata(file_id)        -> dict          (via Box AI)
  * ai_ask(file_id, prompt)          -> str           (Box AI Q&A over a doc)
  * upload_pdf(folder_id, name, b)   -> file_id
  * write_metadata(file_id, data)    -> None

The Box AI calls assume an enterprise with Box AI enabled. Where the exact
request shape differs by Box plan, the single `_box_ai_request` method is the
seam to adjust.
"""
from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class BoxFile:
    id: str
    name: str


class BoxConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise BoxConfigError(
            f"Missing required env var {name}. Copy .env.example to .env and fill it in."
        )
    return val


class BoxClient:
    """
    Wraps Box Server auth (Client Credentials Grant). The real network calls go
    through the official `boxsdk`. If that package isn't installed yet (e.g. in
    the offline build sandbox), the client still constructs; it only fails when
    a method that needs the network is actually called.
    """

    def __init__(self, use_box_ai: Optional[bool] = None):
        self.client_id = os.environ.get("BOX_CLIENT_ID")
        self.client_secret = os.environ.get("BOX_CLIENT_SECRET")
        self.enterprise_id = os.environ.get("BOX_ENTERPRISE_ID")
        self.contracts_folder = os.environ.get("BOX_CONTRACTS_FOLDER_ID", "0")
        self.reports_folder = os.environ.get("BOX_REPORTS_FOLDER_ID", "0")
        self.use_box_ai = (
            use_box_ai
            if use_box_ai is not None
            else os.environ.get("USE_BOX_AI", "true").lower() == "true"
        )
        self._client = None  # lazily created boxsdk client

    # ---- connection ---------------------------------------------------------
    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            from boxsdk import Client, CCGAuth  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on install
            raise BoxConfigError(
                "The 'boxsdk' package is required for live Box calls. "
                "Install it with `pip install boxsdk` and set Box credentials."
            ) from exc

        token = os.environ.get("BOX_DEVELOPER_TOKEN")
        if token:
            from boxsdk import OAuth2  # type: ignore
            auth = OAuth2(client_id=self.client_id, client_secret=self.client_secret, access_token=token)
            self._client = Client(auth)
            return self._client

        auth = CCGAuth(
            client_id=_require("BOX_CLIENT_ID"),
            client_secret=_require("BOX_CLIENT_SECRET"),
            enterprise_id=_require("BOX_ENTERPRISE_ID"),
        )
        self._client = Client(auth)
        return self._client

    # ---- file operations ----------------------------------------------------
    def list_contracts(self, folder_id: Optional[str] = None) -> List[BoxFile]:
        client = self._connect()
        fid = folder_id or self.contracts_folder
        items = client.folder(fid).get_items()
        return [BoxFile(id=i.id, name=i.name) for i in items if i.name.lower().endswith(".pdf")]

    def list_files(self, folder_id: str, ext: str = ".pdf") -> List[BoxFile]:
        client = self._connect()
        items = client.folder(folder_id).get_items()
        return [BoxFile(id=i.id, name=i.name) for i in items if i.type == "file" and i.name.lower().endswith(ext)]

    def download_bytes(self, file_id: str) -> bytes:
        return self._connect().file(file_id).content()

    def download_text(self, file_id: str) -> str:
        """Download a file's bytes. (PDF text parsing is done by the caller /
        Box AI; this returns raw bytes decoded best-effort for text docs.)"""
        client = self._connect()
        content = client.file(file_id).content()
        try:
            return content.decode("utf-8")
        except Exception:
            return content.decode("latin-1", "replace")

    def upload_pdf(self, name: str, data: bytes, folder_id: Optional[str] = None) -> str:
        client = self._connect()
        fid = folder_id or self.reports_folder
        import io
        uploaded = client.folder(fid).upload_stream(io.BytesIO(data), name)
        return uploaded.id

    def write_metadata(self, file_id: str, data: dict, template: str = "realityCheck") -> None:
        client = self._connect()
        f = client.file(file_id)
        try:
            f.metadata("enterprise", template).create(data)
        except Exception:
            # already exists -> update
            ops = [{"op": "replace", "path": f"/{k}", "value": v} for k, v in data.items()]
            f.metadata("enterprise", template).update(ops)

    # ---- Box AI -------------------------------------------------------------
    def _box_ai_request(self, mode: str, prompt: str, file_ids: List[str]) -> str:
        """
        Single seam for Box AI. `mode` is 'ask' or 'extract'. Returns raw text.
        Uses the Box AI endpoint via the SDK's generic API session so this keeps
        working across SDK minor versions.
        """
        client = self._connect()
        items = [{"id": fid, "type": "file"} for fid in file_ids]
        body = {
            "mode": "single_item_qa" if len(file_ids) == 1 else "multiple_item_qa",
            "prompt": prompt,
            "items": items,
        }
        url = "https://api.box.com/2.0/ai/ask"
        resp = client.make_request("POST", url, data=json.dumps(body))
        payload = resp.json()
        return payload.get("answer", "")

    def ai_ask(self, file_id: str, prompt: str) -> str:
        if not self.use_box_ai:
            raise BoxConfigError("USE_BOX_AI is false; enable it to call Box AI.")
        return self._box_ai_request("ask", prompt, [file_id])

    def extract_metadata(self, file_id: str) -> dict:
        """
        Ask Box AI to pull the structured fields we care about from a contract.
        Returns a dict matching the RULES.md metadata schema. Falls back to an
        empty dict on parse failure so callers can degrade gracefully.
        """
        prompt = (
            "Extract the following fields from this tech-sales contract and "
            "return ONLY compact JSON with these keys: customer, vertical, "
            "region, signed_quarter, has_hardware (boolean), hw_vendor, "
            "sla_tier, discount_pct (number), tcv (number), promised_days "
            "(number), actual_days (number if present else null). "
            "Use null for anything not stated."
        )
        raw = self.ai_ask(file_id, prompt)
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            return json.loads(raw[start : end + 1])
        except Exception:
            return {}
