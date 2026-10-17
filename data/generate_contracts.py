#!/usr/bin/env python3
"""
generate_contracts.py — produce N tech-sales contract PDFs + a manifest.

Deterministic (seeded) so re-runs reproduce the same corpus. Each contract is
a realistic multi-line tech-sales agreement (SaaS + platform + optional
hardware + services), with promised vs actual delivery days so the risk/history
story holds together. Planted patterns from catalog.py are applied as biases.

Run:
    python3 data/generate_contracts.py            # 100 contracts -> data/contracts/
    python3 data/generate_contracts.py --count 10 --out /tmp/c

Outputs:
    <out>/CTR-0001.pdf ... CTR-0100.pdf
    <out>/manifest.json   (structured ground truth for all contracts)
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import date, timedelta

from minipdf import PdfDoc
import catalog as C


def _pick_products(rng: random.Random):
    """Choose a realistic line-item bundle. Always >=1 SaaS/platform item."""
    saas_like = [p for p in C.PRODUCTS if p[2] in ("saas", "platform")]
    services = [p for p in C.PRODUCTS if p[2] in ("services", "support")]
    hardware = [p for p in C.PRODUCTS if p[2] == "hardware"]

    lines = []
    for p in rng.sample(saas_like, k=rng.randint(1, 2)):
        qty = rng.choice([50, 100, 150, 250, 400, 600, 1000])
        lines.append((p, qty))

    has_hardware = rng.random() < 0.45
    if has_hardware:
        p = rng.choice(hardware)
        qty = rng.choice([1, 2, 3, 4, 6, 8])
        lines.append((p, qty))

    if rng.random() < 0.6:
        p = rng.choice(services)
        lines.append((p, 1))

    return lines, has_hardware


def _money(n: float) -> str:
    return "${:,.0f}".format(n)


def build_contract(idx: int, rng: random.Random) -> dict:
    cid = f"CTR-{idx:04d}"
    customer, vertical = rng.choice(C.CUSTOMERS)
    region = rng.choice(C.REGIONS)
    quarter = rng.choice(C.QUARTERS)
    term_months = rng.choice(C.TERM_LENGTHS_MONTHS)
    payment_terms = rng.choice(C.PAYMENT_TERMS)
    sla_name, uptime, response, credits = rng.choice(C.SLA_TIERS)

    lines, has_hardware = _pick_products(rng)
    hw_vendor = rng.choice(C.HW_VENDORS) if has_hardware else None

    # Pricing
    subtotal = 0
    line_rows = []
    for (sku, name, cat, unit, price), qty in lines:
        amount = price * qty
        subtotal += amount
        line_rows.append({
            "sku": sku, "name": name, "category": cat,
            "unit": unit, "unit_price": price, "qty": qty, "amount": amount,
        })

    discount_pct = rng.choice([0, 0, 5, 10, 15, 20, 25, 30, 40, 45])
    discount_amt = round(subtotal * discount_pct / 100)
    tcv = subtotal - discount_amt

    # Delivery / implementation promise (days). Baseline by complexity.
    base_days = 30
    if has_hardware:
        base_days += 40
    if any(r["category"] in ("services",) for r in line_rows):
        base_days += 20
    promised_days = base_days + rng.randint(-10, 10)
    promised_days = max(20, promised_days)

    # ---- Apply planted biases to compute an ACTUAL delivery (history) -------
    slip = rng.randint(-3, 7)  # baseline noise
    if has_hardware and quarter == "Q4":
        slip += rng.randint(25, 50)                 # pattern 1
    if hw_vendor == "Meridian Systems":
        slip += rng.randint(10, 25)                 # pattern 2
    if discount_pct > 35:
        slip += rng.randint(8, 20)                  # pattern 3
    actual_days = max(15, promised_days + slip)

    regulated = vertical in C.REGULATED_VERTICALS
    compliance_pack = rng.random() < 0.5

    signed = _quarter_to_date(quarter, rng)
    promised_date = signed + timedelta(days=promised_days)
    actual_date = signed + timedelta(days=actual_days)

    return {
        "contract_id": cid,
        "customer": customer,
        "vertical": vertical,
        "regulated": regulated,
        "region": region,
        "signed_quarter": quarter,
        "signed_date": signed.isoformat(),
        "term_months": term_months,
        "payment_terms": payment_terms,
        "sla_tier": sla_name,
        "sla_uptime": uptime,
        "sla_response": response,
        "sla_credits": credits,
        "has_hardware": has_hardware,
        "hw_vendor": hw_vendor,
        "line_items": line_rows,
        "subtotal": subtotal,
        "discount_pct": discount_pct,
        "discount_amount": discount_amt,
        "tcv": tcv,
        "compliance_pack": compliance_pack,
        "promised_days": promised_days,
        "actual_days": actual_days,
        "slip_days": actual_days - promised_days,
        "promised_date": promised_date.isoformat(),
        "actual_delivery_date": actual_date.isoformat(),
    }


def _quarter_to_date(quarter: str, rng: random.Random) -> date:
    year = rng.choice([2023, 2024, 2025])
    month = {"Q1": 2, "Q2": 5, "Q3": 8, "Q4": 11}[quarter]
    day = rng.randint(1, 27)
    return date(year, month, day)


def render_pdf(c: dict, path: str):
    doc = PdfDoc()
    doc.add_heading("TECH SALES AGREEMENT")
    doc.add_paragraph(f"Contract ID: {c['contract_id']}")
    doc.add_rule()

    doc.add_subheading("1. Parties")
    doc.add_keyvalue("Provider", "CloudSuite, Inc.")
    doc.add_keyvalue("Customer", f"{c['customer']}  ({c['vertical']})")
    doc.add_keyvalue("Deployment region", c["region"])

    doc.add_subheading("2. Commercial Terms")
    doc.add_keyvalue("Signed", f"{c['signed_date']}  ({c['signed_quarter']})")
    doc.add_keyvalue("Term", f"{c['term_months']} months")
    doc.add_keyvalue("Payment terms", c["payment_terms"])

    doc.add_subheading("3. Order Line Items")
    for r in c["line_items"]:
        doc.add_paragraph(
            f"- {r['name']}  [{r['sku']}]  "
            f"{r['qty']} x {_money(r['unit_price'])} ({r['unit']}) = {_money(r['amount'])}"
        )
    doc.add_keyvalue("Subtotal", _money(c["subtotal"]))
    if c["discount_pct"]:
        doc.add_keyvalue("Discount", f"{c['discount_pct']}%  (-{_money(c['discount_amount'])})")
    doc.add_keyvalue("Total Contract Value (TCV)", _money(c["tcv"]))

    if c["has_hardware"]:
        doc.add_subheading("4. Hardware & Supply")
        doc.add_keyvalue("Hardware vendor", c["hw_vendor"])
        doc.add_paragraph(
            "On-prem hardware is subject to vendor lead times. Freight and "
            "customs may affect delivery, particularly for Q4 ship windows."
        )

    doc.add_subheading("5. Service Levels (SLA)")
    doc.add_keyvalue("SLA tier", c["sla_tier"])
    doc.add_keyvalue("Uptime commitment", c["sla_uptime"])
    doc.add_keyvalue("Support response", c["sla_response"])
    doc.add_keyvalue("Service credits", c["sla_credits"])

    doc.add_subheading("6. Delivery & Implementation")
    doc.add_keyvalue("Promised delivery", f"{c['promised_days']} days from signature")
    doc.add_keyvalue("Promised date", c["promised_date"])
    doc.add_paragraph(
        "Compliance pack included: " + ("Yes" if c["compliance_pack"] else "No")
    )

    doc.add_subheading("7. Delivery Outcome (internal closeout record)")
    doc.add_paragraph(
        "This section is an internal post-delivery record for history/analysis "
        "and is not part of the customer-facing agreement."
    )
    doc.add_keyvalue("Actual delivery", f"{c['actual_days']} days from signature")
    doc.add_keyvalue("Actual date", c["actual_delivery_date"])
    doc.add_keyvalue("Slip vs promise", f"{c['slip_days']:+d} days")

    doc.add_spacer(10)
    doc.add_rule()
    doc.add_paragraph(
        "This document is synthetic sample data generated for a hackathon demo. "
        "Customer names are fictional. Not a real agreement."
    )
    doc.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--seed", type=int, default=42)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.join(here, "contracts"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)

    manifest = []
    for i in range(1, args.count + 1):
        c = build_contract(i, rng)
        render_pdf(c, os.path.join(args.out, f"{c['contract_id']}.pdf"))
        manifest.append(c)

    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump({"count": len(manifest), "contracts": manifest}, fh, indent=2)

    # quick summary to stdout
    hw_q4 = [m for m in manifest if m["has_hardware"] and m["signed_quarter"] == "Q4"]
    meridian = [m for m in manifest if m["hw_vendor"] == "Meridian Systems"]
    print(f"Generated {len(manifest)} contracts -> {args.out}")
    print(f"  Q4 hardware deals (high slip): {len(hw_q4)}")
    print(f"  Meridian-sourced deals: {len(meridian)}")
    if hw_q4:
        avg = sum(m["slip_days"] for m in hw_q4) / len(hw_q4)
        print(f"  Avg slip on Q4 hardware deals: {avg:.0f} days")


if __name__ == "__main__":
    main()
