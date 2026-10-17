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
| `agent/infra/setup.md` | Deploy guide (Lambda + agent + Box) | Adequate | Step-by-step; `action_groups.json` is reference-only (no live IaC in repo). |
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

## Findings

1. **No LICENSE (fixed).** The repo was public with no license — added MIT.
2. **OpenAPI under-documents the action surface.** `openapi.yaml` lists 4 of
   ~15 routed actions. Low risk (the agent instructions cover the rest), but
   worth completing if the schema is ever used for external contract testing.
3. **No security documentation (fixed).** Added `SECURITY.md` with an
   OWASP-2025 threat model and a hardening checklist.
4. **No architecture overview (fixed).** Added `ARCHITECTURE.md`.
5. **Deploy docs assume manual setup.** `agent/infra/setup.md` is manual;
   there is no committed IaC (Terraform/CDK/SAM). Fine for a hackathon;
   call out as a productionization gap.
6. **Secret hygiene is sound.** `.env.example` is the only env doc committed;
   real `.env` is gitignored and absent from history (verified).

## Verification performed

- All three test suites pass: `test_comparison.py` (5/5), `test_workflow.py`
  (10/10), `test_features.py` (6/6).
- `.env` confirmed untracked and absent from git history.
- SBOM generator runs clean and produces valid CycloneDX 1.5.
- CI (CodeQL, Bandit, pip-audit, Gitleaks, SBOM) runs green on `main`.
