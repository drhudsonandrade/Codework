# OmniGenis Phase 2C Runner Identity Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the protected-main private runner pool from the legacy runner labels to canonical OmniGenis labels without ever losing all known private executors, while proving real protected-main routing before legacy labels are contracted.

**Architecture:** Use expand-verify-switch-verify-contract. First add canonical labels to both currently online runners while preserving legacy labels. Then change only the trusted protected-main selector in the repository, preserving GitHub-hosted execution for pull requests and write/capability jobs. After human merge, require a real protected-main canary on the canonical pool before removing legacy runner metadata; runner-name re-registration remains one-at-a-time and is blocked unless a fresh Runtime/Resource Gate proves the recreation procedure.

**Tech Stack:** GitHub Actions, GitHub REST runner API via `gh api`, Python 3.12 `unittest`, JSON evidence contracts, repository identity guard, Git worktrees.

**Spec:** `docs/superpowers/specs/2026-09-10-omnigenis-phase2-internal-identity-migration-design.md`

## Global Constraints

- Base branch is `main`; Phase 2C begins only after Phase 2B merge commit `a1e669dd613f68f4d82ca7f1f565772ec8098cb1` and successful protected-main GHCR publication.
- The verified Phase 2B image is `ghcr.io/drhudsonandrade/omnigenis-genome@sha256:b34cddd157132f0b039bebb1674abb4957e024fd0332568fc3ae9c2ca0fa8454` from workflow run `34617560951`, attempt 2, publish job `103363105798`.
- Current runners are IDs `21` and `22`, names `drhudson-codework-01` and `drhudson-codework-02`; both were online and idle before Phase 2C.
- Canonical pool label is `omnigenis-isolated`; canonical per-runner labels are `omnigenis-01` and `omnigenis-02`.
- Do not remove `codework-isolated`, `codework-01`, or `codework-02` before the real protected-main canary succeeds after merge.
- Never unregister, stop, or recreate both runners at the same time.
- Pull-request/fork execution remains on `ubuntu-latest`; only trusted protected `main` push/workflow-dispatch routing may use the private runner pool.
- Hosted write/capability jobs remain GitHub-hosted exactly as before.
- No runner name re-registration is allowed until a fresh Runtime/Resource Gate proves container creation/restart, mounts, registration method, and rollback without exposing secrets.
- All new/modified code, tests, comments, docstrings, technical documentation, and evidence metadata are English-first.
- Canonical GENOMA v3.4 ruleset identity, sealed bytes, genomic/scientific semantics, thresholds, report taxonomy, and normative evidence are out of scope and must not change.
- No auto-merge. Final repository merge remains explicit human action.

---

## File Map

- Create `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json`: durable proof that Phase 2B post-merge publication succeeded after one transient Docker Hub failure.
- Create `docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json`: non-secret pre/post label snapshots, exact implementation evidence, and explicit post-merge requirements.
- Create `tests/test_phase2b_post_merge_ghcr_evidence.py`: verify the Phase 2B prerequisite evidence.
- Create `tests/test_phase2c_runner_identity.py`: enforce canonical routing and trust boundaries.
- Create `tests/test_phase2c_evidence_contract.py`: enforce Git-bound Phase 2C evidence and post-merge obligations.
- Modify `.github/workflows/genoma-audit.yml`: trusted protected-main runner label only.
- Modify `.github/workflows/genoma-policy-engine.yml`: trusted protected-main runner label only.
- Modify `.github/workflows/scaffold-validation.yml`: trusted protected-main runner label only.
- Modify `tests/test_ci_optimization_contract.py`: canonical selector and mutation contracts.
- Modify `tests/test_repository_identity_migration.py`: move Phase 2C from NOT_STARTED to repository cutover state while preserving external post-merge obligations.
- Modify `config/legacy_identity_ledger.json`: contract `runner-pool` and `ci-test-function-name` active repository locations to zero.
- Modify `docs/GITHUB_MOBILE_IMPORT.md`, `docs/MAGALU_PRIVATE_MCP_SETUP.md`, `docs/PROJECT_IDENTITY_CONTRACT.md`: canonical runner label and Phase 2C status.

---

### Task 1: Seal the Phase 2B post-merge GHCR prerequisite

**Files:**
- Create: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json`
- Create: `tests/test_phase2b_post_merge_ghcr_evidence.py`

**Interfaces:**
- Consumes: merge commit `a1e669dd613f68f4d82ca7f1f565772ec8098cb1`, workflow run `34617560951`, attempt 2, job `103363105798`.
- Produces: `phase2b_post_merge_ghcr.status == "VERIFIED"` and immutable image reference used as the hard Phase 2C prerequisite.

- [ ] **Step 1: Write the failing evidence test**

Create a unittest that requires the evidence file and asserts exact values:

```python
self.assertEqual(evidence["schema"], "omnigenis-phase2b-post-merge-ghcr-v1")
self.assertEqual(evidence["merge_commit"], "a1e669dd613f68f4d82ca7f1f565772ec8098cb1")
self.assertEqual(evidence["workflow_run_id"], 34617560951)
self.assertEqual(evidence["successful_attempt"], 2)
self.assertEqual(evidence["publish_job_id"], 103363105798)
self.assertEqual(evidence["status"], "VERIFIED")
self.assertEqual(
    evidence["image_reference"],
    "ghcr.io/drhudsonandrade/omnigenis-genome@sha256:b34cddd157132f0b039bebb1674abb4957e024fd0332568fc3ae9c2ca0fa8454",
)
self.assertEqual(evidence["artifact_id"], 10276395379)
self.assertEqual(evidence["attempt_1_failure_class"], "UPSTREAM_DOCKER_HUB_502")
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_phase2b_post_merge_ghcr_evidence -v
```

Expected: FAIL because the evidence file does not exist.

- [ ] **Step 3: Write the evidence from already executed facts**

Record only the non-secret facts already verified from GitHub Actions logs. Do not claim `read:packages` inspection; the proof source is the protected-main workflow output and uploaded immutable-reference artifact.

- [ ] **Step 4: Run GREEN and identity guard**

```bash
python3 -m unittest tests.test_phase2b_post_merge_ghcr_evidence -v
python3 scripts/project_identity_guard.py --check
git diff --check
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_phase2b_post_merge_ghcr_evidence.py \
  docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json
git diff --cached --check
git commit -m "docs: seal OmniGenis Phase 2B GHCR publication"
```

---

### Task 2: Expand canonical labels on both live runners before repository cutover

**Files:**
- Create/update: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json`
- Create: `tests/test_phase2c_evidence_contract.py`

**Interfaces:**
- Consumes: runner IDs 21/22 and canonical values from `config/project_identity.json`.
- Produces: verified dual-label state where both runners remain online and retain all legacy labels while exposing the canonical pool/per-runner labels.

- [ ] **Step 1: Capture the pre-mutation runner snapshot**

Execute and save only non-secret fields:

```bash
gh api repos/drhudsonandrade/OmniGenis/actions/runners \
  --jq '.runners[] | {id,name,status,busy,labels:[.labels[].name]}'
```

Require IDs 21 and 22, `status=online`, `busy=false`, legacy pool label present.

- [ ] **Step 2: Add canonical labels without deleting anything**

```bash
gh api --method POST repos/drhudsonandrade/OmniGenis/actions/runners/21/labels \
  -f 'labels[]=omnigenis-isolated' -f 'labels[]=omnigenis-01'
gh api --method POST repos/drhudsonandrade/OmniGenis/actions/runners/22/labels \
  -f 'labels[]=omnigenis-isolated' -f 'labels[]=omnigenis-02'
```

Do not use `PUT .../labels`, because that replaces the entire custom-label set.

- [ ] **Step 3: Verify dual-label state via runner API**

Runner 21 must contain `codework-isolated`, `codework-01`, `omnigenis-isolated`, `omnigenis-01`; runner 22 must contain `codework-isolated`, `codework-02`, `omnigenis-isolated`, `omnigenis-02`. Both remain online. Abort if either disappears or legacy labels are lost.

- [ ] **Step 4: Write RED/GREEN evidence contract**

The contract requires `stage == "DUAL_LABEL_EXPANDED"`, pre/post snapshots, runner IDs/names unchanged, canonical labels present post-mutation, legacy labels retained post-mutation, and `repository_selector_cutover == "NOT_MERGED"`.

- [ ] **Step 5: Commit only the non-secret snapshot/evidence contract**

```bash
git add tests/test_phase2c_evidence_contract.py \
  docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json
git diff --cached --check
git commit -m "test: record Phase 2C dual-label runner state"
```

---

### Task 3: Cut trusted repository routing over to the canonical pool

**Files:**
- Modify: `.github/workflows/genoma-audit.yml`
- Modify: `.github/workflows/genoma-policy-engine.yml`
- Modify: `.github/workflows/scaffold-validation.yml`
- Modify: `tests/test_ci_optimization_contract.py`
- Modify: `tests/test_repository_identity_migration.py`
- Create: `tests/test_phase2c_runner_identity.py`
- Modify: `docs/GITHUB_MOBILE_IMPORT.md`
- Modify: `docs/MAGALU_PRIVATE_MCP_SETUP.md`
- Modify: `docs/PROJECT_IDENTITY_CONTRACT.md`

**Interfaces:**
- Consumes: dual-label runners verified in Task 2 and canonical `runners.pool_label` from `config/project_identity.json`.
- Produces: repository selectors use `omnigenis-isolated`; pull requests/forks and hosted write/capability jobs remain `ubuntu-latest`.

- [ ] **Step 1: Write RED tests for canonical trusted routing**

Update the test constant to the canonical selector:

```python
TRUSTED_RUNNER_LINE = (
    "runs-on: ${{ ((github.event_name == 'push' || github.event_name == 'workflow_dispatch') "
    "&& github.ref == 'refs/heads/main' && github.ref_protected) && 'omnigenis-isolated' "
    "|| 'ubuntu-latest' }}"
)
```

The behavior test must assert:

```python
self.assertEqual(selected_runner("pull_request", "refs/pull/53/merge", False), "ubuntu-latest")
self.assertEqual(selected_runner("workflow_dispatch", "refs/heads/feature", False), "ubuntu-latest")
self.assertEqual(selected_runner("workflow_dispatch", "refs/heads/main", False), "ubuntu-latest")
self.assertEqual(selected_runner("workflow_dispatch", "refs/heads/main", True), "omnigenis-isolated")
self.assertEqual(selected_runner("push", "refs/heads/main", True), "omnigenis-isolated")
```

Add a mutation test replacing `github.ref_protected` with `github.ref_protected || true` and require `_trusted_runner_routing_errors` to reject it.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest \
  tests.test_phase2c_runner_identity \
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_trusted_heavy_checks_use_private_omnigenis_runners_without_moving_write_jobs \
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_trusted_runner_contract_rejects_boolean_bypass_mutation -v
```

Expected: FAIL because workflows still route to the legacy pool label.

- [ ] **Step 3: Change only the three trusted runner selectors**

Replace the private pool token in exactly the `audit`, `policy`, and `static` jobs. Do not change their trust expression, permissions, event conditions, or any hosted job.

- [ ] **Step 4: Update active operational docs/status**

Replace active private-pool instructions with `omnigenis-isolated` and state that live runners are dual-labeled until the protected-main post-merge canary contracts the old labels.

- [ ] **Step 5: Run GREEN and workflow boundary tests**

```bash
python3 -m unittest tests.test_phase2c_runner_identity tests.test_ci_optimization_contract tests.test_repository_identity_migration -v
python3 scripts/validate_repo.py
python3 scripts/project_identity_guard.py --check
```

Expected: PASS; hosted jobs remain hosted and only trusted protected-main routing changes.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/genoma-audit.yml \
  .github/workflows/genoma-policy-engine.yml \
  .github/workflows/scaffold-validation.yml \
  tests/test_ci_optimization_contract.py tests/test_repository_identity_migration.py \
  tests/test_phase2c_runner_identity.py docs/GITHUB_MOBILE_IMPORT.md \
  docs/MAGALU_PRIVATE_MCP_SETUP.md docs/PROJECT_IDENTITY_CONTRACT.md
git diff --cached --check
git commit -m "refactor: route trusted jobs to OmniGenis runners"
```

---

### Task 4: Contract repository legacy-runner ledger entries

**Files:**
- Modify: `config/legacy_identity_ledger.json`
- Modify: `tests/test_phase2c_runner_identity.py`

**Interfaces:**
- Consumes: repository cutover from Task 3.
- Produces: `runner-pool.locations == {}` and `ci-test-function-name.locations == {}` without increasing any other ledger budget.

- [ ] **Step 1: Add RED seal assertions**

```python
entries = {entry["id"]: entry for entry in ledger["entries"]}
self.assertEqual(entries["runner-pool"]["locations"], {})
self.assertEqual(entries["ci-test-function-name"]["locations"], {})
```

Also require `scan_repository(ROOT, contract, ledger).unclassified == []` and `.over_budget == []`.

- [ ] **Step 2: Run RED**

Expected: FAIL while reviewed budgets still describe old repository locations.

- [ ] **Step 3: Contract only the two 2C ledger entries**

Set both location maps to `{}`. Do not delete matchers; they remain fail-closed detectors against reintroduction.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest tests.test_phase2c_runner_identity tests.test_project_identity_guard -v
python3 scripts/project_identity_guard.py --check
```

- [ ] **Step 5: Commit**

```bash
git add config/legacy_identity_ledger.json tests/test_phase2c_runner_identity.py
git commit -m "test: seal Phase 2C repository runner identities"
```

---

### Task 5: Produce exact-head pre-merge evidence and validate the complete branch

**Files:**
- Modify: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json`
- Modify: `tests/test_phase2c_evidence_contract.py`

**Interfaces:**
- Consumes: exact implementation HEAD after Tasks 1-4, live dual-label snapshot, Phase 2B GHCR prerequisite.
- Produces: pre-merge evidence that explicitly leaves protected-main canary, legacy-label contraction, and runner-name re-registration pending.

- [ ] **Step 1: Stabilize implementation HEAD before evidence refresh**

Commit all implementation/test changes first. Record `IMPLEMENTATION_HEAD=$(git rev-parse HEAD)` and its tree SHA.

- [ ] **Step 2: Run exact-head pre-evidence gates**

Use the pinned venv and record reproducible commands/log hashes for:

```bash
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 scripts/code_language_guard.py --check
python3 scripts/residual_language_audit.py --check
python3 -m unittest tests.test_developer_documentation_language -v
python3 -m unittest tests.test_phase2b_post_merge_ghcr_evidence tests.test_phase2c_runner_identity -v
find scripts -type f -name '*.sh' -exec bash -n {} +
git diff --check
```

Do not claim the post-merge runner canary before merge.

- [ ] **Step 3: Refresh Phase 2C evidence**

Require:

```json
{
  "stage": "REPOSITORY_CUTOVER_READY_FOR_REVIEW",
  "post_merge": {
    "protected_main_canary": "PENDING_AFTER_HUMAN_MERGE",
    "legacy_runner_label_removal": "BLOCKED_UNTIL_CANARY_PASS",
    "runner_name_reregistration": "BLOCKED_UNTIL_RUNTIME_RESOURCE_GATE"
  }
}
```

Bind implementation SHA/tree and preserve the verified dual-label snapshot.

- [ ] **Step 4: Commit evidence-only**

The evidence refresh must be the only path in the evidence commit.

- [ ] **Step 5: Run final complete regression on final PR HEAD**

```bash
python3 -m unittest tests.test_phase2c_evidence_contract -v
python3 -m unittest discover -s tests -v
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 scripts/code_language_guard.py --check
python3 scripts/residual_language_audit.py --check
find scripts -type f -name '*.sh' -exec bash -n {} +
git diff --check
```

Record the real test count from output.

---

### Task 6: Publish one draft PR and satisfy exact-head review

**Files:**
- No additional implementation files unless a verified reviewer finding requires a correction.

**Interfaces:**
- Consumes: clean final Phase 2C branch and dual-label live runners.
- Produces: one Phase 2C PR ready for explicit human merge.

- [ ] **Step 1: Verify exact changed-file allowlist and boundaries**

Confirm no runner API deletion occurred, no runner name changed, no scientific/normative path changed, and no workflow write/capability job moved from GitHub-hosted runners.

- [ ] **Step 2: Handle workflow-file transport safely**

If local HTTPS OAuth still lacks `workflow`, use the already authorized GitHub App bootstrap method used in Phase 2B: publish exact validated workflow blobs, rebuild branch history over those commits, compare implementation tree SHA, then repeat exact-head validation before evidence refresh/push.

- [ ] **Step 3: Open PR as draft**

Title:

```text
refactor: cut trusted runner routing to OmniGenis
```

The PR body must list pre/post label snapshots, Phase 2B GHCR prerequisite, exact implementation/evidence SHAs, complete test count, and explicit post-merge obligations.

- [ ] **Step 4: Mark Ready only after exact remote HEAD matches validated local HEAD**

Require DeepSource, GitGuardian, Snyk, Semgrep, CodeRabbit required check, applicable Actions, zero unresolved review threads, active semantically-equivalent rulesets, and `mergeStateStatus=CLEAN`.

- [ ] **Step 5: Stop before merge**

No auto-merge. Report the PR as ready for manual merge only when all gates are green.

---

## Post-merge Phase 2C operational gate — not part of the PR merge itself

After explicit human merge:

1. Confirm `main` contains the Phase 2C merge commit.
2. Find the protected-main `static`/trusted job triggered by that merge and prove it completed on a runner selected through `omnigenis-isolated`.
3. Capture run ID, job ID, commit SHA, conclusion, and runner name/ID if exposed by GitHub.
4. Only after that canary passes, remove `codework-isolated`, `codework-01`, and `codework-02` from runner metadata using label-specific DELETE endpoints; never use a replace-all operation accidentally.
5. Verify both runners remain online with `omnigenis-isolated` and their canonical per-runner labels.
6. Rerun the Runtime/Resource Gate before any runner-name re-registration. If recreation details are not verifiably available, stop with names unchanged rather than unregistering a working runner.
7. If safe recreation is proven, keep runner 02 online while runner 01 is re-registered as `drhudson-omnigenis-01`; verify/canary; then and only then repeat for runner 02.
8. Final runner-name/pool evidence is carried into Phase 2D sealing. No simultaneous two-runner outage is permitted.
