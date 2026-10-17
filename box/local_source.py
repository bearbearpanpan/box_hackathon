"""
local_source.py — offline stand-in for BoxClient.

Lets the entire Read -> Check -> Report pipeline run and be demoed before Box
or Bedrock credentials exist, by reading the generated manifest.json instead of
calling Box. Same method surface as the parts of BoxClient the tools use, so
tools can accept either object (duck typing).

Switch between them with get_source() which checks whether Box creds are set.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from box_client import BoxFile  # reuse the dataclass


class LocalSource:
    def __init__(self, manifest_path: Optional[str] = None):
        here = os.path.dirname(os.path.abspath(__file__))
        default = os.path.join(here, "..", "data", "contracts", "manifest.json")
        self.manifest_path = os.path.abspath(manifest_path or default)
        with open(self.manifest_path) as fh:
            self._data = json.load(fh)
        self._by_id = {c["contract_id"]: c for c in self._data["contracts"]}

    def list_contracts(self, folder_id: Optional[str] = None) -> List[BoxFile]:
        return [BoxFile(id=c["contract_id"], name=f"{c['contract_id']}.pdf")
                for c in self._data["contracts"]]

    def extract_metadata(self, file_id: str) -> dict:
        c = self._by_id.get(file_id, {})
        # mirror the exact keys the Box AI path returns
        return {
            "customer": c.get("customer"),
            "vertical": c.get("vertical"),
            "region": c.get("region"),
            "signed_quarter": c.get("signed_quarter"),
            "has_hardware": c.get("has_hardware"),
            "hw_vendor": c.get("hw_vendor"),
            "sla_tier": c.get("sla_tier"),
            "discount_pct": c.get("discount_pct"),
            "tcv": c.get("tcv"),
            "promised_days": c.get("promised_days"),
            "actual_days": c.get("actual_days"),
        }

    def full_record(self, file_id: str) -> dict:
        return self._by_id.get(file_id, {})

    def all_records(self) -> List[dict]:
        return list(self._data["contracts"])

    def ai_ask(self, file_id: str, prompt: str) -> str:
        return ("[local fallback] Box AI is not configured; returning structured "
                "metadata only. Set Box credentials to enable free-form Q&A.")

    def upload_pdf(self, name: str, data: bytes, folder_id: Optional[str] = None) -> str:
        here = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(here, "..", "data", "reports")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def write_metadata(self, file_id: str, data: dict, template: str = "realityCheck") -> None:
        pass  # no-op locally


def get_source():
    """Return a live BoxClient if Box creds are set, else the local fallback."""
    if os.environ.get("BOX_CLIENT_ID") and os.environ.get("BOX_CLIENT_SECRET"):
        from box_client import BoxClient
        return BoxClient()
    return LocalSource()
