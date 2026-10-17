"""
Feature 4 — "What-if" negotiation simulator.

Lets a reviewer move the levers (promised_days, discount_pct, sla_tier,
hw_vendor, compliance_pack) and instantly see the recomputed grade, risk, and
headline. Answers "what would make this a B?" live in the room. Reuses the risk
engine + grade feature, so it's always consistent with the real analysis.
"""
from __future__ import annotations

import os
import sys
from copy import deepcopy
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grade  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import comparison  # noqa: E402

LEVERS = {"promised_days", "discount_pct", "sla_tier", "hw_vendor", "compliance_pack", "signed_quarter"}


def _evaluate(draft: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    comps, _ = comparison.find_comparables(draft, history)
    risk = comparison.risk_level(draft, comps)
    g = grade.score_deal(draft, history)
    return {
        "grade": g["grade"], "score": g["score"], "risk": risk["level"],
        "headline": (f"{draft.get('promised_days')} days promised, history says "
                     f"{risk.get('p50_actual')}." if risk.get("p50_actual") else "no comparables"),
    }


def simulate(draft: Dict[str, Any], overrides: Dict[str, Any],
             history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply one set of overrides and return before/after."""
    before = _evaluate(draft, history)
    scenario = deepcopy(draft)
    applied = {}
    for k, v in overrides.items():
        if k in LEVERS:
            scenario[k] = v
            applied[k] = v
    after = _evaluate(scenario, history)
    return {"applied": applied, "before": before, "after": after,
            "improved": after["score"] - before["score"]}


def find_path_to_grade(draft: Dict[str, Any], target: str,
                       history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Search simple single-lever moves to reach a target grade (e.g. "B").
    Returns the cheapest change that gets there, or the best achievable.
    """
    order = {"A": 90, "B": 80, "C": 70, "D": 60, "F": 0}
    need = order.get(target.upper(), 80)
    comps, _ = comparison.find_comparables(draft, history)
    tl = comparison.suggested_timeline(draft, comps)

    candidates: List[Dict[str, Any]] = []
    # lever: extend the timeline toward (and past) the median actual
    if tl.get("p50_actual"):
        for d in (tl["p50_actual"], tl.get("worst_actual", tl["p50_actual"])):
            candidates.append({"promised_days": d})
    # lever: drop a deep discount
    if (draft.get("discount_pct") or 0) > 35:
        candidates.append({"discount_pct": 35})
    # lever: switch away from the risky vendor
    if draft.get("hw_vendor") == "Meridian Systems":
        candidates.append({"hw_vendor": "Vortex Hardware"})
    # lever: add compliance pack
    if not draft.get("compliance_pack"):
        candidates.append({"compliance_pack": True})

    best = None
    for c in candidates:
        sim = simulate(draft, c, history)
        if sim["after"]["score"] >= need:
            if best is None or sim["after"]["score"] < best["after"]["score"]:
                best = sim  # cheapest that clears the bar
    if best:
        return {"target": target.upper(), "achievable": True, "move": best}

    # none single-handedly reach it: report the strongest single move
    sims = [simulate(draft, c, history) for c in candidates]
    strongest = max(sims, key=lambda s: s["after"]["score"]) if sims else None
    return {"target": target.upper(), "achievable": False, "best_single_move": strongest}
