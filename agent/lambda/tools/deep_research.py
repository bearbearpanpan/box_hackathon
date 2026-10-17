"""
deep_research.py — tool: deep research into features/offerings for a deal.

Two layers:
  1. Deterministic recommendations from the FEATURE_CATALOG, scored against the
     draft deal (vertical, region, SLA, hardware, size). Always available, even
     offline — this is what makes the demo reliable.
  2. Optional LLM-enriched narrative via Bedrock (if configured) that reads the
     comparable-deal history and writes a short "what we could offer and why"
     brief. Falls back gracefully when Bedrock isn't wired yet.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))


def _score_features(draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    import catalog as C  # type: ignore

    recs = []
    vertical = draft.get("vertical", "")
    regulated = bool(draft.get("regulated"))
    region = draft.get("region", "")
    sla = draft.get("sla_tier", "")
    has_hw = bool(draft.get("has_hardware"))
    tcv = draft.get("tcv") or 0

    for name, cat, rationale in C.FEATURE_CATALOG:
        score = 1.0
        reasons = []
        if cat == "compliance" and regulated:
            score += 3; reasons.append("customer is in a regulated vertical")
        if "residency" in name.lower() and ("EU" in region or "APAC" in region):
            score += 2; reasons.append("non-US deployment region")
        if "support" in cat and sla != "Mission-Critical":
            score += 1.5; reasons.append("deal lacks top-tier support")
        if cat == "services" and has_hw:
            score += 1.5; reasons.append("hardware deals benefit from managed migration")
        if cat == "platform" and tcv > 500_000:
            score += 1; reasons.append("large TCV supports premium platform add-ons")
        if cat == "saas":
            score += 0.5; reasons.append("natural expansion of core SaaS footprint")

        recs.append({
            "feature": name,
            "category": cat,
            "fit_score": round(score, 1),
            "why": rationale,
            "deal_specific_reasons": reasons,
        })

    recs.sort(key=lambda r: r["fit_score"], reverse=True)
    return recs


def _bedrock_brief(draft: Dict[str, Any], recs: List[Dict[str, Any]], comparables: List[Dict[str, Any]]) -> str:
    """Optional: ask a Bedrock model to write a short brief. No-op if unset."""
    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id or not os.environ.get("AWS_REGION"):
        return ("[Bedrock not configured] Enable AWS_REGION + BEDROCK_MODEL_ID to "
                "generate a narrative research brief. Deterministic recommendations "
                "above are still fully usable.")
    try:
        import json
        import boto3  # type: ignore
        client = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
        top = recs[:5]
        prompt = (
            "You are a solutions consultant. Given this draft tech-sales deal and "
            "the top recommended add-on features, write a concise 150-word brief on "
            "what to offer and why, referencing the customer's vertical and region.\n\n"
            f"Deal: {json.dumps({k: draft.get(k) for k in ('customer','vertical','region','sla_tier','tcv','has_hardware')})}\n"
            f"Top features: {json.dumps(top)}\n"
            f"Comparable past deals: {json.dumps(comparables)}\n"
        )
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 400,
            "messages": [{"role": "user", "content": prompt}],
        }
        resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        return payload["content"][0]["text"]
    except Exception as exc:  # pragma: no cover
        return f"[Bedrock call failed: {exc}] Using deterministic recommendations only."


def deep_research(draft: Dict[str, Any], comparables: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    recs = _score_features(draft)
    brief = _bedrock_brief(draft, recs, comparables or [])
    return {
        "draft_id": draft.get("contract_id"),
        "recommended_features": recs[:6],
        "research_brief": brief,
    }
