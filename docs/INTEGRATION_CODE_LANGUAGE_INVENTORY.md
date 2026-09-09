# Integration Code Language Inventory — Stage 6

## Baseline and scope

Base commit: `4d6a3ea247bfd6c009878914e1046e464648e79a` (manual merge of PR #61).
Stage-six scope is defined by `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`:
MCP, adapters, CI, and developer tooling.

The bounded inventory examined:

- `mcp/src/**/*.ts` and `mcp/test/**/*.ts`;
- `adapters/**`;
- `.github/workflows/*.yml` and `.github/governance/main-ruleset.json`;
- `scripts/codex/setup-coderabbit.sh` and its guardrail/HTTPS tests.

This is not the final repository-wide residual audit; that remains stage 8.

## Finding

MCP implementation, MCP tests, adapter documentation/configuration, and workflow/job/step display names were already English-first. They are therefore preserved instead of being rewritten for cosmetic churn.

The active stage-six language debt was developer-facing diagnostic/output text in `scripts/codex/setup-coderabbit.sh`. Thirty-four occurrences across thirty-three messages were translated to English. The control flow, exit codes, commands, URLs, checksums, plugin ids, source SHA, and authentication decisions were not changed.

## Preserved contracts

### MCP/API

The following MCP tool names remain exact:

- `runtime_status`
- `reference_status`
- `run_synthetic_canary`
- `audit_record`

Every MCP tool still exposes only the `requestId` input field. `requestId` remains optional for the two status tools and required for the synthetic canary and audit-record tools.

Deployment-admin environment names remain exact:

`PROJECT_ROOT`, `REF_ROOT`, `RESULTS_ROOT`, `AUDIT_ROOT`, `PORT`, `MCP_BIND_HOST`.

### Protected status checks

The tracked protected-main ruleset remains byte-for-byte unchanged from the baseline. Its required contexts remain:

`static`, `container-canary`, `Canonical policy + 263-rule contract`, `OPA/Rego parity`, `Real Docker + canonical read-only mount`, `CodeRabbit`, `Greptile Review`, `GitGuardian Security Checks`, five DeepSource language contexts, `security/snyk (drhudsonandrade)`, and `semgrep-cloud-platform/scan`.

No workflow or governance file is modified by stage 6.

## Intentional Portuguese preserved

The following are not developer-language debt:

- `NÃO DISPONÍVEL` in runtime/resource workflows: normative operational output.
- `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, `NÃO DISPONÍVEL` in the optional Supabase projection: serialized contract values.
- `Conteúdo rastreável para teste editorial de regressão visual.` and `Fixture editorial; não representa paciente.` in visual-QA candidate generation: intentional pt-BR fixture content.
- `dados[ _-]*dna` in the SNP-array workflow: safety detection for Portuguese personal-data filename patterns, not a developer identifier.

These exceptions are protected by `tests/test_integration_code_language.py` so a future language cleanup cannot silently translate them.

## Reproducible validation

Focused validation:

```bash
python -m unittest tests.test_integration_code_language -v
python -m unittest tests.test_coderabbit_guardrails tests.test_coderabbit_https_transport -v
npm test --prefix mcp
bash -n scripts/codex/setup-coderabbit.sh
```

Repository validation before release:

```bash
python scripts/code_language_guard.py --check
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python -m unittest discover -s tests -v
for source in scripts/*.sh scripts/codex/*.sh; do bash -n "$source"; done
npm ci --prefix mcp --ignore-scripts
npm test --prefix mcp
git diff --check
```

The stage-six Python test also pins the current MCP environment-variable set and required status-check contexts. The MCP initialization test pins tool/input-schema compatibility using the real in-memory MCP transport.

## Compatibility classification

- **A — private implementation/developer diagnostics:** CodeRabbit setup messages translated to English.
- **B — public/cross-module symbols:** no rename required; current MCP/adapters symbols were already English.
- **C — serialized/persisted contracts:** MCP tool/input names, environment names, required checks, adapter status values preserved.
- **D — localized content:** pt-BR visual-QA fixture text preserved.
- **E — historical/canonical evidence:** untouched.

No deployment, real genomic analysis, production MCP connection, or post-deployment claim is part of this language refactor.
