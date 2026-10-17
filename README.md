# Reality Check

<p align="center">
  <img src="docs/assets/reality-check.png" alt="Reality Check — Sales Claim Checker Agent" width="400">
</p>

**Help sales teams identify risks before making commitments to customers.**

Reality Check reviews a draft sales contract before the commitments in it are
made. It pulls out every feature, delivery, and performance claim, checks each
one against the company's own evidence in **Box**, comments the result on every
claim directly on the contract in Box, and saves a one-page risk report. It runs
on **Claude via Amazon Bedrock**.

It does not draft, edit, approve, route, or negotiate contracts. It gives the
field team evidence; a human makes the call. Full spec: [PRD.md](./PRD.md).

## The problem

Sales teams make promises about features, delivery dates, and performance
without easy access to reliable delivery information. Checking means piecing
together scattered documents and chasing product and operations for answers, so
risks go unnoticed until after the customer has been promised something.

**Primary user:** a salesperson or field team member preparing a customer
contract. **Supporting users:** product and operations owners who clarify or
approve commitments flagged for review.

## How it works

```
Rep: "Review the Northstar agreement."
   │
   ▼
agent/local_agent.py ── Claude on Bedrock (chat + tool calls)
   │
   ├─ reads the draft contract    Box: contracts/
   ├─ reads the evidence          Box: evidence/
   ├─ Claude extracts each claim and compares it with the evidence
   ├─ severity is fixed in code, never by the model
   ├─ comments the result on every claim     Box: comment on the contract
   └─ uploads the risk report PDF            Box: reports/
```

### Input

One draft sales contract, including any schedules that contain customer
commitments. The rep does not collect evidence; the agent finds it in Box.

### Evidence in Box

| Priority | Documents | What they establish |
|---|---|---|
| 1 | **Approved product documentation** (B1) | What can be promised today: supported features, configurations, benchmarks, limits |
| 2 | **Product roadmap and release plans** (B2) | What is planned, by when, and whether a date is a Target or a Committed release |
| 3 | **Project closeout reports and delivery reviews** (B3) | What similar projects actually took, what slipped, and why |

Every evidence document carries an owner and a last-updated date, and the
report shows both.

### The three risks it checks

| Risk | What gets flagged | Northstar example |
|---|---|---|
| **Feature availability** | A promised capability is unavailable, unsupported, or only planned | Smart Archive Search promised at launch; roadmap says Exploratory |
| **Delivery deadline** | A date has no committed plan or beats comparable delivery history | 30-day migration; comparable migrations took 58–72 days |
| **Performance commitment** | A speed, throughput, or scale promise exceeds the benchmark or its conditions | 10 GB/s sustained; benchmark validates 5 GB/s |

### Decision rules

```
For each claim:
  no relevant source in Box      → No source found   (High)
  source matches the claim       → No risk           (None)
  source does not match          → Risk identified, by category:
                                      Feature availability   (High)
                                      Delivery deadline      (High)
                                      Performance commitment (Medium)
```

- A match must cover the claim's conditions: Region, configuration, date, workload.
- A roadmap Target or Exploratory item does not support a promised date or feature.
- A benchmark supports only claims within its tested conditions; burst numbers are not sustained numbers.
- **No source found** means the claim could not be verified in Box. It does not prove the claim is false.

### Output

1. **A comment on every claim, on the contract itself in Box.** The rep sees the
   result where they're already working: the result, severity, a one-line reason,
   the source, and a link to the report.
2. **A one-page risk report PDF in `reports/`:** a summary banner and counts,
   then "Needs attention" ordered by severity, then "Supported by evidence," then
   the Box sources with owner dates and links.

Each claim result shows: exact claim and location, result, risk category,
severity, and evidence with explanation.

## Box setup

Three top-level folders, each shared with the app's service account
(`AutomationUser_…@boxdevedition.com`) as **Editor** (Editor is needed to upload
reports and post comments):

| Box folder | Contents | `.env` key |
|---|---|---|
| `contracts` | Draft contracts to review (`docs/box_upload/contracts/*.pdf`) | `BOX_CONTRACTS_FOLDER_ID` |
| `evidence` | B1–B3 evidence (`docs/box_upload/evidence/*.pdf`) | `BOX_EVIDENCE_FOLDER_ID` |
| `reports` | Risk reports written by the agent | `BOX_REPORTS_FOLDER_ID` |

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # fill in Box + Bedrock values

python3 agent/check_config.py         # Box ✅  Bedrock ✅
python3 agent/local_agent.py --list   # folders and files the agent sees
python3 agent/local_agent.py          # chat
```

Offline (no Box; reads `docs/box_upload/`, writes report and comments to
`reports/`, still needs Bedrock): `python3 agent/local_agent.py --offline`

## Demo

1. *"Review the Northstar agreement."* → **1 No risk · 3 Risks identified · 1 No source found** (3 High · 1 Medium · 1 None)

   | Claim | Result | Severity |
   |---|---|---|
   | §1 Encryption at rest | No risk (B1 confirms) | None |
   | §2 Smart Archive Search at launch | Feature availability risk (B2: Exploratory) | High |
   | §3 Migration within 30 days | Delivery deadline risk (B3: 58–72 days) | High |
   | §4 10 GB/s sustained | Performance commitment risk (B1: 5 GB/s) | Medium |
   | §5 LegacyVault direct import | No source found | High |

2. Open the contract in Box: one Reality Check comment per claim.
3. Open `reports/` in Box: the one-page risk report.
4. *"Now review v2."* → the revised contract comes back with every claim supported.

Re-running a review posts a fresh set of comments and saves the report as a new
version.

## Scope

**V1:** one draft contract at a time, the three risk categories above, against
the three Box sources, for an initial review and a fresh review of a revised
contract.

**Out of scope:** service-level, support, security, and compliance reviews;
contract drafting, automatic contract changes, approval routing, negotiation,
signature, portfolio reporting, and post-signature obligation tracking.

**Future enhancements:** suggested wording backed by evidence, routing exceptions
to product or operations owners, and rechecking contracts when roadmaps or
capabilities change.

## Success metrics

- **North star, risks caught before commitment:** share of expert-identified risky claims flagged before sales commits.
- **Risk precision:** share of flagged claims that expert reviewers confirm.
- **Risk recall:** share of expert-identified risky claims that get flagged.
- **Source accuracy:** share of results whose cited evidence, or No source found result, experts confirm.

## Repo

```
agent/local_agent.py      the agent: chat loop, Box reads, review, comments, report
agent/check_config.py     preflight for Box + Bedrock
agent/envload.py          .env loader
agent/minipdf.py          dependency-free PDF writer (report + demo docs)
box/box_client.py         Box API wrapper (boxsdk v10, CCG)
docs/contracts, evidence  demo docs (Markdown source)
docs/box_upload/          the same docs as PDFs, ready to upload to Box
docs/build_pdfs.py        rebuild the PDFs after editing the Markdown
PRD.md                    product requirements
PRESENTATION_OUTLINE.md   pitch deck outline
```

Tests: `python3 agent/test_local_agent.py` and `python3 agent/test_check_config.py`

---
*All contracts, evidence, customers, and figures are fictional demo data, not actual AWS commitments.*
