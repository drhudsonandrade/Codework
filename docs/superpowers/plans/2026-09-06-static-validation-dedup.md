# Static Validation Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove one duplicate repository-contract execution from the required `static` job while preserving equivalent fail-closed coverage in the full unittest suite.

**Architecture:** Keep `scaffold-validation.yml` as the protected orchestration boundary. The `static` job continues to run shell/Python compile checks and full unittest discovery; `tests/test_repo_contract.py` remains the real-repository contract path. Only the redundant standalone invocation is removed.

**Tech Stack:** GitHub Actions YAML, Python 3 standard library, unittest, Git/GitHub CLI.

**Spec:** `docs/superpowers/specs/2026-09-06-static-validation-dedup-design.md`

## Global Constraints

- Preserve required check `static` exactly.
- Preserve all protected-main ruleset checks and no-bypass behavior.
- Preserve classifier, draft gating, `container-canary`, Four-plane audit dependency, MCP, shell and WGS checks.
- Do not weaken scientific, policy, normative, security, supply-chain, publication, or human-merge boundaries.
- Work only on `ci/static-validation-dedup`; never change `main` directly and never auto-merge.

---

### Task 1: Prove and remove the duplicate static validation

**Files:**
- Modify: `tests/test_ci_optimization_contract.py`
- Modify: `tests/test_workflow_contracts.py`
- Modify: `.github/workflows/scaffold-validation.yml`

**Interfaces:**
- Consumes: `static` job text and `RepoContractTest.test_contract_accepts_repository_scaffold`.
- Produces: one full unittest execution with no standalone duplicate `scripts/validate_repo.py` call.
- [ ] **Step 1: Add the failing structural regression**

Add a test that asserts the `static` job contains `python3 -m unittest discover -s tests -v`, does not contain a standalone `python3 scripts/validate_repo.py`, and confirms `tests/test_repo_contract.py` contains `test_contract_accepts_repository_scaffold` plus `validator.validate(root)`. Update the full-history workflow contract so only `scaffold-validation.yml/static` may satisfy repository validation through the exact full unittest-discovery command; all other targeted jobs must retain their direct validator invocation.

- [ ] **Step 2: Verify RED**

Run: `python -m unittest tests.test_ci_optimization_contract.CIOptimizationContractTest.test_static_reuses_repository_contract_from_full_unittest_suite -v`

Expected: FAIL because `static` still contains the standalone `python3 scripts/validate_repo.py` step.

- [ ] **Step 3: Apply the minimal workflow change**

Delete only:

```yaml
      - name: Validate repository contract
        run: python3 scripts/validate_repo.py
```

Do not modify any other `static` step.

- [ ] **Step 4: Verify GREEN**

Run the focused regression, then `python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts -q`.

- [ ] **Step 5: Run repository and supply-chain validation**

Run `python scripts/validate_repo.py`, `python scripts/verify_supply_chain_lock.py`, shell syntax checks, `git diff --check`, and inspect workflow/check-name drift.
- [ ] **Step 6: Commit the validated implementation**

Commit the workflow, regression, spec, and plan with message `ci: deduplicate static repository validation`.

- [ ] **Step 7: Push once and open PR #46 as draft**

Push `ci/static-validation-dedup`, open a draft PR against `main`, and wait for external reviewers/checks. Resolve verified findings only; do not auto-merge.

- [ ] **Step 8: Ready-for-review verification**

Before marking ready, confirm the exact head SHA, required checks/ruleset invariants, no unresolved review threads, and that the final `static` run retains all required non-duplicate steps. After human merge, measure actual runner savings on the `main` run.
