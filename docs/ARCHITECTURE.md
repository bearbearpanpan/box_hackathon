# Architecture

Reality Check is an **AWS Bedrock agent** that turns messy sales-call notes into
a risk-checked tech-sales contract. It reads a corpus of historical contracts
from **Box**, drafts a new deal, compares the promised timeline against
comparable past deals plus external risk signals, auto-fixes what it safely can,
escalates hard conflicts to a human reviewer, and writes a risk-report PDF back
to Box with a deal-desk review task.

It runs **fully offline** against local fixtures when no credentials are set, so
the whole pipeline is demoable without any cloud dependency.

## Components

| Area | Path | Responsibility |
|------|------|----------------|
| **Agent action group** | `agent/action_groups.json`, `agent/openapi.yaml` | Reference config + OpenAPI schema the Bedrock agent uses to pick actions. |
| **Lambda router** | `agent/lambda/handler.py` | Entry point. Routes Bedrock (or local CLI) events to tools; flattens params. |
| **Tools** | `agent/lambda/tools/*` | Core: `draft_contract`, `raise_risks`, `deep_research`, `comparison`, `report`, `revise`, `workflow`, `approvals`, `notes_parser`. "Wow" features in `tools/features/`. |
| **Box integration** | `box/box_client.py` | Box API + Box AI wrapper (CCG auth). |
| **Offline source** | `box/local_source.py` | Duck-typed stand-in reading `data/contracts/manifest.json`. `get_source()` picks Box iff credentials are set. |
| **Data model + fixtures** | `data/` | `catalog.py` (reference data + `RISK_LIBRARY`), `risk_signals.py`, `minipdf.py` (dependency-free PDF writer), 100 synthetic contract PDFs. |
| **Demo** | `demo.py` | Narrated end-to-end walkthrough. |

## Request flow

```
Bedrock Agent (LLM picks action + params)
        │  (or local CLI: {"action","params"})
        ▼
handler.lambda_handler ── _bedrock_params ──▶ run_action (dispatch)
        │
        ├─ draft-contract      → draft_contract
        ├─ raise-risks         → comparison.analyze + RISK_LIBRARY rules
        ├─ deep-research       → deep_research (+ optional Bedrock brief)
        ├─ analyze-and-report  → risk + research + buildPdf + upload + review task
        ├─ run-workflow        → workflow._iterate (the agentic loop)
        ├─ get/list/resolve-review, resume-workflow → approvals / workflow
        └─ grade/redline/obligations/simulate/portfolio → tools/features/*
        ▼
Source (Box live | LocalSource offline)  +  filesystem (reports/reviews)
```

## The agentic loop

`workflow.run_workflow` drives: `notes_parser.parse_notes` → `draft_contract`
→ `_iterate` (max 5 passes of `raise_risks` + `risk_signals.gather_signals` +
`revise.revise`). Each pass auto-fixes safe items; any unacknowledged
escalation exits the loop as `needs_human_approval` and opens a review package
(`approvals.create_review`, persisted as JSON under `data/reviews/`).
`resume_from_review` applies the reviewer's decision (approve / reject /
request_changes) and re-enters the loop until it clears.

## External integrations & trust boundaries

1. **Bedrock Agent → Lambda** — the LLM chooses the action and all parameter
   values. The handler does no authn/authz and minimal input validation.
2. **Lambda → Box API** — authenticated with a single enterprise
   Client-Credentials-Grant service token (broad scope). Used for list /
   download / upload / metadata / tasks and Box AI (`/2.0/ai/ask`).
3. **Lambda → Bedrock runtime** — optional LLM calls for notes extraction and
   the research brief; degrade silently to deterministic output if unset.
4. **Lambda → filesystem** — review packages and report PDFs.
5. **LLM / Box AI output → structured data** — model replies are JSON-parsed
   and re-enter the control flow (untrusted-output-as-input boundary).

## Tech stack

- **Python 3** throughout; standard library only for the core engine
  (`minipdf.py` is deliberately dependency-free).
- **Runtime deps** (`agent/lambda/requirements.txt`): `boto3` (Bedrock) and
  `boxsdk` (Box) — only needed for live calls.
- **Foundation model**: `anthropic.claude-3-5-sonnet-20240620-v1:0`.

See [SECURITY.md](./SECURITY.md) for the threat model and
[DOC_AUDIT.md](./DOC_AUDIT.md) for the documentation review.
