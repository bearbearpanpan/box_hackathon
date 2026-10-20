#!/usr/bin/env python3
"""
Generate a CycloneDX SBOM (sbom.json) for Reality Check.

Dependency-free on purpose: the project avoids third-party packages where it
can, and this must run in a bare pre-commit hook as well as in CI. It reads the
declared runtime dependencies from requirements.txt and emits a
valid CycloneDX 1.5 JSON document at the repo root.

Usage:
    python3 scripts/generate_sbom.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO_ROOT / "requirements.txt"
OUTPUT = REPO_ROOT / "sbom.json"

# name (op) version  e.g.  boto3>=1.34.0 , boxsdk==3.9.0
_REQ_RE = re.compile(r"^([A-Za-z0-9_.\-]+)\s*([<>=!~]=?)?\s*([0-9A-Za-z.\-]+)?")


def parse_requirements(path: Path) -> list[dict]:
    components: list[dict] = []
    if not path.exists():
        return components
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _REQ_RE.match(line)
        if not m:
            continue
        name, op, version = m.group(1), m.group(2) or "", m.group(3) or ""
        components.append(
            {
                "type": "library",
                "name": name,
                # Record the declared constraint; keep raw version if present.
                "version": version or "unspecified",
                "purl": f"pkg:pypi/{name.lower()}" + (f"@{version}" if version else ""),
                "properties": [
                    {"name": "constraint", "value": f"{op}{version}".strip() or "any"},
                ],
            }
        )
    return components


def build_sbom(components: list[dict]) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    # Deterministic serial based on component set so unchanged deps -> no diff
    # noise beyond the timestamp (which we keep stable per content below).
    digest = hashlib.sha256(
        json.dumps(components, sort_keys=True).encode("utf-8")
    ).hexdigest()
    serial = uuid.uuid5(uuid.NAMESPACE_URL, f"reality-check-sbom:{digest}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "timestamp": now,
            "tools": [
                {
                    "vendor": "Reality Check",
                    "name": "generate_sbom.py",
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "name": "reality-check",
                "description": "AWS Bedrock agent that reviews tech-sales contracts from Box.",
                "licenses": [{"license": {"id": "MIT"}}],
            },
        },
        "components": components,
    }


def main() -> int:
    components = parse_requirements(REQUIREMENTS)
    sbom = build_sbom(components)

    # Keep the timestamp out of the committed diff unless deps changed: if the
    # existing file has the same components, preserve its timestamp.
    if OUTPUT.exists():
        try:
            prev = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if prev.get("components") == components:
                sbom["metadata"]["timestamp"] = prev["metadata"]["timestamp"]
                sbom["serialNumber"] = prev["serialNumber"]
        except (json.JSONDecodeError, KeyError):
            pass

    OUTPUT.write_text(json.dumps(sbom, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(components)} components).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
