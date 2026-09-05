# Production Witness Capability Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent GitHub-hosted runner allocation for the Production Witness while authoritative Project Instructions installation evidence is unavailable, without changing POST-DEPLOYMENT PASS semantics.

**Architecture:** Keep the workflow subscribed to every `main` push, but add one exact job-level repository-variable guard to the heavy `witness` job. Enforce the guard independently in workflow contracts and `scripts/validate_repo.py`; preserve publisher dependency, live-smoke evidence, hashes, container hardening, and human-only merge.

**Tech Stack:** GitHub Actions YAML, Python 3.12/3.13 `unittest`, repository validator, Markdown operational documentation.

**Spec:** `docs/superpowers/specs/2026-09-05-production-witness-capability-gate-design.md`

## Global Constraints

- Base implementation on `8788e49444e79fe4c91a108de86abb0bd1617a8f` plus the approved spec commit.
- Keep `push: branches: [main]` and do not add `paths:`.
- Exact guard: `${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}`.
- Missing or non-`true` variable means skipped execution and `POST-DEPLOYMENT PENDENTE`, never PASS.
- The variable is capability control only; it is never evidence for `PROJECT_BOOTSTRAP_INSTALLED`.
- Preserve the existing 15 live scenarios, evidence files, hashes, container hardening, deploy key, and append-only publisher behavior.
- Do not change protected-main required check names or rulesets.
- No auto-merge; final merge is human-only.
- Keep implementation PR Draft until exact-head local validation is complete.

---
### Task 1: Enforce the capability guard structurally

**Files:**
- Modify: `tests/test_workflow_contracts.py:244-275`
- Modify: `.github/workflows/genoma-production-witness.yml:14-18`

**Interfaces:**
- Consumes: existing `_job_block()` and `_job_if_condition()` workflow parsers.
- Produces: the exact `witness` job predicate `${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}`.

- [ ] **Step 1: Write the failing workflow contract**

Add this constant near the existing workflow helpers:

```python
PRODUCTION_WITNESS_CAPABILITY_GUARD = (
    "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}"
)
```

Add this test beside `test_production_witness_covers_every_main_commit`:

```python
def test_production_witness_requires_exact_job_level_capability_guard(self):
    workflow = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
    self.assertEqual(
        _job_if_condition(workflow, "witness"),
        PRODUCTION_WITNESS_CAPABILITY_GUARD,
    )
    self.assertIn("needs: witness", _job_block(workflow, "publish-witness"))
```
Add mutation checks inside the same test:

```python
for weakened in (
    "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED }}",
    "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED != 'false' }}",
    "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'TRUE' }}",
):
    mutated = workflow.replace(
        f"    if: {PRODUCTION_WITNESS_CAPABILITY_GUARD}\n",
        f"    if: {weakened}\n",
        1,
    )
    self.assertNotEqual(
        _job_if_condition(mutated, "witness"),
        PRODUCTION_WITNESS_CAPABILITY_GUARD,
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:
`python -m unittest tests.test_workflow_contracts.WorkflowContractTest.test_production_witness_requires_exact_job_level_capability_guard -v`

Expected: FAIL because `witness` has no job-level `if` yet.

- [ ] **Step 3: Add the minimal workflow guard**

Under `jobs: -> witness:` add exactly:

```yaml
    if: ${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}
```

Do not alter triggers, `runs-on`, timeout, steps, evidence, or publisher logic.
- [ ] **Step 4: Run focused workflow tests and verify GREEN**

Run:
`python -m unittest tests.test_workflow_contracts.WorkflowContractTest.test_production_witness_requires_exact_job_level_capability_guard tests.test_workflow_contracts.WorkflowContractTest.test_production_witness_covers_every_main_commit tests.test_workflow_contracts.WorkflowContractTest.test_production_witness_publisher_uses_restricted_deploy_key_without_token_write -v`

Expected: all selected tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add .github/workflows/genoma-production-witness.yml tests/test_workflow_contracts.py
git commit -m "ci: gate production witness on external capability"
```

### Task 2: Make the repository validator fail closed on guard drift

**Files:**
- Modify: `scripts/validate_repo.py:701-709`
- Modify: `tests/test_workflow_contracts.py`

**Interfaces:**
- Consumes: Production Witness workflow text and the exact guard constant used by tests.
- Produces: `validate_production_witness_contract(root: Path, errors: list[str]) -> None`.

- [ ] **Step 1: Add validator regression tests before refactoring**

Import the validator in `tests/test_workflow_contracts.py`:

```python
from scripts import validate_repo
```
Add a test that copies the real workflow into a temporary repository root, mutates the guard, and invokes only the witness validator:

```python
def test_validate_repo_rejects_missing_or_weakened_production_witness_guard(self):
    source = (ROOT / ".github/workflows/genoma-production-witness.yml").read_text(encoding="utf-8")
    mutations = (
        source.replace(f"    if: {PRODUCTION_WITNESS_CAPABILITY_GUARD}\n", "", 1),
        source.replace(
            f"    if: {PRODUCTION_WITNESS_CAPABILITY_GUARD}\n",
            "    if: ${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED }}\n",
            1,
        ),
    )
    for mutated in mutations:
        with self.subTest(mutated=mutated[:80]), tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / ".github/workflows/genoma-production-witness.yml"
            path.parent.mkdir(parents=True)
            path.write_text(mutated, encoding="utf-8")
            errors: list[str] = []
            validate_repo.validate_production_witness_contract(root, errors)
            self.assertTrue(any("capability guard" in error for error in errors))
```

- [ ] **Step 2: Run the validator regression and verify RED**

Run:
`python -m unittest tests.test_workflow_contracts.WorkflowContractTest.test_validate_repo_rejects_missing_or_weakened_production_witness_guard -v`

Expected: ERROR/FAIL because `validate_production_witness_contract` does not exist yet.
- [ ] **Step 3: Extract and harden the witness validator**

Add the module constant:

```python
PRODUCTION_WITNESS_CAPABILITY_GUARD = "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}"
```

Extract the current inline witness checks into:

```python
def validate_production_witness_contract(root: Path, errors: list[str]) -> None:
    witness = root / ".github/workflows/genoma-production-witness.yml"
    if not witness.is_file():
        return
    text = witness.read_text(encoding="utf-8")
    if "--output-dir evidence/live-section-260" in text:
        errors.append("Production Witness still uses obsolete live smoke --output-dir contract")
    for token in ("--deployment-id", "--output evidence/live-section-260/summary.json"):
        if token not in text:
            errors.append(f"Production Witness missing current live smoke contract: {token}")
    marker = "\n  witness:\n"
    publisher_marker = "\n  publish-witness:\n"
    if marker not in text or publisher_marker not in text:
        errors.append("Production Witness capability guard is not attached to the witness job boundary")
        return
    job = text.split(marker, 1)[1].split(publisher_marker, 1)[0]
    conditions = [
        line.removeprefix("    if: ").strip()
        for line in job.splitlines()
        if line.startswith("    if: ")
    ]
    if conditions != [PRODUCTION_WITNESS_CAPABILITY_GUARD]:
        errors.append("Production Witness capability guard must use the exact job-level repository-variable predicate")
```
Replace the old inline witness block inside `validate()` with:

```python
validate_production_witness_contract(root, errors)
```

- [ ] **Step 4: Run validator tests and verify GREEN**

Run:
`python -m unittest tests.test_workflow_contracts.WorkflowContractTest.test_validate_repo_rejects_missing_or_weakened_production_witness_guard tests.test_workflow_contracts.WorkflowContractTest.test_production_witness_requires_exact_job_level_capability_guard -v`

Then run:
`python scripts/validate_repo.py`

Expected: selected tests PASS and repository validator exits 0.

- [ ] **Step 5: Commit Task 2**

```bash
git add scripts/validate_repo.py tests/test_workflow_contracts.py
git commit -m "test: enforce production witness capability guard"
```

### Task 3: Document the operational semantics and rollback

**Files:**
- Modify: `docs/PRODUCTION_CEREMONY.md`
- Modify: `tests/test_workflow_contracts.py`

**Interfaces:**
- Consumes: repository variable `GENOMA_PRODUCTION_WITNESS_ENABLED`.
- Produces: operator-facing rule that `true` arms execution but never proves installation or PASS.

- [ ] **Step 1: Add a documentation contract test**

Add:

```python
def test_production_ceremony_documents_capability_gate_pending_semantics(self):
    text = (ROOT / "docs/PRODUCTION_CEREMONY.md").read_text(encoding="utf-8")
    self.assertIn("GENOMA_PRODUCTION_WITNESS_ENABLED", text)
    self.assertIn("POST-DEPLOYMENT PENDENTE", text)
    self.assertIn("does not grant POST-DEPLOYMENT PASS", text)
    self.assertIn("job is skipped before runner allocation", text)
```
- [ ] **Step 2: Run the documentation test and verify RED**

Run:
`python -m unittest tests.test_workflow_contracts.WorkflowContractTest.test_production_ceremony_documents_capability_gate_pending_semantics -v`

Expected: FAIL because the operational capability gate is not documented yet.

- [ ] **Step 3: Add the capability-gate subsection to `docs/PRODUCTION_CEREMONY.md`**

Insert after `### 4.2 PROJECT_BOOTSTRAP_INSTALLED`:

```markdown
### 4.3 Production Witness capability gate

`GENOMA_PRODUCTION_WITNESS_ENABLED` controls whether the independent Production Witness may allocate a GitHub-hosted runner. It is an operational capability flag only.

If the repository variable is absent or has any value other than exact `true`, the `witness` job is skipped before runner allocation. The corresponding state remains `POST-DEPLOYMENT PENDENTE`; a skipped run creates no witness evidence and does not grant POST-DEPLOYMENT PASS.

Setting the variable to exact `true` only arms the existing witness. It does not prove `PROJECT_BOOTSTRAP_INSTALLED`, does not bypass any fail-closed condition, and does not change the 15/15, zero-critical-failure, exact-SHA, evidence-integrity, or publisher requirements.

To disarm the witness capability and keep the no-runner state, remove the variable or set it to any value other than exact `true`. To restore pre-gate execution without changing code, set `GENOMA_PRODUCTION_WITNESS_ENABLED` to exact `true`; that is the operational rollback of the cost gate. Historical evidence is never rewritten.
```

- [ ] **Step 4: Run documentation and workflow contracts and verify GREEN**

Run:
`python -m unittest tests.test_workflow_contracts -v`

Expected: complete workflow-contract module PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add docs/PRODUCTION_CEREMONY.md tests/test_workflow_contracts.py
git commit -m "docs: define production witness capability lifecycle"
```
### Task 4: Final local proof, Draft PR, and exact-head final CI

**Files:**
- Verify only; no new implementation files expected.

**Interfaces:**
- Consumes: exact branch HEAD from Tasks 1-3.
- Produces: one Draft PR checkpoint, then one final Ready-for-Review CI/reviewer pass on the same SHA.

- [ ] **Step 1: Run the focused and repository validators**

Run in order:

```bash
python -m unittest tests.test_workflow_contracts -v
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python scripts/code_language_guard.py --check
bash -n scripts/*.sh
git diff --check origin/main...HEAD
```

Expected: all commands exit 0. Do not claim the full native-Windows repository suite is green; the approved spec records the pre-existing bootstrap digest mismatch on NOAR.

- [ ] **Step 2: Review scope against `origin/main`**

Run:

```bash
git status --short
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- .github/workflows/genoma-production-witness.yml tests/test_workflow_contracts.py scripts/validate_repo.py docs/PRODUCTION_CEREMONY.md docs/superpowers/specs/2026-09-05-production-witness-capability-gate-design.md docs/superpowers/plans/2026-09-05-production-witness-capability-gate.md
```

Expected: no unrelated production files, no ruleset/hash changes, and only approved capability-gate surfaces.

- [ ] **Step 3: Push the coherent branch and create a Draft PR**

```bash
git push -u origin ci/production-witness-capability-gate
$body = @"
## Scope
Gate the Production Witness heavy job on `GENOMA_PRODUCTION_WITNESS_ENABLED == true` at the job boundary while preserving every-main-push workflow coverage.

## Safety
Missing/non-true means skipped + POST-DEPLOYMENT PENDENTE, never PASS. Exact true only arms the existing 15/15 fail-closed witness. Publisher, evidence, hashes, container hardening, deploy key, required checks, and human-only merge remain unchanged.

## Local evidence
Workflow contracts, validate_repo, supply-chain verification, code-language guard, shell syntax, and diff-check pass on the exact head. The pre-existing NOAR Windows bootstrap digest mismatch remains disclosed; no full native-Windows suite PASS is claimed.
"@
gh pr create --draft --base main --head ci/production-witness-capability-gate --title "ci: gate production witness on external capability" --body $body
```

The PR body must state that missing/false is skipped + PENDENTE, exact `true` only arms execution, no PASS semantics changed, and the Windows bootstrap baseline limitation remains disclosed.
- [ ] **Step 4: Prove Draft-first runner suppression before Ready for Review**

Record the exact branch SHA:

```bash
git rev-parse HEAD
```

Inspect PR checks and workflow runs while the PR is still Draft. Repository-owned PR validation jobs that are covered by the Draft-first contract must be skipped before runner allocation; external GitHub Apps may still report independently.

If any implementation correction is needed, keep the PR Draft, fix locally with TDD, rerun Step 1, commit, and push one coherent correction block.

- [ ] **Step 5: Mark the same validated HEAD Ready for Review**

Confirm `git status --short` is empty and the remote PR head equals local `git rev-parse HEAD`. Then run:

```bash
gh pr ready
```

Do not push after this point unless a blocking finding requires returning the PR to Draft.

- [ ] **Step 6: Verify final exact-head gates and reviewers**

Require the exact Ready-for-Review SHA to complete all applicable protected-main checks and external reviews: `static`, `container-canary`, policy/Rego/Docker checks as applicable, CodeRabbit, Greptile, GitGuardian, DeepSource analyzers, Snyk, and Semgrep.

Verify zero unresolved review threads and confirm GitHub reports the PR mergeable/clean. If a reviewer identifies a valid defect, convert the PR back to Draft before any corrective push and repeat local proof on the new exact HEAD.

- [ ] **Step 7: Stop before merge and hand off to the human**

Report the final SHA, check results, reviewer status, unresolved-thread count, and PR URL. Do not invoke auto-merge or merge the PR; wait for explicit human manual merge.
