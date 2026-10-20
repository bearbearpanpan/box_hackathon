# Reality Check — infrastructure (CDK)

Python AWS CDK app that provisions the **observability stack**: a succinct
CloudWatch dashboard plus baseline alarms for the Reality Check Lambda and its
Box/Bedrock dependencies.

The dashboard visualizes the telemetry emitted by [`box/telemetry.py`](../../../box/telemetry.py)
(custom metrics in the `RealityCheck` namespace, published as EMF when the
Lambda runs with `EMIT_METRICS=true`) alongside the automatic `AWS/Lambda`
service metrics.

## What it creates

- **CloudWatch dashboard** (`RealityCheck`) — three compact rows:
  1. **Lambda health** — invocations / errors / throttles, p50/p99 duration vs
     the 60s timeout, max concurrency.
  2. **Throughput & Bedrock** — contract reviews run vs no-match, claims reviewed,
     Bedrock invokes / failures / token usage.
  3. **Review KPIs** — claims by result (No risk / Risk identified / No source found),
     risks flagged, claim severity mix (High / Medium / None).
- **Baseline alarms** — Lambda errors, p99 duration nearing timeout, Bedrock
  invoke failures.
- **Optional SNS email notifications** for those alarms (pass `alarmEmail`).

## Prerequisites

- Node.js ≥ 20 and Python ≥ 3.9.
- The project's single assigned AWS Region (new AWS experience). The app reads
  `CDK_DEFAULT_ACCOUNT` / `CDK_DEFAULT_REGION` from your environment / profile.

## Setup

```bash
cd agent/infra/cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # CDK library
npm install                         # pinned CDK CLI (invoke via ./node_modules/.bin/cdk)
```

> The CDK CLI is pinned in `package.json` and must stay compatible with
> `aws-cdk-lib` in `requirements.txt` (a newer library needs a newer CLI). If
> you see a "Cloud assembly schema version mismatch", bump the `aws-cdk` pin.

## Deploy

```bash
# first time only, per account+region:
./node_modules/.bin/cdk bootstrap

./node_modules/.bin/cdk synth --strict
./node_modules/.bin/cdk diff
./node_modules/.bin/cdk deploy
```

### Configuration (CDK context)

| Context key     | Default          | Purpose                                   |
|-----------------|------------------|-------------------------------------------|
| `functionName`  | `reality-check`  | Lambda function name the widgets target.  |
| `dashboardName` | `RealityCheck`   | CloudWatch dashboard name.                |
| `alarmEmail`    | *(unset)*        | If set, creates an SNS topic + email sub. |

```bash
./node_modules/.bin/cdk deploy \
  -c functionName=reality-check \
  -c alarmEmail=ops@example.com
```

## Enabling the custom metrics

The `RealityCheck`-namespace widgets populate only when the Lambda emits EMF
metrics. Set `EMIT_METRICS=true` (and optionally `LOG_LEVEL=INFO`) in the
function's environment — see `../setup.md`.
