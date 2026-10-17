"""
notes_parser.py — turn free-text sales meeting notes into structured deal params.

Two paths:
  * Deterministic extractor (always on, offline): regex/keyword matching against
    the known catalog (customers, regions, products, SLAs, vendors, quarters,
    numbers like seats / discount / promised days). Reliable for the demo.
  * Optional Bedrock extractor: for messy notes, ask the model to emit the same
    JSON shape. Falls back to the deterministic result if Bedrock isn't wired.

Output matches the params that draft_contract.draft_contract expects.
"""
from __future__ import annotations

import os
import re
import sys
import json
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))


def _catalog():
    import catalog as C  # type: ignore
    return C


def parse_notes(notes: str) -> Dict[str, Any]:
    """Deterministic first; optionally enrich with Bedrock. Returns deal params."""
    base = _rule_based(notes)
    enriched = _bedrock_extract(notes, base)
    # Bedrock result (if any) wins on fields it filled; otherwise keep base.
    merged = dict(base)
    for k, v in (enriched or {}).items():
        if v not in (None, "", []):
            merged[k] = v
    merged["_source_notes"] = notes.strip()
    return merged


def _rule_based(notes: str) -> Dict[str, Any]:
    C = _catalog()
    # normalize whitespace so line-wrapped multi-word names ("Meridian\nSystems")
    # still match, and keep a lowercased copy for keyword checks.
    text = re.sub(r"\s+", " ", notes)
    low = text.lower()
    params: Dict[str, Any] = {}

    # Customer (match any known customer name, else first capitalized org-ish phrase)
    for name, vertical in C.CUSTOMERS:
        if name.lower() in low:
            params["customer"] = name
            params["vertical"] = vertical
            break
    # Capture an unknown customer name from a "Sales call - <Name> (...)" header.
    if "customer" not in params:
        m = re.search(r"(?:sales call|meeting|call)\s*[\u2014\-:]*\s*([A-Z][\w&.' ]+?)\s*[\(,\u2014\-]", text)
        if m:
            params["customer"] = m.group(1).strip()

    # Vertical inference from industry keywords (independent of customer match).
    if "vertical" not in params:
        vmap = [
            (["fintech", "financial services", "payments", "trading"], "Financial Services"),
            (["health", "hospital", "clinical", "patient"], "Healthcare"),
            (["insurance", "insurer", "claims"], "Insurance"),
            (["bank", "banking"], "Banking"),
            (["pharma", "biotech", "drug"], "Pharma R&D"),
            (["retail", "e-commerce", "ecommerce"], "Retail / E-commerce"),
            (["media", "streaming", "video"], "Media & Streaming"),
            (["logistics", "shipping", "freight carrier"], "Transportation"),
            (["colo", "data center", "datacenter", "hyperscale"], "Technology"),
        ]
        for kws, v in vmap:
            if any(k in low for k in kws):
                params["vertical"] = v
                break

    # Region
    for region in C.REGIONS:
        # match on the metro keyword inside the region label
        metro = re.search(r"\(([^)]+)\)", region)
        key = metro.group(1).split(",")[0].lower() if metro else region.lower()
        if key in low or region.lower() in low:
            params["region"] = region
            break
    # also catch bare "EU" / "APAC" / "us-east" style mentions
    if "region" not in params:
        for hint, region in [("ashburn", 0), ("virginia", 0), ("eu", 3),
                             ("europe", 3), ("frankfurt", 4), ("singapore", 5),
                             ("apac", 5), ("sydney", 6), ("dallas", 2),
                             ("hillsboro", 1), ("oregon", 1)]:
            if hint in low:
                params["region"] = C.REGIONS[region]
                break

    # Quarter
    m = re.search(r"\bq([1-4])\b", low)
    if m:
        params["signed_quarter"] = f"Q{m.group(1)}"
    elif any(w in low for w in ["december", "november", "holiday", "year-end", "end of year"]):
        params["signed_quarter"] = "Q4"

    # SLA tier — numeric uptime first (most explicit), then whole-word tier name.
    if "99.99" in low or "four nines" in low or "mission-critical" in low or "mission critical" in low:
        params["sla_tier"] = "Mission-Critical"
    elif "99.95" in low:
        params["sla_tier"] = "Enterprise"
    elif "99.9" in low:
        params["sla_tier"] = "Business"
    else:
        for name, *_ in C.SLA_TIERS:
            # whole-word match so "standardized" doesn't match "Standard"
            if re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
                params["sla_tier"] = name
                break

    # Discount — find a percentage that is explicitly tied to the word
    # "discount" or "off". We only look at "%" tokens whose nearby context
    # mentions discounting, which keeps SLA uptime figures (99.9%) out.
    disc = None
    for m in re.finditer(r"(\d{1,2})\s*%", low):
        ctx = low[max(0, m.start() - 18): m.end() + 12]
        if "discount" in ctx or re.search(r"\boff\b", ctx):
            disc = int(m.group(1))
            break
    if disc is not None:
        params["discount_pct"] = disc

    # Timeline flexibility signal: rep said no hard date.
    if any(w in low for w in ["no rush", "flexible", "whenever", "no hurry", "sometime"]):
        params["_timeline_flexible"] = True

    # Promised days / timeline
    m = re.search(r"(\d{1,3})\s*(?:day|days)\b", low)
    if m and any(w in low for w in ["deliver", "go live", "go-live", "promise", "timeline", "within", "by"]):
        params["promised_days"] = int(m.group(1))
    elif re.search(r"(\d{1,2})\s*weeks?", low):
        wk = int(re.search(r"(\d{1,2})\s*weeks?", low).group(1))
        if any(w in low for w in ["deliver", "go live", "go-live", "promise", "timeline", "within", "by"]):
            params["promised_days"] = wk * 7

    # Hardware vendor
    for v in C.HW_VENDORS:
        if v.lower() in low:
            params["hw_vendor"] = v
            break

    # Line items — map product keywords to SKUs. Order matters: more specific
    # keywords first so "GPU rack" wins before the generic "seats" catch-all.
    # default_qty is used only when no explicit count is found near the keyword.
    items: List[Dict[str, Any]] = []
    kw_to_sku = [
        (["analytics", "insightiq"], "SKU-SAAS-ANLX", 100),
        (["security", "sentryshield", "sentry"], "SKU-SAAS-SEC", 100),
        (["api platform", "flowedge"], "SKU-PLAT-API", 10),
        (["lakehouse", "dataforge", "data platform"], "SKU-PLAT-DATA", 10),
        (["gpu rack", "accelgrid", "gpu"], "SKU-HW-GPU", 1),
        (["appliance", "edgenode"], "SKU-HW-APPL", 1),
        (["storage node", "vaultarray", "storage"], "SKU-HW-STOR", 1),
        (["migration", "migrate"], "SKU-SVC-MIGR", 1),
        (["implementation", "onboarding", "onboard"], "SKU-SVC-IMPL", 1),
        (["core platform", "cloudsuite", "seats", "seat", "licenses", "users"], "SKU-SAAS-CORE", 100),
    ]
    seen = set()
    for kws, sku, default_qty in kw_to_sku:
        for kw in kws:
            if kw in low and sku not in seen:
                qty = _qty_for(low, kw, default_qty)
                items.append({"sku": sku, "qty": qty})
                seen.add(sku)
                break
    if items:
        params["line_items"] = items

    # Compliance mention
    if any(w in low for w in ["compliance", "soc2", "soc 2", "hipaa", "pci", "residency"]):
        params["compliance_pack"] = True

    return params


def _qty_for(low: str, kw: str, default: int) -> int:
    """
    Find the count for a line item. Prefer a number that DIRECTLY precedes the
    keyword (e.g. "2 GPU racks", "250 seats", "2 AccelGrid GPU racks"), which is
    how people actually write quantities. Fall back to the keyword's default
    rather than grabbing an unrelated nearby number.
    """
    idx = low.find(kw)
    if idx == -1:
        return default
    # look back up to ~25 chars for "<number> [adjective words] <kw>"
    prefix = low[max(0, idx - 25): idx]
    m = re.findall(r"(\d{1,5})(?:\s+[a-z]+){0,3}\s*$", prefix.replace(",", ""))
    if m:
        return int(m[-1])
    return default


def _bedrock_extract(notes: str, base: Dict[str, Any]) -> Dict[str, Any]:
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id or not os.environ.get("AWS_REGION"):
        return {}
    try:
        import boto3  # type: ignore
        C = _catalog()
        client = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
        skus = [p[0] for p in C.PRODUCTS]
        prompt = (
            "Extract tech-sales deal parameters from these meeting notes. Return "
            "ONLY compact JSON with keys: customer, vertical, region, "
            "signed_quarter, sla_tier, discount_pct, promised_days, hw_vendor, "
            "compliance_pack (bool), line_items (list of {sku, qty}). "
            f"Valid SKUs: {skus}. Use null if unknown.\n\nNOTES:\n{notes}"
        )
        body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}]}
        resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        raw = payload["content"][0]["text"]
        return json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception:
        return {}
