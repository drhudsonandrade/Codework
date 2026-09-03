# Local-First Development and Targeted CI Architecture

**Date:** 2026-09-03
**Status:** Implementation tracked in PR #36; final human merge approval pending
**Repository:** `drhudsonandrade/Codework`
**Branch:** `ci/local-first-actions-optimization-impl`
**Governance verification:** before merge, re-read `.github/governance/main-ruleset.json` and query `GET /repos/drhudsonandrade/Codework/rulesets` plus every active ruleset returned by that endpoint. Treat the live GitHub response as authoritative for currently enforced checks and the tracked file as desired-state documentation; record any divergence in the PR before merge.

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

Governance is intentionally checked from two sources: the live GitHub ruleset API for enforcement and `.github/governance/main-ruleset.json` for tracked desired state. Because those sources may diverge over time, check names and fail-closed behavior must remain stable and the verification procedure above must be repeated before merge.

## 6. Trigger optimization

### Fallow

Use explicit PR path filters for TypeScript/JavaScript sources plus the MCP package/configuration files, Fallow configuration, relevant JavaScript regression tests, and the Fallow workflow itself. Do not use the broad `mcp/**` pattern, and do not run Fallow for unrelated Python/reporting/docs-only changes.

### Policy engine

Keep `pull_request` unfiltered at workflow level so potentially required status checks remain present. The workflow performs checked rename-aware `git diff --no-renames` execution and passes NUL-delimited path files to the process-free `scripts/ci_change_classifier.py`. If the classifier or policy workflow changes, policy, Rego, and policy-container validation is forced before any classifier result can suppress those jobs. `Gitleaks secret scan` remains unconditional. Preserve the targeted `push.paths`, including direct classifier/ruleset dependencies and `.github/governance/**`.

### Four-plane audit

Keep the workflow trigger broad. Pull requests generate checked rename-aware path lists inline before the trust guard; `main` pushes use the shared `scripts/ci_changed_paths.sh` helper, whose null/non-null behavior is exercised by `tests/test_ci_changed_paths.sh`. Only additions/modifications consisting exclusively of Markdown may skip the heavy audit. Any deletion, rename involving a non-Markdown source, non-Markdown change, or classifier failure runs the audit.

### Scaffold validation

Keep both `pull_request` and `push` to `main` unfiltered at workflow level and preserve the existing `static` and `container-canary` job names. Pull requests compute checked path lists inline and force validation when the classifier, helper, or controlling workflow changes. Main pushes use `scripts/ci_changed_paths.sh`; its regression test covers both normal and null-base pushes. Heavy jobs may be skipped only for additions/modifications consisting exclusively of Markdown; deletions, renames from non-Markdown paths, non-Markdown changes, and classifier failures require validation.

The Docker canary remains the independent runtime check for code changes in this optimization. Linux/container execution remains authoritative on GitHub when Docker is unavailable on the NOAR host.

### Existing targeted workflows

Preserve the current path scopes of NGS, SNP-array, visual QA, and PR30 regression gates unless a separate test demonstrates a scope defect. Their first optimization is cancellation of superseded PR executions, not narrowing scientific coverage.

## 7. Concurrency policy

Add PR-safe concurrency to validation workflows that do not already have it:

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
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

- policy-engine workflow-level PR trigger remains unfiltered while its shared classifier identifies policy-relevant paths and direct verification dependencies;
- Fallow has its intended explicit TypeScript/JavaScript/configuration PR scope and rejects broad `mcp/**` coverage;
- audit/scaffold skip only safe Markdown additions/modifications and run for deletions, rename source paths, non-Markdown changes, or classifier failures;
- PR validation workflows share a PR-number concurrency group, while non-PR runs use unique `github.run_id` groups;
- `cancel-in-progress` is true only for pull-request runs;
- production/manual workflows retain their existing trigger semantics;
- workflow names and protected job names remain unchanged.

Then run the existing workflow-security tests, repository validator, unit suite, supply-chain verification, shell syntax checks, and `git diff --check` locally.

## 12. Rollout

Implement this as one dedicated CI optimization PR, separate from the English-codebase refactor.

Order:

1. Add structural and behavioral regression tests for trigger, classifier, rename/deletion, and concurrency contracts.
2. Add PR-safe concurrency with unique non-PR run groups.
3. Add explicit Fallow TypeScript/JavaScript/configuration path filtering.
4. Add the shared fail-closed change classifier and keep policy/scaffold PR workflows unfiltered.
5. Make the four-plane audit use the same deletion/rename-aware Markdown classifier instead of workflow-level `paths-ignore`.
6. Run the applicable local validation set and compare unavoidable Windows-only failures with `main` under the same environment.
7. Review the final diff for accidental workflow/check-name drift.
8. Push one locally validated block to the PR.
9. Let CodeRabbit, Codacy, and applicable GitHub Actions review the final SHA; batch any review fixes locally before another push.
10. Merge only after the final SHA is reviewed and explicit human approval is given.

## 13. Expected effect

This design reduces Actions usage through two independent mechanisms:

- fewer pushes because development/testing happens locally;
- fewer or shorter CI runs because unrelated specialized workflows no longer start, and obsolete PR runs are cancelled.

It does not promise a fixed percentage reduction before observing real post-merge workflow usage. After merge, compare workflow-run counts and minutes against the previous development pattern.

## 14. Non-goals

This PR does not refactor application code, translate the codebase, change scientific algorithms, change report content, alter production deployment, or modify the canonical ruleset.

## 15. Safety amendment — required-check preservation

This amendment is implemented in PR #36; final merge approval remains a separate human gate. Its technical basis is reproducible from the governance verification procedure above and the workflow regression tests in this branch.

For workflows that provide status-check names which may be required by repository governance, do not use `pull_request.paths` or `pull_request.paths-ignore` to suppress the whole workflow. GitHub documents that workflow-level path filtering leaves required checks pending, while a job skipped by a job-level `if` condition reports success.

Therefore:

- `genoma-policy-engine.yml` remains unfiltered at `pull_request` workflow level.
- Add a lightweight PR change-classifier job to `genoma-policy-engine.yml`; the workflow owns checked rename-aware Git diff generation, forces policy validation if the classifier/workflow changes, and passes NUL-delimited paths to a process-free `scripts/ci_change_classifier.py`, which treats `.github/governance/**` as policy-relevant.
- On unrelated PRs, skip the policy, Rego, and policy-container jobs at job level while preserving their names; classifier errors run those jobs and fail closed.
- Keep `Gitleaks secret scan` active on every PR so secret scanning is not weakened.
- Preserve the targeted policy-engine `push.paths` filter for `main` pushes and include direct ruleset/classifier dependencies.
- `scaffold-validation.yml` remains unfiltered at both `pull_request` and `push`-to-`main` workflow level.
- Use the shared deletion/rename-aware Markdown classifier for `scaffold-validation.yml`.
- Only safe Markdown additions/modifications may skip `static` and `container-canary`; deletions, non-Markdown rename sources, other non-Markdown changes, and classifier failures require those jobs.
- Fallow may use workflow-level explicit path filters because it does not provide the protected baseline check names.
- The four-plane audit uses a lightweight job-level classifier rather than `paths-ignore`, preventing Markdown deletions or rename destinations from bypassing validation.
- The Windows UTF-8 portability defect discovered in `scripts/validate_repo.py` is part of this implementation because local-first validation on NOAR depends on the repository validator reading JSON deterministically as UTF-8.
