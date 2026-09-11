# OmniGenis Phase 2B Runtime and Build Identity Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut repository-controlled runtime and build identities from Codework-derived names to the canonical OmniGenis identities without changing scientific behavior, runner identity, normative content, or historical provenance.

**Architecture:** Perform the cutover in one draft-first PR with multiple locally validated commits. Migrate runtime/container paths first, then MCP/NGS identities, then Codex/CodeRabbit identities, then contract the Phase 2A legacy ledger and seal the Phase 2B boundary. The protected-main runner label remains unchanged until Phase 2C, and old GHCR artifacts are never deleted or rewritten.

**Tech Stack:** Git, Python 3.12, unittest, Bash, GitHub Actions YAML, Dockerfile/Docker Compose, systemd templates, Node.js/TypeScript MCP package, npm lockfile, Conda YAML, Nextflow config, GitHub CLI/API.

**Spec:** `docs/superpowers/specs/2026-09-10-omnigenis-phase2-internal-identity-migration-design.md`

## Global Constraints

- Base Phase 2B on post-merge `main` commit `4c0e5222248b5f9f2537d627091b80afc9c9e120` or a later verified descendant if `main` moves before execution.
- Repository object must remain `drhudsonandrade/OmniGenis`, repository ID `1212760346`, visibility `public`, default branch `main`.
- Preserve canonical GENOMA v3.4 identity, sealed normative bytes, scientific thresholds, evidence semantics, report taxonomy, and genomic behavior.
- All new or modified code, tests, comments, docstrings, technical messages, configuration descriptions, and developer-facing documentation must be English-first.
- Do not rename `codework-isolated`, `codework-01`, `codework-02`, or the live runner names in Phase 2B; those belong exclusively to Phase 2C.
- Do not delete, rename, retag, or claim inspection of historical `codework-genome` GHCR artifacts without package-read evidence.
- Do not create compatibility symlinks for `/opt/codework` or `/etc/codework` unless a new Runtime/Resource Gate proves a live supported deployment still requires them.
- `OMNIGENIS_CODERABBIT_BIN_DIR` is canonical in 2B; `CODEWORK_CODERABBIT_BIN_DIR` may remain only as a deprecated fallback until 2D, and conflicting old/new values must fail closed.
- Historical repository URLs and the historical archive `codework-genome-runtime-2026-08-15.zip` remain truthful historical evidence and are not cosmetically rewritten.
- Development remains local-first/draft-first; do not mark the PR Ready until the exact final HEAD has passed the complete applicable local gate.
- Final merge remains explicit human action; no auto-merge.

---

## File Responsibility Map

- `config/project_identity.json`: canonical OmniGenis target names; read-only in Phase 2B.
- `config/legacy_identity_ledger.json`: monotonic migration ledger; Phase 2B entries contract to zero active locations.
- `scripts/project_identity_guard.py`: existing fail-closed identity scanner; behavior must not be weakened.
- `Dockerfile`, `.github/workflows/*`, `deploy/*`: runtime root, container/package/cache, GHCR, and deployment-template identity consumers.
- `mcp/package*.json`, `mcp/src/server.ts`, `mcp/test/*`, `mcp/README.md`: MCP package/server/runtime-test identities.
- `environment.yml`, `nextflow.config`, `scripts/generate_canary.py`: NGS environment, Nextflow manifest, and new synthetic-fixture identities.
- `.agents/plugins/*`, `scripts/codex/setup-coderabbit.sh`, `tests/test_coderabbit_guardrails.py`: Codex marketplace, plugin, lock schema, and temporary bin-dir compatibility.
- `docs/MAGALU_PRIVATE_MCP_SETUP.md`, `docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md`, `docs/PROJECT_IDENTITY_CONTRACT.md`: current operational documentation synchronized with each cutover.
- `docs/GITHUB_MOBILE_IMPORT.md` and historical language inventories: preserve historical archive/URL truth and the still-live Phase 2C runner label.
- `tests/test_phase2b_*`: Phase 2B behavior, boundary, seal, and evidence contracts.
- `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json`: exact-head pre-merge evidence; post-merge GHCR proof is a separate checkpoint before 2C.

---

### Task 1: Cut runtime, deployment-template, container, GHCR, and cache identity over

**Files:**
- Create: `tests/test_phase2b_runtime_build_identity.py`
- Read-only inputs: `config/project_identity.json`, `config/legacy_identity_ledger.json`

**Interfaces:**
- Consumes: canonical identity values from `config/project_identity.json`.
- Produces: tests that define the Phase 2B target while explicitly freezing runner identity for Phase 2C.

- [ ] **Step 1: Capture the Runtime/Resource Gate before any 2B mutation**

Run:

```bash
set -euo pipefail
printf 'HEAD=%s\n' "$(git rev-parse HEAD)"
for path in /opt/codework /opt/omnigenis /etc/codework /etc/omnigenis; do
  test -e "$path" && echo "PRESENT $path" || echo "ABSENT $path"
done
systemctl list-unit-files --type=service --no-legend 2>/dev/null \
  | grep -E 'genome-mcp|tunnel-client|omnigenis|codework' || true
printenv | grep -E '^(CODEWORK|OMNIGENIS)_' || true
gh api repos/drhudsonandrade/OmniGenis/actions/runners \
  --jq '.runners[] | [.id,.name,.status,.busy,([.labels[].name]|join(","))] | @tsv'
```

Expected: record actual observations. Do not mutate host resources. If a live `/opt/codework`, `/etc/codework`, Codework systemd service, or unsupported external deployment is discovered, stop and write a host-specific migration/rollback design before continuing.
- [ ] **Step 2: Write the RED boundary test**

Create `tests/test_phase2b_runtime_build_identity.py` with helpers that read tracked text files and load the canonical identity contract. The first test must assert the new runtime/build identities while freezing the runner boundary:

```python
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/project_identity.json").read_text(encoding="utf-8"))
LEGACY_WORD = "code" + "work"

class Phase2BRuntimeBuildIdentityTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_runtime_and_container_identity_are_canonical(self) -> None:
        runtime = IDENTITY["runtime"]
        self.assertIn(f"WORKDIR {runtime['root']}", self.read("Dockerfile"))
        scaffold = self.read(".github/workflows/scaffold-validation.yml")
        self.assertIn(runtime["container_package"], scaffold)
        self.assertIn(runtime["cache_namespace"], scaffold)
        self.assertNotIn("/opt/" + LEGACY_WORD, scaffold)
```

Add a second test that constructs the legacy runner label as `LEGACY_WORD + "-isolated"` so the test source does not create a new active legacy occurrence. Assert that derived legacy label remains present and `IDENTITY["runners"]["pool_label"]` remains absent from the three private-runner workflows during 2B.
- [ ] **Step 3: Convert the old Phase 1 preservation test into a Phase 2B migration test**

In `tests/test_repository_identity_migration.py`, replace `test_phase_two_internal_contracts_are_unchanged` with explicit 2B expectations:

```python
def test_phase_two_b_runtime_contract_uses_omnigenis(self) -> None:
    self.assertIn("WORKDIR /opt/omnigenis", self.read("Dockerfile"))

def test_phase_two_c_runner_contract_is_not_started(self) -> None:
    for path in (
        ".github/workflows/genoma-audit.yml",
        ".github/workflows/genoma-policy-engine.yml",
        ".github/workflows/scaffold-validation.yml",
    ):
        text = self.read(path)
        self.assertIn("codework-isolated", text)
        self.assertNotIn("omnigenis-isolated", text)
```

- [ ] **Step 4: Run the new tests and verify RED**

Run:

```bash
python3 -m unittest \
  tests.test_phase2b_runtime_build_identity \
  tests.test_repository_identity_migration -v
```

Expected: FAIL only because active runtime/build identities still use the old names. Runner-boundary assertions must already PASS.
- [ ] **Step 5: Implement the runtime-root, deployment-template, container, GHCR, and cache cutover**

Modify only these runtime/build surfaces in this step:

```text
Dockerfile
.github/workflows/genoma-ngs-runtime-gate.yml
.github/workflows/genoma-snp-array.yml
.github/workflows/scaffold-validation.yml
deploy/docker-compose.yml
deploy/genome-mcp.service
deploy/tunnel-client.service.example
scripts/validate_repo.py
mcp/test/payloadContracts.test.ts
mcp/test/server.test.ts
tests/test_workflow_contracts.py
tests/test_ci_optimization_contract.py
```

Apply the canonical values from `config/project_identity.json`: `/opt/omnigenis`, `/etc/omnigenis`, `/var/lib/omnigenis-tunnel`, `omnigenis-genome`, `omnigenis-genome-scaffold-v2`, and tunnel profile `omnigenis-genome`. Do not alter any `runs-on` expression or runner label.

In `.github/workflows/scaffold-validation.yml`, the publication block must become:

```yaml
tags: ghcr.io/${{ github.repository_owner }}/omnigenis-genome:${{ github.sha }}
cache-from: type=gha,scope=omnigenis-genome-scaffold-v2
cache-to: type=gha,mode=min,scope=omnigenis-genome-scaffold-v2,ignore-error=true
```

The immutable reference output must print `ghcr.io/%s/omnigenis-genome@%s`.
- [ ] **Step 6: Update the current operational runtime documentation in the same commit**

Modify:

```text
docs/MAGALU_PRIVATE_MCP_SETUP.md
docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md
```

Replace current operational `/opt/codework`, `/etc/codework`, `/var/lib/codework-tunnel`, `codework-genome`, and tunnel profile references with their canonical OmniGenis values. Preserve `codework-isolated` wherever it describes the still-live Phase 2C runner boundary.

Do not rewrite the historical archive reference in `docs/GITHUB_MOBILE_IMPORT.md` and do not rewrite old GitHub PR URLs in language-inventory evidence.

- [ ] **Step 7: Verify the runtime/build GREEN state**

Run:

```bash
python3 -m unittest \
  tests.test_phase2b_runtime_build_identity \
  tests.test_repository_identity_migration \
  tests.test_workflow_contracts \
  tests.test_ci_optimization_contract -v
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
bash -n scripts/*.sh
git diff --check
```

Expected: all PASS. The identity guard may still report reviewed legacy entries belonging to later 2B tasks, the CodeRabbit compatibility alias for 2D, runner identities for 2C, and historical evidence, but it must report no unclassified or over-budget occurrence.

- [ ] **Step 8: Commit the runtime/build cutover**

```bash
git add Dockerfile .github/workflows deploy docs/MAGALU_PRIVATE_MCP_SETUP.md \
  docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md scripts/validate_repo.py mcp/test \
  tests/test_phase2b_runtime_build_identity.py tests/test_repository_identity_migration.py \
  tests/test_workflow_contracts.py tests/test_ci_optimization_contract.py
git diff --cached --check
git commit -m "refactor: cut OmniGenis runtime and container identity over"
```
### Task 2: Cut MCP, NGS, Nextflow, synthetic-canary, and test-temp identities over

**Files:**
- Create: `tests/test_phase2b_mcp_ngs_identity.py`
- Modify: `mcp/package.json`
- Modify: `mcp/package-lock.json`
- Modify: `mcp/src/server.ts`
- Modify: `mcp/README.md`
- Modify: `mcp/test/core.test.ts`
- Modify: `mcp/test/server.test.ts`
- Modify: `environment.yml`
- Modify: `nextflow.config`
- Modify: `scripts/generate_canary.py`
- Modify: `tests/test_repository_identity_migration.py`

**Interfaces:**
- Consumes: `mcp.identity`, `ngs.conda_environment`, `ngs.nextflow_manifest`, `ngs.synthetic_fixture`, and `testing.temp_prefix_namespace` from `config/project_identity.json`.
- Produces: canonical OmniGenis MCP package/server identity, NGS environment identity, Nextflow manifest identity, new canary fixture identity, and canonical temp prefixes.

- [ ] **Step 1: Write RED tests for MCP and NGS identity**

Create `tests/test_phase2b_mcp_ngs_identity.py`:

```python
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = json.loads((ROOT / "config/project_identity.json").read_text(encoding="utf-8"))
LEGACY_WORD = "code" + "work"

class Phase2BMcpNgsIdentityTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_mcp_package_and_server_use_canonical_identity(self) -> None:
        expected = IDENTITY["mcp"]["identity"]
        package = json.loads(self.read("mcp/package.json"))
        lock = json.loads(self.read("mcp/package-lock.json"))
        self.assertEqual(package["name"], expected)
        self.assertEqual(lock["name"], expected)
        self.assertEqual(lock["packages"][""]["name"], expected)
        self.assertIn(expected, self.read("mcp/src/server.ts"))
```
Add these tests in the same class:

```python
    def test_ngs_and_canary_identities_are_canonical(self) -> None:
        ngs = IDENTITY["ngs"]
        self.assertIn(f"name: {ngs['conda_environment']}", self.read("environment.yml"))
        self.assertIn(f"name = '{ngs['nextflow_manifest']}'", self.read("nextflow.config"))
        self.assertIn(f'"fixture": "{ngs["synthetic_fixture"]}"', self.read("scripts/generate_canary.py"))

    def test_active_mcp_tests_use_canonical_temp_prefixes(self) -> None:
        for path in ("mcp/test/core.test.ts", "mcp/test/server.test.ts"):
            text = self.read(path)
            self.assertNotRegex(text, rf"{LEGACY_WORD}-(audit|server|claim|lock|release|budget|timeout|reaped|exit)")
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_phase2b_mcp_ngs_identity -v
```

Expected: FAIL on the current old MCP, NGS, Nextflow, fixture, and temp-prefix identities.

- [ ] **Step 3: Implement the canonical MCP/NGS identity values**

Apply:

```text
codework-genome-mcp            -> omnigenis-genome-mcp
codework-private-genome        -> omnigenis-genome-mcp
codework-ngs                   -> omnigenis-ngs
codework/genome-runtime        -> omnigenis/genome-runtime
codework-synthetic-germline-v1 -> omnigenis-synthetic-germline-v2
codework-<test-temp-prefix>     -> omnigenis-<same-purpose-prefix>
```

Do not rewrite historical evidence that truthfully records the v1 synthetic fixture.
Update the package lock with npm rather than manually editing dependency versions:

```bash
cd mcp
npm install --package-lock-only --ignore-scripts
cd ..
```

The dependency graph and resolved versions must remain unchanged; only package identity metadata may change because of this rename.

In `mcp/src/server.ts`, both the MCP server registration name and listening message become `omnigenis-genome-mcp`. Update the top-level `mcp/README.md` heading and current operational prose to OmniGenis.

- [ ] **Step 4: Run the MCP/NGS GREEN gates**

```bash
python3 -m unittest tests.test_phase2b_mcp_ngs_identity -v
cd mcp
npm ci --ignore-scripts
npm test
npm run build
cd ..
python3 scripts/generate_canary.py --help >/dev/null
python3 scripts/project_identity_guard.py --check
git diff --check
```

Expected: all PASS. `npm ci` must not rewrite the lockfile after the committed package-lock update.

- [ ] **Step 5: Commit the MCP/NGS identity cutover**

```bash
git add mcp environment.yml nextflow.config scripts/generate_canary.py \
  tests/test_phase2b_mcp_ngs_identity.py
git diff --cached --check
git commit -m "refactor: cut OmniGenis MCP and NGS identity over"
```

---
### Task 3: Cut Codex marketplace, CodeRabbit plugin, lock schema, and bin-dir identity over

**Files:**
- Modify: `.agents/plugins/marketplace.json`
- Modify: `.agents/plugins/coderabbit-cli-checksums.json`
- Modify: `scripts/codex/setup-coderabbit.sh`
- Modify: `tests/test_coderabbit_guardrails.py`

**Interfaces:**
- Consumes: `codex.marketplace`, `codex.plugin`, `codex.bin_dir_env`, and `codex.lock_schema` from `config/project_identity.json`.
- Produces: canonical OmniGenis Codex/CodeRabbit identities plus one deprecated old bin-dir environment-variable fallback retained only through Phase 2D.

- [ ] **Step 1: Write RED tests for canonical names and compatibility behavior**

Update `tests/test_coderabbit_guardrails.py` so marketplace/plugin/lock expectations use:

```python
CANONICAL_MARKETPLACE = "omnigenis-codex"
CANONICAL_PLUGIN = "coderabbit@omnigenis-codex"
CANONICAL_LOCK_SCHEMA = "omnigenis-coderabbit-cli-release-lock-v2"
CANONICAL_BIN_ENV = "OMNIGENIS_CODERABBIT_BIN_DIR"
LEGACY_BIN_ENV = "CODE" + "WORK_CODERABBIT_BIN_DIR"
```

Add tests proving canonical-only, fallback-only, same-value dual configuration, and conflicting dual configuration. The conflict test must require exit code `2` and a clear error message rather than silently choosing one value.
Use an isolated fake-home/fake-bin fixture so the tests never install or authenticate the real CLI. The compatibility assertions should resemble:

```python
def test_conflicting_bin_dir_variables_fail_closed(self) -> None:
    env = self.base_env()
    env[CANONICAL_BIN_ENV] = "/tmp/omnigenis-a"
    env[LEGACY_BIN_ENV] = "/tmp/omnigenis-b"
    result = self.run_setup(env)
    self.assertEqual(result.returncode, 2)
    self.assertIn("conflicting CodeRabbit bin directory variables", result.stderr)
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_coderabbit_guardrails -v
```

Expected: FAIL because marketplace/plugin/lock identities are still Codework-derived and the canonical/fallback/conflict behavior is not implemented.

- [ ] **Step 3: Implement the fail-closed environment-variable transition**

Immediately after the `fail()` function definition in `scripts/codex/setup-coderabbit.sh`, replace direct legacy-variable selection with:

```bash
canonical_bin_dir="${OMNIGENIS_CODERABBIT_BIN_DIR:-}"
legacy_bin_dir="${CODEWORK_CODERABBIT_BIN_DIR:-}"
if [[ -n "$canonical_bin_dir" && -n "$legacy_bin_dir" && "$canonical_bin_dir" != "$legacy_bin_dir" ]]; then
  fail "conflicting CodeRabbit bin directory variables"
fi
if [[ -n "$canonical_bin_dir" ]]; then
  INSTALL_BIN_DIR="$canonical_bin_dir"
elif [[ -n "$legacy_bin_dir" ]]; then
  INSTALL_BIN_DIR="$legacy_bin_dir"
  echo "WARNING: CODEWORK_CODERABBIT_BIN_DIR is deprecated; use OMNIGENIS_CODERABBIT_BIN_DIR." >&2
else
  INSTALL_BIN_DIR="$HOME/.local/bin"
fi
```

Keep exactly one active old environment-variable reference in the setup script for the 2B compatibility fallback; tests should construct its name dynamically so the ledger count does not increase.
- [ ] **Step 4: Replace the Codex/CodeRabbit canonical identities**

Apply these exact canonical values without changing the pinned CodeRabbit version, release URL template, platform checksums, or plugin source SHA:

```text
codework-codex                            -> omnigenis-codex
coderabbit@codework-codex                -> coderabbit@omnigenis-codex
codework-coderabbit-cli-release-lock-v1  -> omnigenis-coderabbit-cli-release-lock-v2
Codework Codex Plugins                   -> OmniGenis Codex Plugins
```

All `codex plugin list`, `codex plugin add`, marketplace verification predicates, and final provenance checks must use the new marketplace/plugin identity.

- [ ] **Step 5: Run GREEN without claiming live Codex state**

```bash
python3 -m unittest tests.test_coderabbit_guardrails -v
python3 scripts/project_identity_guard.py --check
bash -n scripts/codex/setup-coderabbit.sh
git diff --check
```

Expected: PASS using the existing mocked CLI fixtures. If the real `codex` CLI remains unavailable on the host, record live marketplace/plugin state as `NOT AVAILABLE`; do not install Codex or invent external state in Phase 2B.

- [ ] **Step 6: Commit the Codex/CodeRabbit cutover**

```bash
git add .agents/plugins scripts/codex/setup-coderabbit.sh \
  tests/test_coderabbit_guardrails.py
git diff --cached --check
git commit -m "refactor: cut OmniGenis Codex plugin identity over"
```

---
### Task 4: Contract the legacy ledger and seal the Phase 2B active-identity boundary

**Files:**
- Create: `tests/test_phase2b_legacy_seal.py`
- Modify: `config/legacy_identity_ledger.json`
- Modify: `docs/PROJECT_IDENTITY_CONTRACT.md`
- Modify: `docs/GITHUB_MOBILE_IMPORT.md` only if current operational prose needs clarification; preserve its historical archive filename and Phase 2C runner label.

**Interfaces:**
- Consumes: `scan_legacy_identities(root, ledger)` from `scripts/project_identity_guard.py`.
- Produces: zero active counts for every ledger entry whose `retire_by` is `2B`, while leaving only explicitly later/historical identities.

- [ ] **Step 1: Write the RED Phase 2B seal test**

Create `tests/test_phase2b_legacy_seal.py`:

```python
from pathlib import Path
import json
import unittest

from scripts.project_identity_guard import scan_legacy_identities

ROOT = Path(__file__).resolve().parents[1]

class Phase2BLegacySealTest(unittest.TestCase):
    def test_every_phase_two_b_identity_is_retired_from_active_content(self) -> None:
        ledger = json.loads((ROOT / "config/legacy_identity_ledger.json").read_text(encoding="utf-8"))
        report = scan_legacy_identities(ROOT, ledger)
        self.assertEqual(report["unclassified"], [])
        self.assertEqual(report["over_budget"], [])
        phase2b_entries = [entry for entry in ledger["entries"] if entry.get("retire_by") == "2B"]
        self.assertTrue(phase2b_entries)
        for entry in phase2b_entries:
            self.assertEqual(entry["locations"], {}, entry["id"])
        phase2b_ids = {entry["id"] for entry in phase2b_entries}
        observed = report["counts"]
        self.assertEqual({key for key in observed if key in phase2b_ids}, set())
```

Add a second test asserting that remaining active legacy IDs are a subset of `runner-pool`, `ci-test-function-name`, `coderabbit-bin-env`, `historical-runtime-zip`, `repository-old-full-name-test`, and `historical-repository-pr-urls`.
- [ ] **Step 2: Run RED before ledger contraction**

```bash
python3 -m unittest tests.test_phase2b_legacy_seal -v
```

Expected: FAIL because the reviewed Phase 2A ledger still reports active `retire_by=2B` occurrences.

- [ ] **Step 3: Reconcile the ledger from the repository, not by manual guess**

Run the inventory after Tasks 1-3 are GREEN:

```bash
python3 scripts/project_identity_guard.py --inventory \
  > /tmp/omnigenis-phase2b-legacy-inventory.json
python3 -m json.tool /tmp/omnigenis-phase2b-legacy-inventory.json >/dev/null
```

Update `config/legacy_identity_ledger.json` so every `retire_by: "2B"` entry has an empty `locations` object. For later/historical entries, reduce location budgets to the exact observed tracked-file counts; never increase a budget to silence a new occurrence.

The exact Phase 2B retirement set is:

```text
runtime-root
config-root
container-package
cache-namespace
mcp-package
mcp-server
conda-environment
nextflow-manifest
codex-marketplace
coderabbit-plugin
synthetic-fixture
runtime-state-dir
coderabbit-lock-schema
mcp-test-temp-prefixes
product-word-active
```

The expected surviving categories are:

```text
runner-pool                    -> Phase 2C
ci-test-function-name          -> Phase 2C
coderabbit-bin-env             -> deprecated fallback through Phase 2D
historical-runtime-zip         -> preserved historical evidence
repository-old-full-name-test  -> redirect/history validation until Phase 2D
historical-repository-pr-urls  -> preserved historical evidence
```

- [ ] **Step 4: Update the project identity documentation**

In `docs/PROJECT_IDENTITY_CONTRACT.md`, record that Phase 2B retires repository-controlled runtime/build identities while runner identity remains intentionally on the Phase 2C compatibility boundary and the legacy CodeRabbit bin-dir variable remains a deprecated 2D fallback.

Do not claim live GHCR package history was inspected if `read:packages` is still unavailable.
- [ ] **Step 5: Run the Phase 2B seal GREEN gates**

```bash
python3 -m unittest \
  tests.test_phase2b_legacy_seal \
  tests.test_phase2b_runtime_build_identity \
  tests.test_phase2b_mcp_ngs_identity \
  tests.test_repository_identity_migration -v
python3 scripts/project_identity_guard.py --check
python3 scripts/project_identity_guard.py --inventory \
  > /tmp/omnigenis-phase2b-final-inventory.json
python3 - <<'PY'
import json
from pathlib import Path
report=json.loads(Path('/tmp/omnigenis-phase2b-final-inventory.json').read_text())
assert report['unclassified'] == []
assert report['over_budget'] == []
PY
python3 scripts/validate_repo.py
git diff --check
```

Expected: PASS; no `retire_by=2B` identity remains in active tracked content.

- [ ] **Step 6: Commit the ledger seal**

```bash
git add config/legacy_identity_ledger.json docs/PROJECT_IDENTITY_CONTRACT.md \
  docs/GITHUB_MOBILE_IMPORT.md tests/test_phase2b_legacy_seal.py
git diff --cached --check
git commit -m "test: seal OmniGenis Phase 2B legacy boundary"
```

---
### Task 5: Build exact-head Phase 2B evidence and run the complete local gate

**Files:**
- Create: `tests/test_phase2b_evidence_contract.py`
- Create: `docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json`

**Interfaces:**
- Consumes: the exact implementation HEAD after Tasks 1-4, canonical identity contract, final legacy inventory, Phase 2A evidence, and validation logs.
- Produces: reproducible pre-merge evidence for the Phase 2B PR. Real protected-main GHCR publication remains explicitly pending until human merge.

- [ ] **Step 1: Write the RED evidence-contract test**

Require schema `omnigenis-phase2b-runtime-build-evidence-v1` and these top-level fields:

```text
base_sha
implementation_head_sha
implementation_tree_sha
project_identity_sha256
legacy_ledger_sha256
legacy_scan
runtime_resource_gate
external_capabilities
ghcr_premerge_state
changed_paths
protected_boundaries
validation_provenance
post_evidence_validation
post_merge_requirements
```

The test must require `ghcr_premerge_state.status == "PENDING_AFTER_HUMAN_MERGE"` rather than allowing a pre-merge success claim, and must require runner names/labels under `protected_boundaries` to be unchanged from the 2A baseline.

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests.test_phase2b_evidence_contract -v
```

Expected: FAIL because the evidence artifact does not exist yet.
- [ ] **Step 3: Commit the evidence-contract test to stabilize the implementation HEAD**

```bash
git add tests/test_phase2b_evidence_contract.py
git diff --cached --check
git commit -m "test: define OmniGenis Phase 2B evidence contract"
```

No implementation commit may be created after the evidence-bearing validation cycle begins. The final evidence-contract test must fail if the evidence artifact is missing. During the bootstrap pre-evidence cycle, run the complete functional suite while explicitly excluding only `tests.test_phase2b_evidence_contract`; generate and commit the evidence next, then run the complete root suite including the evidence contract on the final evidence HEAD before PR readiness.

- [ ] **Step 4: Execute one fail-fast validation cycle on the exact implementation HEAD**

Run under the pinned project environment and capture one log per gate:

```bash
set -euo pipefail
VENV=/tmp/codework-ci-artifact-opt-venv
export PATH="$VENV/bin:$PATH"
LOG_ROOT=/tmp/omnigenis-phase2b-validation
rm -rf "$LOG_ROOT"
mkdir -p "$LOG_ROOT"
IMPLEMENTATION_HEAD="$(git rev-parse HEAD)"

run_gate() {
  local name="$1"; shift
  set +e
  "$@" >"$LOG_ROOT/$name.log" 2>&1
  rc=$?
  set -e
  printf '%s\n' "$rc" >"$LOG_ROOT/$name.exit"
  test "$rc" -eq 0
}

run_gate identity_guard python3 scripts/project_identity_guard.py --check
run_gate validate_repo python3 scripts/validate_repo.py
run_gate supply_chain python3 scripts/verify_supply_chain_lock.py
run_gate code_language python3 scripts/code_language_guard.py --check
run_gate residual_language python3 scripts/residual_language_audit.py --check
run_gate docs_language python3 -m unittest tests.test_developer_documentation_language -v
run_gate phase2b_tests python3 -m unittest \
  tests.test_phase2b_runtime_build_identity tests.test_phase2b_mcp_ngs_identity \
  tests.test_phase2b_legacy_seal -v
```

Then run `find scripts -type f -name '*.sh' -exec bash -n {} +` and `git diff --check` as additional fail-closed gates. Do **not** run `tests.test_phase2b_evidence_contract` or the complete root suite before the evidence artifact exists. The committed evidence records only commands that were actually executable and reproducible at the implementation HEAD; the raw complete root suite is a mandatory post-evidence gate.
- [ ] **Step 5: Capture non-secret external capability state**

Run without printing tokens or environment secrets:

```bash
set +e
gh api /user/packages/container/codework-genome/versions --paginate >/tmp/phase2b-old-package.json 2>/tmp/phase2b-old-package.err
old_package_rc=$?
gh api /user/packages/container/omnigenis-genome/versions --paginate >/tmp/phase2b-new-package.json 2>/tmp/phase2b-new-package.err
new_package_rc=$?
set -e
printf 'OLD_PACKAGE_READ_EXIT=%s\nNEW_PACKAGE_READ_EXIT=%s\n' "$old_package_rc" "$new_package_rc"
command -v codex >/dev/null 2>&1 && echo 'CODEX_CLI=AVAILABLE' || echo 'CODEX_CLI=NOT_AVAILABLE'
```

If package read remains forbidden, evidence must say `NOT_AVAILABLE` and include only exit status/error class, not credentials. If `codex` is absent, live marketplace/plugin state remains `NOT_AVAILABLE`.

- [ ] **Step 6: Generate evidence from the verified logs**

The evidence generator must hash `config/project_identity.json`, `config/legacy_identity_ledger.json`, every validation log, and the inline summaries it stores. It must record the exact implementation commit/tree and changed paths from the verified base SHA.

Use this structure:

```json
{
  "schema": "omnigenis-phase2b-runtime-build-evidence-v1",
  "base_sha": "4c0e5222248b5f9f2537d627091b80afc9c9e120",
  "implementation_head_sha": implementation_head,
  "implementation_tree_sha": implementation_tree,
  "ghcr_premerge_state": {
    "status": "PENDING_AFTER_HUMAN_MERGE",
    "expected_package": "omnigenis-genome",
    "old_package_action": "PRESERVE"
  },
  "protected_boundaries": {
    "runner_cutover": "NOT_STARTED_PHASE_2C",
    "scientific_surface_changes": [],
    "normative_surface_changes": []
  },
  "post_evidence_validation": {
    "status": "REQUIRED_AFTER_EVIDENCE_COMMIT",
    "commands": [
      "python -m unittest tests.test_phase2b_evidence_contract -v",
      "python -m unittest discover -s tests -v",
      "find scripts -type f -name '*.sh' -exec bash -n {} +",
      "git diff --check"
    ]
  }
}
```

Do not put placeholder angle-bracket values into the committed artifact; the generator must substitute actual hashes/SHAs before writing it.
- [ ] **Step 7: Validate the generated artifact before commit**

Before committing the evidence, validate only properties that can truthfully be proven at the implementation HEAD:

```bash
python3 -m json.tool \
  docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json \
  >/dev/null
python3 scripts/project_identity_guard.py --check
git diff --check
```

The artifact must contain only executable/reproducible pre-evidence commands in `validation_provenance`. It must not claim a pre-evidence `root_suite` result or depend on an unversioned `/tmp` runner. `post_evidence_validation` must explicitly require the evidence-contract test and raw complete root suite after the evidence-only commit exists.

- [ ] **Step 8: Commit the implementation evidence separately**

Commit only the evidence artifact:

```bash
git add docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json
git diff --cached --check
git commit -m "docs: record OmniGenis Phase 2B evidence"
```

The final evidence-contract test resolves `implementation_head_sha` as a commit, compares its tree with `implementation_tree_sha`, requires `HEAD^` to equal that implementation commit, and requires the evidence commit to change only the evidence JSON.

- [ ] **Step 9: Execute the final post-evidence gate**

Run the raw final commands named by `post_evidence_validation` on the evidence HEAD:

```bash
python3 -m unittest tests.test_phase2b_evidence_contract -v
python3 -m unittest discover -s tests -v
find scripts -type f -name '*.sh' -exec bash -n {} +
git diff --check
```

Also rerun the identity guard, repository validator, supply-chain gate, code-language gate, residual-language audit, and developer-documentation-language tests. Record the exact root-suite count in the PR body from this final run; do not backfill that result into the pre-evidence artifact. The final worktree must be clean.

---
### Task 6: Publish one governed draft PR and satisfy exact-head external review

**Files:**
- No additional implementation files unless a reviewer finding requires a verified correction.

**Interfaces:**
- Consumes: clean final Phase 2B branch and evidence from Task 5.
- Produces: one reviewed Phase 2B PR ready for explicit human merge.

- [ ] **Step 1: Verify the exact changed-file allowlist before push**

The PR may change only repository-controlled runtime/build/MCP/NGS/Codex identities, their tests/docs, the legacy ledger, the Phase 2B plan, and Phase 2B evidence. It must not modify canonical normative files, scientific-policy/data files, runner registration resources, or secrets.

Run:

```bash
git diff --name-only origin/main...HEAD | sort
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
git diff --check
```

Explicitly inspect `.github/workflows/genoma-audit.yml`, `.github/workflows/genoma-policy-engine.yml`, and `.github/workflows/scaffold-validation.yml` to prove the trusted-runner selector still uses `codework-isolated` and has not moved to `omnigenis-isolated`.

- [ ] **Step 2: Check the Git transport capability before pushing workflow changes**

Run `gh auth status` without printing any token. If the current CLI credential still lacks the `workflow` scope and the branch changes workflow files, do not force-push, remove the workflow diff, or weaken the plan.

Use the already authorized GitHub App path to create the exact workflow-file commit on the target branch, then replay/rebase the non-workflow commits onto that remote commit and compare tree SHAs before a fresh exact-head validation cycle. Alternatively, stop for explicit user re-authentication with workflow scope. Never bypass GitHub's workflow-file permission check.
- [ ] **Step 3: Push and open one draft PR**

```bash
git push -u origin feat/omnigenis-phase2b-runtime-build-identity
gh pr create --draft --base main --head feat/omnigenis-phase2b-runtime-build-identity \
  --title "refactor: cut OmniGenis runtime and build identity over" \
  --body-file /tmp/omnigenis-phase2b-pr-body.md
```

The body must report the verified base SHA, evidence-bound implementation SHA, final PR SHA, exact test count, zero active `retire_by=2B` identities, runner cutover not started, GHCR pre-merge state pending, and any unavailable external capability honestly.

- [ ] **Step 4: Mark Ready only after the remote HEAD equals the locally validated HEAD**

Verify local and remote SHA equality, then mark Ready. Required checks/reviewers include the repository's current ruleset contexts, including `static`, `container-canary`, `Canonical policy + 263-rule contract`, CodeRabbit, GitGuardian, all configured DeepSource analyzers, Snyk, and Semgrep. Scope-skipped checks are acceptable only when the workflow/ruleset reports them as non-blocking for this exact diff.

- [ ] **Step 5: Treat every actionable reviewer finding as a new TDD cycle**

For each still-valid finding: convert PR to draft, write or tighten a failing test where behavior is involved, observe RED, implement the minimum fix, run focused GREEN, rerun the complete exact-head gate, refresh evidence if the implementation HEAD changes, push one coherent corrective block, respond to the thread with the exact SHA/evidence, and return Ready.

Do not dismiss a current review to make the PR mergeable. A stale `CHANGES_REQUESTED` review may be dismissed only after every finding it contained has been independently verified as addressed and all associated threads are resolved.

- [ ] **Step 6: Stop at the manual-merge boundary**

Declare `ready for manual merge` only when the PR is `CLEAN/MERGEABLE`, all required checks are satisfied on the final SHA, review decision has no blocker, and unresolved review threads equal zero. Do not merge automatically.

---
### Task 7: Perform the post-merge Phase 2B gate before Phase 2C

**Files:**
- Create after human merge on the next planning branch: `docs/superpowers/checkpoints/2026-09-11-omnigenis-phase2b-postmerge.json`

**Interfaces:**
- Consumes: human-merged Phase 2B `main` SHA and protected-main GitHub Actions results.
- Produces: a post-merge checkpoint proving repository continuity, runtime identity enforcement, and real `omnigenis-genome` publication before any runner mutation begins.

- [ ] **Step 1: Confirm the human merge and verify clean `main`**

```bash
git fetch origin --prune
MERGE_SHA="$(git rev-parse origin/main)"
echo "MERGE_SHA=$MERGE_SHA"
git worktree add --detach .worktrees/phase2b-postmerge-verify origin/main
cd .worktrees/phase2b-postmerge-verify
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
/tmp/codework-ci-artifact-opt-venv/bin/python -m unittest discover -s tests -v
```

Expected: complete post-merge regression PASS and no active Phase 2B legacy identity reappears.

- [ ] **Step 2: Revalidate repository identity and complete ruleset semantics**

Confirm repository ID `1212760346`, full name `drhudsonandrade/OmniGenis`, public visibility, default branch `main`, and exact semantic equality of rulesets `21303100` and `22347095` against the pinned Phase 1/2A evidence. Any semantic drift blocks Phase 2C.
- [ ] **Step 3: Prove real protected-main publication of the new GHCR identity**

Locate the `scaffold-validation` run for the exact merge SHA:

```bash
RUN_ID="$(gh run list --workflow scaffold-validation.yml --branch main \
  --commit "$MERGE_SHA" --json databaseId,headSha,conclusion \
  --jq '[.[] | select(.headSha == env.MERGE_SHA and .conclusion == "success")][0].databaseId')"
test -n "$RUN_ID" && test "$RUN_ID" != "null"
rm -rf /tmp/omnigenis-phase2b-ghcr
mkdir -p /tmp/omnigenis-phase2b-ghcr
gh run download "$RUN_ID" \
  --name "ghcr-image-reference-${MERGE_SHA}" \
  --dir /tmp/omnigenis-phase2b-ghcr
cat /tmp/omnigenis-phase2b-ghcr/ghcr-image-reference.txt
```

Validate the artifact with:

```bash
python3 - <<'PY'
import re
from pathlib import Path
value=Path('/tmp/omnigenis-phase2b-ghcr/ghcr-image-reference.txt').read_text().strip()
assert re.fullmatch(r'ghcr\.io/[^/]+/omnigenis-genome@sha256:[0-9a-f]{64}', value), value
print('PHASE2B_GHCR_PUBLICATION=PASS')
PY
```

This protected-main artifact is the required proof of new package publication. It does not prove historical package deletion or package-list visibility.

- [ ] **Step 4: Verify the runner boundary remained untouched**

Query repository runners and require both existing runner names to remain online with their legacy Phase 2C labels. No runner name, label, registration, or container may have been changed by Phase 2B.

- [ ] **Step 5: Record the post-merge checkpoint before 2C planning**

The checkpoint JSON must record merge SHA, repository ID, normalized ruleset digests, identity/ledger hashes, root-suite result, GHCR run ID, immutable `omnigenis-genome@sha256:...` reference, runner snapshot, and unavailable capabilities. Do not include credentials or tokens.

Phase 2C planning may begin only after this checkpoint is complete and the temporary verification worktree is cleanly removed.

---