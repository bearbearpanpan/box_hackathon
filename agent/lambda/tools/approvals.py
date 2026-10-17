"""
approvals.py — human-in-the-loop review store.

When the workflow reaches "needs human approval," it doesn't just stop — it
creates a *review package*: the draft, the risks, the escalations, and the exact
changes it wants a human to sign off on. A reviewer then opens that package and
resolves it (approve / reject / request-changes). The workflow resumes from the
decision.

Storage is a JSON file per review under data/reviews/ so the state survives
across separate tool invocations (a real reviewer acts minutes/hours later) and
works fully offline. In production this maps to a Box task + metadata, or a
ticket; the interface here is deliberately the same shape.

Lifecycle:
    PENDING_REVIEW  --approve-->          APPROVED
                    --reject-->           REJECTED
                    --request_changes-->  CHANGES_REQUESTED
"""
from __future__ import annotations

import os
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW_DIR = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "data", "reviews"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_review_id(review_id: str) -> str:
    """review_id can be caller-supplied (create_review accepts one, and
    get/resolve take it from params), so reject anything that could traverse
    outside REVIEW_DIR. Allow only the id charset we actually generate."""
    rid = str(review_id)
    if not rid or rid in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._-]+", rid):
        raise ValueError(f"invalid review_id: {review_id!r}")
    return rid


def _path(review_id: str) -> str:
    return os.path.join(REVIEW_DIR, f"{_safe_review_id(review_id)}.json")


def create_review(package: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a pending review package and return it (with id + review_url)."""
    os.makedirs(REVIEW_DIR, exist_ok=True)
    review_id = package.get("review_id") or f"REV-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "review_id": review_id,
        "status": "PENDING_REVIEW",
        "created_at": _now(),
        "updated_at": _now(),
        "assignee": package.get("assignee", "deal-desk"),
        "draft_id": package.get("draft_id"),
        "draft": package.get("draft"),
        "risk_level": package.get("risk_level"),
        "headline": package.get("headline"),
        "escalations": package.get("escalations", []),
        "proposed_changes": package.get("proposed_changes", []),
        "report_file": package.get("report_file"),
        "iteration_log": package.get("iteration_log", []),
        "history": [{"at": _now(), "event": "created", "by": "agent"}],
        # the review "URL" a reviewer would click. In Box this is the task link.
        "review_url": package.get("review_url") or f"reality-check://review/{review_id}",
        "decision": None,
        "reviewer_note": None,
        "requested_changes": None,
    }
    with open(_path(review_id), "w") as fh:
        json.dump(record, fh, indent=2)
    return record


def get_review(review_id: str) -> Optional[Dict[str, Any]]:
    """Open a review package (what the reviewer sees when they open the doc).
    An invalid/unsafe review_id is treated as 'not found' rather than an error."""
    try:
        p = _path(review_id)
    except ValueError:
        return None
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        return json.load(fh)


def list_reviews(status: Optional[str] = None) -> List[Dict[str, Any]]:
    if not os.path.isdir(REVIEW_DIR):
        return []
    out = []
    for fn in sorted(os.listdir(REVIEW_DIR)):
        if not fn.endswith(".json"):
            continue
        with open(os.path.join(REVIEW_DIR, fn)) as fh:
            r = json.load(fh)
        if status is None or r.get("status") == status:
            out.append(r)
    return out


def resolve_review(review_id: str, decision: str, reviewer: str = "reviewer",
                   note: str = "", requested_changes: Optional[Dict[str, Any]] = None
                   ) -> Dict[str, Any]:
    """
    Apply a reviewer decision.
      decision in {"approve", "reject", "request_changes"}
      requested_changes: optional dict of field overrides for request_changes,
        e.g. {"promised_days": 90, "sla_tier": "Enterprise"} or
             {"accept_proposed": true} to accept the agent's proposed changes.
    """
    record = get_review(review_id)
    if record is None:
        return {"error": f"review {review_id} not found"}
    if record["status"] != "PENDING_REVIEW":
        return {"error": f"review {review_id} already {record['status']}"}

    status_map = {
        "approve": "APPROVED",
        "reject": "REJECTED",
        "request_changes": "CHANGES_REQUESTED",
    }
    if decision not in status_map:
        return {"error": f"invalid decision '{decision}'"}

    record["status"] = status_map[decision]
    record["decision"] = decision
    record["reviewer_note"] = note
    record["requested_changes"] = requested_changes
    record["updated_at"] = _now()
    record["history"].append({
        "at": _now(), "event": decision, "by": reviewer, "note": note,
        "requested_changes": requested_changes,
    })
    with open(_path(review_id), "w") as fh:
        json.dump(record, fh, indent=2)
    return record
