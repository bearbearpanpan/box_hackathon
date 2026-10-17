"""
Feature 2 (part b) — auto-redline.

Turns flagged risks into concrete, tracked-change-style clause edits using the
fallback playbook. Output is a list of redlines (strike + insert + rationale)
plus a rendered "before/after" the reviewer can accept. Market analog: AI
playbook redlining (Sirion/Harvey) reported to cut redline cycles substantially.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import playbook  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import comparison  # noqa: E402


def _sla_cap(tier: str) -> int:
    return {"Standard": 5, "Business": 10, "Enterprise": 15, "Mission-Critical": 25}.get(tier, 10)


def propose_redlines(draft: Dict[str, Any], risk_report: Dict[str, Any],
                     history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return concrete clause edits for the risks in risk_report."""
    comps, _ = comparison.find_comparables(draft, history)
    tl = comparison.suggested_timeline(draft, comps)
    safe_days = tl.get("suggested_days") or draft.get("promised_days")

    redlines: List[Dict[str, Any]] = []
    seen_clauses = set()

    all_items = list(risk_report.get("risks", []))
    for item in all_items:
        clause_key = playbook.RISK_TO_CLAUSE.get(item.get("id") or item.get("source"))
        if not clause_key or clause_key in seen_clauses:
            continue
        seen_clauses.add(clause_key)
        clause = playbook.CLAUSES.get(clause_key, {})

        if clause_key == "delivery_timeline":
            before = clause["standard"].format(days=draft.get("promised_days"))
            after = clause["fallback"].format(days=safe_days)
            redlines.append(_rl(clause_key, before, after,
                                f"Promised {draft.get('promised_days')}d is below comparable actuals; "
                                f"align committed date to {safe_days}d (median of comparables)."))
        elif clause_key == "sla_credits":
            after = clause["fallback"].format(tier=draft.get("sla_tier"),
                                              cap=_sla_cap(draft.get("sla_tier")))
            redlines.append(_rl(clause_key, "(no credit cap clause present)", after,
                                "Cap and bound SLA credits to the deployed architecture."))
        elif clause_key == "liquidated_damages":
            after = clause["fallback"].format(grace=14)
            redlines.append(_rl(clause_key, "(no vendor-delay LD clause present)", after,
                                "Pass vendor backorder risk through to vendor-backed damages."))
        elif clause_key == "discount_approval":
            after = clause["fallback"].format(threshold=35)
            redlines.append(_rl(clause_key, "(no discount-governance clause present)", after,
                                "Govern deep discounts with VP approval + fixed-scope SOW."))
        else:  # vendor_delay, compliance_pack
            after = clause["fallback"]
            redlines.append(_rl(clause_key, "(clause not present in draft)", after,
                                item.get("detail", "Add protective fallback language.")))

    return {
        "draft_id": draft.get("contract_id"),
        "redline_count": len(redlines),
        "redlines": redlines,
        "suggested_days": safe_days,
    }


def _rl(clause: str, before: str, after: str, rationale: str) -> Dict[str, Any]:
    return {"clause": clause, "strike": before, "insert": after, "rationale": rationale}


def render_redline_text(result: Dict[str, Any]) -> str:
    """A simple before/after rendering for the report PDF or console."""
    lines = [f"PROPOSED REDLINES ({result['redline_count']}):", ""]
    for r in result["redlines"]:
        lines.append(f"[{r['clause']}]")
        lines.append(f"  - STRIKE:  {r['strike']}")
        lines.append(f"  + INSERT:  {r['insert']}")
        lines.append(f"  * WHY:     {r['rationale']}")
        lines.append("")
    return "\n".join(lines)
