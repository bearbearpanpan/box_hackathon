# Reality Check

[![CodeQL](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/codeql.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/codeql.yml)
[![Security](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/security.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/security.yml)
[![SBOM](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/sbom.yml/badge.svg)](https://github.com/sethusrinivasan/box_hackathon/actions/workflows/sbom.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![OWASP Top 10:2025](https://img.shields.io/badge/OWASP-Top%2010%3A2025-success.svg)](./docs/SECURITY.md)
[![Python 3](https://img.shields.io/badge/python-3-blue.svg)](https://www.python.org/)

> Sales promises. Ops delivers. Reality Check makes sure they're the same number.

**Reality Check is a deal-intelligence agent for sales reps.** While a tech-sales
rep is drafting a deal, the agent (AWS Bedrock) checks the deal against the
company's own delivery history stored in **Box** and tells the rep whether the
promise is realistic, with evidence. It then saves a risk report to Box and
assigns a review task to the deal desk.

**It does not draft contracts.** The rep owns the contract. The agent only
supplies intelligence.

**Why Box:** the ERP/CRM has dates. It doesn't know the delay was a Q4 hardware
backorder, a vendor that always slips, or a deep discount that dragged services
scope. That lives in the documents, and the documents live in Box.

---

## The flow

```
1. Rep drafts a deal              e.g. Ashburn, Q4, Meridian hardware, "55 days"
2. Rep asks the Bedrock agent     "Is this deal realistic?"
3. Agent reads deal history       100 past contracts in Box (metadata)
4. Agent checks the promise       finds the 3 most similar past deals (RULES.md)
5. Agent answers the rep          🔴 RED  "55 days promised, history says 139"
                                  + cited comparable contracts + top risks
                                  + suggested safer timeline
6. Agent writes back to Box       risk report PDF + review task assigned to deal desk
```

## What the rep gets

| Output | Example |
|---|---|
| Verdict | 🔴 RED / 🟠 AMBER / 🟢 GREEN |
| Headline | "55 days promised, history says 139." |
| Evidence | Comparable contracts by ID (e.g. CTR-0010: promised 100, took 141) |
| Risks | Q4 hardware slip, Meridian Systems backorders, deep-discount scope creep |
| Suggestion | Rebaseline toward the comparable median |
| Hand-off | Report PDF in Box + review task assigned to deal desk |

The verdict comes from deterministic rules ([RULES.md](./RULES.md)), not LLM
guesswork. The LLM only talks to the rep. A human approves the final call.

## Agent actions (Bedrock action group → Lambda)

| Action | Purpose |
|---|---|
| `raiseRisks` | Deal terms in → verdict, headline, risks, cited comparables |
| `analyzeAndReport` | Same check + report PDF uploaded to Box + review task |

## Repo map

```
data/contracts/        100 synthetic past contracts (PDF) + manifest.json (ground truth)
data/catalog.py        customers, SKUs, vendors, planted risk patterns
box/box_client.py      live Box (CCG auth): list, upload, metadata, Box AI, tasks
box/local_source.py    offline fallback; get_source() picks Box when creds are set
agent/bedrock_agent.md agent instructions
agent/openapi.yaml     action-group schema
agent/infra/setup.md   Lambda + Bedrock deploy guide
agent/lambda/handler.py         Lambda entry + local CLI
agent/lambda/tools/comparison.py   the RULES.md engine
agent/lambda/tools/raise_risks.py  history check + risk rules
agent/lambda/tools/report.py       buildPdf() + createReviewTask()
```

## Tests

```bash
python3 agent/lambda/tools/test_comparison.py          # 5/5   (risk engine)
python3 agent/lambda/tools/test_workflow.py            # 10/10 (notes, loop, reviewer paths)
python3 agent/lambda/tools/features/test_features.py   # 6/6   (the wow features)
python3 agent/lambda/tools/test_integration_e2e.py     # 7/7   (full pipeline + metric emissions)
```

The integration test drives the full `handler.run_action` dispatch (the same
path the Lambda uses) and asserts on both functional outcomes and the telemetry
metrics the CloudWatch dashboard reads. It runs offline by default; set
`RC_E2E_LIVE_CW=1` (with AWS creds + the deployed observability stack) to also
round-trip a canary metric through live CloudWatch.

## Planted patterns in the history

1. **Q4 hardware deals slip** 30–60% (supply chain, holiday freight).
2. **Meridian Systems** is the risky hardware vendor (appliance/PDU backorders).
3. **Discounts >35%** correlate with services scope creep.

## Chat with the agent

```bash
python3 chat.py
```
Needs Box + Bedrock configured (see [Going live](#going-live)). See
[DEMO.md](./DEMO.md) for the live demo script.

## Run it offline (no keys)

```bash
cd agent/lambda
python3 handler.py analyze-and-report --params '{
  "region":"US-East (Ashburn, VA)","signed_quarter":"Q4",
  "hw_vendor":"Meridian Systems","promised_days":55,
  "line_items":[{"sku":"SKU-HW-GPU","qty":2},{"sku":"SKU-SAAS-CORE","qty":250}]
}'
```
Expected: 🔴 RED, "55 days promised, history says 139," report PDF in
`data/reports/`, local review task JSON.

```bash
python3 agent/lambda/tools/test_comparison.py   # engine tests
```

## Going live

Copy `.env.example` to `.env`, fill in Box + AWS values, then follow
[`agent/infra/setup.md`](./agent/infra/setup.md).

---

## Issues to solve before the demo

**P0: must have**

1. ~~**Box SDK v10.**~~ Done: `box/box_client.py` now uses the v10 API (`box_sdk_gen`).
   Run `python3 agent/lambda/tools/check_config.py` to verify auth.
2. **Set up Box.** Create `Reality Check/Deal History` and `Reality Check/Reports`
   in your Box, invite the `AutomationUser_…` service account as Editor, upload
   the 100 contract PDFs, set `BOX_CONTRACTS_FOLDER_ID` / `BOX_REPORTS_FOLDER_ID`
   (default `0` is the service account's own root, not yours).
3. **Stop per-request Box AI calls.** `handler._history()` runs Box AI extraction
   on all 100 contracts on every request (≈100 of 1,000 monthly AI units, and a
   Lambda timeout). Index once: write each contract's fields to
   `global/properties` metadata, then read metadata at runtime.
4. **Metadata write fails on the free plan.** `write_metadata()` uses an
   `enterprise` template; switch to `global/properties`.
5. **Review task isn't assigned.** `createReviewTask()` creates the task but
   never calls `task_assignments`. Add `BOX_REVIEWER_USER_ID` and assign it.
6. **Narrow the Bedrock agent to intelligence only.** Remove `draftContract`
   and `deepResearch` from `openapi.yaml` and `bedrock_agent.md`.
7. **Deploy.** Package the Lambda with `boxsdk`, timeout ≥ 60s, Box creds as env
   vars. Create the Bedrock agent + action group, pick a current Claude model
   (`.env.example` lists an old one).

**P1: if time**

8. **Read the draft from Box.** Rep saves the draft deal in `Reality Check/Drafts`;
   the agent pulls its terms with Box AI (`/ai/extract_structured`) instead of
   the rep typing them.
9. **Backup:** record the offline demo in case live Box/Bedrock fails.

**Out of scope for this demo:** contract drafting, the notes → draft workflow,
`docs/` (data-center story), and the extra features (grade, redline,
simulator, portfolio radar). The code stays in the repo but isn't in the pitch.

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
