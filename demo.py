#!/usr/bin/env python3
"""
demo.py — the live customer walkthrough for Reality Check.

Runs the whole agentic story end to end, narrated, with clean output. No keys
required (uses the offline history + review store). Run:

    python3 demo.py            # full guided demo
    python3 demo.py --fast     # no pauses between steps

Story:
  1. A sales rep drops in messy meeting notes.
  2. The agent extracts the deal, drafts a contract, reviews it against 100
     past deals + external risk signals, and auto-fixes what it safely can.
  3. It hits a hard customer promise it can't unilaterally change -> opens a
     review for the deal desk (human in the loop).
  4. The reviewer opens the document and requests the safer timeline.
  5. The agent resumes, re-reviews, and the deal clears -> GREEN. Done.
  6. Then a clean deal that needs no human at all, to show the happy path.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "agent", "lambda", "tools"))
sys.path.insert(0, os.path.join(HERE, "box"))
sys.path.insert(0, os.path.join(HERE, "data"))

import workflow      # noqa: E402
import approvals     # noqa: E402

FAST = "--fast" in sys.argv


def hr(ch="-"):
    print(ch * 72)


def pause(sec=1.2):
    if not FAST:
        time.sleep(sec)


def banner(title):
    print()
    hr("=")
    print(f"  {title}")
    hr("=")


def show(label, value):
    print(f"  {label:<22} {value}")


def reset_state():
    import shutil
    for d in ("reviews", "reports"):
        shutil.rmtree(os.path.join(HERE, "data", d), ignore_errors=True)


def main():
    reset_state()
    print()
    print("  REALITY CHECK — Agentic Deal Desk")
    print("  \"Sales promises. Ops delivers. Reality Check makes sure they're the same number.\"")
    pause()

    # ---------------------------------------------------------------- SCENE 1
    banner("1) Sales rep drops in meeting notes (the ONLY human input)")
    notes = open(os.path.join(HERE, "data", "sample_notes", "notes-northstar-q4.txt")).read()
    print(notes.rstrip())
    pause(2)

    banner("2) Agent: extract deal -> draft -> review vs 100 deals + risk signals")
    res = workflow.run_workflow(notes)
    p = res["extracted_params"]
    print("  Extracted deal intent:")
    for k in ["customer", "vertical", "region", "signed_quarter", "sla_tier",
              "discount_pct", "promised_days", "hw_vendor"]:
        show("  " + k, p.get(k))
    show("  line_items", p.get("line_items"))
    print()
    print("  Agent iteration log:")
    for it in res["iteration_log"]:
        print(f"    - iter {it['iteration']}: risk={it['overall_risk']}  ::  {it['headline']}")
        for c in it["changes_made"]:
            print(f"        auto-fixed: {c['change']}  (reason: {c['reason']})")
        for e in it["escalations"]:
            print(f"        flagged:    {e['issue']}")
    pause(2)

    banner("3) Hard customer promise -> needs a human. Review opened.")
    show("Status", res["status"].upper())
    show("Risk", res["final_risk"])
    show("Headline", res["final_headline"])
    show("Review id", res["review_id"])
    show("Routed to", "deal-desk")
    print("  Proposed safer change(s):")
    for c in res["proposed_changes"]:
        print(f"    - set {c['field']} -> {c['to']}  ({c['reason']})")
    rid = res["review_id"]
    pause(2)

    # ---------------------------------------------------------------- SCENE 4
    banner("4) Reviewer OPENS the document")
    rec = approvals.get_review(rid)
    show("Review", rec["review_id"] + f"  [{rec['status']}]")
    show("Risk", f"{rec['risk_level']}  —  {rec['headline']}")
    show("Report PDF", os.path.basename(str(rec["report_file"])))
    print("  Escalations the reviewer sees:")
    for e in rec["escalations"]:
        print(f"    - [{e['severity']}] {e['issue']}")
        print(f"         -> {e['needs_human']}")
    pause(2)

    banner("5) Reviewer requests the safer timeline (one click)")
    approvals.resolve_review(
        rid, "request_changes", reviewer="jordan@dealdesk",
        note="Agree with history/supplier. Move to the safer date; Meridian risk acknowledged.",
        requested_changes={"accept_proposed": True},
    )
    print("  Reviewer decision recorded: REQUEST_CHANGES (accept proposed)")
    pause(1.5)

    banner("6) Agent RESUMES, re-reviews, and the deal clears")
    out = workflow.resume_from_review(rid)
    show("Applied", ", ".join(out.get("applied_changes", [])))
    show("Status", out["status"].upper())
    show("Final risk", out["final_risk"])
    show("Final headline", out["final_headline"])
    show("Message", out.get("message"))
    pause(2)

    # ---------------------------------------------------------------- SCENE 7
    banner("7) Happy path: a clean deal needs NO human at all")
    clean = open(os.path.join(HERE, "data", "sample_notes", "notes-fourthcoffee-clean.txt")).read()
    print(clean.rstrip())
    print()
    r2 = workflow.run_workflow(clean)
    show("Status", r2["status"].upper())
    show("Final risk", r2["final_risk"])
    show("Final headline", r2["final_headline"])
    show("Routed to", r2["review_task"]["assignee"])
    pause()

    # ---------------------------------------------------------------- SCENE 8
    banner("8) WOW features — grade, redline, obligations, what-if, portfolio")
    sys.path.insert(0, os.path.join(HERE, "agent", "lambda", "tools", "features"))
    import draft_contract            # noqa: E402
    import raise_risks               # noqa: E402
    from features import grade, redline, obligations, simulate, portfolio  # noqa: E402

    _, hist = workflow._history()
    hp = dict(res["extracted_params"])
    hp["promised_days"] = 60                 # the original aggressive promise
    hp["signed_date"] = "2025-11-15"
    hard_draft = draft_contract.draft_contract(hp)["draft"]
    hard_draft["signed_date"] = "2025-11-15"

    g = grade.grade_with_benchmark(hard_draft, hist)
    print("  [1] DEAL GRADE:    " + g["summary"])

    rr = raise_risks.raise_risks(hard_draft, hist)
    rl = redline.propose_redlines(hard_draft, rr, hist)
    print(f"  [2] AUTO-REDLINE:  {rl['redline_count']} clause edits proposed "
          f"(timeline -> {rl['suggested_days']}d fallback, +vendor/compliance language)")

    ob = obligations.build_register(hard_draft)
    print(f"  [3] OBLIGATIONS:   {ob['obligation_count']} dated commitments tracked; "
          f"first: '{ob['obligations'][0]['title']}' on {ob['obligations'][0]['due_date']}")

    ptg = simulate.find_path_to_grade(hard_draft, "B", hist)
    mv = ptg.get("move") or ptg.get("best_single_move")
    if mv:
        print(f"  [4] WHAT-IF:       {mv['before']['grade']} -> {mv['after']['grade']} "
              f"by changing {mv['applied']}")

    pr = portfolio.scan(hist)
    top = pr["clusters"][0]
    print(f"  [5] PORTFOLIO:     {pr['headline']}")
    print(f"                     #1 cluster: {top['title']} — "
          f"{top['deal_count']} deals, {top['evidence']}")
    pause()

    banner("DEMO COMPLETE")
    print("  Hard deal: caught an undeliverable promise, looped a human in, and")
    print("  converged to a safe contract. Clean deal: auto-approved untouched.")
    print("  Plus: letter grade, auto-redlines, obligation tracking, what-if")
    print("  simulation, and portfolio-wide early warning.")
    print("  Every number came from real document history — not a guess.")
    print()


if __name__ == "__main__":
    argparse.ArgumentParser().parse_known_args()
    main()
