# Deploying Reality Check

## Do you even need Lambda? (short answer: no, not for a local demo)

There are two ways to run this, and they are independent:

| | Local | AWS (Bedrock agent + Lambda) |
|---|---|---|
| **Need Lambda?** | **No** | Yes |
| **How it runs** | `python3 demo.py` / `python3 handler.py <action>` | Bedrock agent calls the Lambda |
| **Bedrock** | Optional — calls Bedrock directly via `boto3` using your AWS creds; falls back to deterministic logic if unset | Lambda calls Bedrock with its IAM role |
| **Box** | Optional — direct Box API via `boxsdk`; falls back to local `manifest.json` | Same, from inside Lambda |
| **Best for** | the demo, dev, iterating | a hosted, always-on agent |

**Lambda is only the hosting mechanism for the Bedrock *agent*.** Running
locally, your machine IS the executor — the same `handler.py` runs your Python
directly, and it talks to Bedrock/Box over the network using your local
credentials. No Lambda, no API Gateway, no IAM roles required.

Use Lambda only when you want the agent to live in AWS and be invoked by the
Bedrock Agent runtime (so a conversational agent, not just a script, drives it).

---

## Local demo (no Lambda, no AWS infra)

```bash
cp .env.example .env          # fill in keys you have (all optional)
pip install boto3 boxsdk      # only needed for LIVE Bedrock/Box
python3 agent/lambda/handler.py check-config   # preflight: are keys live?
python3 demo.py               # full narrated demo
```
- `.env` is auto-loaded (no `source` needed). Real shell/Lambda env vars win.
- With **no keys**: everything runs in deterministic offline mode — still a
  complete, honest demo.
- With **AWS keys** (`AWS_REGION`, `BEDROCK_MODEL_ID`, credentials via
  `aws configure` or env): the notes parser and research brief use Bedrock.
- With **Box keys**: contracts are read from / reports written to Box.

`check-config` makes one tiny real call to each configured service and prints
`✅ connected` or a clear error, so you verify keys BEFORE going live.

---

## AWS deployment (only if you want the hosted agent)

Everything below assumes you've filled in `.env` from `.env.example`.

## 0. Prerequisites
- AWS account with Bedrock model access enabled (Claude 3.5 Sonnet or similar).
- A Box custom app (Server auth / Client Credentials Grant) with Box AI enabled.
- Python 3.11+, `pip install -r agent/lambda/requirements.txt`.

## 1. Generate / confirm the data
```bash
python3 data/generate_contracts.py          # 100 PDFs + manifest.json
```
Upload `data/contracts/*.pdf` to your Box contracts folder; set
`BOX_CONTRACTS_FOLDER_ID` to that folder's id. (Or keep running offline against
`manifest.json` — the pipeline auto-detects which to use.)

## 2. Run it locally first (no AWS needed)
```bash
cd agent/lambda
python3 handler.py analyze-and-report --params '{
  "region":"US-East (Ashburn, VA)","signed_quarter":"Q4",
  "hw_vendor":"Meridian Systems","promised_days":55,
  "line_items":[{"sku":"SKU-HW-GPU","qty":2},{"sku":"SKU-SAAS-CORE","qty":250}]
}'
```
You should see a RED verdict, cited comparables, a report PDF in
`data/reports/`, and a `task_*.json` review task. This is your demo fallback.

## 3. Package & deploy the Lambda
```bash
cd agent/lambda
pip install -r requirements.txt -t build/
cp -r *.py tools build/
cp -r ../../box ../../data build/        # bundle box client + manifest
cd build && zip -r ../reality-check-tools.zip . && cd ..
aws lambda create-function \
  --function-name reality-check-tools \
  --runtime python3.11 --handler handler.lambda_handler \
  --timeout 60 --memory-size 512 \
  --role arn:aws:iam::<ACCOUNT_ID>:role/<lambda-exec-role> \
  --zip-file fileb://reality-check-tools.zip \
  --environment "Variables={BOX_CLIENT_ID=...,BOX_CLIENT_SECRET=...,BOX_ENTERPRISE_ID=...,USE_BOX_AI=true,BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0,AWS_REGION=us-east-1,LOG_LEVEL=INFO,EMIT_METRICS=true}"
```

**Observability env vars** (handled by `box/telemetry.py`):
- `LOG_LEVEL` — `INFO` (default), `DEBUG`, or `WARNING`. Structured JSON logs go
  to stderr → CloudWatch Logs.
- `EMIT_METRICS` — set `true` to emit EMF metrics (namespace `RealityCheck`) that
  the dashboard in step 7 reads. Off by default so the local CLI stays clean.

## 4. Create the Bedrock agent
1. Bedrock console -> Agents -> Create agent `reality-check`.
2. Instructions: paste `agent/bedrock_agent.md`.
3. Action group `deal-tools`: executor = the Lambda above; API schema =
   `agent/openapi.yaml`.
4. Grant the agent's resource role `lambda:InvokeFunction` on the Lambda, and
   the Lambda's role `bedrock:InvokeModel`.
5. Prepare + create an alias; set `BEDROCK_AGENT_ID` / `BEDROCK_AGENT_ALIAS_ID`.

## 5. Wire Box MCP (optional, for agent-driven doc reads)
Register `box/mcp_config.json` with your MCP-capable runtime. Read-only tools
are auto-approved; write/report tools require confirmation. If you're not using
MCP federation, the Lambda already talks to Box directly via `box_client.py`.

## 6. Demo flow
Upload a draft contract to the Box folder, then ask the agent:
> "Run a reality check on the new draft."
~30s later it returns the RED headline with citations and drops a review task on
the deal desk.

## 7. Observability dashboard (CDK)
Deploy the CloudWatch dashboard + baseline alarms that visualize the Lambda's
health, Box AI / Bedrock usage, and the agentic-workflow KPIs:

```bash
cd agent/infra/cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install                 # pinned CDK CLI
./node_modules/.bin/cdk bootstrap        # first time per account+region
./node_modules/.bin/cdk deploy -c functionName=reality-check-tools
```
The dashboard's custom-metric widgets populate once the Lambda runs with
`EMIT_METRICS=true` (step 3). See `agent/infra/cdk/README.md` for details and
the optional `alarmEmail` notification wiring.
