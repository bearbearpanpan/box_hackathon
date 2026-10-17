"""
Feature 2 (part a) — the clause / fallback playbook.

A machine-readable library mapping each risk condition to approved replacement
("fallback") contract language. This is what powers auto-redlining: instead of
"timeline too aggressive," the agent proposes the actual clause edit. Market
analog: Sirion/Harvey fallback clause libraries + playbook redlining.

In production this is versioned config a legal admin edits. Here it's a module.
"""
from __future__ import annotations

CLAUSES = {
    "delivery_timeline": {
        "standard": (
            "Provider shall deliver and commission the ordered systems within "
            "{days} days of the Effective Date."
        ),
        "fallback": (
            "Provider shall use commercially reasonable efforts to deliver within "
            "{days} days of the Effective Date. For orders including on-prem "
            "hardware signed in Q4, the committed date reflects vendor lead times "
            "and seasonal freight; milestone dates are set in the applicable SOW."
        ),
    },
    "vendor_delay": {
        "fallback": (
            "Where hardware is sourced through a third-party vendor, delivery "
            "milestones are contingent on that vendor's confirmed lead time. "
            "Provider will notify Customer within 5 business days of any vendor "
            "delay notice and the parties will rebaseline the schedule in good faith."
        ),
    },
    "sla_credits": {
        "fallback": (
            "Service credits for the {tier} tier are capped at {cap}% of the "
            "monthly fee and are Customer's sole remedy for availability misses."
        ),
    },
    "liquidated_damages": {
        "fallback": (
            "If delivery slips beyond {grace} days due to vendor backorder, "
            "Provider's liability is limited to the vendor-backed liquidated "
            "damages passed through under the applicable purchase order."
        ),
    },
    "compliance_pack": {
        "fallback": (
            "Provider will include the applicable Compliance Pack "
            "(SOC 2 / HIPAA / PCI as relevant) and, for EU/APAC deployments, a "
            "data-residency guarantee for in-region processing."
        ),
    },
    "discount_approval": {
        "fallback": (
            "Discounts above {threshold}% require documented VP approval and a "
            "fixed-scope Statement of Work; included professional-services hours "
            "are capped as set out therein."
        ),
    },
}

# Map a risk/signal id to the clause remedy it triggers.
RISK_TO_CLAUSE = {
    "R-HISTORY-TIMELINE": "delivery_timeline",
    "R-DELIVERY-Q4-HW": "delivery_timeline",
    "R-VENDOR-MERIDIAN": "vendor_delay",
    "SIG-MERIDIAN-Q4-DELAY": "vendor_delay",
    "SIG-MERIDIAN-SLA-HISTORY": "liquidated_damages",
    "SIG-Q4-FREIGHT": "delivery_timeline",
    "R-SLA-MISMATCH": "sla_credits",
    "SIG-MISSIONCRIT-ARCH": "sla_credits",
    "R-DATA-RESIDENCY": "compliance_pack",
    "SIG-EU-RESIDENCY": "compliance_pack",
    "SIG-REGULATED-COMPLIANCE": "compliance_pack",
    "R-DISCOUNT-SCOPE": "discount_approval",
    "SIG-DISCOUNT-APPROVAL": "discount_approval",
}
