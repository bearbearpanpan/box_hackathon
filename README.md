# Reality Check

[![CodeQL](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/codeql.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/codeql.yml)
[![Security](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/security.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/security.yml)
[![SBOM](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/sbom.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/sbom.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![OWASP Top 10:2025](https://img.shields.io/badge/OWASP-Top%2010%3A2025-success.svg)](./docs/SECURITY.md)
[![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org/)

> Sales promises. Ops delivers. Reality Check makes sure they're the same number.

An **AWS Bedrock agent** that reads tech-sales contracts from **Box**, drafts new
contracts, raises risks by comparing promised timelines against real deal
history, and researches features worth offering — then writes a risk report PDF
back to Box with a review task for the deal desk.

**The gap it closes:** your ERP/CRM has dates and amounts. It doesn't know the
delay was a Q4 hardware backorder, a risky supplier, or a deep discount that
dragged services scope. That's in the documents — and that's what the agent reads.

---

## What's in here

```
box_hackathon/
├── RULES.md                    # the risk engine spec (similarity / timeline / risk tiers)
├── .env.example                # all config keys (Box, Box AI, Bedrock) — copy to .env
│
├── data/                       # the document corpus
│   ├── minipdf.py              # dependency-free PDF writer (sandbox has no network)
│   ├── catalog.py              # customers, products, SLAs, vendors, planted risk patterns
│   ├── generate_contracts.py   # deterministic generator
│   └── contracts/              # 100 CTR-*.pdf + manifest.json (structured ground truth)
│
├── box/                        # Box integration
│   ├── box_client.py           # Box API + Box AI wrapper (creds from env)
│   ├── local_source.py         # offline fallback (reads manifest.json) — demo w/o keys
│   └── mcp_config.json         # Box MCP server config
│
└── agent/                      # the Bedrock agent
    ├── bedrock_agent.md        # agent instructions (paste into Bedrock)
    ├── openapi.yaml            # action-group API schema
    ├── action_groups.json      # agent/action-group reference config
    ├── infra/setup.md          # step-by-step deploy guide
    └── lambda/
        ├── handler.py          # Lambda entry + Bedrock routing + local CLI
        ├── requirements.txt    # boto3, boxsdk (only needed for live calls)
        └── tools/
            ├── comparison.py       # the RULES.md engine
            ├── draft_contract.py   # tool: draft a contract
            ├── raise_risks.py      # tool: raise risks (history + rules, with citations)
            ├── deep_research.py     # tool: feature research (+ optional Bedrock brief)
            ├── report.py            # buildPdf() + createReviewTask()
            └── test_comparison.py   # engine tests (5/5 passing)
```

## The three capabilities

| Capability | Tool | What it does |
|---|---|---|
| **Draft** | `draftContract` | Assemble a normalized tech-sales contract from deal params; defaults are reported as `assumptions`. |
| **Raise risks** | `raiseRisks` | Compare promised timeline vs comparable past deals + static risk rules. Returns a headline, risk level, ranked risks, and cited comparables. |
| **Deep research** | `deepResearch` | Recommend add-on features scored against vertical/region/SLA/size; optional Bedrock-written brief. |
| **Full report** | `analyzeAndReport` | Read → Check → Report: builds the PDF, writes it to Box, creates a deal-desk review task. |

## The planted patterns (so the demo finds something real)

The 100-contract history is noisy but biased so the agent discovers:
1. **Q4 hardware deals slip** (~30–60% over promise) — supply chain + holiday freight.
2. **Meridian Systems is the risky vendor** — appliance/PDU backorders.
3. **Discounts >35% correlate with services scope creep.**

See `data/catalog.py` and `RULES.md`.

## The agentic workflow (meeting notes → signed-off contract)

The headline feature. One input (messy sales-call notes), a fully autonomous
loop, and a human only when a human is actually needed:

```
meeting notes
  → extract deal intent          (notes_parser)
  → draft contract               (draft_contract)
  → review & flag risks          (raise_risks + external risk_signals)
  → revise: auto-fix what's safe (revise: discount caps, buffers, compliance)
  → loop until converged OR a hard customer promise needs human approval
  → open a REVIEW the deal desk opens, then approve / reject / request changes
  → resume from the decision and loop again until it clears
  → final report PDF + review task
```

**The agent generates its own risk signals** (not just what's in the deal):
supplier delay notices, SLA-credit history, Q4 freight advisories, and
compliance alerts — see `data/risk_signals.py`.

**Human-in-the-loop is real.** When a deal needs sign-off, the agent opens a
review package (`approvals.py`); a reviewer opens it, and can **approve as-is**
(owns the risk), **reject** (walk away), or **request changes** (accept the
agent's safer proposal or set their own number). The workflow resumes from that
decision. All four paths are tested.

### See the whole story in one command

```bash
python3 demo.py            # narrated walkthrough (--fast to skip pauses)
```
It runs a hard deal (undeliverable 60-day promise → RED → human loops in →
converges to a safe timeline → GREEN) and a clean deal (auto-approved, no human).

### Workflow actions (via the Lambda/CLI or Bedrock)

| Action | What it does |
|---|---|
| `run-workflow` | notes → draft → loop; opens a review if a human is needed |
| `get-review` / `list-reviews` | what the reviewer sees when they open the doc |
| `resolve-review` | reviewer decision: approve / reject / request_changes |
| `resume-workflow` | continue from the decision until it clears |

### Tests (every path)
```bash
python3 agent/lambda/tools/test_comparison.py          # 5/5  (risk engine)
python3 agent/lambda/tools/test_workflow.py             # 10/10 (notes, loop, reviewer paths)
python3 agent/lambda/tools/features/test_features.py    # 6/6  (the 5 wow features)
python3 agent/lambda/tools/test_integration_e2e.py      # 7/7  (full pipeline + metric emissions)
```

The integration test drives the full `handler.run_action` dispatch (the same
path the Lambda uses) and asserts on both functional outcomes and the telemetry
metrics the CloudWatch dashboard reads. It runs offline by default; set
`RC_E2E_LIVE_CW=1` (with AWS creds + the deployed observability stack) to also
round-trip a canary metric through live CloudWatch.

## "Wow" features (see [ROADMAP.md](./ROADMAP.md))

Five capabilities that extend the core, each grounded in what the contract-
intelligence market ships (Ironclad, LinkSquares, Sirion) plus our promise-vs-
reality wedge. All runnable via the handler/CLI and covered by tests:

| # | Feature | Action | What it shows |
|---|---------|--------|---------------|
| 1 | **Deal Grade (A–F) + benchmark** | `grade-deal` | "This deal is a D. Portfolio median is C. Safer than 25% of deals." |
| 2 | **Auto-redline from clause playbook** | `redline` | Actual clause edits (strike/insert) with fallback language + rationale |
| 3 | **Obligation & milestone tracker** | `obligations` | Dated register of every commitment with owners + alert windows |
| 4 | **"What-if" negotiation simulator** | `simulate`, `path-to-grade` | Move the levers, watch grade/risk recompute; "what gets us to a B?" |
| 5 | **Portfolio radar / early-warning** | `portfolio-radar` | "10 deals route Meridian hardware in Q4 — $9M TCV exposed, +52d avg slip" |

## Run it right now (no keys needed)

The pipeline auto-detects: if Box credentials are set it uses Box; otherwise it
reads `data/contracts/manifest.json`. So you can demo tonight:

```bash
# regenerate the 100 PDFs (optional; already committed)
python3 data/generate_contracts.py

# run the full pipeline on an aggressive Q4 + Meridian hardware deal
cd agent/lambda
python3 handler.py analyze-and-report --params '{
  "region":"US-East (Ashburn, VA)","signed_quarter":"Q4",
  "hw_vendor":"Meridian Systems","promised_days":55,
  "line_items":[{"sku":"SKU-HW-GPU","qty":2},{"sku":"SKU-SAAS-CORE","qty":250}]
}'
```
Expected: **🔴 RED — "55 days promised, history says 91,"** with cited
comparable contracts, a report PDF in `data/reports/`, and a review task.

Run the engine tests:
```bash
python3 agent/lambda/tools/test_comparison.py        # 5/5
```

## Going live

Drop your keys into `.env` (see `.env.example`), then follow
[`agent/infra/setup.md`](./agent/infra/setup.md) to deploy the Lambda, create the
Bedrock agent + action group, and wire Box (API or MCP).

## Security & docs

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — components, request flow, trust boundaries.
- [`docs/SECURITY.md`](./docs/SECURITY.md) — threat model mapped to OWASP Top 10:2025.
- [`docs/DOC_AUDIT.md`](./docs/DOC_AUDIT.md) — documentation audit.
- [`sbom.json`](./sbom.json) — CycloneDX SBOM, regenerated on every check-in.

Security tooling runs on every push/PR: CodeQL + Bandit (SAST), pip-audit +
Dependabot (dependencies), and Gitleaks (secret scanning). Install the SBOM
pre-commit hook once with `./scripts/install-hooks.sh`.

---
*All contract data is synthetic. Customer names are fictional.*
