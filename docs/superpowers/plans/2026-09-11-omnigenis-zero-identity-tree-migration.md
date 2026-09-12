# OmniGenis Zero Identity Tree Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current tracked OmniGenis tree contain zero P1-P4 identity-token matches while preserving scientific behavior, governance, auditability, and external runner continuity.

**Architecture:** Implement a fingerprint-only raw-byte guard first, migrate canonical contracts and provider-bound metadata to neutral representations, purge every current tracked blob including history/evidence, and only then wire the guard into the official validator. External runner re-registration is a post-merge rolling operation and is not mixed into the repository PR.

**Tech Stack:** Git, Python 3.12 stdlib, `unittest`, GitHub Actions, GitHub CLI for live post-merge verification, existing OmniGenis validators, JSON evidence, SHA-256.

**Spec:** `docs/superpowers/specs/2026-09-11-omnigenis-zero-personal-assistant-identity-design.md`

## Global Constraints

- Baseline `main`: `fe0c91c99fe4cd57e14c69cc3b3c58edcb4e8be8`.
- Planning baseline requirement: the full root suite must pass before implementation; no immutable test-count artifact was bound to the planning commit.
- P1-P4 plaintext is forbidden in tracked path names and tracked blob bytes, case-insensitively.
- The enforcement implementation stores only fingerprints, lengths, class IDs, and non-plaintext numeric/hex mutation fixtures.
- There are no history/evidence/spec/plan exemptions.
- Canonical future runner names are `omnigenis-runner-01` and `omnigenis-runner-02`.
- Repository identity is tracked by numeric repository ID `1212760346` plus neutral repository name `OmniGenis`.
- Provider-qualified repository/package values are resolved at runtime and are not committed as repository data.
- Canonical report control marker is `GENOMA-RULESET-v3.4`; generic prefix is `GENOMA-RULESET-v`.
- Canonical GENOMA v3.4 ruleset bytes, scientific thresholds, interpretation semantics, report taxonomy, and consent rules must not change.
- All modified code/tests/docs remain English-first except already justified normative/localized contracts.
- No auto-merge.

## Baseline Inventory

The pre-migration inventory was used only as an execution checklist and was not persisted as an attested artifact. Exact baseline match counts are therefore intentionally omitted from this plan rather than presented as verified evidence. The authoritative completion condition is the final seal: every required class P1-P4 must have zero tracked-path and zero tracked-blob findings independently.

---

### Task 1: Build the standalone repository-wide fingerprint guard

**Files:**
- Create: `config/zero_identity_policy.json`
- Create: `scripts/zero_identity_guard.py`
- Create: `tests/test_zero_identity_guard.py`

**Interfaces:**
- Consumes: Git tracked-file enumeration and the approved P1-P4 fingerprints/lengths.
- Produces: `scan_repository(root: Path) -> list[Finding]` and `validate_zero_identity(root: Path) -> list[str]`.
- The guard is standalone in this task; it is not added to `validate_repo.py` until Task 7, because the baseline tree is intentionally RED.

- [ ] **Step 1: Add the fingerprint-only policy file**

Create JSON with schema `omnigenis-zero-identity-policy-v1` and exactly these records:

```json
{
  "schema": "omnigenis-zero-identity-policy-v1",
  "classes": [
    {"id": "P1", "length": 8, "sha256": "dd052083021cc0cd9c53c4456f395785eea0021d5ea56f5fb3869a6be535786f"},
    {"id": "P2", "length": 6, "sha256": "0f6360072cf8ed9f46f90ce9d01fae4e42f5e8ff629499d2206c68ed403e2fe7"},
    {"id": "P3", "length": 7, "sha256": "60965168ce762e949600281ba6d01fee136e5b6e8257b1f216f9025ed324474c"},
    {"id": "P4", "length": 6, "sha256": "c857d09db23e6822e3600bc06ad8d58f92ed62bc8efd81c753f77048662cb97d"}
  ]
}
```

- [ ] **Step 2: Write RED tests without plaintext fixtures**

Construct mutation bytes from hex only:

```python
MUTATIONS = {
    "P1": bytes.fromhex("6472687564736f6e"),
    "P2": bytes.fromhex("687564736f6e"),
    "P3": bytes.fromhex("63686174677074"),
    "P4": bytes.fromhex("636c61756465"),
}
```

Tests must prove:
- each class is detected in blob content;
- mixed ASCII case is detected;
- each class is detected in a tracked path name;
- binary bytes are scanned;
- a tracked file under `docs/history/` is scanned;
- untracked files do not affect the official result;
- Git enumeration/read failures fail closed;
- duplicate class IDs, duplicate `(length, sha256)` pairs, malformed digests, or zero lengths reject policy load;
- findings report only class, path, and byte offset, never matched bytes.

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest tests.test_zero_identity_guard -v
```

Expected: FAIL because the guard module does not exist.

- [ ] **Step 4: Implement raw-byte matching**

Use `git ls-files -z` as the sole authority. Normalize only ASCII A-Z to a-z for candidate-window hashing. Read tracked blobs as bytes. Reject symlink ambiguity consistently with repository policy. Never recurse ambient filesystem state.

Required CLI:

```bash
python3 scripts/zero_identity_guard.py --check
python3 scripts/zero_identity_guard.py --inventory-json
```

`--inventory-json` outputs class IDs/counts/paths only and never matched bytes.

- [ ] **Step 5: Run focused GREEN**

```bash
python3 -m unittest tests.test_zero_identity_guard -v
python3 -m py_compile scripts/zero_identity_guard.py
```

The standalone `--check` is expected to remain RED against the baseline tree until Task 6 completes.

- [ ] **Step 6: Commit**

```bash
git add config/zero_identity_policy.json scripts/zero_identity_guard.py tests/test_zero_identity_guard.py
git diff --cached --check
git commit -m "test: add fail-closed zero identity guard"
```

---

### Task 2: Neutralize canonical repository and runner identity contracts

**Files:**
- Modify: `config/project_identity.json`
- Modify: `config/legacy_identity_ledger.json`
- Modify: `tests/test_project_identity_contract.py`
- Modify: `tests/test_project_identity_guard.py`
- Modify: `tests/test_phase2c_runner_identity.py`
- Modify: `tests/test_repository_identity_migration.py`
- Modify: `docs/PROJECT_IDENTITY_CONTRACT.md`
- Modify: `docs/BRANCH_GOVERNANCE.md`

**Interfaces:**
- Consumes: repository ID `1212760346`, product name `OmniGenis`, existing canonical labels.
- Produces: owner-neutral repository metadata and future runner names `omnigenis-runner-01/02`.

- [ ] **Step 1: Write RED contract assertions**

Require:

```python
self.assertEqual(identity["repository"], {
    "repository_id": 1212760346,
    "repository_name": "OmniGenis",
})
self.assertEqual(
    identity["runners"]["runner_names"],
    ["omnigenis-runner-01", "omnigenis-runner-02"],
)
```

Add an assertion that `repository.full_name` is absent.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest \
  tests.test_project_identity_contract \
  tests.test_project_identity_guard \
  tests.test_phase2c_runner_identity \
  tests.test_repository_identity_migration -v
```

Expected: FAIL on the old owner-qualified repository field and future runner names.

- [ ] **Step 3: Update canonical identity and ledger**

Replace the account-qualified repository field with ID/name fields. Remove ledger entries whose only purpose is preserving an account-qualified old repository name. Keep generic legacy-product matchers only when they contain no P1-P4 match and still protect an active migration boundary.

Documentation must explain that provider-qualified names are runtime-derived and never committed.

- [ ] **Step 4: Run GREEN plus standalone inventory**

```bash
python3 -m unittest \
  tests.test_project_identity_contract \
  tests.test_project_identity_guard \
  tests.test_phase2c_runner_identity \
  tests.test_repository_identity_migration -v
python3 scripts/project_identity_guard.py --check
python3 scripts/zero_identity_guard.py --inventory-json
```

The zero-identity inventory may still be nonzero because later tasks own other surfaces.

- [ ] **Step 5: Commit**

```bash
git add config/project_identity.json config/legacy_identity_ledger.json \
  tests/test_project_identity_contract.py tests/test_project_identity_guard.py \
  tests/test_phase2c_runner_identity.py tests/test_repository_identity_migration.py \
  docs/PROJECT_IDENTITY_CONTRACT.md docs/BRANCH_GOVERNANCE.md
git diff --cached --check
git commit -m "refactor: neutralize canonical repository identity"
```

---

### Task 3: Replace personal report/template control markers

**Files:**
- Modify: `reporting/template_v3.py`
- Modify: `scripts/build_report_coordinate_pack.py`
- Modify: `tests/test_report_coordinate_pack_ruleset_markers.py`
- Modify: `tests/test_template_v3_contract.py`
- Modify: `tests/test_superseded_identity_scanner.py`

**Interfaces:**
- Consumes: canonical v3.4 ruleset identity and report rendering contracts.
- Produces: `GENOMA-RULESET-v3.4` and prefix `GENOMA-RULESET-v` only.

- [ ] **Step 1: Write RED marker tests**

Require exact canonical marker and reject malformed suffixes/prefixes:

```python
self.assertEqual(CURRENT_RULESET_TEMPLATE_SOURCE, "GENOMA-RULESET-v3.4")
self.assertEqual(RULESET_TEMPLATE_PREFIX, "GENOMA-RULESET-v")
```

Mutation tests must construct retired marker bytes from non-plaintext hex/numeric fixtures if needed.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest \
  tests.test_report_coordinate_pack_ruleset_markers \
  tests.test_template_v3_contract \
  tests.test_superseded_identity_scanner -v
```

- [ ] **Step 3: Implement neutral markers**

Change only marker constants/regexes and their tests. Do not alter canonical ruleset bytes, manifests, scientific thresholds, model schemas, or report taxonomy.

- [ ] **Step 4: Run GREEN and protected-boundary checks**

```bash
python3 -m unittest \
  tests.test_report_coordinate_pack_ruleset_markers \
  tests.test_template_v3_contract \
  tests.test_superseded_identity_scanner \
  tests.test_ruleset_digest_binding \
  tests.test_sealed_ruleset_contract -v
python3 scripts/validate_repo.py
```

- [ ] **Step 5: Commit**

```bash
git add reporting/template_v3.py scripts/build_report_coordinate_pack.py \
  tests/test_report_coordinate_pack_ruleset_markers.py \
  tests/test_template_v3_contract.py tests/test_superseded_identity_scanner.py
git commit -m "refactor: neutralize report control markers"
```

---

### Task 4: Neutralize AI/MCP interface and project-instruction provenance

**Files:**
- Modify: `.github/workflows/genoma-production-witness.yml`
- Modify: `adapters/README.md`
- Modify: `adapters/config.example.json`
- Modify: `deploy/attestations/project-instructions-v3.4.json`
- Modify: `docs/DETERMINISTIC_ENGINE.md`
- Modify: `docs/GITHUB_MOBILE_IMPORT.md`
- Modify: `docs/MAGALU_PRIVATE_MCP_SETUP.md`
- Modify: `docs/PORTABILITY_MATRIX.md`
- Modify: `docs/PRODUCTION_CEREMONY.md`
- Modify: `docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md`
- Modify: `docs/REFERENCE_FOUNDRY.md`
- Modify: `docs/history/v3.3/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md`
- Modify: `docs/history/v3.3/audits/GENOMA_V0.8_FINAL_AUDIT_2026-08-16.md`
- Modify: `docs/history/v3.3/bootstrap-project-v3.3.HISTORICAL.json`
- Modify: `docs/history/v3.3/superpowers/plans/2026-08-14-magalu-private-mcp.md`
- Modify: `docs/history/v3.3/superpowers/plans/2026-08-16-genoma-array-evidence-template-lock-v0.8.md`
- Modify: `docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md`
- Modify: `mcp/README.md`
- Modify: `policy_engine/README_GENOMA_POLICY.md`
- Modify: `policy_engine/docs/GENOMA_EXECUTABLE_ARCHITECTURE.md`
- Modify: `policy_engine/docs/TRANSLATION_MATRIX.md`
- Modify: `scripts/project_instructions_attestation.py`
- Modify: `scripts/run_live_post_deployment_smoke.py`
- Modify: `tests/test_post_merge_bootstrap_governance.py`
- Modify: `tests/test_project_instructions_attestation_committed.py`
- Modify: `config/residual_language_classification.json` only to refresh fingerprints for edited classified surfaces; categories and counts must not change.

**Interfaces:**
- Consumes: existing project-instruction snapshot and fail-closed witness semantics.
- Produces: provider-neutral interface language and locator `project-instructions://GENOMA/instructions`.

- [ ] **Step 1: Write RED neutral-attestation tests**

Require:

```python
self.assertEqual(
    evidence["source_locator"],
    "project-instructions://GENOMA/instructions",
)
```

Add tests that optional interface docs use capability terms (`AI client`, `MCP client`, `interactive AI workspace`, `secure MCP tunnel`) and that deterministic core independence remains unchanged.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest \
  tests.test_post_merge_bootstrap_governance \
  tests.test_project_instructions_attestation_committed -v
```

- [ ] **Step 3: Update code, attestation JSON, workflows, and docs**

Do not weaken `PROJECT_BOOTSTRAP_INSTALLED` fail-closed semantics. Replace provider/product-specific locator and prose with capability-based terms. Historical records must say the external locator was intentionally de-identified where exact reconstruction can no longer use a stored provider-qualified URL. Refresh only the residual-language fingerprints of edited classified surfaces after proving category/count invariance.

- [ ] **Step 4: Run GREEN**

```bash
python3 -m unittest \
  tests.test_post_merge_bootstrap_governance \
  tests.test_project_instructions_attestation_committed \
  tests.test_post_deployment_witness_contract -v
python3 scripts/residual_language_audit.py --check
python3 -m unittest tests.test_developer_documentation_language -v
```

- [ ] **Step 5: Commit**

Stage exactly the files listed above, run `git diff --cached --check`, then:

```bash
git commit -m "refactor: make AI interface provenance provider neutral"
```

---

### Task 5: Decouple provider account namespace from governance and package provenance

**Files:**
- Modify: `.github/governance/main-ruleset.json`
- Create: `scripts/governance_context_identity.py`
- Create: `tests/test_governance_context_identity.py`
- Modify: `scripts/verify_supply_chain_lock.py`
- Modify: `tests/test_supply_chain_lock.py`
- Modify: `tests/test_integration_code_language.py`
- Modify: `tests/test_post_merge_bootstrap_governance.py`
- Modify: `tests/test_workflow_contracts.py`
- Modify: `docs/BRANCH_GOVERNANCE.md`
- Modify: `docs/INTEGRATION_CODE_LANGUAGE_INVENTORY.md`
- Modify: `tests/test_phase2b_post_merge_ghcr_evidence.py`
- Modify: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json` to add neutral package/repository fields; Task 6 removes the legacy qualified provenance field.
- Modify: `tests/test_phase2c_evidence_contract.py`

**Interfaces:**
- Consumes: live required-check contexts, integration IDs, repository ID, workflow/job/artifact IDs, package digest.
- Produces: tracked neutral desired-state records that identify account-derived external checks by fingerprint/metadata instead of plaintext context.

- [ ] **Step 1: Define neutral external-check schema in RED tests**

For the account-derived required check, compute the fingerprint from authenticated live ruleset state and write only the digest into tracked governance:

```bash
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
gh api "repos/$repo/rulesets/21303100" > "$RUNNER_TEMP/live-main-ruleset.json"
python3 - <<'PYCODE'
import hashlib, json, os
from pathlib import Path
source = Path(os.environ["RUNNER_TEMP"]) / "live-main-ruleset.json"
payload = json.loads(source.read_text(encoding="utf-8"))
checks = next(
    rule["parameters"]["required_status_checks"]
    for rule in payload["rules"]
    if rule["type"] == "required_status_checks"
)
candidates = [
    item["context"] for item in checks
    if item.get("context", "").startswith("security/snyk (")
]
assert len(candidates) == 1
digest = hashlib.sha256(candidates[0].encode("utf-8")).hexdigest()
print(digest)
PYCODE
```

Insert that exact 64-hex digest into `context_fingerprint.digest` with `algorithm=sha256`, `case_sensitive=true`, and `provider_family=dependency-security`. The test must never store the plaintext input used to compute it.

- [ ] **Step 2: Write fingerprint verifier**

`scripts/governance_context_identity.py` must provide:

```python
def context_digest(value: str) -> str: ...
def match_expected_check(live: dict, expected: dict) -> bool: ...
```

Literal stable contexts continue using `context`; account-derived contexts use `context_fingerprint`.

- [ ] **Step 3: Run RED then GREEN**

```bash
python3 -m unittest \
  tests.test_governance_context_identity \
  tests.test_supply_chain_lock \
  tests.test_integration_code_language \
  tests.test_post_merge_bootstrap_governance \
  tests.test_workflow_contracts -v
```

- [ ] **Step 4: Neutralize package/repository evidence assertions**

Package evidence must assert fields separately:

```python
self.assertEqual(evidence["registry"], "ghcr.io")
self.assertEqual(evidence["package"], "omnigenis-genome")
self.assertRegex(evidence["digest"], r"^sha256:[0-9a-f]{64}$")
self.assertEqual(evidence["repository_id"], 1212760346)
```

Remove hard-coded provider-qualified image strings from tests/evidence contracts. Runtime workflows continue to use provider runtime variables.

- [ ] **Step 5: Commit**

```bash
git add .github/governance/main-ruleset.json scripts/governance_context_identity.py \
  scripts/verify_supply_chain_lock.py tests/test_governance_context_identity.py \
  tests/test_supply_chain_lock.py tests/test_integration_code_language.py \
  tests/test_post_merge_bootstrap_governance.py tests/test_workflow_contracts.py \
  docs/BRANCH_GOVERNANCE.md docs/INTEGRATION_CODE_LANGUAGE_INVENTORY.md \
  tests/test_phase2b_post_merge_ghcr_evidence.py tests/test_phase2c_evidence_contract.py
git commit -m "refactor: decouple provider account namespace"
```

---

### Task 6: Purge P1-P3 from all remaining tracked history, plans, specs, checkpoints, and evidence

**Files:**
- Modify: `docs/POLICY_CODE_LANGUAGE_INVENTORY.md`
- Modify: `docs/REPORTING_CODE_LANGUAGE_INVENTORY.md`
- Modify: `docs/SCIENTIFIC_CODE_LANGUAGE_INVENTORY.md`
- Modify: `docs/history/v3.3/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md`
- Modify: `docs/superpowers/checkpoints/2026-09-03-local-first-ci-session.md`
- Modify: `docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json`
- Modify: `docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json`
- Modify: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json`
- Modify: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json`
- Modify: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2c-runner-cutover.json`
- Modify: `docs/superpowers/plans/2026-09-05-four-plane-audit-static-dependency.md`
- Modify: `docs/superpowers/plans/2026-09-08-scientific-internals-english.md`
- Modify: `docs/superpowers/plans/2026-09-09-policy-evidence-audit-english.md`
- Modify: `docs/superpowers/plans/2026-09-09-reporting-english-locale.md`
- Modify: `docs/superpowers/plans/2026-09-10-omnigenis-phase2a-internal-identity-contract.md`
- Modify: `docs/superpowers/plans/2026-09-10-omnigenis-repository-identity-migration.md`
- Modify: `docs/superpowers/plans/2026-09-11-omnigenis-phase2b-runtime-build-identity-cutover.md`
- Modify: `docs/superpowers/plans/2026-09-11-omnigenis-phase2c-runner-identity-cutover.md`
- Modify: `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`
- Modify: `docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md`
- Modify: `docs/superpowers/specs/2026-09-05-draft-first-final-ci-design.md`
- Modify: `docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md`
- Modify: `docs/superpowers/specs/2026-09-10-omnigenis-phase2-internal-identity-migration-design.md`
- Modify: `docs/superpowers/specs/2026-09-10-omnigenis-repository-identity-migration-design.md`
- Modify: `tests/test_phase2b_evidence_contract.py`
- Modify: `tests/test_repository_identity_migration.py`
- Modify any additional path reported by `python3 scripts/zero_identity_guard.py --inventory-json` after Tasks 2-5.

**Interfaces:**
- Consumes: stable numeric IDs/digests and current evidence schemas.
- Produces: zero P1-P3 current-tree content without falsifying historical facts.

- [ ] **Step 1: Generate an inventory artifact outside Git**

```bash
python3 scripts/zero_identity_guard.py --inventory-json > "$RUNNER_TEMP/zero-identity-pre.json"
```

Use this only as an execution checklist. Do not commit matched plaintext or external temporary paths.

- [ ] **Step 2: Migrate historical source-control locators**

Replace owner-qualified URLs with structured factual records such as:

```text
repository_id=1212760346; run_id=31857676091; job_id=94945373740
```

For pull requests use `repository_id + pr_number + optional comment_id`. For artifacts use `repository_id + run_id + artifact_id`. Do not invent replacement URLs.

- [ ] **Step 3: Migrate runner historical names**

Historical evidence keeps runner IDs and a SHA-256 digest of the retired name if identity correlation is needed. It does not retain the plaintext retired name.

- [ ] **Step 4: Rewrite old migration commands**

Commands that previously embedded an owner-qualified repository path become runtime-derived:

```bash
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
gh api "repos/$repo/rulesets/21303100"
```

The command is historical documentation of the neutral method after migration; do not claim it was the literal command originally executed. Where exact historical command provenance matters, state that the command text was de-identified and preserve the run/commit IDs.

- [ ] **Step 5: Run inventory repeatedly until only deliberate in-progress files remain**

```bash
python3 scripts/zero_identity_guard.py --inventory-json
```

P4 must remain zero throughout.

- [ ] **Step 6: Run documentation/evidence contracts**

```bash
python3 -m unittest \
  tests.test_developer_documentation_language \
  tests.test_phase2b_evidence_contract \
  tests.test_phase2c_evidence_contract \
  tests.test_repository_identity_migration -v
python3 scripts/residual_language_audit.py --check
```

- [ ] **Step 7: Commit**

Stage exactly the migrated paths returned by the inventory plus the listed tests. Verify `git diff --cached --check`, then:

```bash
git commit -m "refactor: purge identity tokens from tracked history"
```

---

### Task 7: Integrate the zero-token guard and seal the current tree

**Files:**
- Modify: `scripts/validate_repo.py`
- Modify: `tests/test_repo_contract.py`
- Create: `docs/superpowers/evidence/2026-09-11-omnigenis-zero-identity-seal.json`
- Create: `tests/test_zero_identity_seal.py`

**Interfaces:**
- Consumes: Tasks 1-6 with current-tree zero inventory.
- Produces: official fail-closed repository gate and exact-head seal evidence.

- [ ] **Step 1: Write RED integration test**

Require `validate_repo.py` to import/call `validate_zero_identity(ROOT)` exactly once and require the policy/guard paths.

Add a mutation repository test that injects each P1-P4 class through hex fixtures into a tracked file and proves the official validator rejects it.

- [ ] **Step 2: Wire the guard into `validate_repo.py`**

The gate runs on every official repository validation. No allowlist or history bypass exists.

- [ ] **Step 3: Require zero path/blob inventory**

```bash
python3 scripts/zero_identity_guard.py --check
python3 scripts/zero_identity_guard.py --inventory-json
```

Expected final inventory:

```json
{"P1": 0, "P2": 0, "P3": 0, "P4": 0}
```

The actual schema may contain path/content subcounts, but every count must be zero.

- [ ] **Step 4: Stabilize implementation HEAD and run exact-head gates**

Run in the pinned project environment:

```bash
python3 scripts/zero_identity_guard.py --check
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 scripts/code_language_guard.py --check
python3 scripts/residual_language_audit.py --check
python3 -m unittest tests.test_developer_documentation_language -v
find scripts -type f -name '*.sh' -exec bash -n {} +
git diff --check
```

- [ ] **Step 5: Write exact-head evidence**

Evidence schema `omnigenis-zero-identity-seal-v1` must record:
- base SHA;
- implementation SHA/tree;
- policy SHA-256;
- repository ID;
- zero class counts;
- protected scientific/normative surface list as unchanged;
- exact commands, exit codes, and durable sanitized output digests;
- P1-P4 class IDs only, never plaintext matched values;
- post-merge runner operation as pending.

- [ ] **Step 6: Commit evidence-only and run full final regression**

The evidence-only commit changes only the seal JSON. Then run:

```bash
python3 -m unittest tests.test_zero_identity_seal -v
python3 scripts/zero_identity_guard.py --check
python3 scripts/validate_repo.py
python3 -m unittest discover -s tests -v
find scripts -type f -name '*.sh' -exec bash -n {} +
git diff --check
```

Record the actual test count from output.

- [ ] **Step 7: Negative seal mutation**

In a disposable worktree/repository, inject a P-class byte fixture into a tracked path and prove both the standalone guard and official validator fail. Restore/throw away only the disposable workspace.

---

### Task 8: Publish one governed PR and satisfy exact-head external review

**Files:**
- No new implementation files unless a verified reviewer finding requires correction.

**Interfaces:**
- Consumes: clean sealed branch from Task 7.
- Produces: one Ready-for-Review PR with exact-head external checks and zero unresolved threads.

- [ ] **Step 1: Verify final scope**

Confirm the diff does not change normative ruleset bytes, scientific thresholds, genomic calling behavior, report taxonomy, or consent semantics.

- [ ] **Step 2: Verify the tree has zero P1-P4 path/blob matches before push**

```bash
python3 scripts/zero_identity_guard.py --check
```

- [ ] **Step 3: Handle workflow-file transport safely**

If the local token cannot update workflows, use the already established connected-App bootstrap method: publish exact validated workflow blobs, compare remote blob SHAs, rebuild local history over the bootstrap, require tree-SHA identity, rerun exact-head validation, regenerate evidence, then push non-workflow commits.

- [ ] **Step 4: Open draft PR**

Title:

```text
refactor: seal OmniGenis zero identity tree
```

PR body must state P1-P4 zero counts, implementation/evidence SHAs, complete test count, protected-boundary results, and that runner re-registration is post-merge only.

- [ ] **Step 5: Mark Ready and run external checks**

Require applicable Actions, DeepSource analyzers, secret scanning, dependency/security scanning, Semgrep, automated review, zero unresolved threads, active rulesets, and `mergeStateStatus=CLEAN`.

For each finding: verify against current HEAD, return to draft for real code changes, use TDD, regenerate evidence if implementation changes, and rerun exact-head validation.

- [ ] **Step 6: Stop for explicit human merge**

Never auto-merge.

---

### Task 9: Post-merge operational runner continuity and neutral re-registration

**Files:**
- No repository file mutation is authorized by this task unless a separate evidence follow-up PR is explicitly approved.

**Interfaces:**
- Consumes: merged zero-identity PR, protected-main routing through `omnigenis-isolated`, live runner API.
- Produces: externally renamed runners `omnigenis-runner-01/02` with at least one runner online throughout.

- [ ] **Step 1: Verify protected-main canary from the Phase 2C merge**

Capture merge SHA, workflow run ID, job ID, selected runner ID/name, conclusion, and non-secret routing evidence. Do not remove rollback labels until a job was actually accepted and completed through `omnigenis-isolated`.

- [ ] **Step 2: Rerun Runtime/Resource Gate**

Determine actual container image/digest, creation command, mounts, network, registration mechanism, restart policy, and rollback. Do not infer from old sessions.

- [ ] **Step 3: Remove retired labels only after canary success**

Operate one runner at a time and verify the untouched runner remains online and idle/available.

- [ ] **Step 4: Re-register runner 01**

Leave runner 02 serving traffic. Drain runner 01, re-register as `omnigenis-runner-01` with canonical labels, verify online, and execute a controlled canary.

- [ ] **Step 5: Re-register runner 02**

Only after runner 01 canary passes, drain runner 02, re-register as `omnigenis-runner-02`, verify online, and execute a final pool canary.

- [ ] **Step 6: Verify external zero-personal identity state**

Runner names and canonical labels must be neutral. Repository tracked tree remains sealed by Task 7. Historical external provider records are not rewritten.

---

## Final Completion Gate

Before declaring the migration complete, all of the following must be true:

```text
tracked path P1 = 0
tracked path P2 = 0
tracked path P3 = 0
tracked path P4 = 0
tracked blob P1 = 0
tracked blob P2 = 0
tracked blob P3 = 0
tracked blob P4 = 0
```

Additionally:
- full root suite is green on exact final HEAD;
- official validator includes the zero-identity guard;
- canonical v3.4 ruleset bytes are unchanged;
- protected-main governance remains satisfiable;
- external runner continuity is proven before re-registration;
- no auto-merge occurred.
