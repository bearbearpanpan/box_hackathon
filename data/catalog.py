"""
catalog.py — the data model and reference data for generated tech-sales contracts.

Everything a contract is assembled from lives here: customers, products,
regions, suppliers/vendors, SLA tiers, and the deliberately *planted* risk
patterns the agent is meant to discover.

The planted patterns (so the demo has something real to find):

  1. "Hardware in Q4 slips."  Deals that include on-prem hardware/appliance
     line items and are signed in Q4 historically slip ~30-60% vs promise,
     because of the same supply-chain + holiday-freight dynamics as the rack
     deals. Pure-SaaS deals rarely slip.

  2. "Vendor 'Meridian' is the risky supplier."  Any deal whose hardware is
     sourced via Meridian Systems carries extra delay risk (PDU/appliance
     backorders). This mirrors RULES.md so the two datasets tell one story.

  3. "Aggressive discounts correlate with scope creep."  Deals discounted
     >35% tend to over-promise on professional-services timelines.

These are encoded as biases in generate_contracts.py, not hard rules, so the
history looks realistic (noisy) rather than synthetic-perfect.
"""
from __future__ import annotations

CUSTOMERS = [
    ("Northwind Traders", "Retail / E-commerce"),
    ("Contoso Manufacturing", "Industrial / IoT"),
    ("Fabrikam Media", "Media & Streaming"),
    ("Tailspin Logistics", "Transportation"),
    ("Adventure Works", "Travel / Hospitality"),
    ("Proseware Health", "Healthcare"),
    ("Wingtip Fintech", "Financial Services"),
    ("Litware Analytics", "Data / Analytics"),
    ("Alpine Energy", "Energy / Utilities"),
    ("Coho Vineyards", "Consumer Goods"),
    ("Blue Yonder Air", "Aviation"),
    ("Graphic Design Inst", "Education"),
    ("Humongous Insurance", "Insurance"),
    ("Lucerne Publishing", "Publishing"),
    ("Margie's Travel", "Travel / Hospitality"),
    ("Trey Research", "Pharma R&D"),
    ("VanArsdel Devices", "Consumer Electronics"),
    ("Woodgrove Bank", "Banking"),
    ("Fourth Coffee", "Food & Beverage"),
    ("Southridge Video", "Media & Streaming"),
]

REGIONS = [
    "US-East (Ashburn, VA)",
    "US-West (Hillsboro, OR)",
    "US-Central (Dallas, TX)",
    "EU-West (Dublin, IE)",
    "EU-Central (Frankfurt, DE)",
    "APAC (Singapore)",
    "APAC (Sydney)",
]

# Products: (sku, name, category, unit, list_price_per_unit)
# category is one of: saas, platform, hardware, services, support
PRODUCTS = [
    ("SKU-SAAS-CORE", "CloudSuite Core Platform (SaaS)", "saas", "per seat / yr", 1200),
    ("SKU-SAAS-ANLX", "InsightIQ Analytics (SaaS)", "saas", "per seat / yr", 1800),
    ("SKU-SAAS-SEC", "SentryShield Security (SaaS)", "saas", "per seat / yr", 2100),
    ("SKU-PLAT-API", "FlowEdge API Platform", "platform", "per 1M calls", 90),
    ("SKU-PLAT-DATA", "DataForge Lakehouse", "platform", "per TB / mo", 180),
    ("SKU-HW-APPL", "EdgeNode Appliance (on-prem)", "hardware", "per unit", 42000),
    ("SKU-HW-GPU", "AccelGrid GPU Rack", "hardware", "per rack", 215000),
    ("SKU-HW-STOR", "VaultArray Storage Node", "hardware", "per node", 68000),
    ("SKU-SVC-IMPL", "Implementation & Onboarding", "services", "fixed", 85000),
    ("SKU-SVC-MIGR", "Data Migration Services", "services", "fixed", 120000),
    ("SKU-SVC-TAM", "Technical Account Management", "support", "per yr", 60000),
]

# Hardware vendors. "Meridian Systems" is the planted-risk supplier.
HW_VENDORS = [
    "Meridian Systems",   # risky one
    "Vortex Hardware",
    "Apex Compute",
    "Cascade Devices",
]

SLA_TIERS = [
    # (name, uptime, support_response, credits)
    ("Standard", "99.5%", "Next business day", "5% monthly credit per 0.5% miss"),
    ("Business", "99.9%", "4 business hours", "10% monthly credit per 0.1% miss"),
    ("Enterprise", "99.95%", "1 hour, 24x7", "15% monthly credit per 0.05% miss"),
    ("Mission-Critical", "99.99%", "15 minutes, 24x7", "25% monthly credit per 0.01% miss"),
]

PAYMENT_TERMS = ["Net 30", "Net 45", "Net 60", "Annual prepay", "Quarterly in advance"]

TERM_LENGTHS_MONTHS = [12, 24, 36]

QUARTERS = ["Q1", "Q2", "Q3", "Q4"]

# Catalog of candidate "features we could offer" — used by the deep_research
# tool to suggest upsell / expansion options based on the drafted deal.
FEATURE_CATALOG = [
    ("Single Sign-On (SAML/OIDC)", "security", "Common enterprise requirement; low lift, high close-rate impact."),
    ("Private networking / VPC peering", "security", "Often needed by regulated customers (fintech, health, insurance)."),
    ("Data residency guarantee", "compliance", "Required for EU/APAC regions; ties to region of deployment."),
    ("Dedicated tenancy", "platform", "Premium isolation; strong margin, pairs with Enterprise SLA."),
    ("Advanced analytics add-on", "saas", "Natural upsell on top of Core; expands seat value."),
    ("24x7 premium support", "support", "Attach to any deal lacking Mission-Critical SLA."),
    ("Managed migration", "services", "Reduces time-to-value; de-risks onboarding timeline."),
    ("Usage-based burst capacity", "platform", "Appeals to spiky workloads (media, retail peaks)."),
    ("Compliance pack (SOC2/HIPAA/PCI)", "compliance", "Unlocks regulated verticals; required for health/fintech/insurance."),
    ("Sandbox / non-prod environment", "platform", "Low-cost add; improves adoption and reduces churn."),
]

# Risk register the raise_risks tool draws from, keyed by trigger condition.
RISK_LIBRARY = [
    {
        "id": "R-DELIVERY-Q4-HW",
        "title": "Aggressive delivery promise on Q4 hardware deal",
        "severity": "HIGH",
        "trigger": "has_hardware and quarter == 'Q4' and promised_days < 90",
        "detail": (
            "On-prem hardware signed in Q4 has historically slipped 30-60% vs "
            "the promised date due to supply-chain backorders and holiday "
            "freight. Promising under 90 days exposes the deal to SLA credits."
        ),
        "mitigation": "Rebaseline delivery to >= 90 days or stage the hardware portion.",
    },
    {
        "id": "R-VENDOR-MERIDIAN",
        "title": "Hardware sourced via Meridian Systems",
        "severity": "HIGH",
        "trigger": "hw_vendor == 'Meridian Systems'",
        "detail": (
            "Meridian Systems has a documented pattern of appliance/PDU "
            "backorders. Lead-time quotes from this vendor behave as a floor, "
            "not an estimate."
        ),
        "mitigation": "Add explicit vendor-delay buffer; make PDU/appliance line item drive the committed date.",
    },
    {
        "id": "R-DISCOUNT-SCOPE",
        "title": "Deep discount correlated with scope creep",
        "severity": "MEDIUM",
        "trigger": "discount_pct > 35",
        "detail": (
            "Deals discounted beyond 35% historically over-commit on "
            "professional-services scope and timelines, eroding margin."
        ),
        "mitigation": "Fix services scope in a signed SOW; cap included hours.",
    },
    {
        "id": "R-SLA-MISMATCH",
        "title": "SLA tier exceeds deployed architecture",
        "severity": "MEDIUM",
        "trigger": "sla_tier in ('Mission-Critical',) and not has_hardware",
        "detail": (
            "A 99.99% commitment on a single-region SaaS deployment is not "
            "architecturally backed and risks chronic credit payouts."
        ),
        "mitigation": "Require multi-region/active-active or step the SLA down to Enterprise.",
    },
    {
        "id": "R-DATA-RESIDENCY",
        "title": "Regulated vertical without data-residency / compliance pack",
        "severity": "MEDIUM",
        "trigger": "regulated and not compliance_pack",
        "detail": (
            "Customer is in a regulated vertical (health / fintech / insurance / "
            "banking) but the deal lacks a compliance pack or residency guarantee."
        ),
        "mitigation": "Attach Compliance pack and Data residency guarantee before signature.",
    },
    {
        "id": "R-PAYMENT-RISK",
        "title": "Long payment terms on large TCV",
        "severity": "LOW",
        "trigger": "payment_terms in ('Net 60',) and tcv > 1_000_000",
        "detail": "Net 60 on a >$1M contract increases DSO and collection exposure.",
        "mitigation": "Negotiate annual prepay or milestone billing.",
    },
]

REGULATED_VERTICALS = {
    "Healthcare", "Financial Services", "Insurance", "Banking", "Pharma R&D",
}
