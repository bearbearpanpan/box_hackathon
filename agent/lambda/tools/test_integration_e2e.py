"""
test_integration_e2e.py — end-to-end integration test.

Unlike the unit suites (test_comparison / test_workflow / test_features) which
check individual engines, this drives the FULL stack the way the Lambda does —
through handler.run_action — and validates BOTH:

  1. Functional behavior: draft -> risk -> report PDF -> review task, the agentic
     workflow loop, the human-in-the-loop review, and the "wow" features.
  2. Observability: that the telemetry metrics the CloudWatch dashboard reads are
     actually emitted, with the right names and dimensions, during real runs —
     and that EMF lines are written to the stream when EMIT_METRICS=true while
     stdout stays clean JSON (the contract the local CLI depends on).

Everything runs offline against the generated fixtures, so it needs no AWS/Box
credentials and is safe to run anywhere.

Optional live check: set RC_E2E_LIVE_CW=1 (with AWS creds + a deployed stack in
the current region) to also publish a canary metric to the RealityCheck
namespace and read it back, proving the code -> CloudWatch path. Skipped by
default so the test stays hermetic.

Run:
    python3 agent/lambda/tools/test_integration_e2e.py
    python3 -m pytest agent/lambda/tools/test_integration_e2e.py
"""
import io
import json
import os
import shutil
import sys
import time
from contextlib import redirect_stdout

# Guarantee OFFLINE mode before importing the handler. The handler auto-loads a
# repo .env (envload), which may carry Box credentials that would flip
# get_source() to the live BoxClient. This test exercises the offline pipeline
# against fixtures, so strip those creds up front — same posture the public web
# handler enforces. This keeps the test hermetic regardless of local .env.
for _k in ("BOX_CLIENT_ID", "BOX_CLIENT_SECRET", "BOX_ENTERPRISE_ID"):
    os.environ.pop(_k, None)
os.environ["BOX_CLIENT_ID"] = ""
os.environ["BOX_CLIENT_SECRET"] = ""

HERE = os.path.dirname(os.path.abspath(__file__))
# tools/ -> lambda/ ; box/ and data/ live at the repo root.
LAMBDA_DIR = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
for p in (LAMBDA_DIR, HERE, os.path.join(ROOT, "box"), os.path.join(ROOT, "data")):
    sys.path.insert(0, p)

import handler  # noqa: E402  (the Lambda router — our system-under-test)
import telemetry  # noqa: E402

DATA = os.path.join(ROOT, "data")
NOTES_DIR = os.path.join(DATA, "sample_notes")
HARD = open(os.path.join(NOTES_DIR, "notes-northstar-q4.txt")).read()
CLEAN = open(os.path.join(NOTES_DIR, "notes-fourthcoffee-clean.txt")).read()

# An aggressive Q4 + Meridian hardware deal — the README's canonical RED case.
AGGRESSIVE_PARAMS = {
    "region": "US-East (Ashburn, VA)",
    "signed_quarter": "Q4",
    "hw_vendor": "Meridian Systems",
    "promised_days": 55,
    "line_items": [{"sku": "SKU-HW-GPU", "qty": 2}, {"sku": "SKU-SAAS-CORE", "qty": 250}],
}


def _clean_state():
    for d in ("reviews", "reports"):
        shutil.rmtree(os.path.join(DATA, d), ignore_errors=True)


# --------------------------------------------------------------------------- #
# 1. Full analyze-and-report pipeline + its metrics
# --------------------------------------------------------------------------- #
def test_analyze_and_report_pipeline_and_metrics():
    _clean_state()
    with telemetry.capture_metrics() as cap:
        result = handler.run_action("analyze-and-report", dict(AGGRESSIVE_PARAMS))

    # --- functional assertions ---
    assert result["overall_risk"] == "RED", result["overall_risk"]
    assert "history says" in result["headline"], result["headline"]
    assert result["report_file"], "a report PDF path/id must be returned"
    assert os.path.exists(result["report_file"]), "report PDF should exist on disk (offline)"
    assert result["review_task"]["status"] in ("created", "created_local")
    assert result["risk_report"]["comparables"], "RED verdict must cite comparables"

    # --- observability assertions ---
    # run_action wraps every dispatch with an ActionInvoked metric.
    assert cap.count("ActionInvoked", action="analyze-and-report") == 1, cap.names()


# --------------------------------------------------------------------------- #
# 2. Agentic workflow (hard case) opens a review + emits workflow KPIs
# --------------------------------------------------------------------------- #
def test_workflow_hard_case_metrics():
    _clean_state()
    with telemetry.capture_metrics() as cap:
        result = handler.run_action("run-workflow", {"notes": HARD})

    assert result["status"] == "pending_review", result["status"]
    assert result["final_risk"] == "RED"

    # KPI metrics the dashboard's row-3 widgets read:
    assert cap.count("ActionInvoked", action="run-workflow") == 1
    assert cap.count("WorkflowRun", status="needs_human_approval") == 1, cap.records
    assert cap.count("WorkflowNeedsHuman") == 1
    assert cap.count("WorkflowFinalRisk", risk="RED") == 1
    assert cap.total("WorkflowIterations") >= 1


# --------------------------------------------------------------------------- #
# 3. Clean case converges with no human, emits the converged outcome
# --------------------------------------------------------------------------- #
def test_workflow_clean_case_metrics():
    _clean_state()
    with telemetry.capture_metrics() as cap:
        result = handler.run_action("run-workflow", {"notes": CLEAN})

    assert result["status"] == "converged", result["status"]
    assert result["final_risk"] == "GREEN"
    assert cap.count("WorkflowRun", status="converged") == 1, cap.records
    assert cap.count("WorkflowNeedsHuman") == 0
    assert cap.count("WorkflowFinalRisk", risk="GREEN") == 1


# --------------------------------------------------------------------------- #
# 4. Human-in-the-loop resume path end-to-end
# --------------------------------------------------------------------------- #
def test_review_resume_roundtrip_metrics():
    _clean_state()
    opened = handler.run_action("run-workflow", {"notes": HARD})
    review_id = opened["review_id"]

    # Reviewer accepts the agent's safer proposal.
    handler.run_action("resolve-review", {
        "review_id": review_id, "decision": "request_changes",
        "requested_changes": {"accept_proposed": True},
    })

    with telemetry.capture_metrics() as cap:
        resumed = handler.run_action("resume-workflow", {"review_id": review_id})

    assert resumed["status"] == "converged", resumed["status"]
    assert resumed["report_file"]
    # resume path re-enters the loop and must report its own outcome metric.
    assert cap.count("WorkflowRun", status="converged") == 1, cap.records
    assert cap.count("ActionInvoked", action="resume-workflow") == 1


# --------------------------------------------------------------------------- #
# 5. A "wow" feature path still flows through the metered dispatcher
# --------------------------------------------------------------------------- #
def test_feature_dispatch_metrics():
    _clean_state()
    with telemetry.capture_metrics() as cap:
        grade = handler.run_action("grade-deal", dict(AGGRESSIVE_PARAMS))
        portfolio = handler.run_action("portfolio-radar", {})

    assert grade["grade"] in {"A", "B", "C", "D", "F"}
    assert portfolio["cluster_count"] >= 1
    assert cap.count("ActionInvoked", action="grade-deal") == 1
    assert cap.count("ActionInvoked", action="portfolio-radar") == 1


# --------------------------------------------------------------------------- #
# 6. EMF is written to the stream when enabled, and stdout stays clean JSON
# --------------------------------------------------------------------------- #
def test_emf_emission_and_clean_stdout():
    _clean_state()
    prev = os.environ.get("EMIT_METRICS")
    os.environ["EMIT_METRICS"] = "true"
    # Force the non-Lambda branch so EMF goes to stderr and stdout stays clean,
    # matching local CLI behavior. (In Lambda, EMF goes to stdout for CW.)
    prev_lambda = os.environ.pop("AWS_LAMBDA_FUNCTION_NAME", None)
    try:
        emf_stream = io.StringIO()
        # emit_metric writes to sys.stderr locally; capture it.
        real_stderr = sys.stderr
        sys.stderr = emf_stream
        out_buf = io.StringIO()
        try:
            with redirect_stdout(out_buf):
                result = handler.run_action("analyze-and-report", dict(AGGRESSIVE_PARAMS))
        finally:
            sys.stderr = real_stderr

        # stdout from run_action must be empty (results are returned, not printed)
        # — the CLI itself does the printing — so nothing corrupts the JSON.
        assert out_buf.getvalue() == "", repr(out_buf.getvalue()[:200])

        # At least one EMF line must have been written, and each must be valid
        # JSON carrying the RealityCheck namespace.
        emf_lines = [ln for ln in emf_stream.getvalue().splitlines()
                     if ln.strip().startswith("{") and "_aws" in ln]
        assert emf_lines, "expected EMF metric lines on stderr when EMIT_METRICS=true"
        sample = json.loads(emf_lines[0])
        assert sample["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "RealityCheck"
        assert result["overall_risk"] == "RED"
    finally:
        if prev is None:
            os.environ.pop("EMIT_METRICS", None)
        else:
            os.environ["EMIT_METRICS"] = prev
        if prev_lambda is not None:
            os.environ["AWS_LAMBDA_FUNCTION_NAME"] = prev_lambda


# --------------------------------------------------------------------------- #
# 7. OPTIONAL: live CloudWatch round-trip (opt-in, needs AWS creds + stack)
# --------------------------------------------------------------------------- #
def test_live_cloudwatch_roundtrip():
    if os.environ.get("RC_E2E_LIVE_CW", "").strip().lower() not in ("1", "true", "yes"):
        print("SKIP test_live_cloudwatch_roundtrip (set RC_E2E_LIVE_CW=1 to enable)")
        return
    import boto3  # type: ignore

    cw = boto3.client("cloudwatch")
    canary = f"E2ECanary"
    marker = int(time.time())
    cw.put_metric_data(
        Namespace="RealityCheck",
        MetricData=[{
            "MetricName": canary,
            "Dimensions": [{"Name": "run", "Value": str(marker)}],
            "Value": 1, "Unit": "Count",
        }],
    )
    # get-metric-statistics reflects data almost immediately.
    found = 0.0
    for _ in range(6):
        time.sleep(5)
        resp = cw.get_metric_statistics(
            Namespace="RealityCheck", MetricName=canary,
            Dimensions=[{"Name": "run", "Value": str(marker)}],
            StartTime=marker - 120, EndTime=marker + 300,
            Period=60, Statistics=["Sum"],
        )
        pts = resp.get("Datapoints", [])
        if pts:
            found = sum(p["Sum"] for p in pts)
            break
    assert found >= 1.0, "canary metric did not round-trip through CloudWatch"


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def _all_tests():
    g = globals()
    return [g[n] for n in sorted(g) if n.startswith("test_") and callable(g[n])]


if __name__ == "__main__":
    # Keep logs quiet unless the caller asked otherwise.
    os.environ.setdefault("LOG_LEVEL", "WARNING")
    passed = failed = 0
    for fn in _all_tests():
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
            failed += 1
        except Exception as e:  # noqa: BLE001
            import traceback
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    _clean_state()
    sys.exit(1 if failed else 0)
