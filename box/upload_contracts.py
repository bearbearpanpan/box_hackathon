"""
upload_contracts.py — one-time uploader to seed Box with the contract corpus.

Creates (or reuses) a folder owned by the CCG service account, uploads every
data/contracts/*.pdf into it (skipping files already present so re-runs are
safe), and prints the folder id to drop into BOX_CONTRACTS_FOLDER_ID.

Usage:
    set -a && source .env && set +a
    python3 box/upload_contracts.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from box_client import BoxClient  # noqa: E402

CONTRACTS_DIR = os.path.join(ROOT, "data", "contracts")
CONTRACTS_FOLDER_NAME = "reality-check-contracts"
REPORTS_FOLDER_NAME = "reality-check-reports"


def _find_or_create_folder(client, parent_id: str, name: str) -> str:
    """Return id of a child folder named `name` under `parent_id`, creating it if absent."""
    for item in client.folder(parent_id).get_items():
        if item.type == "folder" and item.name == name:
            return item.id
    created = client.folder(parent_id).create_subfolder(name)
    return created.id


def main() -> int:
    client = BoxClient()._connect()

    contracts_id = _find_or_create_folder(client, "0", CONTRACTS_FOLDER_NAME)
    reports_id = _find_or_create_folder(client, "0", REPORTS_FOLDER_NAME)
    print(f"contracts folder: {CONTRACTS_FOLDER_NAME} -> id {contracts_id}")
    print(f"reports folder  : {REPORTS_FOLDER_NAME} -> id {reports_id}")

    # names already in the contracts folder (so re-runs skip existing uploads)
    existing = {
        item.name
        for item in client.folder(contracts_id).get_items()
        if item.type == "file"
    }

    pdfs = sorted(f for f in os.listdir(CONTRACTS_DIR) if f.lower().endswith(".pdf"))
    uploaded = skipped = 0
    for i, name in enumerate(pdfs, 1):
        if name in existing:
            skipped += 1
            continue
        path = os.path.join(CONTRACTS_DIR, name)
        with open(path, "rb") as fh:
            client.folder(contracts_id).upload_stream(fh, name)
        uploaded += 1
        if uploaded % 10 == 0:
            print(f"  uploaded {uploaded} (at {name}, {i}/{len(pdfs)})")

    print(f"\nDone. uploaded={uploaded}  skipped(existing)={skipped}  total_local={len(pdfs)}")
    print("\nAdd these to your .env:")
    print(f"  BOX_CONTRACTS_FOLDER_ID={contracts_id}")
    print(f"  BOX_REPORTS_FOLDER_ID={reports_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
