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
    through the official `boxsdk` v10+ (`box_sdk_gen` module). If that package isn't installed yet (e.g. in
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
            from box_sdk_gen import BoxClient as _SdkClient, BoxCCGAuth, CCGConfig  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on install
            raise BoxConfigError(
                "The 'boxsdk' package (v10+, imported as box_sdk_gen) is required for "
                "live Box calls. Install it with `pip install 'boxsdk>=10'` and set Box credentials."
            ) from exc

        client_id = _require("BOX_CLIENT_ID")
        client_secret = _require("BOX_CLIENT_SECRET")
        if client_id == client_secret:
            raise BoxConfigError(
                "BOX_CLIENT_SECRET is identical to BOX_CLIENT_ID. Copy the Client Secret "
                "from Developer Console -> your app -> Configuration -> OAuth 2.0 Credentials."
            )
        auth = BoxCCGAuth(
            CCGConfig(
                client_id=client_id,
                client_secret=client_secret,
                enterprise_id=_require("BOX_ENTERPRISE_ID"),
            )
        )
        self._client = _SdkClient(auth=auth)
        return self._client

    def whoami(self) -> str:
        """Login of the user the token acts as (the CCG service account)."""
        me = self._connect().users.get_user_me()
        return f"{me.name} <{me.login}>"

    # ---- file operations ----------------------------------------------------
    def list_contracts(self, folder_id: Optional[str] = None) -> List[BoxFile]:
        client = self._connect()
        fid = folder_id or self.contracts_folder
        items = client.folders.get_folder_items(fid, limit=1000).entries or []
        return [BoxFile(id=i.id, name=i.name) for i in items
                if i.type == "file" and i.name.lower().endswith(".pdf")]

    def download_text(self, file_id: str) -> str:
        """Download a file's bytes. (PDF text parsing is done by the caller /
        Box AI; this returns raw bytes decoded best-effort for text docs.)"""
        client = self._connect()
        content = client.downloads.download_file(file_id).read()
        try:
            return content.decode("utf-8")
        except Exception:
            return content.decode("latin-1", "replace")

    def upload_pdf(self, name: str, data: bytes, folder_id: Optional[str] = None) -> str:
        from box_sdk_gen import UploadFileAttributes, UploadFileAttributesParentField
        client = self._connect()
        fid = folder_id or self.reports_folder
        import io
        uploaded = client.uploads.upload_file(
            UploadFileAttributes(name=name, parent=UploadFileAttributesParentField(id=fid)),
            io.BytesIO(data),
        )
        return uploaded.entries[0].id

    def write_metadata(self, file_id: str, data: dict, template: str = "properties") -> None:
        """Write free-form key/values to the file's global/properties metadata
        (works on every Box plan; no enterprise template needed)."""
        from box_sdk_gen import (
            BoxAPIError,
            CreateFileMetadataByIdScope,
            UpdateFileMetadataByIdScope,
            UpdateFileMetadataByIdRequestBody,
            UpdateFileMetadataByIdRequestBodyOpField,
        )
        client = self._connect()
        data = {k: ("" if v is None else v if isinstance(v, (str, int, float)) else str(v))
                for k, v in data.items()}
        try:
            client.file_metadata.create_file_metadata_by_id(
                file_id, CreateFileMetadataByIdScope.GLOBAL, template, data)
        except BoxAPIError as exc:
            if exc.response_info.status_code != 409:
                raise
            # already exists -> update
            ops = [UpdateFileMetadataByIdRequestBody(
                       op=UpdateFileMetadataByIdRequestBodyOpField.ADD, path=f"/{k}", value=v)
                   for k, v in data.items()]
            client.file_metadata.update_file_metadata_by_id(
                file_id, UpdateFileMetadataByIdScope.GLOBAL, template, ops)

    def create_review_task(self, file_id: str, message: str) -> str:
        from box_sdk_gen import CreateTaskItem, CreateTaskItemTypeField, CreateTaskAction
        task = self._connect().tasks.create_task(
            CreateTaskItem(id=file_id, type=CreateTaskItemTypeField.FILE),
            action=CreateTaskAction.REVIEW,
            message=message,
        )
        return task.id

    # ---- Box AI -------------------------------------------------------------
    def _box_ai_request(self, mode: str, prompt: str, file_ids: List[str]) -> str:
        """
        Single seam for Box AI. `mode` is 'ask' or 'extract'. Returns raw text.
        """
        from box_sdk_gen import AiItemAsk, CreateAiAskMode
        client = self._connect()
        items = [AiItemAsk(id=fid) for fid in file_ids]
        ask_mode = (CreateAiAskMode.SINGLE_ITEM_QA if len(file_ids) == 1
                    else CreateAiAskMode.MULTIPLE_ITEM_QA)
        resp = client.ai.create_ai_ask(ask_mode, prompt, items)
        return resp.answer if resp else ""

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
