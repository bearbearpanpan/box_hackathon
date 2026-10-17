"""
risk_signals.py — a source of EXTERNAL risk events the agent discovers.

The deal itself only tells you so much. Real risk often comes from outside the
contract: a supplier posts a delay notice, a region gets a new data-residency
rule, a vendor's SLA-credit history spikes. This module is the agent's "world":
a small store of such signals, queryable by vendor / region / vertical.

In a live system these would come from Box docs, vendor portals, or a feed. Here
they're generated so the agentic loop has real, documented reasons to revise a
draft — including signals that are NOT derivable from the deal fields alone.

Each signal:
  {
    "id": "SIG-...",
    "kind": "supplier_notice" | "sla_history" | "compliance_alert" | "freight_advisory",
    "severity": "HIGH" | "MEDIUM" | "LOW",
    "matches": {vendor?, region?, vertical?, quarter?},   # when it applies
    "title": str,
    "detail": str,
    "recommended_action": str,     # what the reviser should do
    "action": {field, op, value}?  # machine-applicable fix (optional)
    "source": str,                 # citation
    "issued": "YYYY-MM-DD",
  }
"""
from __future__ import annotations

from typing import Dict, Any, List


SIGNALS: List[Dict[str, Any]] = [
    {
        "id": "SIG-MERIDIAN-Q4-DELAY",
        "kind": "supplier_notice",
        "severity": "HIGH",
        "matches": {"vendor": "Meridian Systems"},
        "title": "Meridian Systems — Q4 PDU/appliance backorder notice",
        "detail": ("Meridian issued a supplier delay notice: upstream PDU and "
                   "appliance components are backordered 3-5 weeks beyond standard "
                   "lead time; Q4 ship windows additionally exposed to holiday freight."),
        "recommended_action": "Add >= 30 days delivery buffer for Meridian hardware; do not promise sub-90-day delivery.",
        "action": {"field": "promised_days", "op": "min_floor", "value": 90},
        "source": "Vendor notice DN-MERIDIAN-2025-Q4",
        "issued": "2025-10-01",
    },
    {
        "id": "SIG-MERIDIAN-SLA-HISTORY",
        "kind": "sla_history",
        "severity": "MEDIUM",
        "matches": {"vendor": "Meridian Systems"},
        "title": "Meridian deals have triggered SLA credits before",
        "detail": ("Prior Meridian-sourced deals breached delivery milestones and "
                   "triggered service-credit clauses, eroding margin."),
        "recommended_action": "Attach explicit delivery-milestone language and vendor-backed liquidated damages.",
        "action": None,
        "source": "SLA credit memo SLA-01",
        "issued": "2025-03-15",
    },
    {
        "id": "SIG-EU-RESIDENCY",
        "kind": "compliance_alert",
        "severity": "HIGH",
        "matches": {"region_contains": "EU"},
        "title": "EU data-residency enforcement update",
        "detail": ("Deployments in EU regions must guarantee in-region data "
                   "residency and processing for regulated workloads."),
        "recommended_action": "Attach the Compliance pack / data-residency guarantee before signature.",
        "action": {"field": "compliance_pack", "op": "set", "value": True},
        "source": "Compliance bulletin CB-EU-2025-07",
        "issued": "2025-07-01",
    },
    {
        "id": "SIG-REGULATED-COMPLIANCE",
        "kind": "compliance_alert",
        "severity": "HIGH",
        "matches": {"vertical_in": ["Healthcare", "Financial Services", "Insurance", "Banking", "Pharma R&D"]},
        "title": "Regulated vertical requires compliance pack",
        "detail": ("Customer operates in a regulated vertical; a SOC2/HIPAA/PCI "
                   "compliance pack is required to pass procurement review."),
        "recommended_action": "Attach the Compliance pack before sending for signature.",
        "action": {"field": "compliance_pack", "op": "set", "value": True},
        "source": "Policy POL-REG-COMPLIANCE",
        "issued": "2025-01-10",
    },
    {
        "id": "SIG-Q4-FREIGHT",
        "kind": "freight_advisory",
        "severity": "MEDIUM",
        "matches": {"quarter": "Q4", "has_hardware": True},
        "title": "Q4 holiday freight advisory",
        "detail": "Carriers announce peak-season surcharges and 1-2 week transit delays for Nov-Dec hardware shipments.",
        "recommended_action": "Add freight buffer to any Q4 hardware delivery date.",
        "action": {"field": "promised_days", "op": "add", "value": 14},
        "source": "Freight advisory FA-2025-Q4",
        "issued": "2025-10-05",
    },
    {
        "id": "SIG-DISCOUNT-APPROVAL",
        "kind": "policy",
        "severity": "MEDIUM",
        "matches": {"discount_over": 35},
        "title": "Discount exceeds standing approval threshold",
        "detail": "Discounts above 35% require VP-level approval and a fixed-scope SOW to prevent services bleed.",
        "recommended_action": "Cap discount at 35% or route for VP approval; attach fixed-scope SOW.",
        "action": {"field": "discount_pct", "op": "max_cap", "value": 35},
        "source": "Deal-desk policy DDP-DISCOUNT",
        "issued": "2024-11-01",
    },
    {
        "id": "SIG-MISSIONCRIT-ARCH",
        "kind": "architecture_alert",
        "severity": "MEDIUM",
        "matches": {"sla_tier": "Mission-Critical", "has_hardware": False},
        "title": "Mission-Critical SLA without supporting architecture",
        "detail": "A 99.99% SLA on single-region SaaS is not architecturally backed and risks chronic credits.",
        "recommended_action": "Step SLA down to Enterprise, or require multi-region.",
        "action": {"field": "sla_tier", "op": "set", "value": "Enterprise"},
        "source": "Architecture guideline AG-SLA",
        "issued": "2025-02-20",
    },
]


def gather_signals(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return every signal whose match conditions apply to this draft."""
    hits = []
    vendor = draft.get("hw_vendor")
    region = draft.get("region") or ""
    vertical = draft.get("vertical")
    quarter = draft.get("signed_quarter")
    has_hw = bool(draft.get("has_hardware"))
    discount = draft.get("discount_pct") or 0
    sla = draft.get("sla_tier")

    for sig in SIGNALS:
        m = sig["matches"]
        ok = True
        if "vendor" in m and m["vendor"] != vendor:
            ok = False
        if "region_contains" in m and m["region_contains"] not in region:
            ok = False
        if "vertical_in" in m and vertical not in m["vertical_in"]:
            ok = False
        if "quarter" in m and m["quarter"] != quarter:
            ok = False
        if "has_hardware" in m and bool(m["has_hardware"]) != has_hw:
            ok = False
        if "discount_over" in m and not (discount > m["discount_over"]):
            ok = False
        if "sla_tier" in m and m["sla_tier"] != sla:
            ok = False
        if ok:
            hits.append(sig)
    return hits
