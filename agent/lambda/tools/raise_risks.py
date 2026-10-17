"""
raise_risks.py — tool: evaluate a draft deal and surface risks.

Combines two sources of risk:
  1. The history-based comparison (comparison.analyze) -> timeline/SLA risk.
  2. The static RISK_LIBRARY rules (catalog) evaluated against the draft.

Returns a structured risk report the agent can narrate and the report builder
can turn into a PDF.
"""
from __future__ import annotations

import ast
import operator
import os
import sys
from typing import Dict, Any, List

# make sibling / data imports work both in Lambda and locally
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))

import comparison  # noqa: E402


# --- safe trigger evaluation ------------------------------------------------
# RISK_LIBRARY triggers are small boolean expressions (e.g.
# "has_hardware and quarter == 'Q4' and promised_days < 90"). We evaluate them
# with a restricted AST walker instead of eval() so that a trigger string can
# never execute arbitrary code — even if RISK_LIBRARY is ever sourced
# externally (a feed, Box, config). Only the node types the rules actually use
# are permitted; anything else raises and the rule is skipped.
_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}


class _UnsafeExpression(ValueError):
    """Raised when a trigger expression contains a disallowed construct."""


def _safe_eval(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body, ctx)
    if isinstance(node, ast.BoolOp):
        values = [_safe_eval(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise _UnsafeExpression("unsupported boolean operator")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _safe_eval(node.operand, ctx)
    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            fn = _CMP_OPS.get(type(op))
            if fn is None:
                raise _UnsafeExpression("unsupported comparison operator")
            right = _safe_eval(comparator, ctx)
            if not fn(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise _UnsafeExpression(f"unknown name: {node.id}")
    if isinstance(node, (ast.Tuple, ast.List)):
        return [_safe_eval(e, ctx) for e in node.elts]
    if isinstance(node, ast.Constant):
        return node.value
    raise _UnsafeExpression(f"disallowed expression node: {type(node).__name__}")


def _eval_trigger(expr: str, ctx: Dict[str, Any]) -> bool:
    """Safely evaluate a single RISK_LIBRARY trigger expression."""
    tree = ast.parse(expr, mode="eval")
    return bool(_safe_eval(tree, ctx))


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
            if _eval_trigger(rule["trigger"], ctx):
                fired.append({
                    "id": rule["id"],
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "detail": rule["detail"],
                    "mitigation": rule["mitigation"],
                })
        except (_UnsafeExpression, SyntaxError):
            # A malformed or disallowed trigger never fires and never executes.
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
