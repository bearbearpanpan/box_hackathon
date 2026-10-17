"""
envload.py — zero-dependency .env loader.

Loads KEY=VALUE lines from a .env file into os.environ so you can drop your
Box + AWS keys in one file and just run, with no `source .env` step and no
pip install. Values already set in the real environment win (so Lambda env
vars / exported shell vars are never overridden by the file).

Looked up from the repo root by default; call load_env() early in any entry
point. Safe to call multiple times.
"""
from __future__ import annotations

import os

_LOADED = False


def _find_env(start: str) -> str | None:
    """Walk up from `start` looking for a .env file (repo root)."""
    cur = os.path.abspath(start)
    for _ in range(6):
        candidate = os.path.join(cur, ".env")
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return None


def load_env(path: str | None = None, override: bool = False) -> bool:
    """
    Load .env into os.environ. Returns True if a file was found and read.
    Real environment variables take precedence unless override=True.
    """
    global _LOADED
    if _LOADED and path is None:
        return True

    env_path = path or _find_env(os.path.dirname(os.path.abspath(__file__)))
    if not env_path or not os.path.isfile(env_path):
        return False

    with open(env_path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = val

    if path is None:
        _LOADED = True
    return True
