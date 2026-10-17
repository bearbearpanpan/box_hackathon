"""
handler.py — AWS Lambda entry point for the Bedrock agent action group.

Bedrock invokes this with an event describing which action (apiPath/function)
the model wants to call and the parameters. We route to the right tool and
return a response in the shape Bedrock expects.

Actions exposed (see openapi.yaml):
  POST /draft-contract     -> draft_contract.draft_contract
  POST /raise-risks        -> raise_risks.raise_risks
  POST /deep-research      -> deep_research.deep_research
  POST /analyze-and-report -> full Read->Check->Report pipeline

The handler also works when invoked directly (local tests / CLI) with a plain
dict event, so you can exercise it before deploying.
"""
from __future__ import annotations

import os
import sys
import json
from typing import Dict, Any

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "box")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "data")))

import draft_contract as draft_tool          # noqa: E402
import raise_risks as risk_tool              # noqa: E402
import deep_research as research_tool        # noqa: E402
import report as report_tool                 # noqa: E402


def _history():
    """Load deal history from Box (live) or local manifest (offline)."""
    from local_source import get_source
    src = get_source()
    if hasattr(src, "all_records"):   # LocalSource
        return src, src.all_records()
    # Live Box: pull metadata for all contracts in the folder.
    records = []
    for f in src.list_contracts():
        md = src.extract_metadata(f.id)
        md["contract_id"] = f.name.rsplit(".", 1)[0]
        records.append(md)
    return src, records


def run_action(action: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if action == "draft-contract":
        return draft_tool.draft_contract(params)

    if action == "raise-risks":
        src, history = _history()
        draft = params.get("draft") or _resolve_draft(src, params)
        return risk_tool.raise_risks(draft, history)

    if action == "deep-research":
        src, history = _history()
        draft = params.get("draft") or _resolve_draft(src, params)
        import comparison
        comps, _ = comparison.find_comparables(draft, history)
        return research_tool.deep_research(draft, comps)

    if action == "analyze-and-report":
        return analyze_and_report(params)

    if action == "run-workflow":
        import workflow
        return workflow.run_workflow(
            notes=params.get("notes", ""),
            hard_promises=params.get("hard_promises"),
            auto_upload=params.get("auto_upload", True),
            open_review=params.get("open_review", True),
        )

    if action == "get-review":
        import approvals
        rec = approvals.get_review(params["review_id"])
        return rec or {"error": f"review {params.get('review_id')} not found"}

    if action == "list-reviews":
        import approvals
        return {"reviews": approvals.list_reviews(params.get("status"))}

    if action == "resolve-review":
        import approvals
        return approvals.resolve_review(
            review_id=params["review_id"],
            decision=params["decision"],
            reviewer=params.get("reviewer", "reviewer"),
            note=params.get("note", ""),
            requested_changes=params.get("requested_changes"),
        )

    if action == "resume-workflow":
        import workflow
        return workflow.resume_from_review(
            review_id=params["review_id"],
            auto_upload=params.get("auto_upload", True),
        )

    raise ValueError(f"Unknown action: {action}")


def _resolve_draft(src, params: Dict[str, Any]) -> Dict[str, Any]:
    """Get the draft deal: either passed inline, drafted from params, or loaded
    by contract_id from the source."""
    if params.get("contract_id") and hasattr(src, "full_record"):
        rec = src.full_record(params["contract_id"])
        if rec:
            return rec
    return draft_tool.draft_contract(params)["draft"]


def analyze_and_report(params: Dict[str, Any]) -> Dict[str, Any]:
    """Full pipeline: Read -> Check -> Report (PDF + review task)."""
    src, history = _history()
    draft = params.get("draft") or _resolve_draft(src, params)

    risk = risk_tool.raise_risks(draft, history)

    import comparison
    comps, _ = comparison.find_comparables(draft, history)
    research = research_tool.deep_research(draft, comps)

    pdf_bytes = report_tool.buildPdf(risk, research)
    report_name = f"RealityCheck_{draft.get('contract_id','draft')}.pdf"
    file_id = src.upload_pdf(report_name, pdf_bytes)

    task = report_tool.createReviewTask(
        src, report_file_id=file_id, draft_id=draft.get("contract_id", "draft"),
        risk_level=risk["overall_risk"],
    )

    return {
        "headline": risk["headline"],
        "overall_risk": risk["overall_risk"],
        "report_file": file_id,
        "review_task": task,
        "risk_report": risk,
        "research": research,
    }


# ---- Bedrock agent event shape -------------------------------------------
def lambda_handler(event: Dict[str, Any], context=None) -> Dict[str, Any]:
    # Direct/local invocation: {"action": "...", "params": {...}}
    if "action" in event:
        result = run_action(event["action"], event.get("params", {}))
        return {"result": result}

    # Bedrock agent invocation
    api_path = (event.get("apiPath") or event.get("function") or "").lstrip("/")
    params = _bedrock_params(event)
    result = run_action(api_path, params)

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event.get("actionGroup"),
            "apiPath": event.get("apiPath"),
            "httpMethod": event.get("httpMethod", "POST"),
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {"body": json.dumps(result)}
            },
        },
    }


def _bedrock_params(event: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten Bedrock's parameter / requestBody shapes into a plain dict."""
    out: Dict[str, Any] = {}
    for p in event.get("parameters", []) or []:
        out[p.get("name")] = p.get("value")
    rb = event.get("requestBody", {}).get("content", {}).get("application/json", {})
    for prop in rb.get("properties", []) or []:
        out[prop.get("name")] = prop.get("value")
    return out


if __name__ == "__main__":
    # tiny CLI for local testing
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("action")
    ap.add_argument("--params", default="{}")
    a = ap.parse_args()
    print(json.dumps(run_action(a.action, json.loads(a.params)), indent=2, default=str))
