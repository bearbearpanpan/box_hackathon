# Documentation Audit

A review of every document in the repository: what it covers, whether it is
accurate against the code, and any gaps. Audited October 2026.

## Inventory & assessment

| Document | Purpose | Accuracy | Notes |
|----------|---------|----------|-------|
| `README.md` | Project overview, capabilities, run instructions | **Good** | Matches the code: actions, offline fallback, tests, and planted-pattern claims all verified. Lists more actions than `openapi.yaml` (expected — the Lambda routes a superset). |
| `RULES.md` | Risk-engine spec (similarity / timeline / risk tiers) | **Good** | The comparison engine and `RISK_LIBRARY` match the spec; covered by `test_comparison.py` (5/5). |
| `ROADMAP.md` | The five "wow" features | **Good** | All five features exist under `tools/features/` and are tested (6/6). |
| `.env.example` | All config keys with guidance | **Good** | Complete; correctly warns "NEVER commit `.env`". `.env` is gitignored and was never committed. |
| `agent/bedrock_agent.md` | Agent instructions to paste into Bedrock | Adequate | Deployment-time reference; not executed. |
| `agent/infra/setup.md` | Deploy guide (Lambda + agent + Box + dashboard) | **Good** | Step-by-step; now includes the observability env vars and the CDK dashboard step. |
| `agent/infra/cdk/README.md` | CDK observability app (dashboard + alarms) | **Good** | Matches the stack; documents context config and the `EMIT_METRICS` dependency. |
| `agent/openapi.yaml` | Action-group API schema | **Partial** | Declares 4 paths; the Lambda implements ~15 actions. Intentional, but the schema under-documents the surface. |
| `docs/closeouts/*.md` | Scenario closeout write-ups | Narrative | Demo/story content; not code-bearing. |

## New documents added in this pass

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE.md` | Succinct architecture: components, request flow, trust boundaries, stack. |
| `docs/SECURITY.md` | Threat model mapped to OWASP Top 10:2025. |
| `docs/DOC_AUDIT.md` | This file. |
| `LICENSE` | MIT license (previously absent). |
| `sbom.json` | CycloneDX SBOM, regenerated on every check-in. |

## Observability pass (added later)

| Change | Purpose |
|--------|---------|
| `box/telemetry.py` | Dependency-free structured logging, latency timing, and EMF metrics across the Bedrock→Lambda, Lambda→Box, and Lambda→Bedrock boundaries plus workflow KPIs. Opt-in via `LOG_LEVEL` / `EMIT_METRICS`. |
| `agent/infra/cdk/` | Python CDK app: a compact CloudWatch dashboard (with collapsible per-widget explanations) + baseline alarms over the `RealityCheck` metric namespace. |
| `agent/lambda/tools/test_integration_e2e.py` | End-to-end test driving `handler.run_action`; asserts functional outcomes and metric emissions (plus an opt-in live CloudWatch round-trip). |

## Findings

1. **No LICENSE (fixed).** The repo was public with no license — added MIT.
2. **OpenAPI under-documents the action surface.** `openapi.yaml` lists 4 of
   ~15 routed actions. Low risk (the agent instructions cover the rest), but
   worth completing if the schema is ever used for external contract testing.
3. **No security documentation (fixed).** Added `SECURITY.md` with an
   OWASP-2025 threat model and a hardening checklist.
4. **No architecture overview (fixed).** Added `ARCHITECTURE.md`.
5. **Deploy docs: partially IaC now.** The observability layer ships as a
   committed CDK app (`agent/infra/cdk/`). The Lambda + Bedrock agent setup in
   `agent/infra/setup.md` is still manual CLI/console — a remaining
   productionization gap, but no longer a total absence of IaC.
6. **Secret hygiene is sound.** `.env.example` is the only env doc committed;
   real `.env` is gitignored and absent from history (verified).

## Verification performed

- All four test suites pass: `test_comparison.py` (5/5), `test_workflow.py`
  (10/10), `test_features.py` (6/6), `test_integration_e2e.py` (7/7).
- `.env` confirmed untracked and absent from git history.
- SBOM generator runs clean and produces valid CycloneDX 1.5.
- CDK observability stack synthesizes (`cdk synth --strict`) and deploys; a live
  canary metric round-trips through CloudWatch.
- CI (CodeQL, Bandit, pip-audit, Gitleaks, SBOM) runs green on `main`.
