from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "agent", "lambda", "tools"))
sys.path.insert(0, os.path.join(ROOT, "box"))

import envload  # noqa: E402

envload.load_env()

from box_client import BoxClient  # noqa: E402

UPLOAD = os.path.join(ROOT, "docs", "box_upload")


def set_env(key: str, value: str) -> None:
    path = os.path.join(ROOT, ".env")
    text = open(path).read() if os.path.isfile(path) else ""
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, re.M):
        text = re.sub(rf"^{key}=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    os.environ[key] = value


def upload_dir(box: BoxClient, sub: str, folder_id: str, only: list | None = None) -> None:
    for name in sorted(os.listdir(os.path.join(UPLOAD, sub))):
        if not name.endswith(".pdf") or (only and name not in only):
            continue
        with open(os.path.join(UPLOAD, sub, name), "rb") as fh:
            file_id = box.upload_pdf(name, fh.read(), folder_id=folder_id)
        print(f"  uploaded {name} -> https://app.box.com/file/{file_id}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Create Evidence + Contracts for Review folders inside the contracts folder in Box and upload the demo docs.")
    ap.add_argument("--with-v2", action="store_true", help="also upload the revised v2 contract")
    args = ap.parse_args()

    box = BoxClient()
    print(f"Box user: {box.whoami()}")
    parent = os.environ["BOX_CONTRACTS_FOLDER_ID"]
    evidence = box.ensure_folder("Evidence", parent)
    contracts = box.ensure_folder("Contracts for Review", parent)
    set_env("BOX_EVIDENCE_FOLDER_ID", evidence)
    set_env("BOX_REVIEW_CONTRACTS_FOLDER_ID", contracts)
    print(f"Evidence folder: https://app.box.com/folder/{evidence}")
    upload_dir(box, "evidence", evidence)
    print(f"Contracts for Review folder: https://app.box.com/folder/{contracts}")
    only = None if args.with_v2 else ["Northstar-Archive-Migration-Agreement.pdf"]
    upload_dir(box, "contracts", contracts, only)
    print("Folder IDs written to .env. Next: python3 agent/local_agent.py --list")


if __name__ == "__main__":
    main()
