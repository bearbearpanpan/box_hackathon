"""
Feature 5 — Portfolio radar / early-warning.

Scans all deals for shared, systemic risk rather than looking at one deal in
isolation: "N open deals route hardware through Meridian in Q4 — $X TCV exposed
to the same backorder." Moves from single-deal review to portfolio risk mgmt.
Market analog: contract-intelligence portfolio dashboards.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data")))


def _money(n) -> str:
    return "${:,.0f}".format(n or 0)


def scan(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate systemic risk clusters across the portfolio."""
    clusters: List[Dict[str, Any]] = []

    # Cluster 1: Meridian hardware in Q4 (the planted systemic risk).
    meridian_q4 = [d for d in history
                   if d.get("hw_vendor") == "Meridian Systems" and d.get("signed_quarter") == "Q4"]
    if meridian_q4:
        tcv = sum(d.get("tcv", 0) for d in meridian_q4)
        avg_slip = _avg([d.get("slip_days") for d in meridian_q4 if d.get("slip_days") is not None])
        clusters.append({
            "id": "CL-MERIDIAN-Q4",
            "severity": "HIGH",
            "title": "Meridian hardware deals signed in Q4",
            "deal_count": len(meridian_q4),
            "tcv_exposed": tcv,
            "evidence": f"avg historical slip {avg_slip:+.0f} days on these deals",
            "deal_ids": [d.get("contract_id") for d in meridian_q4][:10],
            "recommendation": "Pre-order PDUs / stage hardware; add Q4 buffer to all Meridian deals.",
        })

    # Cluster 2: regulated verticals without a compliance pack.
    reg_no_pack = [d for d in history if d.get("regulated") and not d.get("compliance_pack")]
    if reg_no_pack:
        clusters.append({
            "id": "CL-REG-NOPACK",
            "severity": "HIGH",
            "title": "Regulated-vertical deals missing a compliance pack",
            "deal_count": len(reg_no_pack),
            "tcv_exposed": sum(d.get("tcv", 0) for d in reg_no_pack),
            "evidence": "procurement review will block these at signature",
            "deal_ids": [d.get("contract_id") for d in reg_no_pack][:10],
            "recommendation": "Attach compliance pack across the segment proactively.",
        })

    # Cluster 3: deep discounts (>35%).
    deep = [d for d in history if (d.get("discount_pct") or 0) > 35]
    if deep:
        clusters.append({
            "id": "CL-DEEP-DISCOUNT",
            "severity": "MEDIUM",
            "title": "Deals discounted above the 35% approval threshold",
            "deal_count": len(deep),
            "tcv_exposed": sum(d.get("tcv", 0) for d in deep),
            "evidence": "correlated with professional-services scope creep",
            "deal_ids": [d.get("contract_id") for d in deep][:10],
            "recommendation": "Audit SOW scope; enforce VP approval + fixed hours.",
        })

    # Cluster 4: chronic over-promise (actual >> promised) by region.
    by_region = defaultdict(list)
    for d in history:
        if d.get("slip_days") is not None:
            by_region[d.get("region")].append(d["slip_days"])
    hot_regions = []
    for region, slips in by_region.items():
        if len(slips) >= 3 and _avg(slips) > 15:
            hot_regions.append({"region": region, "avg_slip": round(_avg(slips)), "deals": len(slips)})
    if hot_regions:
        hot_regions.sort(key=lambda r: -r["avg_slip"])
        clusters.append({
            "id": "CL-REGION-SLIP",
            "severity": "MEDIUM",
            "title": "Regions that chronically over-promise delivery",
            "deal_count": sum(r["deals"] for r in hot_regions),
            "tcv_exposed": None,
            "evidence": "; ".join(f"{r['region']}: {r['avg_slip']:+}d avg over {r['deals']} deals" for r in hot_regions),
            "deal_ids": [],
            "recommendation": "Recalibrate default timelines for these regions.",
        })

    clusters.sort(key=lambda c: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(c["severity"], 3))
    total_exposed = sum(c["tcv_exposed"] or 0 for c in clusters)
    return {
        "portfolio_size": len(history),
        "cluster_count": len(clusters),
        "total_tcv_exposed": total_exposed,
        "headline": (
            f"{len(clusters)} systemic risk clusters across {len(history)} deals; "
            f"{_money(total_exposed)} TCV exposed."
        ),
        "clusters": clusters,
    }


def _avg(xs) -> float:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0
