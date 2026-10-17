"""
raise_risks.py — tool: evaluate a draft deal and surface risks.

Combines two sources of risk:
  1. The history-based comparison (comparison.analyze) -> timeline/SLA risk.
  2. The static RISK_LIBRARY rules (catalog) evaluated against the draft.

Returns a structured risk report the agent can narrate and the report builder
can turn into a PDF.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List

# make sibling / data imports work both in Lambda and locally
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))

import comparison  # noqa: E402


def _eval_static_rules(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Evaluate RISK_LIBRARY triggers against the draft deal."""
    try:
        import catalog as C  # from data/
    except Exception:
        return []

    ctx = {
        "has_hardware": bool(draft.get("has_hardware")),
        "quarter": draft.get("signed_quarter"),
        "promised_days": draft.get("promised_days") or 0,
        "hw_vendor": draft.get("hw_vendor"),
        "discount_pct": draft.get("discount_pct") or 0,
        "sla_tier": draft.get("sla_tier"),
        "regulated": bool(draft.get("regulated")),
        "compliance_pack": bool(draft.get("compliance_pack")),
        "payment_terms": draft.get("payment_terms"),
        "tcv": draft.get("tcv") or 0,
    }
    fired = []
    for rule in C.RISK_LIBRARY:
        try:
            if eval(rule["trigger"], {"__builtins__": {}}, ctx):  # noqa: S307 - trusted internal rules
                fired.append({
                    "id": rule["id"],
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "detail": rule["detail"],
                    "mitigation": rule["mitigation"],
                })
        except Exception:
            continue
    return fired


def raise_risks(draft: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    analysis = comparison.analyze(draft, history)
    static_risks = _eval_static_rules(draft)

    # Promote the history risk into the same list shape.
    history_risk = analysis["risk"]
    severity_map = {"RED": "HIGH", "AMBER": "MEDIUM", "GREEN": "LOW", "UNKNOWN": "LOW"}
    risks = [{
        "id": "R-HISTORY-TIMELINE",
        "title": "Promised timeline vs comparable deal history",
        "severity": severity_map.get(history_risk["level"], "MEDIUM"),
        "detail": history_risk["reason"],
        "mitigation": (
            f"Rebaseline delivery toward {analysis['suggested_timeline'].get('suggested_days')} days "
            f"(median of comparable actuals)."
        ),
    }] + static_risks

    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    risks.sort(key=lambda r: order.get(r["severity"], 3))

    return {
        "draft_id": draft.get("contract_id"),
        "overall_risk": history_risk["level"],
        "overall_emoji": history_risk["emoji"],
        "headline": _headline(draft, analysis),
        "risks": risks,
        "comparables": analysis["comparables"],
        "suggested_timeline": analysis["suggested_timeline"],
        "thin_history": analysis["thin_history"],
    }


def _headline(draft: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    promised = draft.get("promised_days")
    p50 = analysis["suggested_timeline"].get("p50_actual")
    if promised is not None and p50 is not None:
        return f"{promised} days promised, history says {p50}."
    return "Risk analysis complete."
