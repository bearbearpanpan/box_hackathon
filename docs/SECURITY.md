# Security Threat Model

Scope: the Reality Check Bedrock agent, its Lambda tools, the Box integration,
and the local/offline execution path. Checked against the
**[OWASP Top 10:2025](https://owasp.org/Top10/2025/)**.

> All contract data in this repo is synthetic. Customer names are fictional.
> No secret credential values are committed; see "Secrets" below.

## Assets & trust boundaries

| Asset | Where | Sensitivity |
|-------|-------|-------------|
| Box enterprise service token (CCG) | env / Lambda config | **High** — enterprise-wide access |
| AWS credentials / Bedrock access | provider chain | High |
| Contract corpus + generated reports | Box / `data/` | Medium (synthetic here) |
| Review packages (approval state) | `data/reviews/*.json` | Medium — authorizes deals |

Trust boundaries (from [ARCHITECTURE.md](./ARCHITECTURE.md)):

1. **Bedrock Agent → Lambda** — LLM controls action + all parameters.
2. **Lambda → Box API** — single broad-scope enterprise token.
3. **Lambda → Bedrock runtime** — deal/notes data sent in prompts.
4. **Lambda → filesystem** — review/report writes.
5. **LLM / Box AI output → structured data** — model replies re-parsed and
   re-entered into control flow.

## Findings mapped to OWASP Top 10:2025

| ID | OWASP 2025 | Finding | Status |
|----|-----------|---------|--------|
| F1 | **A01 Broken Access Control** | No authn/authz in the Lambda. Any caller can invoke any action, including `resolve-review` / `resume-workflow`. Reviewer identity is unverified free text; no segregation of duties. | Open — mitigate at deploy (IAM + agent-layer auth) |
| F2 | **A01 Broken Access Control** | Path traversal: `contract_id` / `draft_id` / caller-supplied `review_id` flow into filesystem paths (`local_source.upload_pdf`, `report.createReviewTask`, `approvals._path`) without sanitization. | **Fixed** (input sanitization) |
| F3 | **A05 Injection** | `eval()` of `RISK_LIBRARY` triggers in `raise_risks._eval_static_rules` — a dynamic code-execution sink, latent if rules ever become externally sourced. | **Fixed** (safe AST evaluator) |
| F4 | **A08 Software/Data Integrity Failures** | Untrusted LLM / Box AI output JSON-parsed via naive `{`…`}` slicing and re-entered as structured data. | Open — documented; schema-validate on hardening |
| F5 | **A07 Authentication Failures** | One broad Box enterprise CCG token — wide blast radius if leaked. Partly mitigated: MCP `autoApprove` whitelists only read-only Box tools. | Mitigated by design; scope-down recommended |
| F6 | **A03 Software Supply Chain Failures** | `>=` version ranges, no lockfile; placeholder MCP package name (typosquat-prone). | **Mitigated** (SBOM + Dependabot + pip-audit + dep-review) |
| F7 | **A02 Security Misconfiguration** | `.env` present at repo root; risk of committing real credentials. | **Verified safe** — `.env` is gitignored and was never committed |
| F8 | **A05 Injection** | No input validation on flattened Bedrock params; types/ranges trusted implicitly. | Open — documented |
| F9 | **A10 Mishandling of Exceptional Conditions** | Broad `try/except: continue` / bare excepts silently swallow errors (e.g. around rule eval, AI JSON parsing). | Partially addressed — eval path now catches narrow exceptions |

### Not applicable / low relevance
- **A04 Cryptographic Failures** — no custom crypto; TLS handled by SDKs.
- **A06 Insecure Design** — human-in-the-loop approval is an intentional
  security control, not a gap.
- **A09 Logging & Alerting Failures** — CI now surfaces SAST/secret/dependency
  alerts; application-level audit logging is a deploy-time concern.

## Controls in place

- **SAST:** CodeQL (`security-extended`) + Bandit, on every push/PR (SARIF → Security tab).
- **Secret scanning:** Gitleaks over full history.
- **Dependency scanning:** pip-audit + Dependabot (pip + GitHub Actions) + PR dependency-review; vulnerability alerts + automated security fixes enabled.
- **Supply chain:** CycloneDX SBOM (`sbom.json`) regenerated on every check-in (pre-commit hook) and verified in CI.
- **Secret hygiene:** `.env` gitignored; `.env.example` documents keys; no secret values in source.

## Recommended hardening before production

1. **F1 / A01** — enforce authz at the Bedrock-agent / API-Gateway / IAM layer;
   verify reviewer identity and require segregation of duties on `resolve-review`.
2. **F4 / A08** — validate LLM/Box AI output against an explicit schema before use.
3. **F5 / A07** — scope the Box token to the minimum folders; rotate regularly.
4. **F6 / A03** — pin exact dependency versions + commit a lockfile; resolve the
   real Box MCP package name.
5. **F8 / A05** — validate and type-check all inbound params in the handler.
6. **F9 / A10** — narrow broad excepts; log swallowed errors.
