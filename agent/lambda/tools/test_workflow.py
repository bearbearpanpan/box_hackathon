"""
End-to-end tests for the agentic workflow + human-in-the-loop.

Covers every feature path so a demo can't surprise us:
  - notes parsing (hard case + clean case)
  - draft generation
  - risk raising (history + static + external signals)
  - the loop: converge vs needs-human
  - review package creation
  - all 4 reviewer decisions: approve / reject / request_changes(accept) /
    request_changes(custom override)
  - resume converging to GREEN/AMBER
  - idempotence guard (can't resolve a review twice)

Run:
    python3 agent/lambda/tools/test_workflow.py        # standalone
    python3 -m pytest agent/lambda/tools/test_workflow.py
"""
import os
import sys
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
# tools/ -> lambda/ -> agent/ -> repo root; box/ and data/ live at the root.
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "box"))
sys.path.insert(0, os.path.join(ROOT, "data"))

import workflow
import approvals
import notes_parser

NOTES_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data", "sample_notes"))
HARD = open(os.path.join(NOTES_DIR, "notes-northstar-q4.txt")).read()
CLEAN = open(os.path.join(NOTES_DIR, "notes-fourthcoffee-clean.txt")).read()


def _clean_state():
    base = os.path.abspath(os.path.join(HERE, "..", "..", "..", "data"))
    for d in ("reviews", "reports"):
        shutil.rmtree(os.path.join(base, d), ignore_errors=True)


# ---- notes parsing --------------------------------------------------------
def test_parse_hard_case():
    p = notes_parser.parse_notes(HARD)
    assert p["customer"] == "Northstar Colo"
    assert p["vertical"] == "Financial Services"
    assert p["region"] == "US-East (Ashburn, VA)"
    assert p["signed_quarter"] == "Q4"
    assert p["sla_tier"] == "Mission-Critical"
    assert p["discount_pct"] == 40
    assert p["promised_days"] == 60
    assert p["hw_vendor"] == "Meridian Systems"
    skus = {li["sku"] for li in p["line_items"]}
    assert "SKU-HW-GPU" in skus and "SKU-SAAS-CORE" in skus
    gpu = next(li for li in p["line_items"] if li["sku"] == "SKU-HW-GPU")
    assert gpu["qty"] == 2, gpu
    seats = next(li for li in p["line_items"] if li["sku"] == "SKU-SAAS-CORE")
    assert seats["qty"] == 250, seats       # "~250 seats", not the product-name default


def test_parse_clean_case():
    p = notes_parser.parse_notes(CLEAN)
    assert p["customer"] == "Fourth Coffee"
    assert p["region"] == "US-Central (Dallas, TX)"
    assert p["sla_tier"] == "Business"
    assert p.get("discount_pct") is None       # "99.9" must NOT be read as discount
    assert p.get("_timeline_flexible") is True
    seats = next(li for li in p["line_items"] if li["sku"] == "SKU-SAAS-CORE")
    assert seats["qty"] == 150, seats          # "about 150 seats", not the default


# ---- the loop -------------------------------------------------------------
def test_clean_case_converges_green():
    _clean_state()
    r = workflow.run_workflow(CLEAN)
    assert r["status"] == "converged", r["status"]
    assert r["final_risk"] == "GREEN", r["final_risk"]
    assert r["review_task"]["assignee"] == "auto-approved"


def test_hard_case_opens_review():
    _clean_state()
    r = workflow.run_workflow(HARD)
    assert r["status"] == "pending_review", r["status"]
    assert r["final_risk"] == "RED"
    assert r["review_id"].startswith("REV-")
    assert any(c["field"] == "promised_days" for c in r["proposed_changes"])


# ---- reviewer decisions ---------------------------------------------------
def _open_review():
    _clean_state()
    return workflow.run_workflow(HARD)["review_id"]


def test_reviewer_approve_as_is():
    rid = _open_review()
    approvals.resolve_review(rid, "approve", note="exception granted")
    res = workflow.resume_from_review(rid)
    assert res["status"] == "approved"
    assert res["final_risk"] == "RED"           # risk preserved, reviewer owns it
    assert res["report_file"]


def test_reviewer_reject():
    rid = _open_review()
    approvals.resolve_review(rid, "reject", note="walk away")
    res = workflow.resume_from_review(rid)
    assert res["status"] == "rejected"


def test_reviewer_accept_proposed_converges():
    rid = _open_review()
    approvals.resolve_review(rid, "request_changes",
                             requested_changes={"accept_proposed": True})
    res = workflow.resume_from_review(rid)
    assert res["status"] == "converged", res["status"]
    assert res["final_risk"] == "GREEN"
    assert any("promised_days" in a for a in res["applied_changes"])


def test_reviewer_custom_override():
    rid = _open_review()
    approvals.resolve_review(rid, "request_changes",
                             requested_changes={"promised_days": 95})
    res = workflow.resume_from_review(rid)
    assert res["status"] == "converged"
    assert res["final_draft"]["promised_days"] == 95


def test_cannot_resolve_twice():
    rid = _open_review()
    approvals.resolve_review(rid, "approve")
    again = approvals.resolve_review(rid, "reject")
    assert "error" in again


def test_resume_before_resolve_is_pending():
    rid = _open_review()
    res = workflow.resume_from_review(rid)
    assert res["status"] == "still_pending"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
