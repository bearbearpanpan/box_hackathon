"""
Feature 3 — Obligation & milestone tracker.

Extracts every commitment in a deal into a dated register with an owner and an
alert window, so nothing is missed post-signature. Market analog: Ironclad /
LinkSquares obligation tracking (deadlines, milestones, renewals, SLA, payment).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Any, List


def _parse_date(s: str) -> date:
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception:
        return date.today()


def build_register(draft: Dict[str, Any]) -> Dict[str, Any]:
    """Return a list of dated obligations derived from the draft."""
    signed = _parse_date(draft.get("signed_date") or date.today().isoformat())
    obligations: List[Dict[str, Any]] = []

    def add(kind, title, due, owner, alert_days, detail=""):
        obligations.append({
            "kind": kind, "title": title, "due_date": due.isoformat(),
            "owner": owner, "alert_date": (due - timedelta(days=alert_days)).isoformat(),
            "detail": detail,
        })

    # Delivery / go-live milestone
    pd = draft.get("promised_days")
    if pd:
        add("delivery", "Deliver & commission ordered systems",
            signed + timedelta(days=pd), "Delivery Ops", alert_days=14,
            detail=f"Committed {pd} days from signature.")

    # SLA obligation (ongoing, first review at 30 days)
    if draft.get("sla_tier"):
        add("sla", f"Meet {draft['sla_tier']} SLA ({draft.get('sla_uptime','')})",
            signed + timedelta(days=30), "SRE / Support", alert_days=7,
            detail="First monthly availability review.")

    # Payment terms
    terms = draft.get("payment_terms", "")
    net_days = {"Net 30": 30, "Net 45": 45, "Net 60": 60}.get(terms)
    if net_days:
        add("payment", f"First invoice due ({terms})",
            signed + timedelta(days=net_days), "Finance / AR", alert_days=5)

    # Renewal / term end
    term = draft.get("term_months")
    if term:
        add("renewal", "Contract term ends — renewal decision",
            signed + timedelta(days=term * 30), "Account Manager", alert_days=90,
            detail="Open renewal conversation 90 days out.")

    # Compliance commitment
    if draft.get("regulated") or draft.get("compliance_pack"):
        add("compliance", "Deliver compliance pack / residency evidence",
            signed + timedelta(days=max(30, (pd or 30))), "Security / Compliance",
            alert_days=14, detail="Required for regulated vertical / EU-APAC region.")

    # Hardware vendor milestone
    if draft.get("has_hardware"):
        add("vendor", f"Confirm hardware lead time with {draft.get('hw_vendor','vendor')}",
            signed + timedelta(days=7), "Procurement", alert_days=2,
            detail="Lock vendor PO and confirmed ship date before promising go-live.")

    obligations.sort(key=lambda o: o["due_date"])
    return {
        "draft_id": draft.get("contract_id"),
        "signed_date": signed.isoformat(),
        "obligation_count": len(obligations),
        "obligations": obligations,
    }
