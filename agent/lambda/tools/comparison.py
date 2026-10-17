"""
comparison.py — the comparison engine implementing RULES.md.

Pure functions, no I/O, so they're trivial to unit-test and reuse from any of
the three tools. Given a draft deal and a history of past contracts, it finds
comparable deals, computes a safer timeline, and assigns a risk level.
"""
from __future__ import annotations

from statistics import median
from typing import List, Dict, Any


SIZE_BAND = 0.40  # ±40% size gate (uses TCV as the "size" axis for sales deals)


def _passes_gate(draft: Dict[str, Any], cand: Dict[str, Any]) -> bool:
    same_region = cand.get("region") == draft.get("region")
    same_vendor = (
        cand.get("hw_vendor")
        and cand.get("hw_vendor") == draft.get("hw_vendor")
    )
    if not (same_region or same_vendor):
        return False
    d_tcv = draft.get("tcv") or 0
    c_tcv = cand.get("tcv") or 0
    if d_tcv <= 0:
        return True
    return abs(c_tcv - d_tcv) <= SIZE_BAND * d_tcv


def _score(draft: Dict[str, Any], cand: Dict[str, Any]) -> float:
    score = 0.0
    if cand.get("hw_vendor") and cand.get("hw_vendor") == draft.get("hw_vendor"):
        score += 3
    if cand.get("region") == draft.get("region"):
        score += 2
    if cand.get("signed_quarter") == draft.get("signed_quarter"):
        score += 1
    d_tcv = draft.get("tcv") or 0
    c_tcv = cand.get("tcv") or 0
    if d_tcv > 0:
        closeness = 1 - abs(c_tcv - d_tcv) / d_tcv
        score += max(0.0, min(1.0, closeness))
    return score


def find_comparables(draft: Dict[str, Any], history: List[Dict[str, Any]], top_n: int = 3):
    """Return (top_n comparables sorted by score desc, thin_history flag)."""
    gated = [
        c for c in history
        if c.get("contract_id") != draft.get("contract_id")
        and c.get("actual_days") is not None
        and _passes_gate(draft, c)
    ]
    ranked = sorted(gated, key=lambda c: _score(draft, c), reverse=True)
    top = ranked[:top_n]
    return top, len(top) < top_n


def suggested_timeline(draft: Dict[str, Any], comparables: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not comparables:
        return {"suggested_days": draft.get("promised_days"), "basis": "no comparables"}
    actuals = [c["actual_days"] for c in comparables]
    p50 = int(round(median(actuals)))
    promised = draft.get("promised_days") or 0
    return {
        "suggested_days": max(p50, promised),
        "p50_actual": p50,
        "worst_actual": max(actuals),
        "best_actual": min(actuals),
        "basis": f"median actual of {len(comparables)} comparable deals",
    }


def risk_level(draft: Dict[str, Any], comparables: List[Dict[str, Any]]) -> Dict[str, Any]:
    promised = draft.get("promised_days") or 0
    if not comparables:
        return {"level": "UNKNOWN", "emoji": "⚪", "reason": "No comparable history found."}
    actuals = [c["actual_days"] for c in comparables]
    p50 = median(actuals)
    mn = min(actuals)
    if promised >= p50:
        level, emoji = "GREEN", "🟢"
        reason = f"Promised {promised}d meets or beats the typical actual ({int(p50)}d)."
    elif promised >= mn:
        level, emoji = "AMBER", "🟡"
        reason = (f"Promised {promised}d beats the typical actual ({int(p50)}d) but "
                  f"some comparable deals delivered this fast (min {mn}d).")
    else:
        level, emoji = "RED", "🔴"
        reason = (f"Promised {promised}d is faster than EVERY comparable deal "
                  f"(fastest actual was {mn}d).")
    return {"level": level, "emoji": emoji, "reason": reason,
            "promised_days": promised, "p50_actual": int(p50), "min_actual": mn}


def analyze(draft: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Full Read->Check result for a draft against history."""
    comps, thin = find_comparables(draft, history)
    timeline = suggested_timeline(draft, comps)
    risk = risk_level(draft, comps)
    return {
        "draft_id": draft.get("contract_id"),
        "comparables": [
            {
                "contract_id": c["contract_id"],
                "customer": c.get("customer"),
                "region": c.get("region"),
                "hw_vendor": c.get("hw_vendor"),
                "signed_quarter": c.get("signed_quarter"),
                "promised_days": c.get("promised_days"),
                "actual_days": c.get("actual_days"),
            }
            for c in comps
        ],
        "thin_history": thin,
        "suggested_timeline": timeline,
        "risk": risk,
    }
