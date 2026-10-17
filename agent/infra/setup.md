# Deploying Reality Check

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
  --environment "Variables={BOX_CLIENT_ID=...,BOX_CLIENT_SECRET=...,BOX_ENTERPRISE_ID=...,USE_BOX_AI=true,BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0,AWS_REGION=us-east-1}"
```

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
