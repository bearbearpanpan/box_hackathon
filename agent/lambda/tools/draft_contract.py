"""
draft_contract.py — tool: draft a new tech-sales contract.

Given deal parameters (customer, region, products, SLA, timeline, etc.), it
assembles a normalized draft deal dict and a human-readable contract body. The
draft dict is the same shape the comparison/risk tools expect, so a freshly
drafted deal can be risk-checked immediately.

If a field is omitted, sensible defaults are chosen and flagged in `assumptions`
so the agent can tell the user what it filled in.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))


def _lookup_products(skus: Optional[List[str]]):
    try:
        import catalog as C
    except Exception:
        return []
    by_sku = {p[0]: p for p in C.PRODUCTS}
    out = []
    for s in skus or []:
        if s in by_sku:
            out.append(by_sku[s])
    return out


def draft_contract(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    params may include: customer, vertical, region, signed_quarter, term_months,
    payment_terms, sla_tier, line_items [{sku, qty}], discount_pct, promised_days,
    hw_vendor, compliance_pack.
    """
    import catalog as C  # type: ignore

    assumptions: List[str] = []

    def default(key, value, note=None):
        if params.get(key) in (None, ""):
            if note:
                assumptions.append(note)
            return value
        return params[key]

    customer = default("customer", "Prospect Customer", "customer not given -> placeholder")
    vertical = default("vertical", "Technology")
    region = default("region", C.REGIONS[0], f"region defaulted to {C.REGIONS[0]}")
    quarter = default("signed_quarter", "Q4", "quarter defaulted to Q4")
    term_months = default("term_months", 36)
    payment_terms = default("payment_terms", "Net 30")
    sla_tier = default("sla_tier", "Enterprise", "SLA defaulted to Enterprise")
    discount_pct = default("discount_pct", 0)
    compliance_pack = default("compliance_pack", False)

    # Resolve line items
    by_sku = {p[0]: p for p in C.PRODUCTS}
    raw_items = params.get("line_items") or [{"sku": "SKU-SAAS-CORE", "qty": 250}]
    line_rows = []
    subtotal = 0
    has_hardware = False
    for item in raw_items:
        p = by_sku.get(item.get("sku"))
        if not p:
            continue
        sku, name, cat, unit, price = p
        qty = item.get("qty", 1)
        amount = price * qty
        subtotal += amount
        if cat == "hardware":
            has_hardware = True
        line_rows.append({"sku": sku, "name": name, "category": cat,
                          "unit": unit, "unit_price": price, "qty": qty, "amount": amount})

    hw_vendor = params.get("hw_vendor") if has_hardware else None
    if has_hardware and not hw_vendor:
        hw_vendor = C.HW_VENDORS[1]  # default to a non-risky vendor
        assumptions.append(f"hardware vendor defaulted to {hw_vendor}")

    discount_amt = round(subtotal * (discount_pct or 0) / 100)
    tcv = subtotal - discount_amt

    # Promised delivery default based on complexity
    promised_days = params.get("promised_days")
    if promised_days is None:
        promised_days = 30 + (40 if has_hardware else 0)
        assumptions.append(f"promised delivery defaulted to {promised_days} days")

    sla = next((t for t in C.SLA_TIERS if t[0] == sla_tier), C.SLA_TIERS[2])

    draft = {
        "contract_id": params.get("contract_id", "DRAFT-NEW"),
        "customer": customer,
        "vertical": vertical,
        "regulated": vertical in C.REGULATED_VERTICALS,
        "region": region,
        "signed_quarter": quarter,
        "term_months": term_months,
        "payment_terms": payment_terms,
        "sla_tier": sla[0],
        "sla_uptime": sla[1],
        "sla_response": sla[2],
        "sla_credits": sla[3],
        "has_hardware": has_hardware,
        "hw_vendor": hw_vendor,
        "line_items": line_rows,
        "subtotal": subtotal,
        "discount_pct": discount_pct,
        "discount_amount": discount_amt,
        "tcv": tcv,
        "compliance_pack": compliance_pack,
        "promised_days": promised_days,
        "actual_days": None,  # unknown for a draft
    }

    return {"draft": draft, "assumptions": assumptions, "body": _render_body(draft)}


def _money(n: float) -> str:
    return "${:,.0f}".format(n)


def _render_body(d: Dict[str, Any]) -> str:
    lines = [
        "TECH SALES AGREEMENT (DRAFT)",
        f"Customer: {d['customer']} ({d['vertical']})",
        f"Region: {d['region']}    Signed: {d['signed_quarter']}    Term: {d['term_months']} mo",
        f"Payment: {d['payment_terms']}",
        "",
        "Line items:",
    ]
    for r in d["line_items"]:
        lines.append(f"  - {r['name']} [{r['sku']}] {r['qty']} x {_money(r['unit_price'])} = {_money(r['amount'])}")
    lines += [
        f"Subtotal: {_money(d['subtotal'])}   Discount: {d['discount_pct']}%   TCV: {_money(d['tcv'])}",
        f"SLA: {d['sla_tier']} ({d['sla_uptime']}, {d['sla_response']})",
        f"Promised delivery: {d['promised_days']} days from signature",
    ]
    if d["has_hardware"]:
        lines.append(f"Hardware vendor: {d['hw_vendor']}")
    return "\n".join(lines)
