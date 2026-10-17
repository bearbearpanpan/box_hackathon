# Reality Check

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

---
*All contract data is synthetic. Customer names are fictional.*
