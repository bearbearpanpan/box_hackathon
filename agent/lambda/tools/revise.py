"""
revise.py — apply fixes to a draft based on flagged risks + external signals.

The reviser decides, for each issue, whether the agent can fix it autonomously
or whether it needs a human. It returns the revised draft, the list of changes
it made (with citations), and the list of issues that still require human
approval. The workflow loop uses this to decide whether to iterate again or stop.

Autonomy policy (what the agent may change on its own):
  * promised_days  — extend to a safer floor / add buffer (never shorten).
  * compliance_pack — attach when required.
  * sla_tier       — step DOWN to a supportable tier (never silently up).
  * discount_pct   — cap at policy threshold.
Anything that would REDUCE a customer-facing commitment the sales rep explicitly
made in the notes (e.g. a hard promised date the customer insisted on) is NOT
auto-changed; it is escalated for human approval instead.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List, Tuple

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))

# Fields the agent is allowed to modify autonomously.
AUTO_FIELDS = {"promised_days", "compliance_pack", "sla_tier", "discount_pct"}


def _apply_action(draft: Dict[str, Any], action: Dict[str, Any]) -> Tuple[bool, str]:
    """Apply one machine action. Returns (changed, human_readable_change)."""
    field = action["field"]
    op = action["op"]
    val = action["value"]
    cur = draft.get(field)

    if field not in AUTO_FIELDS:
        return False, ""

    if op == "set":
        if cur != val:
            draft[field] = val
            return True, f"{field}: {cur} -> {val}"
    elif op == "min_floor":          # raise up to at least val
        if (cur or 0) < val:
            draft[field] = val
            return True, f"{field}: {cur} -> {val} (floor)"
    elif op == "add":                # extend by val (buffer)
        draft[field] = (cur or 0) + val
        return True, f"{field}: {cur} -> {draft[field]} (+{val} buffer)"
    elif op == "max_cap":            # cap down to val
        if (cur or 0) > val:
            draft[field] = val
            return True, f"{field}: {cur} -> {val} (capped)"
    return False, ""


def revise(draft: Dict[str, Any], risk_report: Dict[str, Any],
           signals: List[Dict[str, Any]], hard_promises: Dict[str, Any] | None = None
           ) -> Dict[str, Any]:
    """
    Produce a revised draft. `hard_promises` are commitments the rep locked in
    from the meeting (e.g. {"promised_days": 60}) that the agent must NOT soften
    without human sign-off — these become escalations instead of auto-fixes.
    """
    hard_promises = hard_promises or {}
    revised = dict(draft)
    changes: List[Dict[str, Any]] = []
    escalations: List[Dict[str, Any]] = []

    # 1) Apply machine-applicable external signal actions.
    for sig in signals:
        action = sig.get("action")
        if not action:
            escalations.append({
                "source": sig["id"], "severity": sig["severity"],
                "issue": sig["title"],
                "needs_human": sig["recommended_action"],
            })
            continue

        field = action["field"]
        # Guard: don't override a hard customer promise without a human.
        if field in hard_promises and action["op"] in ("set", "max_cap"):
            escalations.append({
                "source": sig["id"], "severity": sig["severity"],
                "issue": sig["title"],
                "needs_human": (
                    f"{sig['recommended_action']} — but the rep committed "
                    f"{field}={hard_promises[field]} in the meeting; needs approval to change."
                ),
            })
            continue

        # Special case: timeline floor/buffer conflicts with a hard promised date.
        if field == "promised_days" and "promised_days" in hard_promises \
                and action["op"] in ("min_floor", "add"):
            # We can still *recommend* the safer number but flag the conflict.
            proposed = _preview(revised.get("promised_days"), action)
            if proposed > hard_promises["promised_days"]:
                escalations.append({
                    "source": sig["id"], "severity": sig["severity"],
                    "issue": sig["title"],
                    "needs_human": (
                        f"History/supplier says >= {proposed} days, but the rep "
                        f"promised {hard_promises['promised_days']} days to the "
                        f"customer. Approve the later date or get an exception."
                    ),
                })
                continue

        changed, desc = _apply_action(revised, action)
        if changed:
            changes.append({"source": sig["id"], "change": desc,
                            "reason": sig["title"], "citation": sig.get("source")})

    # 2) Escalate any HIGH history/static risk that has no machine action.
    for r in risk_report.get("risks", []):
        if r["severity"] == "HIGH" and not _was_addressed(r, changes):
            # history timeline risk is addressed via the signal floor if applied
            if r["id"] == "R-HISTORY-TIMELINE" and any(c["change"].startswith("promised_days") for c in changes):
                continue
            escalations.append({
                "source": r["id"], "severity": r["severity"],
                "issue": r["title"], "needs_human": r.get("mitigation", "Review required."),
            })

    return {"revised_draft": revised, "changes": changes, "escalations": escalations}


def _preview(cur, action) -> int:
    val = action["value"]
    if action["op"] == "min_floor":
        return max(cur or 0, val)
    if action["op"] == "add":
        return (cur or 0) + val
    return cur or 0


def _was_addressed(risk: Dict[str, Any], changes: List[Dict[str, Any]]) -> bool:
    return False  # kept simple; escalation de-dup handled by caller logic above
