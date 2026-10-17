"""
Tests for the 5 'wow' features. Standalone:
    python3 agent/lambda/tools/features/test_features.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))        # tools/
sys.path.insert(0, os.path.join(ROOT, "box"))
sys.path.insert(0, os.path.join(ROOT, "data"))

import json
import grade
import redline
import obligations
import simulate
import portfolio
import raise_risks

HISTORY = json.load(open(os.path.join(ROOT, "data", "contracts", "manifest.json")))["contracts"]

RISKY = {
    "contract_id": "T-RISKY", "customer": "Test", "vertical": "Financial Services",
    "regulated": True, "region": "US-East (Ashburn, VA)", "signed_quarter": "Q4",
    "signed_date": "2025-11-15", "term_months": 36, "payment_terms": "Net 60",
    "hw_vendor": "Meridian Systems", "has_hardware": True, "promised_days": 60,
    "discount_pct": 40, "sla_tier": "Mission-Critical", "compliance_pack": False,
    "tcv": 480000,
}


def test_grade_risky_is_low():
    g = grade.grade_with_benchmark(RISKY, HISTORY)
    assert g["grade"] in ("D", "F"), g
    assert "portfolio_median_grade" in g
    assert 0 <= g["percentile"] <= 100


def test_redline_produces_edits():
    rr = raise_risks.raise_risks(RISKY, HISTORY)
    rl = redline.propose_redlines(RISKY, rr, HISTORY)
    assert rl["redline_count"] >= 1
    clauses = {r["clause"] for r in rl["redlines"]}
    assert "delivery_timeline" in clauses
    for r in rl["redlines"]:
        assert r["insert"] and r["rationale"]


def test_obligations_dated_and_sorted():
    reg = obligations.build_register(RISKY)
    assert reg["obligation_count"] >= 4
    dates = [o["due_date"] for o in reg["obligations"]]
    assert dates == sorted(dates)
    for o in reg["obligations"]:
        assert o["alert_date"] <= o["due_date"]


def test_simulate_improves_score():
    sim = simulate.simulate(RISKY, {"promised_days": 120}, HISTORY)
    assert sim["after"]["score"] >= sim["before"]["score"]


def test_path_to_grade_finds_move():
    res = simulate.find_path_to_grade(RISKY, "B", HISTORY)
    assert res["achievable"] in (True, False)
    mv = res.get("move") or res.get("best_single_move")
    assert mv and "applied" in mv


def test_portfolio_has_meridian_q4_cluster():
    pr = portfolio.scan(HISTORY)
    titles = [c["title"] for c in pr["clusters"]]
    assert any("Meridian" in t and "Q4" in t for t in titles), titles
    mer = next(c for c in pr["clusters"] if "Meridian" in c["title"])
    assert mer["deal_count"] >= 1
    assert mer["tcv_exposed"] and mer["tcv_exposed"] > 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    p = f = 0
    for fn in fns:
        try:
            fn(); print(f"PASS {fn.__name__}"); p += 1
        except Exception as e:
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}"); f += 1
    print(f"\n{p} passed, {f} failed")
    sys.exit(1 if f else 0)
