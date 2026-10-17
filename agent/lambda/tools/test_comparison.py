"""
Lightweight tests for the comparison engine (RULES.md). Run with:
    python3 -m pytest agent/lambda/tools/test_comparison.py
or standalone:
    python3 agent/lambda/tools/test_comparison.py
No external test deps required for the standalone path.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import comparison as cmp


def _deal(cid, region, vendor, q, tcv, promised=None, actual=None):
    return {"contract_id": cid, "region": region, "hw_vendor": vendor,
            "signed_quarter": q, "tcv": tcv, "promised_days": promised,
            "actual_days": actual}


HISTORY = [
    _deal("H1", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 100000, 60, 95),
    _deal("H2", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 120000, 75, 110),
    _deal("H3", "US-East (Ashburn, VA)", "Meridian Systems", "Q2", 110000, 70, 88),
    _deal("H4", "US-West (Hillsboro, OR)", "Vortex Hardware", "Q1", 105000, 80, 84),  # gated out (region+vendor differ)
    _deal("H5", "EU-West (Dublin, IE)", "Meridian Systems", "Q4", 500000, 100, 140),  # gated out (size)
]


def test_gate_and_topn():
    draft = _deal("D", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 110000, 60)
    comps, thin = cmp.find_comparables(draft, HISTORY)
    ids = [c["contract_id"] for c in comps]
    assert ids == ["H1", "H2", "H3"], ids       # the 3 Ashburn/Meridian deals
    assert thin is False


def test_red_risk():
    draft = _deal("D", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 110000, 60)
    comps, _ = cmp.find_comparables(draft, HISTORY)
    risk = cmp.risk_level(draft, comps)
    assert risk["level"] == "RED"               # 60 < min actual (88)
    assert risk["p50_actual"] == 95


def test_timeline():
    draft = _deal("D", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 110000, 60)
    comps, _ = cmp.find_comparables(draft, HISTORY)
    tl = cmp.suggested_timeline(draft, comps)
    assert tl["p50_actual"] == 95
    assert tl["worst_actual"] == 110
    assert tl["suggested_days"] == 95           # max(p50, promised)


def test_green_risk():
    draft = _deal("D", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 110000, 150)
    comps, _ = cmp.find_comparables(draft, HISTORY)
    risk = cmp.risk_level(draft, comps)
    assert risk["level"] == "GREEN"             # 150 >= p50 (95)


def test_size_gate_excludes_big_deal():
    draft = _deal("D", "US-East (Ashburn, VA)", "Meridian Systems", "Q4", 110000, 60)
    comps, _ = cmp.find_comparables(draft, HISTORY)
    assert "H5" not in [c["contract_id"] for c in comps]  # 500k outside +/-40%


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"PASS {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")
