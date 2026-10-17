"""
box_client.py — thin wrapper over the Box API (boxsdk v10, CCG auth) used by the agent.

Credentials and folder IDs come from the environment (see .env.example).

Operations:
  * whoami()                         -> str
  * list_files(folder_id)            -> [BoxFile]     (PDFs, up to two subfolders deep)
  * folder_summary(folder_id)        -> dict
  * download_bytes(file_id)          -> bytes
  * upload_pdf(name, data, folder)   -> file_id       (new version on name conflict)
  * add_comment(file_id, message)    -> comment_id
"""
from __future__ import annotations

import os
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

    def __init__(self):
        self.client_id = os.environ.get("BOX_CLIENT_ID")
        self.client_secret = os.environ.get("BOX_CLIENT_SECRET")
        self.enterprise_id = os.environ.get("BOX_ENTERPRISE_ID")
        self.contracts_folder = os.environ.get("BOX_CONTRACTS_FOLDER_ID", "0")
        self.reports_folder = os.environ.get("BOX_REPORTS_FOLDER_ID", "0")
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
            uploaded = client.uploads.upload_file_version(
                conflict["id"], UploadFileVersionAttributes(name=name), io.BytesIO(data))
        return uploaded.entries[0].id

    def add_comment(self, file_id: str, message: str) -> str:
        from box_sdk_gen import CreateCommentItem, CreateCommentItemTypeField
        comment = self._connect().comments.create_comment(
            message, CreateCommentItem(id=file_id, type=CreateCommentItemTypeField.FILE))
        return comment.id
