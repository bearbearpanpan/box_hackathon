"""
workflow.py — the fully agentic deal workflow.

    meeting notes
        -> extract deal intent
        -> draft contract (v1)
        -> review & flag risks (deal history + static rules + external signals)
        -> revise draft (auto-fix what's safe)
        -> loop until converged OR human approval is required OR max iterations
        -> emit final report PDF + review task, with a full iteration log

"Converged" = after revision, no HIGH risks remain AND no escalations remain.
"Needs human" = escalations exist that the agent is not allowed to resolve on
its own (e.g. a hard customer promise that conflicts with history/supplier
reality, or a risk with no machine-applicable fix).

The whole loop runs offline against the generated history, so it's demoable
before any keys are set.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, Any, List

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

MAX_ITERATIONS = 5


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


def run_workflow(notes: str, hard_promises: Dict[str, Any] | None = None,
                 auto_upload: bool = True) -> Dict[str, Any]:
    """Drive the full loop. `hard_promises` are rep commitments the agent must
    not soften without human approval (often inferred from the notes)."""
    src, history = _history()

    # [1] Extract deal intent from the meeting notes.
    params = notes_parser.parse_notes(notes)

    # Infer hard promises from the notes if not supplied: a timeline the rep
    # explicitly promised the customer is a commitment, not a suggestion.
    if hard_promises is None:
        hard_promises = {}
        if params.get("promised_days") and any(
            w in notes.lower() for w in ["promised", "committed", "guarantee", "insist", "hard date", "no later"]
        ):
            hard_promises["promised_days"] = params["promised_days"]

    # [2] Draft v1.
    drafted = draft_contract.draft_contract(params)
    draft = drafted["draft"]

    # If the rep gave no hard date (timeline defaulted or explicitly flexible),
    # propose a REALISTIC timeline up front using comparable history, rather than
    # inventing an aggressive date and then flagging ourselves for it. Extending
    # a non-committed timeline is always safe, so this needs no human approval.
    if draft.get("timeline_is_default") and "promised_days" not in hard_promises:
        comps0, _ = comparison.find_comparables(draft, history)
        tl0 = comparison.suggested_timeline(draft, comps0)
        safe = tl0.get("suggested_days")
        if safe and safe > (draft.get("promised_days") or 0):
            draft["promised_days"] = safe

    iterations: List[Dict[str, Any]] = []
    status = "in_progress"

    for i in range(1, MAX_ITERATIONS + 1):
        # [3] Review & flag.
        risk_report = raise_risks.raise_risks(draft, history)
        signals = risk_signals.gather_signals(draft)

        # [4] Revise (auto-fix what's safe; collect escalations).
        rev = reviser.revise(draft, risk_report, signals, hard_promises)

        iteration_record = {
            "iteration": i,
            "overall_risk": risk_report["overall_risk"],
            "headline": risk_report["headline"],
            "signals_found": [{"id": s["id"], "title": s["title"], "severity": s["severity"]} for s in signals],
            "changes_made": rev["changes"],
            "escalations": rev["escalations"],
            "draft_snapshot": {
                "promised_days": draft.get("promised_days"),
                "sla_tier": draft.get("sla_tier"),
                "compliance_pack": draft.get("compliance_pack"),
                "discount_pct": draft.get("discount_pct"),
                "hw_vendor": draft.get("hw_vendor"),
            },
        }
        iterations.append(iteration_record)

        # [5] Convergence check.
        high_remaining = [r for r in risk_report["risks"] if r["severity"] == "HIGH"]
        if rev["escalations"]:
            status = "needs_human_approval"
            draft = rev["revised_draft"]
            break
        if not rev["changes"] and not high_remaining:
            status = "converged"
            break
        if not rev["changes"]:
            # nothing left to auto-fix but HIGH risk persists -> human
            status = "needs_human_approval"
            break

        # Apply the revision and loop again.
        draft = rev["revised_draft"]
    else:
        status = "max_iterations_reached"

    # Final review on the settled draft + research.
    final_risk = raise_risks.raise_risks(draft, history)
    comps, _ = comparison.find_comparables(draft, history)
    research = deep_research.deep_research(draft, comps)

    report_file = None
    review_task = None
    if auto_upload:
        pdf = report_tool.buildPdf(final_risk, research)
        name = f"RealityCheck_{draft.get('contract_id','draft')}_v{len(iterations)}.pdf"
        report_file = src.upload_pdf(name, pdf)
        review_task = report_tool.createReviewTask(
            src, report_file_id=report_file, draft_id=draft.get("contract_id", "draft"),
            risk_level=final_risk["overall_risk"],
            assignee="deal-desk" if status == "needs_human_approval" else "auto-approved",
        )

    return {
        "status": status,
        "iterations_run": len(iterations),
        "extracted_params": params,
        "hard_promises": hard_promises,
        "final_draft": draft,
        "final_risk": final_risk["overall_risk"],
        "final_headline": final_risk["headline"],
        "open_escalations": iterations[-1]["escalations"] if iterations else [],
        "iteration_log": iterations,
        "report_file": report_file,
        "review_task": review_task,
        "research_brief": research.get("research_brief"),
    }
