# Reality Check

> Sales promises. Ops delivers. Reality Check makes sure they're the same thing.

**Reality Check reviews a sales contract before it goes to the customer.** It
pulls every feature, delivery, and performance claim out of the contract,
checks each one against the company's own evidence in **Box**, and writes a
claim-by-claim risk report back to Box. It runs on **Claude via Amazon Bedrock**.

It does not draft, edit, approve, or negotiate contracts. It gives the field
team evidence; a human makes the call. Full spec: [PRD.md](./PRD.md).

## How it works

```
Rep: "Review the Northstar agreement."
   │
   ▼
agent/local_agent.py ── Claude on Bedrock (chat + tool calls)
   │
   ├─ reads the contract        Box: contracts/
   ├─ reads the evidence        Box: evidence/   (B1 product docs, B2 roadmap, B3 delivery reviews)
   ├─ Claude compares each claim with the evidence
   ├─ severity is fixed in code (Feature High, Delivery High, Performance Medium, No source High)
   └─ uploads the report PDF    Box: reports/
```

## Box setup

Three top-level folders, each shared with the app's service account
(`AutomationUser_…@boxdevedition.com`) as **Editor**:

| Box folder | Contents | `.env` key |
|---|---|---|
| `contracts` | Contracts to review (`docs/box_upload/contracts/*.pdf`) | `BOX_CONTRACTS_FOLDER_ID` |
| `evidence` | B1–B3 evidence (`docs/box_upload/evidence/*.pdf`) | `BOX_EVIDENCE_FOLDER_ID` |
| `reports` | Review reports written by the agent | `BOX_REPORTS_FOLDER_ID` |

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                  # fill in Box + Bedrock values

python3 agent/check_config.py         # Box ✅  Bedrock ✅
python3 agent/local_agent.py --list   # shows folders and files the agent sees
python3 agent/local_agent.py          # chat
```

Offline (no Box, reads `docs/box_upload/`, still needs Bedrock):
`python3 agent/local_agent.py --offline`

## Demo

1. *"Review the Northstar agreement."* → **1 No risk · 3 Risk identified · 1 No source found**
   - Smart Archive Search promised at launch, roadmap says Exploratory (Feature, High)
   - 30-day migration, comparable migrations took 58–72 days (Delivery, High)
   - 10 GB/s sustained, benchmark validates 5 GB/s (Performance, Medium)
   - LegacyVault direct import, no source in Box (No source found, High)
   - Encryption at rest, confirmed by B1 (No risk)
2. Open `reports/` in Box and show the report PDF with source links.
3. *"Now review v2."* → the revised contract comes back clean.

## Repo

```
agent/local_agent.py      the agent: chat loop, Box reads, review, report
agent/check_config.py     preflight for Box + Bedrock
agent/envload.py          .env loader
agent/minipdf.py          dependency-free PDF writer (reports + demo docs)
box/box_client.py         Box API wrapper (boxsdk v10, CCG)
docs/contracts, evidence  demo docs (Markdown source)
docs/box_upload/          the same docs as PDFs, ready to upload to Box
docs/build_pdfs.py        rebuild the PDFs after editing the Markdown
```

Tests: `python3 agent/test_local_agent.py` and `python3 agent/test_check_config.py`

---
*All contracts, evidence, customers, and figures are fictional demo data.*
