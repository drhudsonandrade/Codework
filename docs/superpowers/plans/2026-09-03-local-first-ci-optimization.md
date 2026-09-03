# Local-First CI Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce repeated GitHub Actions execution while preserving protected check names, security gates, scientific gates, and manual merge.

**Architecture:** Development and repeated validation run locally on NOAR. Non-required workflows use path filters; workflows that may provide required check names remain PR-triggered and skip irrelevant heavy jobs with job-level conditions. Gitleaks remains unconditional on pull requests.

**Tech Stack:** GitHub Actions YAML, Python 3 standard library, unittest, Git/GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md`

## Global Constraints

- Do not use Codex or subagents for this execution.
- Never change `main` directly and never auto-merge.
- Preserve existing workflow names and protected job/check names.
- Do not weaken hashes, locks, validators, evidence integrity, Gitleaks, or scientific fail-closed behavior.
- Do not change canonical ruleset identity, sealed transport, report artifacts, production witness, production ceremony, or reference foundry triggers.
- Use job-level skip conditions, not PR workflow path filters, for workflows that may provide required checks.
- Run all repeated tests locally and push only after the final local validation block is green.

---

### Task 1: Make repository JSON validation deterministic on Windows

**Files:**
- Modify: `tests/test_repo_contract.py`
- Modify: `scripts/validate_repo.py`

**Interfaces:**
- Consumes: `validate(root: Path) -> list[str]`
- Produces: every `.json` file scan is decoded explicitly as UTF-8.
- [ ] **Step 1: Add a failing portability regression**

In `tests/test_repo_contract.py`, import `patch` from `unittest.mock` and add a test that creates a UTF-8 JSON file, patches `Path.read_text` so an omitted encoding raises `UnicodeDecodeError` for that file, runs `validate()`, and asserts no `invalid JSON` diagnostic is produced.

- [ ] **Step 2: Run the regression and verify RED**

Run: `python -m unittest tests.test_repo_contract.RepoContractTest.test_json_scan_reads_utf8_explicitly -v`

Expected: FAIL because the JSON scan currently calls `path.read_text()` without an encoding and records an `invalid JSON` error.

- [ ] **Step 3: Apply the minimal fix**

Change the JSON scan in `scripts/validate_repo.py` from:

```python
json.loads(path.read_text())
```

to:

```python
json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 4: Verify GREEN and the real NOAR validator**

Run:

```text
python -m unittest tests.test_repo_contract -v
python scripts/validate_repo.py
```

Expected: the new regression passes and the prior Windows `charmap` JSON failures disappear.

- [ ] **Step 5: Commit Task 1**

Commit message: `fix: make repository JSON validation UTF-8 deterministic`

### Task 2: Add structural tests for targeted CI semantics

**Files:**
- Create: `tests/test_ci_optimization_contract.py`

**Interfaces:**
- Consumes: workflow text under `.github/workflows/`
- Produces: regression coverage for triggers, concurrency, job-level classifiers, and preserved check names.
- [ ] **Step 1: Write failing CI contract tests**

Create tests that assert all of the following:

```text
Concurrency expression:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

Apply that contract to `fallow.yml`, `genoma-audit.yml`, `genoma-ngs-runtime-gate.yml`, `genoma-policy-engine.yml`, `genoma-snp-array.yml`, `genoma-visual-qa-candidates.yml`, `pr30-regressions.yml`, and `scaffold-validation.yml`.

Also assert:

- Fallow PR paths enumerate TypeScript/JavaScript sources plus the exact MCP package/configuration files, relevant JavaScript tests, `.fallowrc.json`, and its own workflow; broad `mcp/**` is rejected.
- Four-plane audit remains broadly triggered and uses the shared deletion/rename-aware classifier to skip only safe Markdown additions/modifications.
- Policy workflow has no PR-level path filter, has a fail-closed `changes` job, keeps `Gitleaks secret scan` unconditional, and gates `policy`, `rego`, and `container` on either classifier failure or `policy_relevant`.
- Scaffold workflow has no PR-level path filter, has a fail-closed `changes` job, and gates `static` and `container-canary` on either classifier failure or `validation_required`.
- Existing protected job identifiers/names remain present.

- [ ] **Step 2: Run the new test and verify RED**

Run: `python -m unittest tests.test_ci_optimization_contract -v`

Expected: FAIL on missing concurrency, filters, and classifier jobs.

### Task 3: Optimize non-required workflow triggers and cancellation

**Files:**
- Modify: `.github/workflows/fallow.yml`
- Modify: `.github/workflows/genoma-audit.yml`
- Modify: `.github/workflows/genoma-ngs-runtime-gate.yml`
- Modify: `.github/workflows/genoma-snp-array.yml`
- Modify: `.github/workflows/genoma-visual-qa-candidates.yml`
- Modify: `.github/workflows/pr30-regressions.yml`

**Interfaces:**
- Produces: narrower non-required PR execution and cancellation of superseded PR runs without changing manual/main semantics.

- [ ] **Step 1: Add the approved concurrency map**

Add the exact top-level concurrency expression from Task 2 to each listed validation workflow.

- [ ] **Step 2: Narrow Fallow to JS/TS-related PR surfaces**

Set `pull_request.paths` to the approved JS/TS/MCP/Fallow files only. Keep `workflow_dispatch`.

- [ ] **Step 3: Skip four-plane audit only for proven-safe Markdown modifications**

Keep `pull_request` and `push` triggers broad. Add a lightweight fail-closed `changes` job that uses rename-aware changed/deleted path lists and the shared `scripts/ci_change_classifier.py`; gate the heavy `audit` job only when classification proves that the change consists exclusively of Markdown additions/modifications.

- [ ] **Step 4: Run CI contract tests**

Run: `python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts -v`

Expected: only policy/scaffold classifier assertions may still fail.

- [ ] **Step 5: Commit Task 3**

Commit message: `ci: cancel superseded runs and target non-required checks`

### Task 4: Preserve required checks while skipping irrelevant heavy jobs

**Files:**
- Modify: `.github/workflows/genoma-policy-engine.yml`
- Modify: `.github/workflows/scaffold-validation.yml`

**Interfaces:**
- Produces: job-level relevance outputs `policy_relevant` and `validation_required`.
- Preserves: `Canonical policy + 263-rule contract`, `OPA/Rego parity`, `Gitleaks secret scan`, `Real Docker + canonical read-only mount`, `static`, and `container-canary` check names.

- [ ] **Step 1: Add the shared fail-closed classifier and policy classifier job**

Create `scripts/ci_change_classifier.py` using only the standard library. It owns the checked `git diff --no-renames` execution and accepts exact `--base`/`--head` SHAs, so invalid refs propagate as non-zero errors. In the policy `changes` job, use `fetch-depth: 0` and pass the PR SHAs to the classifier. Include direct verification dependencies such as `scripts/sealed_ruleset.py`, `.github/governance/**`, and the classifier itself in the policy scope. For push/manual events, set `policy_relevant=true`.

- [ ] **Step 2: Gate policy-heavy jobs fail closed**

Add `needs: changes` and `always()` to `policy`, `rego`, and `container`; execute them when `needs.changes.result != 'success'` or when `policy_relevant == 'true'`. Make the first step fail explicitly when classification did not complete successfully. Do not apply this relevance gate to `secrets`.

- [ ] **Step 3: Add the scaffold classifier job**

For pull requests, pass exact base/head SHAs to `ci_change_classifier.py markdown`; the classifier itself executes checked rename-aware changed/deleted diffs. Set `validation_required=false` only for Markdown additions/modifications with no deletions. For push/manual events, set it to `true`. Preserve the PR trigger without workflow-level path filters.

- [ ] **Step 4: Gate scaffold heavy jobs fail closed**

Add `needs: changes` and `always()` to `static` and `container-canary`; execute them when classification failed/cancelled or `validation_required == 'true'`. Make the first step fail explicitly if classification failed. Keep `publish-ghcr` dependent on both existing jobs.

- [ ] **Step 5: Verify required-check semantics structurally**

Run: `python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts tests.test_codacy_workflow_security -v`

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

Commit message: `ci: preserve required checks with job-level scope gates`

### Task 5: Full local validation and controlled handoff

**Files:**
- Modify: `docs/superpowers/checkpoints/2026-09-03-local-first-ci-session.md`

- [ ] **Step 1: Run repository validation**

Run:

```text
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python -m unittest discover -s tests -v
```

- [ ] **Step 2: Run shell and diff checks**

Run:

```text
bash -n scripts/*.sh tests/test_wgs_align_or_stage.sh
git diff --check origin/main...HEAD
```

If Bash is unavailable in the Windows shell, use Git for Windows Bash explicitly and record that fact.

- [ ] **Step 3: Review workflow/check-name drift**

Verify that production witness, production ceremony, reference foundry, canonical ruleset identity, protected job names, and CodeRabbit/Codacy boundaries are unchanged.

- [ ] **Step 4: Update checkpoint and commit**

Record executed commands and their actual outcomes. Never record a PASS for a command not executed.

Commit message: `docs: checkpoint local-first CI optimization validation`

- [ ] **Step 5: Push one validated implementation branch**

Push `ci/local-first-actions-optimization-impl` only after the working tree is clean and every applicable local gate above is green. Then open one PR for CodeRabbit, Codacy, and applicable GitHub Actions. Do not merge automatically.
