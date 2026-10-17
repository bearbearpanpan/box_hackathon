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
import logging
from dataclasses import dataclass
from typing import List, Optional

from telemetry import get_logger, log_event, timed, emit_metric

_log = get_logger("reality_check.box")


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
        # Log the connection (never the secret) so a live vs. misconfigured
        # deployment is visible in CloudWatch.
        log_event(_log, "box.connect", use_box_ai=self.use_box_ai,
                  contracts_folder=self.contracts_folder,
                  reports_folder=self.reports_folder)
        return self._client

    def whoami(self) -> str:
        """Login of the user the token acts as (the CCG service account)."""
        me = self._connect().users.get_user_me()
        return f"{me.name} <{me.login}>"

    # ---- file operations ----------------------------------------------------
    def list_contracts(self, folder_id: Optional[str] = None) -> List[BoxFile]:
        client = self._connect()
        fid = folder_id or self.contracts_folder
        with timed(_log, "box.list_contracts", folder_id=fid) as span:
            items = client.folders.get_folder_items(fid, limit=1000).entries or []
            files = [BoxFile(id=i.id, name=i.name) for i in items
                     if i.type == "file" and i.name.lower().endswith(".pdf")]
            span["count"] = len(files)
        return files

    def list_files(self, folder_id: str, ext: str = ".pdf", depth: int = 2) -> List[BoxFile]:
        items = self._connect().folders.get_folder_items(folder_id, limit=1000).entries or []
        out = []
        for i in items:
            if i.type == "file" and i.name.lower().endswith(ext):
                out.append(BoxFile(id=i.id, name=i.name))
            elif i.type == "folder" and depth > 0:
                out.extend(self.list_files(i.id, ext, depth - 1))
        return out

    def folder_summary(self, folder_id: str) -> dict:
        client = self._connect()
        folder = client.folders.get_folder_by_id(folder_id)
        items = client.folders.get_folder_items(folder_id, limit=1000).entries or []
        return {"id": folder_id, "name": folder.name,
                "items": [f"{getattr(i.type, 'value', i.type)}: {i.name}" for i in items]}

    def download_bytes(self, file_id: str) -> bytes:
        return self._connect().downloads.download_file(file_id).read()

    def ensure_folder(self, name: str, parent_id: str) -> str:
        from box_sdk_gen import BoxAPIError, CreateFolderParent
        client = self._connect()
        try:
            return client.folders.create_folder(name, CreateFolderParent(id=parent_id)).id
        except BoxAPIError as exc:
            conflicts = (exc.response_info.context_info or {}).get("conflicts") or []
            if isinstance(conflicts, dict):
                conflicts = [conflicts]
            if exc.response_info.status_code != 409 or not conflicts:
                raise
            return conflicts[0]["id"]

    def download_text(self, file_id: str) -> str:
        """Download a file's bytes. (PDF text parsing is done by the caller /
        Box AI; this returns raw bytes decoded best-effort for text docs.)"""
        client = self._connect()
        with timed(_log, "box.download_text", file_id=file_id) as span:
            content = client.downloads.download_file(file_id).read()
            span["bytes"] = len(content)
            try:
                return content.decode("utf-8")
            except Exception:
                # Non-UTF-8 content is expected for some docs; record that we
                # fell back rather than failing, so it's not silent.
                log_event(_log, "box.download_text.decode_fallback", file_id=file_id)
                return content.decode("latin-1", "replace")

    def upload_pdf(self, name: str, data: bytes, folder_id: Optional[str] = None) -> str:
        from box_sdk_gen import (
            BoxAPIError,
            UploadFileAttributes,
            UploadFileAttributesParentField,
            UploadFileVersionAttributes,
        )
        client = self._connect()
        fid = folder_id or self.reports_folder
        import io
        with timed(_log, "box.upload_pdf", folder_id=fid, name=name,
                   bytes=len(data)) as span:
            try:
                uploaded = client.uploads.upload_file(
                    UploadFileAttributes(name=name, parent=UploadFileAttributesParentField(id=fid)),
                    io.BytesIO(data),
                )
            except BoxAPIError as exc:
                # same name already in the folder (e.g. a re-run) -> upload a new version
                conflict = (exc.response_info.context_info or {}).get("conflicts") or {}
                if exc.response_info.status_code != 409 or not conflict.get("id"):
                    raise
                log_event(_log, "box.upload_pdf.new_version", folder_id=fid,
                          name=name, existing_file_id=conflict["id"])
                uploaded = client.uploads.upload_file_version(
                    conflict["id"], UploadFileVersionAttributes(name=name), io.BytesIO(data))
            file_id = uploaded.entries[0].id
            span["file_id"] = file_id
        return file_id

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
            log_event(_log, "box.write_metadata", file_id=file_id,
                      template=template, mode="create")
        except BoxAPIError as exc:
            if exc.response_info.status_code != 409:
                raise
            # already exists -> update. Log at DEBUG (the expected path for
            # existing metadata) so it's observable, not silent.
            log_event(_log, "box.write_metadata.exists_updating",
                      level=logging.DEBUG, file_id=file_id, template=template)
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
        from box_sdk_gen import AiItemAsk, AiItemAskTypeField, CreateAiAskMode
        client = self._connect()
        items = [AiItemAsk(id=fid, type=AiItemAskTypeField.FILE) for fid in file_ids]
        ask_mode = (CreateAiAskMode.SINGLE_ITEM_QA if len(file_ids) == 1
                    else CreateAiAskMode.MULTIPLE_ITEM_QA)
        # Box AI is the slowest external hop (one call per contract). Time every
        # call and emit a latency metric so p99 and throttling are visible.
        with timed(_log, "box.ai_ask", request_mode=mode,
                   file_count=len(file_ids)) as span:
            resp = client.ai.create_ai_ask(ask_mode, prompt, items)
            answer = resp.answer if resp else ""
            span["answer_len"] = len(answer)
            emit_metric("BoxAiCall", 1, "Count", mode=str(ask_mode))
        return answer

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
            md = json.loads(raw[start : end + 1])
            log_event(_log, "box.extract_metadata", file_id=file_id,
                      field_count=len(md))
            return md
        except Exception as exc:
            # Degrading to {} is intentional (callers handle it), but it was
            # previously silent — a run full of empty metadata would look fine.
            # Log a warning and count it so extraction failures are visible.
            log_event(_log, "box.extract_metadata.parse_failed",
                      level=logging.WARNING, file_id=file_id, error=str(exc))
            emit_metric("BoxExtractParseFailure", 1, "Count")
            return {}
