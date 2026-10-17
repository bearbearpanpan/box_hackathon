"""
Feature 1 — Deal Grade (A-F) + portfolio benchmarking.

Collapses the full risk analysis into a single letter grade an exec remembers,
and benchmarks it against the deal portfolio. Market analog: LinkSquares' A-F
risk scoring. Our twist: the grade is driven by promise-vs-history reality, not
just clause risk.

Scoring (0-100, higher = safer):
  start 100
  - timeline gap:  how far the promise is below comparable actuals (biggest lever)
  - open HIGH risks: -12 each
  - open MEDIUM risks: -5 each
  - no comparable history: cap at C (we can't vouch for an unbenchmarked deal)
Grade bands: A >=90, B >=80, C >=70, D >=60, F <60.
"""
from __future__ import annotations

import os
import sys
from statistics import median
from typing import Dict, Any, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import comparison  # noqa: E402


def _band(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def score_deal(draft: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    comps, thin = comparison.find_comparables(draft, history)
    risk = comparison.risk_level(draft, comps)
    score = 100.0
    reasons: List[str] = []

    if comps:
        p50 = median([c["actual_days"] for c in comps])
        promised = draft.get("promised_days") or 0
        if promised < p50:
            gap_pct = (p50 - promised) / p50
            penalty = min(45, round(gap_pct * 90))
            score -= penalty
            reasons.append(f"-{penalty}: promised {promised}d vs typical actual {int(p50)}d")
    else:
        score = min(score, 72)  # unbenchmarked -> cannot exceed C
        reasons.append("capped at C: no comparable deal history to benchmark against")

    # count open risks via the full risk tool shape if present, else infer
    highs = draft.get("_open_high_risks", 0)
    meds = draft.get("_open_medium_risks", 0)
    if highs:
        score -= 12 * highs
        reasons.append(f"-{12*highs}: {highs} open HIGH risk(s)")
    if meds:
        score -= 5 * meds
        reasons.append(f"-{5*meds}: {meds} open MEDIUM risk(s)")

    score = max(0, min(100, round(score)))
    return {
        "score": score,
        "grade": _band(score),
        "risk_level": risk["level"],
        "reasons": reasons,
        "benchmarked": not thin,
    }


def grade_with_benchmark(draft: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grade this deal and benchmark the grade against the whole portfolio."""
    me = score_deal(draft, history)

    # Grade every historical deal (using its own promise vs its peers) for a
    # distribution to benchmark against.
    portfolio_scores = []
    for h in history:
        s = score_deal(h, history)
        portfolio_scores.append(s["score"])
    portfolio_scores.sort()
    med = int(median(portfolio_scores)) if portfolio_scores else 0
    better_than = sum(1 for s in portfolio_scores if s < me["score"])
    pct = round(100 * better_than / len(portfolio_scores)) if portfolio_scores else 0

    return {
        **me,
        "portfolio_median_score": med,
        "portfolio_median_grade": _band(med),
        "percentile": pct,
        "summary": (
            f"Deal grade {me['grade']} ({me['score']}/100). "
            f"Portfolio median is {_band(med)} ({med}). "
            f"This deal is safer than {pct}% of past deals."
        ),
    }
