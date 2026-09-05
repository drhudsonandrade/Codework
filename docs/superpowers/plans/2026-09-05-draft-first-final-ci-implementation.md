# Draft-First Final CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent GitHub-hosted PR validation jobs from allocating runners while a PR is draft, then run the normal exact-head gates when it becomes ready for review.

**Architecture:** Keep existing workflow topology, check names, classifiers, and path filters. Add `ready_for_review` to PR event types and combine a common draft predicate into runner jobs; main pushes and manual production workflows remain unchanged.

**Tech Stack:** GitHub Actions YAML, Python 3.13, `unittest`, PyYAML, GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-09-05-draft-first-final-ci-design.md`

## Global Constraints

- Do not rename required status checks.
- Do not weaken scientific, policy, runtime, evidence, supply-chain, or fail-closed gates.
- Keep protected-main push behavior unchanged.
- Keep auto-merge disabled and final merge human-only.
- Do not use `[skip ci]` as the implementation mechanism.

---

### Task 1: Draft-gate regression contract

**Files:**
- Modify: `tests/test_ci_optimization_contract.py`

**Interfaces:**
- Consumes: existing `_read()` and `_job_block()` workflow test helpers.
- Produces: structural contract for PR event types and the draft runner predicate.

- [ ] **Step 1: Write failing structural tests**

Add a `DRAFT_GATE` constant, a workflow-to-job mapping for runner jobs, and a test that requires `types: [opened, synchronize, reopened, ready_for_review]` plus the draft predicate in each mapped job block.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest tests.test_ci_optimization_contract.CIOptimizationContractTest.test_draft_pr_validation_defers_runner_jobs_until_ready -v
```

Expected: FAIL because the current workflows do not subscribe to `ready_for_review` and do not contain the draft predicate.

- [ ] **Step 3: Commit only after GREEN implementation in Task 2**

The test and workflow changes form one behavior change and should be committed together after the complete red/green cycle.

### Task 2: Gate PR runners while draft

**Files:**
- Modify: `.github/workflows/fallow.yml`
- Modify: `.github/workflows/genoma-audit.yml`
- Modify: `.github/workflows/genoma-ngs-runtime-gate.yml`
- Modify: `.github/workflows/genoma-policy-engine.yml`
- Modify: `.github/workflows/genoma-snp-array.yml`
- Modify: `.github/workflows/genoma-visual-qa-candidates.yml`
- Modify: `.github/workflows/pr30-regressions.yml`
- Modify: `.github/workflows/scaffold-validation.yml`

**Interfaces:**
- Consumes: GitHub `pull_request.draft` and `ready_for_review` event semantics.
- Produces: zero runner allocation from mapped PR jobs while draft, normal execution when ready/non-draft.

- [ ] **Step 1: Add `ready_for_review` to each PR trigger**

Use the exact event list:

```yaml
pull_request:
  types: [opened, synchronize, reopened, ready_for_review]
```

Preserve existing `paths` blocks immediately below `types` where present.

- [ ] **Step 2: Add the draft predicate to every mapped runner job**

Use the exact predicate:

```yaml
${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}
```

For jobs with an existing `if`, combine it with logical `&&` and parentheses. Do not alter the existing predicate's meaning.

- [ ] **Step 3: Verify GREEN**

Run the focused draft-gate test from Task 1, then:

```bash
python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit the behavior change**

```bash
git add .github/workflows tests/test_ci_optimization_contract.py
git commit -m "ci: defer PR runners until review-ready"
```

### Task 3: Document the operator contract

**Files:**
- Modify: `AGENTS.md`
- Create: `docs/superpowers/specs/2026-09-05-draft-first-final-ci-design.md`
- Create: `docs/superpowers/plans/2026-09-05-draft-first-final-ci-implementation.md`

**Interfaces:**
- Consumes: the implemented draft-gate behavior.
- Produces: one explicit local-first operator workflow for humans and coding agents.

- [ ] **Step 1: Update `AGENTS.md`**

Require implementation PRs to remain draft during iterative pushes, require local validation/batching before remote checkpoints, and require marking ready only for exact-head external review and CI. State that review fixes return the PR to draft before another implementation push.

- [ ] **Step 2: Verify documentation matches executable behavior**

Search active guidance for contradictory instructions and confirm no active guidance recommends GitHub Actions as an iterative debugger or `[skip ci]` as the primary mechanism.

- [ ] **Step 3: Commit documentation**

```bash
git add AGENTS.md docs/superpowers/specs/2026-09-05-draft-first-final-ci-design.md docs/superpowers/plans/2026-09-05-draft-first-final-ci-implementation.md
git commit -m "docs: define draft-first final CI workflow"
```

### Task 4: Full validation and live proof

**Files:** No production file changes expected.

- [ ] **Step 1: Run local validation**

```bash
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts tests.test_repo_contract -v
git diff --check origin/main...HEAD
```

- [ ] **Step 2: Push one locally validated block and open a draft PR**

Confirm the draft HEAD produces skipped GitHub-hosted PR jobs rather than runner execution.

- [ ] **Step 3: Mark the unchanged HEAD ready for review**

Confirm `ready_for_review` starts the applicable checks for the same exact SHA.

- [ ] **Step 4: Record evidence**

Report exact HEAD, draft/ready workflow behavior, external reviewer statuses, applicable Actions results, and any remaining blocker. Do not merge automatically.
