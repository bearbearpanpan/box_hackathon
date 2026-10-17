# Reality Check — Expansion Roadmap & "Wow" Features

How we make this more robust and where it goes next. Grounded in what the
contract-intelligence market (Ironclad, LinkSquares, Sirion, Luminance, Harvey)
actually ships today, plus differentiators unique to our "promise vs reality"
angle. Market context rephrased for compliance from public vendor material;
sources inline.

## Where the market is

- **Letter-grade / profile-based risk scoring** — LinkSquares' risk agent gives
  incoming agreements an immediate A–F grade against a defined risk profile.
  [[LinkSquares](https://blog.linksquares.com/linksquares-launches-ai-powered-risk-scoring-agent-to-automate-contract-risk-management)]
- **Obligation tracking** — extract and monitor deadlines, milestones, renewals,
  and performance commitments; alert before they're missed.
  [[Ironclad](https://ironcladapp.com/resources/articles/what-are-contract-obligations-types-examples-and-how-to-track-them)]
- **Playbook redlining with fallback clause libraries** — AI proposes edits from
  approved/fallback language; reported 45–90% cycle-time cuts.
  [[Sirion](https://www.sirion.ai/library/contract-insights/fallback-clauses-ai-playbooks-reduce-redlines/)]
- **Explainable recommendations + routed approvals** — flag deviations with
  reasons, automate routing/notifications.
  [[Ironclad](https://ironcladapp.com/product/ai-based-contract-management)]

Our wedge the incumbents don't have: **we check promises against our own
delivery history** — not just legal risk, but *operational* reality ("history
says 95, you promised 60"). The five features below extend that wedge.

---

## The 5 "Wow" features

### 1. Deal Grade (A–F) + portfolio benchmarking
A single letter grade for the deal, plus how it ranks against the portfolio:
"This deal is a **D**. Your median tech-sales deal is a **B**." Turns a nuanced
risk analysis into one number an exec remembers. Built on the existing risk
engine. **Status: implemented** (`grade.py`).

### 2. Auto-redline from a clause playbook
Instead of only flagging "timeline too aggressive," propose the actual edit:
strike the 60-day clause, insert the 95-day fallback, with tracked-change
rationale. A clause/fallback library maps each risk → approved replacement
language. **Status: implemented** (`playbook.py`, `redline.py`).

### 3. Obligation & milestone tracker
Extract every commitment (delivery date, SLA uptime, renewal, payment, data-
residency) into a dated obligation register with owners and alert windows, so
nothing is missed post-signature. **Status: implemented** (`obligations.py`).

### 4. "What-if" negotiation simulator
Let a reviewer move the levers — promised days, discount, SLA tier, vendor — and
watch the grade/risk/headline recompute instantly. Answers "what would make this
a B?" in the room. **Status: implemented** (`simulate.py`).

### 5. Portfolio radar / early-warning
Scan all open/active deals for shared systemic risk: "4 open deals route hardware
through Meridian in Q4 — $X TCV exposed to the same backorder." Moves from
single-deal review to portfolio risk management. **Status: implemented**
(`portfolio.py`).

---

## Making it more robust (beyond the 5)

- **Confidence + provenance on every extracted field** — show where in the doc
  each value came from, with a confidence score; low-confidence fields get
  human verification instead of silent defaults.
- **Learning loop** — when actuals come in, feed them back so the history (and
  thus every future prediction) improves automatically.
- **Policy-as-config** — move risk rules/thresholds and the clause playbook into
  versioned config a legal/ops admin edits, not code.
- **Multi-model + guardrails** — Bedrock model routing with a cheaper model for
  extraction and a stronger one for drafting; schema-validate all tool output.
- **Audit trail & e-sign** — immutable decision log (who approved what, when, why)
  and a handoff to DocuSign/Adobe Sign once a deal clears.
- **Deeper Box** — Box AI for extraction, Box metadata templates for the register,
  Box Relay for routing, Box Sign for signature.
