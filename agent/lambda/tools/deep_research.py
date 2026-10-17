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
    import logging
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "box")))
    from telemetry import get_logger, log_event, timed, emit_metric
    _log = get_logger("reality_check.bedrock")

    model_id = os.environ.get("BEDROCK_MODEL_ID")
    if not model_id or not os.environ.get("AWS_REGION"):
        log_event(_log, "bedrock.skipped", reason="not_configured")
        return ("[Bedrock not configured] Enable AWS_REGION + BEDROCK_MODEL_ID to "
                "generate a narrative research brief. Deterministic recommendations "
                "above are still fully usable.")
    try:
        import json
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
        # Give the Bedrock client resilient defaults (adaptive retries +
        # bounded timeouts) and a tagged User-Agent for cost attribution.
        bedrock_cfg = Config(
            retries={"max_attempts": 3, "mode": "adaptive"},
            connect_timeout=5,
            read_timeout=30,
            user_agent_extra="reality-check/observability",
        )
        client = boto3.client("bedrock-runtime",
                              region_name=os.environ["AWS_REGION"],
                              config=bedrock_cfg)
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
        with timed(_log, "bedrock.invoke_model", model_id=model_id,
                   max_tokens=body["max_tokens"]) as span:
            resp = client.invoke_model(modelId=model_id, body=json.dumps(body))
            payload = json.loads(resp["body"].read())
            # Capture token usage for cost/latency visibility when present.
            usage = payload.get("usage", {}) or {}
            span["input_tokens"] = usage.get("input_tokens")
            span["output_tokens"] = usage.get("output_tokens")
            emit_metric("BedrockInvoke", 1, "Count", model_id=model_id)
            if usage.get("input_tokens") is not None:
                emit_metric("BedrockInputTokens", usage["input_tokens"], "Count")
            if usage.get("output_tokens") is not None:
                emit_metric("BedrockOutputTokens", usage["output_tokens"], "Count")
            return payload["content"][0]["text"]
    except Exception as exc:  # pragma: no cover
        # Degrade to deterministic output (unchanged behavior) but make the
        # failure observable instead of only inlining it into the PDF text.
        log_event(_log, "bedrock.invoke_failed", level=logging.ERROR,
                  model_id=model_id, error=str(exc), error_type=type(exc).__name__)
        emit_metric("BedrockInvokeFailure", 1, "Count")
        return f"[Bedrock call failed: {exc}] Using deterministic recommendations only."


def deep_research(draft: Dict[str, Any], comparables: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    recs = _score_features(draft)
    brief = _bedrock_brief(draft, recs, comparables or [])
    return {
        "draft_id": draft.get("contract_id"),
        "recommended_features": recs[:6],
        "research_brief": brief,
    }
