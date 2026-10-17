"""
workflow.py — the fully agentic deal workflow with human-in-the-loop.

    meeting notes
        -> extract deal intent
        -> draft contract (v1)
        -> review & flag risks (deal history + static rules + external signals)
        -> revise draft (auto-fix what's safe)
        -> loop until: converged, OR human approval required, OR max iterations
        -> if human needed: open a REVIEW PACKAGE (reviewer opens the doc)
        -> reviewer approves / rejects / requests changes
        -> workflow RESUMES from the decision and loops again if needed
        -> emit final report PDF + review task, with a full iteration log

"Converged"  = after revision, no HIGH risks AND no escalations remain.
"Needs human"= escalations the agent may not resolve itself (e.g. a hard
               customer promise conflicting with history/supplier reality).

Everything runs offline against the generated history + review store, so the
whole human-in-the-loop cycle is demoable before any keys are set.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "box")))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "data")))

import notes_parser          # noqa: E402
import draft_contract        # noqa: E402
import raise_risks           # noqa: E402
import deep_research         # noqa: E402
import comparison            # noqa: E402
import revise as reviser     # noqa: E402
import report as report_tool  # noqa: E402
import risk_signals          # noqa: E402
import approvals             # noqa: E402

from telemetry import get_logger, log_event, emit_metric  # noqa: E402

_log = get_logger("reality_check.workflow")

MAX_ITERATIONS = 5


def _log_loop_outcome(entry: str, status: str, iterations: List[Dict[str, Any]]) -> None:
    """Emit the agentic-loop KPIs — the numbers operations actually cares about:
    how many passes it took, where it ended up, and whether a human was needed.
    Pure telemetry; does not touch the workflow result."""
    final = iterations[-1] if iterations else {}
    final_risk = final.get("overall_risk")
    escalations = len(final.get("escalations", []))
    log_event(_log, "workflow.outcome", entry=entry, status=status,
              iterations_run=len(iterations), final_risk=final_risk,
              open_escalations=escalations)
    emit_metric("WorkflowRun", 1, "Count", status=status)
    emit_metric("WorkflowIterations", len(iterations), "Count")
    if status == "needs_human_approval":
        emit_metric("WorkflowNeedsHuman", 1, "Count")
    if final_risk:
        emit_metric("WorkflowFinalRisk", 1, "Count", risk=final_risk)


def _history():
    from local_source import get_source
    src = get_source()
    if hasattr(src, "all_records"):
        return src, src.all_records()
    records = []
    for f in src.list_contracts():
        md = src.extract_metadata(f.id)
        md["contract_id"] = f.name.rsplit(".", 1)[0]
        records.append(md)
    return src, records


# ---------------------------------------------------------------------------
# Core loop (resumable)
# ---------------------------------------------------------------------------
def _iterate(draft: Dict[str, Any], history: List[Dict[str, Any]],
             hard_promises: Dict[str, Any], start_iter: int = 1,
             prior_iterations: Optional[List[Dict[str, Any]]] = None,
             acknowledged: Optional[set] = None):
    """
    Run the review/revise loop from `draft`. Returns
    (status, draft, iterations). status is one of:
      converged | needs_human_approval | max_iterations_reached

    `acknowledged` is a set of signal/risk ids a reviewer has already accepted;
    advisory items in that set no longer block the loop (they're recorded as
    acknowledged notes), which is what lets a resumed workflow actually finish.
    """
    iterations = list(prior_iterations or [])
    acknowledged = acknowledged or set()

    for i in range(start_iter, MAX_ITERATIONS + 1):
        risk_report = raise_risks.raise_risks(draft, history)
        signals = risk_signals.gather_signals(draft)
        rev = reviser.revise(draft, risk_report, signals, hard_promises, acknowledged)

        iterations.append({
            "iteration": i,
            "overall_risk": risk_report["overall_risk"],
            "headline": risk_report["headline"],
            "signals_found": [{"id": s["id"], "title": s["title"], "severity": s["severity"]} for s in signals],
            "changes_made": rev["changes"],
            "escalations": rev["escalations"],
            "acknowledged_notes": rev.get("acknowledged_notes", []),
            "draft_snapshot": {
                "promised_days": draft.get("promised_days"),
                "sla_tier": draft.get("sla_tier"),
                "compliance_pack": draft.get("compliance_pack"),
                "discount_pct": draft.get("discount_pct"),
                "hw_vendor": draft.get("hw_vendor"),
            },
        })

        # Only unacknowledged escalations block. On the first pass nothing is
        # acknowledged, so the reviewer sees the full list; after they resolve,
        # the acknowledged set clears the advisory ones.
        blocking = [e for e in rev["escalations"]]
        if blocking:
            return "needs_human_approval", rev["revised_draft"], iterations
        if not rev["changes"]:
            return "converged", draft, iterations
        draft = rev["revised_draft"]

    return "max_iterations_reached", draft, iterations


def _finalize(src, draft, history, iterations, status):
    """Build the final report + review task; return the result payload."""
    final_risk = raise_risks.raise_risks(draft, history)
    comps, _ = comparison.find_comparables(draft, history)
    research = deep_research.deep_research(draft, comps)

    pdf = report_tool.buildPdf(final_risk, research)
    name = f"RealityCheck_{draft.get('contract_id','draft')}_v{len(iterations)}.pdf"
    report_file = src.upload_pdf(name, pdf)
    assignee = "deal-desk" if status == "needs_human_approval" else "auto-approved"
    review_task = report_tool.createReviewTask(
        src, report_file_id=report_file, draft_id=draft.get("contract_id", "draft"),
        risk_level=final_risk["overall_risk"], assignee=assignee,
    )
    return final_risk, research, report_file, review_task


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def run_workflow(notes: str, hard_promises: Dict[str, Any] | None = None,
                 auto_upload: bool = True, open_review: bool = True) -> Dict[str, Any]:
    """
    Drive the loop from meeting notes. If it needs a human and `open_review` is
    True, it creates a pending review package and returns status
    'pending_review' with a review_id the reviewer can open/resolve.
    """
    src, history = _history()

    params = notes_parser.parse_notes(notes)

    if hard_promises is None:
        hard_promises = {}
        if params.get("promised_days") and any(
            w in notes.lower() for w in
            ["promised", "committed", "guarantee", "insist", "hard date", "no later", "non-negotiable", "adamant"]
        ):
            hard_promises["promised_days"] = params["promised_days"]

    drafted = draft_contract.draft_contract(params)
    draft = drafted["draft"]

    if draft.get("timeline_is_default") and "promised_days" not in hard_promises:
        comps0, _ = comparison.find_comparables(draft, history)
        safe = comparison.suggested_timeline(draft, comps0).get("suggested_days")
        if safe and safe > (draft.get("promised_days") or 0):
            draft["promised_days"] = safe

    status, draft, iterations = _iterate(draft, history, hard_promises)

    _log_loop_outcome("run_workflow", status, iterations)

    result = {
        "status": status,
        "iterations_run": len(iterations),
        "extracted_params": params,
        "hard_promises": hard_promises,
        "final_draft": draft,
        "iteration_log": iterations,
        "open_escalations": iterations[-1]["escalations"] if iterations else [],
    }

    if status == "needs_human_approval" and open_review:
        return _open_review(src, draft, history, hard_promises, iterations, result)

    if auto_upload:
        final_risk, research, report_file, review_task = _finalize(src, draft, history, iterations, status)
        result.update({
            "final_risk": final_risk["overall_risk"],
            "final_headline": final_risk["headline"],
            "report_file": report_file,
            "review_task": review_task,
            "research_brief": research.get("research_brief"),
        })
    return result


def _open_review(src, draft, history, hard_promises, iterations, result):
    """Create a review package a human can open and resolve, then pause."""
    final_risk, research, report_file, _ = _finalize(src, draft, history, iterations, "needs_human_approval")
    escalations = iterations[-1]["escalations"] if iterations else []
    # proposed changes = concrete field overrides the agent recommends
    proposed = _proposed_changes(draft, escalations)
    pkg = approvals.create_review({
        "draft_id": draft.get("contract_id", "draft"),
        "draft": draft,
        "risk_level": final_risk["overall_risk"],
        "headline": final_risk["headline"],
        "escalations": escalations,
        "proposed_changes": proposed,
        "report_file": report_file,
        "iteration_log": iterations,
        "assignee": "deal-desk",
    })
    result.update({
        "status": "pending_review",
        "review_id": pkg["review_id"],
        "review_url": pkg["review_url"],
        "final_risk": final_risk["overall_risk"],
        "final_headline": final_risk["headline"],
        "report_file": report_file,
        "proposed_changes": proposed,
        "message": (
            f"Draft needs human approval. Review {pkg['review_id']} opened for "
            f"{pkg['assignee']}. Open it, then approve / reject / request changes."
        ),
    })
    return result


def _proposed_changes(draft, escalations) -> List[Dict[str, Any]]:
    """Translate escalations into concrete field overrides the reviewer can
    accept with one click (the 'safer' version of the deal)."""
    changes = []
    for e in escalations:
        nh = e.get("needs_human", "")
        # pull a ">= N days" recommendation into a concrete promised_days
        import re
        m = re.search(r">=\s*(\d+)\s*days", nh) or re.search(r"toward\s*(\d+)\s*days", nh)
        if m:
            changes.append({"field": "promised_days", "to": int(m.group(1)),
                            "reason": e.get("issue")})
    # de-dup to the largest (safest) proposed timeline
    days = [c["to"] for c in changes if c["field"] == "promised_days"]
    out = []
    if days:
        out.append({"field": "promised_days", "to": max(days),
                    "reason": "Align promised date with supplier/history reality."})
    return out


def resume_from_review(review_id: str, auto_upload: bool = True) -> Dict[str, Any]:
    """
    Continue the workflow after a reviewer has resolved the review.
      APPROVED           -> finalize as-is (reviewer accepted the risk/draft).
      REJECTED           -> close the deal workflow (no contract produced).
      CHANGES_REQUESTED  -> apply the requested changes (or the agent's proposed
                            ones) and run the loop again.
    """
    record = approvals.get_review(review_id)
    if record is None:
        return {"error": f"review {review_id} not found"}
    if record["status"] == "PENDING_REVIEW":
        return {"status": "still_pending",
                "message": f"Review {review_id} has not been resolved yet."}

    src, history = _history()
    draft = dict(record["draft"])
    decision = record.get("decision")

    if decision == "reject":
        return {"status": "rejected", "review_id": review_id,
                "reviewer_note": record.get("reviewer_note"),
                "message": "Reviewer rejected the draft. No contract produced."}

    if decision == "approve":
        # Reviewer accepted the draft (and any residual risk) as-is.
        final_risk, research, report_file, review_task = _finalize(
            src, draft, history, record.get("iteration_log", []), "approved")
        return {
            "status": "approved",
            "review_id": review_id,
            "final_draft": draft,
            "final_risk": final_risk["overall_risk"],
            "final_headline": final_risk["headline"],
            "report_file": report_file,
            "review_task": review_task,
            "reviewer_note": record.get("reviewer_note"),
            "message": "Reviewer approved. Final contract + report issued.",
        }

    # CHANGES_REQUESTED: apply overrides, then loop again.
    overrides = record.get("requested_changes") or {}
    applied = []
    if overrides.get("accept_proposed"):
        for c in record.get("proposed_changes", []):
            draft[c["field"]] = c["to"]
            applied.append(f"{c['field']} -> {c['to']} (accepted agent proposal)")
    for k, v in overrides.items():
        if k == "accept_proposed":
            continue
        draft[k] = v
        applied.append(f"{k} -> {v} (reviewer override)")

    # Once the reviewer sets a timeline, it becomes the new hard promise so the
    # agent treats it as approved rather than re-escalating it.
    hard_promises = {}
    if "promised_days" in draft:
        hard_promises["promised_days"] = draft["promised_days"]

    # Everything the reviewer already saw in the prior review is "acknowledged":
    # by requesting changes they signed off on proceeding with the known risks.
    acknowledged = set()
    for it in record.get("iteration_log", []):
        for e in it.get("escalations", []):
            acknowledged.add(e.get("source"))

    status, draft, iterations = _iterate(
        draft, history, hard_promises,
        start_iter=len(record.get("iteration_log", [])) + 1,
        prior_iterations=record.get("iteration_log", []),
        acknowledged=acknowledged,
    )

    _log_loop_outcome("resume_from_review", status, iterations)

    result = {
        "status": status,
        "review_id": review_id,
        "applied_changes": applied,
        "iterations_run": len(iterations),
        "final_draft": draft,
        "iteration_log": iterations,
    }

    if status == "needs_human_approval":
        # still not clean -> open a NEW review round
        return _open_review(src, draft, history, hard_promises, iterations, result)

    if auto_upload:
        final_risk, research, report_file, review_task = _finalize(src, draft, history, iterations, status)
        result.update({
            "final_risk": final_risk["overall_risk"],
            "final_headline": final_risk["headline"],
            "report_file": report_file,
            "review_task": review_task,
            "message": "Changes applied; draft now clears review automatically.",
        })
    return result
