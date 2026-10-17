"""
prime_cache.py — extract every contract's metadata via Box AI once, and cache it.

The live history loader calls Box AI once per contract. With 100 docs that's
100 sequential AI calls (minutes) on every run. This script does that extraction
a single time and writes the results to data/contracts/box_cache.json, keyed by
contract_id. handler._history() loads that cache instead of re-extracting.

Safe to re-run: by default it only extracts contracts missing from the cache,
so you can resume if it's interrupted. Pass --force to re-extract everything.

Usage:
    set -a && source .env && set +a
    python3 box/prime_cache.py            # fill in whatever's missing
    python3 box/prime_cache.py --force    # re-extract all 100
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

from box_client import BoxClient  # noqa: E402

CACHE_PATH = os.path.join(ROOT, "data", "contracts", "box_cache.json")


def main() -> int:
    force = "--force" in sys.argv
    client = BoxClient()

    cache: dict = {}
    if os.path.exists(CACHE_PATH) and not force:
        with open(CACHE_PATH) as fh:
            cache = json.load(fh)
        print(f"loaded existing cache: {len(cache)} records")

    files = client.list_contracts()
    print(f"contracts in Box: {len(files)}")

    done = 0
    for i, f in enumerate(files, 1):
        cid = f.name.rsplit(".", 1)[0]
        if cid in cache and not force:
            continue
        md = client.extract_metadata(f.id)
        md["contract_id"] = cid
        md["_box_file_id"] = f.id
        cache[cid] = md
        done += 1
        if done % 10 == 0:
            print(f"  extracted {done} (at {cid}, {i}/{len(files)})")
            # checkpoint so an interruption doesn't lose progress
            with open(CACHE_PATH, "w") as fh:
                json.dump(cache, fh, indent=2)

    with open(CACHE_PATH, "w") as fh:
        json.dump(cache, fh, indent=2)

    print(f"\nDone. newly_extracted={done}  cache_total={len(cache)}")
    print(f"cache written to {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
