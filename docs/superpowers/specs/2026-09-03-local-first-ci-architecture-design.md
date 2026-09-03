# Local-First Development and Targeted CI Architecture

**Date:** 2026-09-03
**Status:** User-approved architecture; implementation pending written-spec review
**Repository:** `drhudsonandrade/Codework`
**Branch:** `ci/local-first-actions-optimization`

## 1. Objective

Reduce repeated Codex/agent usage and GitHub Actions consumption without weakening GENOMA's scientific, security, evidence, review, or manual-merge gates.

Development becomes local-first on the NOAR VM. GitHub remains authoritative, but it is used as the review and verification boundary rather than as the iterative development environment.

## 2. Selected architecture

- ChatGPT normal chat: planning, analysis, coordination, and implementation control.
- Remote Desktop Commander: edit files on NOAR and execute Python, Node, Git, shell tests, and validators.
- VS Code: inspect and edit the local repository.
- Git + GitHub CLI: branches, commits, controlled pushes, and pull requests.
- GitHub: authoritative remote repository and PR history.
- CodeRabbit + Codacy + GitHub Actions: independent review and CI.
- Superpowers: methodology and gates, without Codex subagents.

## 3. Development flow

The normal cycle is:

`edit on NOAR -> run targeted local tests -> fix locally -> run repository validation -> commit locally -> push one validated block -> PR review/CI`

Rules:

1. Do not use GitHub Actions as an iterative debugger.
2. Do not push every small correction.
3. Batch a coherent, locally validated block before pushing.
4. After a review finding, fix the whole related batch locally and revalidate before the next push.
5. Never auto-merge. Human approval remains the final gate.
6. Never claim PASS for a check that was not executed.

## 4. CI strategies considered

### A. Selected: local-first + targeted CI

Run frequent checks locally, trigger specialized GitHub workflows only for relevant paths, cancel superseded PR runs, and keep a baseline validation for code changes.

### B. Keep current CI and only reduce pushes

Safest but leaves avoidable specialized workflow executions on unrelated PRs.

### C. Almost local-only CI

Lowest Actions usage but removes too much independent GitHub verification and is rejected.

## 5. Current workflow findings

The repository currently has 16 workflow files. The relevant PR-triggered validation workflows are:

- `codacy-api-report-tests.yml`: PR-triggered; already has concurrency.
- `fallow.yml`: all PRs; no path filter or concurrency.
- `genoma-audit.yml`: all PRs and all main pushes; no path filter or concurrency.
- `genoma-ngs-runtime-gate.yml`: already path-filtered for PR and main; no concurrency.
- `genoma-policy-engine.yml`: all PRs, but main push is path-filtered; no concurrency.
- `genoma-snp-array.yml`: already path-filtered for PR and main; no concurrency.
- `genoma-visual-qa-candidates.yml`: already path-filtered; no concurrency.
- `pr30-regressions.yml`: already path-filtered; no concurrency.
- `scaffold-validation.yml`: all PRs and all main pushes; no concurrency; includes a Docker canary.

The live GitHub ruleset currently requires `Codacy Static Code Analysis`. The repository's tracked desired-state ruleset documents additional checks, so check names and fail-closed behavior must remain stable even when execution is optimized.

## 6. Trigger optimization

### Fallow

Add PR path filters for `mcp/**`, JavaScript/TypeScript tests used by the MCP/Codacy surface, Fallow configuration, package locks, and the Fallow workflow itself. Do not run Fallow for unrelated Python/reporting/docs-only changes.

### Policy engine

Mirror the existing `push.paths` list under `pull_request.paths`. This removes policy-engine CI from PRs that do not touch normative, policy, lock, template, validator, adapter, or policy workflow surfaces.

### Four-plane audit

Keep the audit broad for code/configuration changes, but skip PRs and main pushes that change only documentation. Use `paths-ignore` narrowly for documentation-only surfaces; do not enumerate code directories because new code paths must remain covered by default.

### Scaffold validation

Keep `static` as the baseline code validation. Skip the workflow only for documentation-only changes. Preserve the existing `static` and `container-canary` job names.

The Docker canary remains a baseline independent runtime check for code changes in this first optimization. A later PR may add a path classifier inside the workflow to avoid Docker builds for non-runtime code while preserving a successful `container-canary` check.

### Existing targeted workflows

Preserve the current path scopes of NGS, SNP-array, visual QA, and PR30 regression gates unless a separate test demonstrates a scope defect. Their first optimization is cancellation of superseded PR executions, not narrowing scientific coverage.

## 7. Concurrency policy

Add PR-safe concurrency to validation workflows that do not already have it:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

This cancels obsolete runs for the same PR while preserving main pushes and manual runs. Production publication workflows are not changed by this rule unless separately reviewed.

## 8. Heavy scientific jobs

GRCh38 reference foundry and per-sample runtime workflows remain manual/self-hosted as currently designed.

NGS preflight continues to run automatically only when its declared scientific/runtime paths change. Full GRCh38 remains manual.

No raw genomic data is uploaded to GitHub Actions as part of this optimization.

## 9. Pre-merge validation contract

"Complete validation" means every gate applicable to the final diff plus the repository baseline, not unrelated scientific jobs.

Before manual merge of a code PR:

1. Run the relevant local targeted tests on NOAR.
2. Run repository baseline validation locally where supported.
3. Push only after the local block is green.
4. Require Codacy and CodeRabbit review on the final pushed SHA.
5. Require the baseline GitHub validation applicable to the final SHA.
6. Require every domain workflow selected by the changed paths.
7. If a required Linux/container check cannot be reproduced locally, GitHub Actions remains authoritative for that check.
8. Do not merge if any applicable check is unavailable, stale, or attached to an older SHA.

Documentation-only PRs may skip scientific/runtime workflows, but still require review and any documentation/governance checks that apply.

## 10. Safety constraints

- Do not weaken validators, hashes, locks, evidence integrity, or fail-closed behavior.
- Do not rename status checks in this optimization.
- Do not change canonical GENOMA v3.4 ruleset identity, manifests, sealed transport, or report artifacts.
- Do not modify Codacy trusted-publisher security boundaries already implemented by PR35.
- Do not add third-party path-filter actions when native workflow filters are sufficient.
- Do not alter production witness, production ceremony, or reference foundry triggers without a separate review.
- Do not add auto-merge.

## 11. Testing strategy

Before editing workflows, add or extend structural tests that parse workflow YAML/text and assert:

- policy engine has matching PR and main path scopes;
- Fallow has its intended narrow PR scope;
- audit/scaffold ignore documentation-only changes without excluding active code by default;
- PR validation workflows have the approved concurrency expression;
- `cancel-in-progress` is true only for pull-request runs;
- production/manual workflows retain their existing trigger semantics;
- workflow names and protected job names remain unchanged.

Then run the existing workflow-security tests, repository validator, unit suite, supply-chain verification, shell syntax checks, and `git diff --check` locally.

## 12. Rollout

Implement this as one dedicated CI optimization PR, separate from the English-codebase refactor.

Order:

1. Add structural regression tests for trigger and concurrency contracts.
2. Add concurrency to non-production PR validation workflows.
3. Add Fallow PR path filtering.
4. Mirror policy-engine `push.paths` to `pull_request.paths`.
5. Add narrow documentation-only `paths-ignore` to audit and scaffold validation.
6. Run the full local validation set.
9. Review the final diff for accidental workflow/check-name drift.
10. Push one validated block and open a PR.
11. Let CodeRabbit, Codacy, and applicable GitHub Actions review the final SHA.
12. Merge only after explicit human approval.

## 13. Expected effect

This design reduces Actions usage through two independent mechanisms:

- fewer pushes because development/testing happens locally;
- fewer or shorter CI runs because unrelated specialized workflows no longer start, and obsolete PR runs are cancelled.

It does not promise a fixed percentage reduction before observing real post-merge workflow usage. After merge, compare workflow-run counts and minutes against the previous development pattern.

## 14. Non-goals

This PR does not refactor application code, translate the codebase, change scientific algorithms, change report content, alter production deployment, or modify the canonical ruleset.

## 15. Approved safety amendment — required-check preservation

The user approved this amendment on 2026-09-03 after review of the versioned governance contract and current GitHub behavior.

For workflows that provide status-check names which may be required by repository governance, do not use `pull_request.paths` or `pull_request.paths-ignore` to suppress the whole workflow. GitHub documents that workflow-level path filtering leaves required checks pending, while a job skipped by a job-level `if` condition reports success.

Therefore:

- `genoma-policy-engine.yml` remains unfiltered at `pull_request` workflow level.
- Add a lightweight PR change-classifier job to `genoma-policy-engine.yml`.
- On unrelated PRs, skip the policy, Rego, and policy-container jobs at job level while preserving their names.
- Keep `Gitleaks secret scan` active on every PR so secret scanning is not weakened.
- Preserve the existing policy-engine `push.paths` filter for `main` pushes.
- `scaffold-validation.yml` remains unfiltered at `pull_request` workflow level.
- Add a lightweight Markdown-only classifier to `scaffold-validation.yml`.
- On Markdown-only PRs, skip `static` and `container-canary` at job level while preserving their check names.
- On non-documentation PRs, run `static` and `container-canary` unchanged.
- For non-required workflows such as Fallow and the four-plane audit, workflow-level `paths` / `paths-ignore` remain allowed.
- The Windows UTF-8 portability defect discovered in `scripts/validate_repo.py` is part of this implementation because local-first validation on NOAR depends on the repository validator reading JSON deterministically as UTF-8.
