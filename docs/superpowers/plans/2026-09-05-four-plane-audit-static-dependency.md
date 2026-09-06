# Four-Plane Audit Static Dependency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make four-plane audit evidence depend on successful `static` validation for the same SHA while removing duplicated CI work from the audit runner.

**Architecture:** `scaffold-validation.yml` remains the PR/push/manual orchestration boundary. Its existing `changes` classifier gates `static`; a new reusable-workflow caller then invokes `genoma-audit.yml` only when classification succeeded, validation is required, and `static.result == 'success'`. `genoma-audit.yml` becomes `workflow_call`-only and retains only audit-specific evidence work.

**Tech Stack:** GitHub Actions YAML, Python 3.12, `unittest`, existing workflow-test utilities, PowerShell/Git/gh CLI on NOAR.

**Spec:** `docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md`

## Global Constraints

- Preserve the required check context `static` exactly; do not rename or weaken it.
- Keep all 14 protected-main required checks unchanged.
- `GENOMA protected main` must remain strict with no bypass.
- Do not change `container-canary`, policy checks, Production Witness, scientific runtime code, normative artifacts, or merge policy.
- `genoma-audit.yml` must have no direct `pull_request`, `push`, or standalone `workflow_dispatch` path after implementation.
- A normal audit artifact may exist only after `static` succeeds for the same SHA.
- Preserve `genoma_audit.py`, template evidence, SHA-bound artifact naming, 365-day retention, and fail-closed behavior.
- Keep Draft-first behavior and human-only merge.

---
## File Structure

- Modify `.github/workflows/scaffold-validation.yml`: remain the direct event workflow; add the reusable audit caller after `static`.
- Modify `.github/workflows/genoma-audit.yml`: convert to reusable-only audit core and remove duplicated pre-audit work.
- Modify `tests/test_ci_optimization_contract.py`: encode orchestration, trigger, draft-first, mutation, and duplicate-work contracts.
- Modify `tests/test_workflow_contracts.py`: preserve full-history/provenance guarantees after direct `validate_repo.py` is removed from the audit workflow.
- Modify `docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md`: update implementation stage only; do not alter approved semantics.
- Modify this plan only for checkbox/status bookkeeping if execution tracking is desired.

### Task 1: Establish the reusable audit orchestration boundary

**Files:**
- Modify: `.github/workflows/scaffold-validation.yml`
- Modify: `.github/workflows/genoma-audit.yml`
- Modify: `tests/test_ci_optimization_contract.py`

**Interfaces:**
- Consumes: existing `changes.outputs.validation_required` and job result `static.result` from `scaffold-validation.yml`.
- Produces: caller job `four-plane-audit` using `./.github/workflows/genoma-audit.yml`; reusable workflow entrypoint `workflow_call`.

- [ ] **Step 1: Replace the old audit-trigger contract with a failing reusable-boundary contract**
Add this replacement test in `CIOptimizationContractTest` and remove `genoma-audit.yml` from `CONCURRENCY_WORKFLOWS` because a reusable workflow no longer owns an independent PR/push run:

```python
def test_four_plane_audit_is_reusable_and_gated_by_required_static(self):
    scaffold = _read("scaffold-validation.yml")
    audit = _read("genoma-audit.yml")
    audit_header = audit.split("permissions:", 1)[0]
    self.assertIn("on:\n  workflow_call:\n", audit_header)
    for forbidden in ("pull_request:", "push:", "workflow_dispatch:"):
        self.assertNotIn(forbidden, audit_header)

    caller = _job_block(scaffold, "four-plane-audit")
    self.assertIn("needs: [changes, static]", caller)
    self.assertIn("uses: ./.github/workflows/genoma-audit.yml", caller)
    for required in (
        "always() &&",
        DRAFT_GATE,
        "needs.changes.result == 'success'",
        "needs.changes.outputs.validation_required == 'true'",
        "needs.static.result == 'success'",
    ):
        self.assertIn(required, caller)
```
- [ ] **Step 2: Run the focused contract and verify RED**

Run:

```powershell
python -m unittest tests.test_ci_optimization_contract.CIOptimizationContractTest.test_four_plane_audit_is_reusable_and_gated_by_required_static -v
```

Expected: FAIL because `genoma-audit.yml` still has direct PR/push/manual triggers and `scaffold-validation.yml` has no `four-plane-audit` caller.

- [ ] **Step 3: Convert the audit workflow to reusable-only without removing duplicate steps yet**

Replace the audit event header with:

```yaml
name: GENOMA v0.8 four-plane audit

on:
  workflow_call:

permissions:
  contents: read
```

Remove the audit workflow's `concurrency:` block and its `changes` job. Keep the existing `audit` job body intact for this task so the structural change is isolated from deduplication.
Add this caller job to `scaffold-validation.yml` after `static` and before `container-canary`:

```yaml
  four-plane-audit:
    name: Four-plane audit
    needs: [changes, static]
    if: >-
      always() &&
      (github.event_name != 'pull_request' || github.event.pull_request.draft == false) &&
      needs.changes.result == 'success' &&
      needs.changes.outputs.validation_required == 'true' &&
      needs.static.result == 'success'
    uses: ./.github/workflows/genoma-audit.yml
```

Do not add `secrets: inherit`, `runs-on`, or a second classifier to this caller job.

- [ ] **Step 4: Run the focused orchestration and draft contracts**

Run:

```powershell
python -m unittest `
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_four_plane_audit_is_reusable_and_gated_by_required_static `
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_draft_pr_validation_defers_runner_jobs_until_ready -v
```

Expected: PASS. Draft-first still applies to direct runner workflows; the reusable audit no longer appears in `CONCURRENCY_WORKFLOWS`.
- [ ] **Step 5: Commit the orchestration boundary**

```powershell
git add .github/workflows/scaffold-validation.yml .github/workflows/genoma-audit.yml tests/test_ci_optimization_contract.py
git diff --cached --check
git commit -m "ci: gate four-plane audit on static"
```

### Task 2: Remove duplicated audit work while preserving evidence/provenance

**Files:**
- Modify: `.github/workflows/genoma-audit.yml`
- Modify: `tests/test_ci_optimization_contract.py`
- Modify: `tests/test_workflow_contracts.py`

**Interfaces:**
- Consumes: successful `static` prerequisite from Task 1.
- Produces: the same `audit.json` and `template-store-verification.json` artifact package, but without repeating standalone contracts or architecture test modules.

- [ ] **Step 1: Add a failing contract for the reusable audit core**

Add this test to `CIOptimizationContractTest`:

```python
def test_reusable_four_plane_audit_keeps_only_unique_evidence_work(self):
    audit = _read("genoma-audit.yml")
    job = _job_block(audit, "audit")
    self.assertNotIn("Repository and supply-chain contracts", job)
    self.assertNotIn("Unit tests for v0.8 architecture", job)
    self.assertNotIn("python3 -m unittest", job)
```
Extend that test with the audit-specific invariants:

```python
    self.assertIn("python3 scripts/genoma_audit.py --allow-template-sealed-only --output audit.json", job)
    self.assertIn("python3 scripts/verify_template_store.py --allow-sealed-only", job)
    self.assertIn("name: genoma-v0.8-audit-${{ github.sha }}", job)
    self.assertIn("retention-days: 365", job)
    self.assertIn("if: always()", job)
```

- [ ] **Step 2: Run the new contract and verify RED**

Run:

```powershell
python -m unittest tests.test_ci_optimization_contract.CIOptimizationContractTest.test_reusable_four_plane_audit_keeps_only_unique_evidence_work -v
```

Expected: FAIL because both duplicated steps still exist in the reusable audit job.

- [ ] **Step 3: Remove only the two duplicated workflow steps**

Delete these step blocks from `.github/workflows/genoma-audit.yml`:

```yaml
      - name: Repository and supply-chain contracts
        run: |
          python3 scripts/validate_repo.py
          python3 scripts/verify_supply_chain_lock.py
```
and:

```yaml
      - name: Unit tests for v0.8 architecture
        run: |
          python3 -m unittest \
            tests.test_snp_array_qc \
            tests.test_array_scientific_data_plane \
            tests.test_partial_genome_annotation \
            tests.test_grch38_compute_strategy \
            tests.test_supply_chain_lock \
            tests.test_template_store \
            tests.test_genoma_audit -v
```

Keep checkout with `fetch-depth: 0`, Python 3.12 setup, `genoma_audit.py`, explicit template verification, and artifact upload unchanged.

- [ ] **Step 4: Replace the generic direct-validate_repo history assertion for the reusable audit**

In `tests/test_workflow_contracts.py`, remove this entry from the generic `targets` map inside `test_validate_repo_jobs_fetch_full_history_for_baseline_provenance`:

```python
"genoma-audit.yml": ("audit",),
```
Add this dedicated replacement test so provenance is not weakened:

```python
def test_reusable_four_plane_audit_fetches_full_history_before_core(self):
    workflow = (ROOT / ".github/workflows/genoma-audit.yml").read_text(encoding="utf-8")
    steps = _job_steps(workflow, "audit")
    checkout_indexes = [i for i, step in enumerate(steps) if "uses: actions/checkout@" in step]
    core_indexes = [
        i for i, step in enumerate(steps)
        if "python3 scripts/genoma_audit.py --allow-template-sealed-only --output audit.json"
        in _step_run_commands(step)
    ]
    self.assertEqual(len(checkout_indexes), 1)
    self.assertEqual(len(core_indexes), 1)
    self.assertLess(checkout_indexes[0], core_indexes[0])
    checkout_config = _with_mapping(steps[checkout_indexes[0]])
    self.assertEqual(checkout_config.get("fetch-depth"), 0)
```

- [ ] **Step 5: Run the audit-core and provenance contracts**

Run:

```powershell
python -m unittest `
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_reusable_four_plane_audit_keeps_only_unique_evidence_work `
  tests.test_workflow_contracts.WorkflowContractTest.test_reusable_four_plane_audit_fetches_full_history_before_core `
  tests.test_workflow_contracts.WorkflowContractTest.test_validate_repo_jobs_fetch_full_history_for_baseline_provenance -v
```

Expected: PASS.
- [ ] **Step 6: Commit the deduplication**

```powershell
git add .github/workflows/genoma-audit.yml tests/test_ci_optimization_contract.py tests/test_workflow_contracts.py
git diff --cached --check
git commit -m "ci: remove duplicate four-plane audit validation"
```

### Task 3: Add mutation guards for fail-closed orchestration

**Files:**
- Modify: `tests/test_ci_optimization_contract.py`

**Interfaces:**
- Consumes: the caller contract from Task 1.
- Produces: executable mutation tests that reject removal or weakening of the `static` dependency, classifier boundary, or reusable-only trigger model.

- [ ] **Step 1: Extract a reusable contract-error helper**

Add a helper above the test class:

```python
def _four_plane_audit_orchestration_errors(scaffold: str, audit: str) -> list[str]:
    errors: list[str] = []
    caller = _job_block(scaffold, "four-plane-audit")
    required = (
        "needs: [changes, static]",
        "uses: ./.github/workflows/genoma-audit.yml",
        DRAFT_GATE,
        "needs.changes.result == 'success'",
        "needs.changes.outputs.validation_required == 'true'",
        "needs.static.result == 'success'",
    )
    for token in required:
        if token not in caller:
            errors.append(f"four-plane-audit caller missing: {token}")
```
Continue the helper with reusable-only trigger checks:

```python
    header = audit.split("permissions:", 1)[0]
    if "on:\n  workflow_call:\n" not in header:
        errors.append("genoma-audit must expose workflow_call")
    for forbidden in ("pull_request:", "push:", "workflow_dispatch:"):
        if forbidden in header:
            errors.append(f"genoma-audit direct trigger forbidden: {forbidden}")
    if "concurrency:" in audit:
        errors.append("reusable genoma-audit must not own concurrency")
    return errors
```

Change `test_four_plane_audit_is_reusable_and_gated_by_required_static` so its first assertion is:

```python
self.assertEqual([], _four_plane_audit_orchestration_errors(scaffold, audit))
```

Keep the positive artifact/evidence assertions from Task 2 separate.

- [ ] **Step 2: Add mutations that must fail the contract**

```python
def test_four_plane_audit_orchestration_rejects_weakened_static_boundary(self):
    scaffold = _read("scaffold-validation.yml")
    audit = _read("genoma-audit.yml")
    mutations = (
        scaffold.replace("needs: [changes, static]", "needs: changes", 1),
        scaffold.replace(DRAFT_GATE, "true", 1),
        scaffold.replace("needs.static.result == 'success'", "needs.static.result != 'failure'", 1),
        scaffold.replace("needs.changes.result == 'success'", "needs.changes.result != 'failure'", 1),
    )
    for mutated in mutations:
        self.assertTrue(_four_plane_audit_orchestration_errors(mutated, audit))
```
Add a direct-trigger mutation as well:

```python
    direct_trigger = audit.replace(
        "on:\n  workflow_call:\n",
        "on:\n  workflow_call:\n  pull_request:\n",
        1,
    )
    self.assertTrue(_four_plane_audit_orchestration_errors(scaffold, direct_trigger))
```

- [ ] **Step 3: Run the mutation contract**

Run:

```powershell
python -m unittest `
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_four_plane_audit_is_reusable_and_gated_by_required_static `
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_four_plane_audit_orchestration_rejects_weakened_static_boundary -v
```

Expected: PASS; each mutant is rejected by the executable contract.

- [ ] **Step 4: Commit the fail-closed hardening**

```powershell
git add tests/test_ci_optimization_contract.py
git diff --cached --check
git commit -m "test: harden four-plane audit orchestration"
```

### Task 4: Exact-tree validation, Draft PR, and final CI evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md` only for status text after implementation.
- No additional production files unless a valid reviewer finding requires a TDD fix.
**Interfaces:**
- Consumes: Tasks 1-3 exact HEAD.
- Produces: one Draft PR with exact-head local evidence, then one Ready-for-Review Actions pass and a human merge handoff.

- [ ] **Step 1: Update the spec implementation stage**

Change only the status line to:

```markdown
**Status:** Written spec approved; implementation complete; pending validation/review
```

Then commit that status update separately:

```powershell
git add docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md
git diff --cached --check
git commit -m "docs: mark four-plane audit implementation complete"
```

- [ ] **Step 2: Run the exact-tree local validation suite**

```powershell
python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts -v
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python scripts/code_language_guard.py --check
& 'C:\Program Files\Git\bin\bash.exe' -lc "bash -n scripts/*.sh tests/test_wgs_align_or_stage.sh tests/test_ci_changed_paths.sh"
git diff --check
git status --short
```

Expected: both unittest modules PASS, all three validators PASS, shell syntax PASS, `git diff --check` clean, and no uncommitted files.
- [ ] **Step 3: Verify scope before pushing**

Run:

```powershell
git diff origin/main...HEAD --stat
git diff origin/main...HEAD -- .github/workflows/scaffold-validation.yml .github/workflows/genoma-audit.yml tests/test_ci_optimization_contract.py tests/test_workflow_contracts.py docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md docs/superpowers/plans/2026-09-05-four-plane-audit-static-dependency.md
```

Expected changed files are limited to the two workflows, the two workflow-contract test files, the approved spec, and this plan. No application/scientific/policy/runtime file belongs in the diff.

- [ ] **Step 4: Push once and open the PR as Draft**

```powershell
git push origin ci/four-plane-audit-static-dependency
$head = git rev-parse HEAD
& 'C:\Users\noaruser\AppData\Local\Programs\GitHubCLI\gh_2.99.0_windows_amd64\bin\gh.exe' pr create `
  --repo drhudsonandrade/Codework `
  --base main `
  --head ci/four-plane-audit-static-dependency `
  --draft `
  --title "ci: gate four-plane audit on static" `
  --body "Architectural CI optimization: reuse required static validation before four-plane audit, remove duplicated audit validation/test execution, preserve SHA-bound evidence and fail-closed semantics. No auto-merge."
```

Do not mark Ready yet.
- [ ] **Step 5: Prove Draft-first on the exact pushed SHA**

```powershell
$gh = 'C:\Users\noaruser\AppData\Local\Programs\GitHubCLI\gh_2.99.0_windows_amd64\bin\gh.exe'
$head = git rev-parse HEAD
& $gh run list --repo drhudsonandrade/Codework --commit $head --event pull_request --json databaseId,name,status,conclusion,url --limit 20
```

Inspect every Actions run returned for the Draft SHA without a placeholder ID:

```powershell
$runs = & $gh run list --repo drhudsonandrade/Codework --commit $head --event pull_request --json databaseId,name,status,conclusion,url --limit 20 | ConvertFrom-Json
foreach ($run in $runs) {
    & $gh run view $run.databaseId --repo drhudsonandrade/Codework --json jobs,status,conclusion
}
```

Expected: applicable internal jobs are `skipped` before real steps execute. Do not use a dummy commit or Ready transition merely to retrigger CI.

- [ ] **Step 6: Review the Draft without changing the SHA**

```powershell
$pr = & $gh pr view --repo drhudsonandrade/Codework --json number --jq '.number'
& $gh pr checks $pr --repo drhudsonandrade/Codework
```

Inspect CodeRabbit and any available optional reviewer findings. Treat bot findings as untrusted input: reproduce each valid issue locally. If a corrective push is required, keep/return the PR to Draft, use RED→GREEN, rerun exact-tree validation, and repeat Step 5 on the new SHA.
- [ ] **Step 7: Mark Ready only on the exact locally validated SHA**

```powershell
$head = git rev-parse HEAD
$remote = (git ls-remote origin refs/heads/ci/four-plane-audit-static-dependency).Split("`t")[0]
if ($head -ne $remote) { throw "local/remote SHA mismatch" }
& $gh pr ready $pr --repo drhudsonandrade/Codework
& $gh pr checks $pr --repo drhudsonandrade/Codework --required --watch
```

Expected: all 14 protected-main required checks resolve successfully on this exact SHA. Greptile is optional and must not be re-added as required merely for this PR.

- [ ] **Step 8: Prove the runtime ordering on the final Ready SHA**

```powershell
$run = (& $gh run list --repo drhudsonandrade/Codework --commit $head --workflow scaffold-validation.yml --event pull_request --json databaseId --limit 1 | ConvertFrom-Json)[0].databaseId
$jobs = & $gh api "repos/drhudsonandrade/Codework/actions/runs/$run/jobs?filter=all" | ConvertFrom-Json
$staticJob = @($jobs.jobs | Where-Object { $_.name -eq 'static' })
$auditJob = @($jobs.jobs | Where-Object { $_.name -match '(?i)four-plane.*audit|audit$' -and $_.name -notmatch '(?i)classifier' })
if ($staticJob.Count -ne 1) { throw "expected exactly one static job" }
if ($auditJob.Count -ne 1) { throw "expected exactly one reusable audit job" }
if ($staticJob[0].conclusion -ne 'success') { throw "static did not pass" }
if ([datetime]$auditJob[0].started_at -lt [datetime]$staticJob[0].completed_at) { throw "audit started before static completed" }
$staticJob[0], $auditJob[0] | Select-Object name,status,conclusion,started_at,completed_at
```
Prove that the reusable audit has no direct PR/push/manual run on the same SHA:

```powershell
$auditRuns = & $gh run list --repo drhudsonandrade/Codework --commit $head --workflow genoma-audit.yml --json databaseId,event,status,conclusion --limit 20 | ConvertFrom-Json
$forbidden = @($auditRuns | Where-Object { $_.event -in @('pull_request','push','workflow_dispatch') })
if ($forbidden.Count -ne 0) { throw "reusable audit has a forbidden direct event run" }
$auditRuns
```

- [ ] **Step 9: Verify governance and hand off for manual merge**

```powershell
$ruleset = & $gh api repos/drhudsonandrade/Codework/rulesets/21303100 | ConvertFrom-Json
$statusRule = $ruleset.rules | Where-Object { $_.type -eq 'required_status_checks' }
$contexts = @($statusRule.parameters.required_status_checks | ForEach-Object { $_.context })
if ($contexts.Count -ne 14) { throw "protected-main required check count changed" }
if ($contexts -contains 'Greptile Review') { throw "Greptile unexpectedly became required again" }
if ($ruleset.current_user_can_bypass -ne 'never') { throw "protected-main bypass changed" }
& $gh pr view $pr --repo drhudsonandrade/Codework --json headRefOid,isDraft,mergeable,mergeStateStatus,state,url
```

Use the GitHub review-thread API to confirm every inline thread is resolved. Do not enable auto-merge and do not merge from automation. Hand the PR to the user only when the exact HEAD remains `MERGEABLE`/`CLEAN` with all required checks satisfied.
- [ ] **Step 10: After the user performs the manual merge, measure the realized saving**

```powershell
$merged = & $gh pr view $pr --repo drhudsonandrade/Codework --json mergedAt,mergeCommit --jq '{mergedAt:.mergedAt,sha:.mergeCommit.oid}' | ConvertFrom-Json
if (-not $merged.mergedAt) { throw "PR has not been merged by the user" }
git fetch origin main
if ((git rev-parse origin/main) -ne $merged.sha) { throw "origin/main does not match the PR merge SHA" }
$mainRun = (& $gh run list --repo drhudsonandrade/Codework --commit $merged.sha --workflow scaffold-validation.yml --event push --json databaseId --limit 1 | ConvertFrom-Json)[0].databaseId
$mainJobs = & $gh api "repos/drhudsonandrade/Codework/actions/runs/$mainRun/jobs?filter=all" | ConvertFrom-Json
$mainStatic = @($mainJobs.jobs | Where-Object { $_.name -eq 'static' })
$mainAudit = @($mainJobs.jobs | Where-Object { $_.name -match '(?i)four-plane.*audit|audit$' -and $_.name -notmatch '(?i)classifier' })
if ($mainStatic.Count -ne 1 -or $mainAudit.Count -ne 1) { throw "missing post-merge static/audit evidence" }
if ([datetime]$mainAudit[0].started_at -lt [datetime]$mainStatic[0].completed_at) { throw "post-merge audit ordering violated" }
$auditSeconds = ([datetime]$mainAudit[0].completed_at - [datetime]$mainAudit[0].started_at).TotalSeconds
$savedSeconds = 366 - $auditSeconds
[pscustomobject]@{OldAuditSeconds=366; NewAuditSeconds=$auditSeconds; ApproxRunnerSecondsSavedPerAudit=$savedSeconds}
```

Record actual timestamps instead of claiming the forecasted 5m20 saving if the measured result differs.

## Rollback Boundary

If ordering, SHA binding, evidence retention, or reusable-workflow semantics fail, revert this optimization in a new human-reviewed PR: restore the former direct audit triggers/classifier and duplicated pre-audit validation steps, remove the `four-plane-audit` reusable caller, and rerun the normal required checks. Never roll back by disabling `static`, reducing required checks, enabling bypass, or weakening `genoma_audit.py`.
