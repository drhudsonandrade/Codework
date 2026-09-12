# OmniGenis Phase 2A Internal Identity Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a canonical OmniGenis internal-identity contract and a fail-closed, monotonic legacy-identity ledger without changing runtime, runner, container, workflow-routing, scientific, or normative behavior.

**Architecture:** Phase 2A adds a versioned identity registry under `config/`, a separate machine-readable ledger for active Codework-derived compatibility occurrences, and a focused Python guard that validates both structures and scans tracked/unignored repository text. `scripts/validate_repo.py` invokes the guard so unclassified legacy identities or increases above the reviewed baseline fail the official repository gate. Runtime literals remain unchanged until Phase 2B.

**Tech Stack:** Python 3.12 standard library, JSON, `unittest`, Git, existing `scripts/validate_repo.py`, existing English-first and residual-language guards.

**Spec:** `docs/superpowers/specs/2026-09-10-omnigenis-phase2-internal-identity-migration-design.md`

## Global Constraints

- Phase 2A MUST NOT modify runtime behavior, runner metadata, GitHub Actions routing semantics, Docker image names, GHCR publication, MCP runtime identity, Conda identity, Nextflow identity, filesystem deployment paths, or external resources. The only workflow-file change allowed is adding `scripts/project_identity_guard.py` to the existing NGS runtime-gate `pull_request` and `push` path filters so dependency-closure validation remains complete.
- Repository ID remains `1212760346`; canonical repository identity remains the owner-neutral pair `repository_id=1212760346` and `repository_name=OmniGenis`.
- Canonical GENOMA v3.4 identity, sealed normative bytes, scientific thresholds, report taxonomy, evidence semantics, and genomic interpretation remain unchanged.
- All newly added or modified code, tests, comments, docstrings, technical messages, configuration descriptions, and developer-facing documentation are written in English.
- Existing Codework-derived runtime literals remain temporarily unchanged in 2A and are permitted only through the reviewed legacy ledger.
- A new unclassified Codework-derived occurrence MUST fail validation.
- An allowed occurrence count MAY decrease but MUST NOT increase above its per-path reviewed baseline.
- Historical migration/spec/evidence/checkpoint roots are excluded from the active migration ledger only during 2A; Phase 2D replaces broad transitional exclusions with an exact final historical allowlist.
- No auto-merge. Final merge remains explicit human action.

---

### Task 1: Add the canonical OmniGenis identity contract

**Files:**
- Create: `config/project_identity.json`
- Create: `tests/test_project_identity_contract.py`

**Interfaces:**
- Consumes: approved target map from the Phase 2 design spec.
- Produces: `config/project_identity.json`, schema `omnigenis-project-identity-v1`, whose leaf string values are the canonical replacement identities consumed by later validation tasks.

- [ ] **Step 1: Write the RED contract test**

Create `tests/test_project_identity_contract.py` with the exact contract expected by Phase 2:

```python
from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "project_identity.json"

EXPECTED = {
    "schema": "omnigenis-project-identity-v1",
    "version": "2026-09-10.1",
    "repository": {
        "product_name": "OmniGenis",
        "repository_id": 1212760346,
        "repository_name": "OmniGenis",
    },
    "runtime": {
        "root": "/opt/omnigenis",
        "config_root": "/etc/omnigenis",
        "state_root": "/var/lib/omnigenis-tunnel",
        "container_package": "omnigenis-genome",
        "cache_namespace": "omnigenis-genome-scaffold-v2",
        "tunnel_profile": "omnigenis-genome",
    },
    "mcp": {"identity": "omnigenis-genome-mcp"},
    "ngs": {
        "conda_environment": "omnigenis-ngs",
        "nextflow_manifest": "omnigenis/genome-runtime",
        "synthetic_fixture": "omnigenis-synthetic-germline-v2",
    },
    "runners": {
        "pool_label": "omnigenis-isolated",
        "per_runner_labels": ["omnigenis-01", "omnigenis-02"],
        "runner_names": ["runner_id=21; retired_name_sha256=0840cef7416ffb5cfc1eb56b6273c34797f68d9e39bddf4293c187db450ea594", "runner_id=22; retired_name_sha256=c009b56b587f276bb06642ff98931b2ddfeb566f75f48075c73695cda5b72e54"],
    },
    "codex": {
        "marketplace": "omnigenis-codex",
        "plugin": "coderabbit@omnigenis-codex",
        "bin_dir_env": "OMNIGENIS_CODERABBIT_BIN_DIR",
        "lock_schema": "omnigenis-coderabbit-cli-release-lock-v2",
    },
    "testing": {
        "temp_prefix_namespace": "omnigenis-",
        "runner_test_symbol": "private_omnigenis_runners",
    },
}


class ProjectIdentityContractTest(unittest.TestCase):
    def test_identity_contract_is_exact(self) -> None:
        self.assertTrue(CONTRACT.is_file())
        self.assertEqual(json.loads(CONTRACT.read_text(encoding="utf-8")), EXPECTED)

    def test_contract_contains_no_legacy_identity(self) -> None:
        raw = CONTRACT.read_text(encoding="utf-8")
        legacy_word = "code" + "work"
        self.assertNotIn(legacy_word, raw.lower())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m unittest tests.test_project_identity_contract -v
```

Expected: FAIL because `config/project_identity.json` does not exist.

- [ ] **Step 3: Create the minimal canonical contract**

Create `config/project_identity.json` with exactly this content:

```json
{
  "schema": "omnigenis-project-identity-v1",
  "version": "2026-09-10.1",
  "repository": {
    "product_name": "OmniGenis",
    "repository_id": 1212760346,
    "repository_name": "OmniGenis"
  },
  "runtime": {
    "root": "/opt/omnigenis",
    "config_root": "/etc/omnigenis",
    "state_root": "/var/lib/omnigenis-tunnel",
    "container_package": "omnigenis-genome",
    "cache_namespace": "omnigenis-genome-scaffold-v2",
    "tunnel_profile": "omnigenis-genome"
  },
  "mcp": {
    "identity": "omnigenis-genome-mcp"
  },
  "ngs": {
    "conda_environment": "omnigenis-ngs",
    "nextflow_manifest": "omnigenis/genome-runtime",
    "synthetic_fixture": "omnigenis-synthetic-germline-v2"
  },
  "runners": {
    "pool_label": "omnigenis-isolated",
    "per_runner_labels": [
      "omnigenis-01",
      "omnigenis-02"
    ],
    "runner_names": [
      "runner_id=21; retired_name_sha256=0840cef7416ffb5cfc1eb56b6273c34797f68d9e39bddf4293c187db450ea594",
      "runner_id=22; retired_name_sha256=c009b56b587f276bb06642ff98931b2ddfeb566f75f48075c73695cda5b72e54"
    ]
  },
  "codex": {
    "marketplace": "omnigenis-codex",
    "plugin": "coderabbit@omnigenis-codex",
    "bin_dir_env": "OMNIGENIS_CODERABBIT_BIN_DIR",
    "lock_schema": "omnigenis-coderabbit-cli-release-lock-v2"
  },
  "testing": {
    "temp_prefix_namespace": "omnigenis-",
    "runner_test_symbol": "private_omnigenis_runners"
  }
}
```

- [ ] **Step 4: Run GREEN and JSON validation**

Run:

```bash
python3 -m unittest tests.test_project_identity_contract -v
python3 -m json.tool config/project_identity.json >/dev/null
```

Expected: 2/2 tests PASS; JSON parser exits `0`.

- [ ] **Step 5: Commit the canonical identity contract**

```bash
git add config/project_identity.json tests/test_project_identity_contract.py
git diff --cached --check
git commit -m "feat: add OmniGenis identity contract"
```

Expected: one focused commit containing only the contract and its tests.

### Task 2: Add the fail-closed legacy identity guard and reviewed ledger

**Files:**
- Create: `config/legacy_identity_ledger.json`
- Create: `scripts/project_identity_guard.py`
- Create: `tests/test_project_identity_guard.py`

**Interfaces:**
- Consumes: `config/project_identity.json` from Task 1.
- Produces: `validate_project_identity(root: Path) -> list[str]` and `scan_legacy_identities(root: Path, ledger: dict[str, Any]) -> dict[str, Any]` for Task 3.
- Produces CLI: `python3 scripts/project_identity_guard.py --check` and read-only `--inventory`.

- [ ] **Step 1: Write RED tests for fail-closed classification and monotonic counts**

Create `tests/test_project_identity_guard.py` with temporary Git repositories so scanner behavior is proved independently of the real repository:

```python
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

from scripts.project_identity_guard import validate_project_identity


IDENTITY = {
    "schema": "omnigenis-project-identity-v1",
    "version": "2026-09-10.1",
    "repository": {"product_name": "OmniGenis", "repository_id": 1212760346, "repository_name": "OmniGenis"},
    "runtime": {
        "root": "/opt/omnigenis",
        "config_root": "/etc/omnigenis",
        "state_root": "/var/lib/omnigenis-tunnel",
        "container_package": "omnigenis-genome",
        "cache_namespace": "omnigenis-genome-scaffold-v2",
        "tunnel_profile": "omnigenis-genome",
    },
    "mcp": {"identity": "omnigenis-genome-mcp"},
    "ngs": {
        "conda_environment": "omnigenis-ngs",
        "nextflow_manifest": "omnigenis/genome-runtime",
        "synthetic_fixture": "omnigenis-synthetic-germline-v2",
    },
    "runners": {
        "pool_label": "omnigenis-isolated",
        "per_runner_labels": ["omnigenis-01", "omnigenis-02"],
        "runner_names": ["runner_id=21; retired_name_sha256=0840cef7416ffb5cfc1eb56b6273c34797f68d9e39bddf4293c187db450ea594", "runner_id=22; retired_name_sha256=c009b56b587f276bb06642ff98931b2ddfeb566f75f48075c73695cda5b72e54"],
    },
    "codex": {
        "marketplace": "omnigenis-codex",
        "plugin": "coderabbit@omnigenis-codex",
        "bin_dir_env": "OMNIGENIS_CODERABBIT_BIN_DIR",
        "lock_schema": "omnigenis-coderabbit-cli-release-lock-v2",
    },
    "testing": {
        "temp_prefix_namespace": "omnigenis-",
        "runner_test_symbol": "private_omnigenis_runners",
    },
}


class ProjectIdentityGuardTest(unittest.TestCase):
    def make_repo(self, text: str, max_count: int = 1) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "config").mkdir()
        (root / "config/project_identity.json").write_text(
            json.dumps(IDENTITY), encoding="utf-8"
        )
        ledger = {
            "schema": "omnigenis-legacy-identity-ledger-v1",
            "baseline_commit": "939dfea5cc7cb2745638168d518d2005e941e9c6",
            "phase": "2A",
            "scan_suffixes": EXPECTED_SCAN_SUFFIXES,
            "historical_prefixes": EXPECTED_HISTORICAL_PREFIXES,
            "entries": [
                {
                    "id": "runtime-root",
                    "matcher": {"kind": "literal", "value": "/opt/codework"},
                    "replacement": "/opt/omnigenis",
                    "retire_by": "2B",
                    "reason": "Temporary runtime-root compatibility.",
                    "locations": {"active.txt": max_count},
                }
            ],
        }
        (root / "config/legacy_identity_ledger.json").write_text(
            json.dumps(ledger), encoding="utf-8"
        )
        (root / "active.txt").write_text(text, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        return root

    def test_reviewed_occurrence_passes(self) -> None:
        self.assertEqual(validate_project_identity(self.make_repo("/opt/codework")), [])

    def test_removing_a_legacy_occurrence_is_allowed(self) -> None:
        self.assertEqual(validate_project_identity(self.make_repo("clean", max_count=1)), [])

    def test_new_unclassified_codework_identity_fails(self) -> None:
        errors = validate_project_identity(self.make_repo("codework-surprise"))
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))

    def test_reviewed_count_may_not_increase(self) -> None:
        errors = validate_project_identity(self.make_repo("/opt/codework /opt/codework"))
        self.assertTrue(any("legacy occurrence count increased" in error for error in errors))

    def test_reviewed_identity_may_not_move_to_an_unlisted_path(self) -> None:
        root = self.make_repo("clean")
        (root / "moved.txt").write_text("/opt/codework", encoding="utf-8")
        subprocess.run(["git", "add", "moved.txt"], cwd=root, check=True)
        errors = validate_project_identity(root)
        self.assertTrue(any("unclassified legacy identity" in error for error in errors))

    def test_ledger_replacement_must_be_canonical(self) -> None:
        root = self.make_repo("/opt/codework")
        ledger_path = root / "config/legacy_identity_ledger.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][0]["replacement"] = "/opt/not-omnigenis"
        ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        errors = validate_project_identity(root)
        self.assertTrue(any("replacement is not canonical" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m unittest tests.test_project_identity_guard -v
```

Expected: import failure because `scripts/project_identity_guard.py` does not exist.

- [ ] **Step 3: Implement the minimal guard API**

Create `scripts/project_identity_guard.py`. Use only Python standard library. The implementation must treat `config/legacy_identity_ledger.json` as control metadata: the guard loads and validates it, but the operational-content scanner MUST skip that exact file so the ledger does not classify its own legacy matchers. No directory-wide exclusion is permitted.

The implementation must:

```python
#!/usr/bin/env python3
"""Validate the canonical OmniGenis identity contract and migration ledger."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
IDENTITY_PATH = Path("config/project_identity.json")
LEDGER_PATH = Path("config/legacy_identity_ledger.json")
LEGACY_PATTERN = re.compile("code" + "work", re.IGNORECASE)
CONTROL_METADATA_PATHS = {LEDGER_PATH}
PHASE2A_SCAN_SUFFIXES = (
    "", ".example", ".json", ".md", ".nf", ".py", ".service",
    ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
)
PHASE2A_HISTORICAL_PREFIXES = (
    "docs/history/",
    "docs/superpowers/specs/",
    "docs/superpowers/plans/",
    "docs/superpowers/evidence/",
    "docs/superpowers/checkpoints/",
)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _flatten_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _flatten_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_strings(child)


def _repository_paths(root: Path) -> tuple[Path, ...]:
    proc = subprocess.run(
        ["git", "ls-files", "-z", "--cached"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(
        Path(item)
        for item in proc.stdout.decode("utf-8").split("\0")
        if item
    )


def _compile_matcher(entry: dict[str, Any]) -> re.Pattern[str]:
    matcher = entry["matcher"]
    kind = matcher["kind"]
    value = matcher["value"]
    if kind == "literal":
        return re.compile(re.escape(value))
    if kind == "regex":
        return re.compile(value)
    raise ValueError(f"unsupported matcher kind: {kind}")


def _validate_scope_policy(ledger: dict[str, Any]) -> None:
    if ledger.get("scan_suffixes") != list(PHASE2A_SCAN_SUFFIXES):
        raise ValueError("legacy identity scan suffix policy mismatch")
    if ledger.get("historical_prefixes") != list(PHASE2A_HISTORICAL_PREFIXES):
        raise ValueError("legacy identity historical prefix policy mismatch")


def scan_legacy_identities(root: Path, ledger: dict[str, Any]) -> dict[str, Any]:
    _validate_scope_policy(ledger)
    suffixes = tuple(ledger["scan_suffixes"])
    historical = tuple(ledger["historical_prefixes"])
    entries = ledger["entries"]
    report: dict[str, Any] = {
        "counts": {},
        "unclassified": [],
        "over_budget": [],
    }
    for relative in _repository_paths(root):
        posix = relative.as_posix()
        if relative in CONTROL_METADATA_PATHS:
            continue
        if posix.startswith(historical) or relative.suffix not in suffixes:
            continue
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        covered: list[tuple[int, int]] = []
        for entry in entries:
            allowed = entry["locations"].get(posix)
            pattern = _compile_matcher(entry)
            matches = list(pattern.finditer(text))
            count = len(matches)
            if count:
                report["counts"].setdefault(entry["id"], {})[posix] = count
            if count and allowed is None:
                continue
            if allowed is not None and count > allowed:
                report["over_budget"].append(
                    {"id": entry["id"], "path": posix, "count": count, "max": allowed}
                )
            if allowed is not None:
                covered.extend((match.start(), match.end()) for match in matches)
        for match in LEGACY_PATTERN.finditer(text):
            if not any(start <= match.start() and match.end() <= end for start, end in covered):
                line = text.count("\n", 0, match.start()) + 1
                report["unclassified"].append({"path": posix, "line": line})
    return report


def validate_project_identity(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        identity = _load_json(root / IDENTITY_PATH)
        ledger = _load_json(root / LEDGER_PATH)
    except (OSError, ValueError) as exc:
        return [f"project identity contract unreadable: {exc}"]

    if identity.get("schema") != "omnigenis-project-identity-v1":
        errors.append("project identity schema mismatch")
    if ledger.get("schema") != "omnigenis-legacy-identity-ledger-v1":
        errors.append("legacy identity ledger schema mismatch")
    if ledger.get("phase") != "2A":
        errors.append("legacy identity ledger must remain in Phase 2A during this subphase")

    canonical = set(_flatten_strings(identity))
    for entry in ledger.get("entries", []):
        replacement = entry.get("replacement")
        disposition = entry.get("disposition", "migrate")
        if disposition == "migrate" and replacement not in canonical:
            errors.append(f"legacy identity replacement is not canonical: {entry.get('id')}")
        if not entry.get("reason") or not entry.get("retire_by"):
            errors.append(f"legacy identity entry lacks reason/retire_by: {entry.get('id')}")

    try:
        report = scan_legacy_identities(root, ledger)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return errors + [f"legacy identity scan failed closed: {exc}"]
    for item in report["unclassified"]:
        errors.append(
            f"unclassified legacy identity: {item['path']}:{item['line']}"
        )
    for item in report["over_budget"]:
        errors.append(
            "legacy occurrence count increased: "
            f"{item['id']} {item['path']} {item['count']}>{item['max']}"
        )
    return errors
```

Add a CLI `main()` that supports exactly `--check` and `--inventory`. `--check` prints each error as `FAIL\t...` and exits 1 or prints `PASS\tproject_identity_contract` and exits 0. `--inventory` prints the JSON scan report only and never writes or updates the ledger.

- [ ] **Step 4: Run the behavioral tests and verify GREEN for the guard implementation**

Run:

```bash
python3 -m unittest tests.test_project_identity_guard -v
```

Expected: all guard tests PASS, including tracked-only scanning, exact Phase 2A scope enforcement, control-metadata exclusion, fail-closed UTF-8 handling, monotonic counts, and unclassified-identity rejection. Test source constructs legacy tokens from string fragments so the test file itself does not add active legacy occurrences.

- [ ] **Step 5: Create the reviewed real-repository ledger**

Create `config/legacy_identity_ledger.json` with schema `omnigenis-legacy-identity-ledger-v1`, baseline commit `939dfea5cc7cb2745638168d518d2005e941e9c6`, phase `2A`, scan suffixes:

```json
["", ".example", ".json", ".md", ".nf", ".py", ".service", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml"]
```

and transitional historical prefixes:

```json
[
  "docs/history/",
  "docs/superpowers/specs/",
  "docs/superpowers/plans/",
  "docs/superpowers/evidence/",
  "docs/superpowers/checkpoints/"
]
```

The ledger entries MUST cover the reviewed active classes below, using literal matchers unless `regex` is explicitly shown. The empty-string suffix is intentional so extensionless tracked text such as `Dockerfile` is scanned; `.service` and `.example` cover the current systemd templates. Each entry records only the exact active paths observed at baseline and the exact count in each path; later counts may fall but not rise.

```text
runtime-root                 /opt/codework                         -> /opt/omnigenis                    retire_by=2B
config-root                  /etc/codework                         -> /etc/omnigenis                    retire_by=2B
runner-pool                  codework-isolated                     -> omnigenis-isolated                retire_by=2C
container-package            regex: (?<![A-Za-z0-9_-])codework-genome(?![A-Za-z0-9_-]) -> omnigenis-genome retire_by=2B
cache-namespace              codework-genome-scaffold-v1           -> omnigenis-genome-scaffold-v2     retire_by=2B
mcp-package                  codework-genome-mcp                   -> omnigenis-genome-mcp             retire_by=2B
mcp-server                   codework-private-genome               -> omnigenis-genome-mcp             retire_by=2B
conda-environment            codework-ngs                          -> omnigenis-ngs                    retire_by=2B
nextflow-manifest            codework/genome-runtime               -> omnigenis/genome-runtime         retire_by=2B
codex-marketplace            regex: (?<![A-Za-z0-9_-])codework-codex(?![A-Za-z0-9_-]) -> omnigenis-codex retire_by=2B
coderabbit-plugin            coderabbit@codework-codex             -> coderabbit@omnigenis-codex      retire_by=2B
coderabbit-bin-env           CODEWORK_CODERABBIT_BIN_DIR           -> OMNIGENIS_CODERABBIT_BIN_DIR    retire_by=2D
synthetic-fixture            codework-synthetic-germline-v1        -> omnigenis-synthetic-germline-v2 retire_by=2B
historical-runtime-zip       codework-genome-runtime-2026-08-15.zip disposition=preserve_historical     retire_by=2D
runtime-state-dir            codework-tunnel                       -> /var/lib/omnigenis-tunnel        retire_by=2B
coderabbit-lock-schema       codework-coderabbit-cli-release-lock-v1 -> omnigenis-coderabbit-cli-release-lock-v2 retire_by=2B
mcp-test-temp-prefixes       regex: codework-(?:audit|server|claim|lock|release|budget|timeout|reaped|exit)[A-Za-z0-9_-]* -> omnigenis- test namespace retire_by=2B
ci-test-function-name        private_codework_runners              -> private_omnigenis_runners        retire_by=2C
product-word                 regex: (?<![A-Za-z0-9_-])Codework(?![A-Za-z0-9_-]) -> OmniGenis          retire_by=2B/2D by path
```

For `product-word`, keep the two historical URL inventory paths as `disposition=preserve_historical` ledger entries and use a separate migrating entry for active descriptions/tests. Do not allow one broad entry to bless both semantics.

Populate every `locations` map from the current baseline using a reviewed one-off inventory. The known baseline counts that MUST reconcile before commit include:

```text
/opt/codework = 50
/etc/codework = 5
codework-isolated = 14
codework-genome-scaffold-v1 = 4
codework-genome-mcp = 4
codework-private-genome = 2
codework-ngs = 2
codework/genome-runtime = 2
coderabbit@codework-codex = 12
CODEWORK_CODERABBIT_BIN_DIR = 3
codework-codex substring family = 28 before boundary filtering
codework-synthetic-germline-v1 = 1
codework-genome-runtime-2026-08-15.zip = 2
codework-tunnel = 2
codework-coderabbit-cli-release-lock-v1 = 3
MCP test temporary-prefix class = 29
private_codework_runners = 1
boundary-matched Codework product word = 10
boundary-matched codework-genome = 22
```

Use `python3 scripts/project_identity_guard.py --inventory` plus `git grep -n -i codework` to reconcile every uncovered occurrence. The guard MUST report `unclassified: []` before the ledger is accepted.

- [ ] **Step 6: Add mutation tests proving the real ledger is fail-closed**

Extend `tests/test_project_identity_guard.py` with repository-copy mutation tests that prove:

```python
def test_real_repository_has_no_unclassified_legacy_identity(self) -> None:
    self.assertEqual(validate_project_identity(ROOT), [])
```

and mutate a copied active file to add a dynamically constructed legacy identity, duplicate the dynamically constructed legacy runtime root, and move one reviewed identity to an unlisted file. The test source itself must not contain the legacy product token as a contiguous literal. Each mutation must make `validate_project_identity()` return the expected failure. Do not mutate the real working tree during tests.

- [ ] **Step 7: Run the real guard and focused suite**

Run:

```bash
python3 scripts/project_identity_guard.py --check
python3 -m unittest tests.test_project_identity_contract tests.test_project_identity_guard -v
```

Expected: guard PASS; all focused tests PASS; inventory has zero unclassified occurrences and zero over-budget entries.

- [ ] **Step 8: Commit the guard and ledger**

```bash
git add config/legacy_identity_ledger.json scripts/project_identity_guard.py tests/test_project_identity_guard.py
git diff --cached --check
git commit -m "feat: guard OmniGenis identity migration"
```

Expected: one focused commit; no runtime/workflow file changes.

### Task 3: Integrate the identity guard into the official repository validator

**Files:**
- Modify: `scripts/validate_repo.py`
- Modify: `tests/test_repo_contract.py`
- Create: `docs/PROJECT_IDENTITY_CONTRACT.md`

**Interfaces:**
- Consumes: `validate_project_identity(root: Path) -> list[str]` from Task 2.
- Produces: official `scripts/validate_repo.py` enforcement and English developer documentation for the 2A contract.

- [ ] **Step 1: Write RED integration tests**

In `tests/test_repo_contract.py`, import `scripts.validate_repo` and add a sentinel invocation test following the existing residual-language pattern:

```python
from unittest import mock
import scripts.validate_repo as validate_repo


def test_validate_repo_invokes_project_identity_guard(self) -> None:
    with mock.patch.object(
        validate_repo,
        "validate_project_identity",
        return_value=["project identity sentinel"],
    ) as guard:
        errors = validate_repo.validate(ROOT)
    guard.assert_called_once_with(ROOT)
    self.assertIn("project identity sentinel", errors)
```

Also add an assertion that `REQUIRED_PATHS` includes:

```text
config/project_identity.json
config/legacy_identity_ledger.json
scripts/project_identity_guard.py
docs/PROJECT_IDENTITY_CONTRACT.md
```

- [ ] **Step 2: Run RED**

Run:

```bash
python3 -m unittest tests.test_repo_contract -v
```

Expected: FAIL because `validate_repo` does not yet import/invoke the new guard and the documentation path does not exist.

- [ ] **Step 3: Integrate the guard minimally**

In `scripts/validate_repo.py`, add after the existing language imports:

```python
from scripts.project_identity_guard import validate_project_identity  # noqa: E402
```

Add the four Task 3 paths to `REQUIRED_PATHS`.

Inside `validate(root: Path)`, immediately after required-path checks and before scientific/runtime checks, add:

```python
errors.extend(validate_project_identity(root))
```

Do not change any existing token, workflow, scientific, ruleset, or reporting checks in this task.

- [ ] **Step 4: Create the English contract documentation**

Create `docs/PROJECT_IDENTITY_CONTRACT.md` containing these sections with concrete content:

```markdown
# OmniGenis Project Identity Contract

## Purpose
`config/project_identity.json` is the canonical target identity registry for the Phase 2 internal-name migration. It does not dynamically configure every runtime consumer; repository guards compare active literals against the approved contract during later cutover phases.

## Phase 2A behavior
Phase 2A changes no runtime identity. `config/legacy_identity_ledger.json` records reviewed active legacy-identity compatibility occurrences. Counts may decrease but may not increase, and an unclassified occurrence fails `scripts/validate_repo.py`.

## Transitional historical scope
During Phase 2A only, migration specifications, implementation plans, evidence, checkpoints, and `docs/history/` are outside the active compatibility ledger. Phase 2D replaces these broad transitional exclusions with an exact final historical/provenance allowlist.

## Editing rule
Do not update the ledger to make a failing new legacy occurrence pass. First determine whether the occurrence is an approved migration compatibility need. A new runtime identity requires a design/spec change; historical evidence remains immutable.

## Phase boundaries
2A defines and guards identities. 2B cuts repository-controlled runtime/build identities over. 2C migrates live self-hosted runners. 2D removes temporary compatibility and seals zero active legacy identity.
```

- [ ] **Step 5: Run GREEN integration tests and official validator**

Run:

```bash
python3 -m unittest tests.test_repo_contract -v
python3 scripts/validate_repo.py
python3 scripts/project_identity_guard.py --check
```

Expected: all tests PASS; both validators exit `0`.

- [ ] **Step 6: Prove 2A did not alter runtime surfaces**

Run:

```bash
changed_runtime="$(git diff --name-only origin/main -- \
  Dockerfile environment.yml nextflow.config deploy mcp \
  scripts/codex/setup-coderabbit.sh scripts/generate_canary.py)"
test -z "$changed_runtime"
workflow_changed="$(git diff --name-only origin/main -- .github/workflows)"
test "$workflow_changed" = ".github/workflows/genoma-ngs-runtime-gate.yml"
python3 -m unittest \
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_ngs_runtime_gate_trigger_only_change_preserves_baseline_semantics \
  tests.test_ci_optimization_contract.CIOptimizationContractTest.test_ngs_runtime_gate_uses_explicit_ngs_script_paths_instead_of_all_scripts -v
printf '%s\n' 'PHASE2A_RUNTIME_BOUNDARY=PASS'
```

Expected: `PHASE2A_RUNTIME_BOUNDARY=PASS`.

- [ ] **Step 7: Commit validator integration and documentation**

```bash
git add scripts/validate_repo.py tests/test_repo_contract.py docs/PROJECT_IDENTITY_CONTRACT.md
git diff --cached --check
git commit -m "chore: enforce OmniGenis identity contract"
```

Expected: focused validator/docs commit; no runtime surface changed.

### Task 4: Produce exact-HEAD Phase 2A evidence and run complete validation

**Files:**
- Create: `docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json`

**Interfaces:**
- Consumes: completed Tasks 1-3.
- Produces: non-secret evidence binding the reviewed ledger/contract and complete validation to one exact HEAD.

- [ ] **Step 1: Run focused mutation and contract gates before evidence creation**

Run:

```bash
python3 -m unittest \
  tests.test_project_identity_contract \
  tests.test_project_identity_guard \
  tests.test_repo_contract -v
python3 scripts/project_identity_guard.py --check
```

Expected: PASS with zero unclassified or over-budget legacy identities.

- [ ] **Step 2: Run repository, supply-chain, language, and documentation gates**

Use the existing project Python environment with pinned renderer dependencies:

```bash
VENV=/tmp/codework-ci-artifact-opt-venv
"$VENV/bin/python" scripts/validate_repo.py
"$VENV/bin/python" scripts/verify_supply_chain_lock.py
"$VENV/bin/python" scripts/code_language_guard.py --check
"$VENV/bin/python" scripts/residual_language_audit.py --check
"$VENV/bin/python" -m unittest tests.test_developer_documentation_language -v
bash -n scripts/*.sh
git diff --check
```

Expected: all commands exit `0`.

- [ ] **Step 3: Run the complete root suite at the exact implementation HEAD**

Run:

```bash
VENV=/tmp/codework-ci-artifact-opt-venv
"$VENV/bin/python" -m unittest discover -s tests -v \
  > /tmp/omnigenis-phase2a-root-suite.log 2>&1
rc=$?
grep -E 'Ran [0-9]+ tests|^OK|^FAILED' /tmp/omnigenis-phase2a-root-suite.log | tail -n 10
exit "$rc"
```

Expected: exit `0`, zero failures, zero errors. Record the exact test count rather than assuming it remains 1,047 after the new tests are added.

- [ ] **Step 4: Seal the validation cycle state before evidence generation**

Run all evidence-bearing commands in one fail-fast shell and write a temporary validation-state record only after they succeed:

```bash
set -euo pipefail
VENV=/tmp/codework-ci-artifact-opt-venv
IMPLEMENTATION_HEAD="$(git rev-parse HEAD)"
STATE=/tmp/omnigenis-phase2a-validation-state.json
ROOT_LOG=/tmp/omnigenis-phase2a-root-suite.log
rm -f "$STATE" "$ROOT_LOG"

"$VENV/bin/python" -m unittest \
  tests.test_project_identity_contract \
  tests.test_project_identity_guard \
  tests.test_repo_contract -v
"$VENV/bin/python" scripts/project_identity_guard.py --check
"$VENV/bin/python" scripts/validate_repo.py
"$VENV/bin/python" scripts/verify_supply_chain_lock.py
"$VENV/bin/python" scripts/code_language_guard.py --check
"$VENV/bin/python" scripts/residual_language_audit.py --check
"$VENV/bin/python" -m unittest tests.test_developer_documentation_language -v
bash -n scripts/*.sh
git diff --check
"$VENV/bin/python" -m unittest discover -s tests -v > "$ROOT_LOG" 2>&1

grep -Eq '^OK( \(skipped=[0-9]+\))?$' "$ROOT_LOG"
ROOT_TESTS="$(sed -nE 's/^Ran ([0-9]+) tests.*/\1/p' "$ROOT_LOG" | tail -n 1)"
test -n "$ROOT_TESTS"

IMPLEMENTATION_HEAD="$IMPLEMENTATION_HEAD" ROOT_TESTS="$ROOT_TESTS" \
python3 - <<'PY'
import json
import os
from pathlib import Path
state = {
    "schema": "omnigenis-phase2a-validation-state-v1",
    "implementation_head_sha": os.environ["IMPLEMENTATION_HEAD"],
    "root_test_count": int(os.environ["ROOT_TESTS"]),
    "validation": {
        "project_identity_guard": "PASS",
        "validate_repo": "PASS",
        "supply_chain": "PASS",
        "code_language": "PASS",
        "residual_language": "PASS",
        "developer_documentation_tests": "PASS",
        "shell_syntax": "PASS",
        "diff_check": "PASS",
        "root_suite": "PASS",
    },
}
Path("/tmp/omnigenis-phase2a-validation-state.json").write_text(
    json.dumps(state, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
```

Expected: the state file exists only after all commands complete successfully and records the exact implementation HEAD plus the observed root-suite count. This temporary state is not the durable evidence artifact; its boolean PASS map is only an input to the provenance-enriched evidence record.

### Reviewer-remediation evidence requirements

The durable evidence schema is `omnigenis-phase2a-identity-contract-evidence-v2`. For every validation gate, `validation_provenance` records `status`, the exact `command`, `exit_code`, an `environment` key, and an inline output summary with its SHA-256. When a full raw log is ephemeral, also retain its SHA-256 and explicitly state that only the digest is durable. `baseline_provenance` uses the same record shape for repository metadata, rulesets, Git endpoint continuity, baseline `validate_repo.py`, and the baseline root suite. `provenance_sources.phase1_migration_evidence` pins the Phase 1 evidence path and SHA-256. The executable schema is enforced by `tests/test_phase2a_evidence_contract.py`.

Baseline verification commands are exactly:

```bash
repo="$(gh api repositories/1212760346 --jq .full_name)"
owner="${repo%%/*}"
gh api "repos/$repo" --jq '{id,full_name,visibility,default_branch}'
gh api "repos/$repo/rulesets/21303100" --jq '{id,name,enforcement,conditions,rules,bypass_actors}'
gh api "repos/$repo/rulesets/22347095" --jq '{id,name,enforcement,conditions,rules,bypass_actors}'
git ls-remote "https://github.com/$owner/Codework.git" refs/heads/main
git ls-remote "https://github.com/$repo.git" refs/heads/main
# In a detached worktree at baseline SHA 939dfea5cc7cb2745638168d518d2005e941e9c6:
/tmp/codework-ci-artifact-opt-venv/bin/python scripts/validate_repo.py
/tmp/codework-ci-artifact-opt-venv/bin/python -m unittest discover -s tests -v
```

- [ ] **Step 5: Generate the non-secret evidence artifact from verified state**

Generate `docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json` with this exact procedure:

```bash
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.project_identity_guard import _load_json, scan_legacy_identities

ROOT = Path.cwd()
BASE_SHA = "939dfea5cc7cb2745638168d518d2005e941e9c6"
STATE = Path("/tmp/omnigenis-phase2a-validation-state.json")
OUT = ROOT / "docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changed_paths(*pathspecs: str) -> list[str]:
    command = ["git", "diff", "--name-only", BASE_SHA, "--", *pathspecs]
    return sorted(
        path
        for path in subprocess.check_output(command, text=True).splitlines()
        if path
    )


state = json.loads(STATE.read_text(encoding="utf-8"))
implementation_head = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True
).strip()
if state["implementation_head_sha"] != implementation_head:
    raise SystemExit("validation state does not match current implementation HEAD")
if any(value != "PASS" for value in state["validation"].values()):
    raise SystemExit("validation state contains a non-PASS result")

identity_path = ROOT / "config/project_identity.json"
ledger_path = ROOT / "config/legacy_identity_ledger.json"
ledger = _load_json(ledger_path)
legacy_scan = scan_legacy_identities(ROOT, ledger)
if legacy_scan["unclassified"] or legacy_scan["over_budget"]:
    raise SystemExit("legacy identity scan is not clean")

runtime_paths = changed_paths(
    "Dockerfile",
    "environment.yml",
    "nextflow.config",
    "deploy",
    "mcp",
    "scripts/codex/setup-coderabbit.sh",
    "scripts/generate_canary.py",
)
trigger_workflow_paths = changed_paths(".github/workflows")
expected_trigger_workflow_paths = [".github/workflows/genoma-ngs-runtime-gate.yml"]
if trigger_workflow_paths != expected_trigger_workflow_paths:
    raise SystemExit("unexpected GitHub Actions workflow changed during Phase 2A")
normative_paths = changed_paths("normative", "manifests/RULESET_V3.4.sha256")
scientific_paths = changed_paths(
    "array_pipeline",
    "evidence_adapters",
    "policy_engine/genoma_policy",
    "reporting",
    "workflows",
    "main.nf",
)
if runtime_paths or normative_paths or scientific_paths:
    raise SystemExit("Phase 2A protected surface changed")

# Build `environments`, `validation_provenance`, `baseline_provenance`, and
# `provenance_sources` from the exact commands and output digests specified above.
# `tests/test_phase2a_evidence_contract.py` validates their complete record shape.

evidence = {
    "schema": "omnigenis-phase2a-identity-contract-evidence-v2",
    "base_sha": BASE_SHA,
    "implementation_head_sha": implementation_head,
    "identity_contract_sha256": sha256(identity_path),
    "legacy_ledger_sha256": sha256(ledger_path),
    "legacy_scan": legacy_scan,
    "root_test_count": state["root_test_count"],
    "runtime_surface_changed_paths": runtime_paths,
    "trigger_only_workflow_changed_paths": trigger_workflow_paths,
    "normative_surface_changed_paths": normative_paths,
    "scientific_surface_changed_paths": scientific_paths,
    "validation_state": state["validation"],
    "validation_provenance": validation_provenance,
    "baseline_provenance": baseline_provenance,
    "environments": environments,
    "provenance_sources": provenance_sources,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"EVIDENCE_WRITTEN={OUT}")
print(f"IMPLEMENTATION_HEAD={implementation_head}")
PY
```

Do not include tokens, runner registration data, credentials, package credentials, or genomic/patient data.

- [ ] **Step 6: Validate the evidence before its commit**

Run:

```bash
python3 -m json.tool \
  docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json \
  >/dev/null
python3 - <<'PY'
import json
import subprocess
from pathlib import Path
path = Path("docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json")
evidence = json.loads(path.read_text(encoding="utf-8"))
current = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert evidence["base_sha"] == "939dfea5cc7cb2745638168d518d2005e941e9c6"
assert evidence["implementation_head_sha"] == current
assert evidence["legacy_scan"]["unclassified"] == []
assert evidence["legacy_scan"]["over_budget"] == []
assert evidence["runtime_surface_changed_paths"] == []
assert evidence["trigger_only_workflow_changed_paths"] == [
    ".github/workflows/genoma-ngs-runtime-gate.yml"
]
assert evidence["normative_surface_changed_paths"] == []
assert evidence["scientific_surface_changed_paths"] == []
assert all(record["status"] == "PASS" for record in evidence["validation_provenance"].values())
assert all(record["exit_code"] == 0 for record in evidence["validation_provenance"].values())
assert set(evidence["baseline_provenance"]) == {
    "repository_metadata", "rulesets", "git_endpoint_continuity", "validate_repo", "root_suite"
}
assert evidence["root_test_count"] > 0
PY
git diff --check
```

Expected: all assertions PASS while `HEAD` is still the implementation commit recorded by the evidence.

- [ ] **Step 7: Commit the evidence checkpoint**

```bash
git add docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json
git diff --cached --check
git commit -m "docs: record OmniGenis Phase 2A evidence"
```

Expected: evidence-only commit. The evidence intentionally binds its parent implementation commit through `implementation_head_sha`; it does not claim to hash or prove the commit that contains itself.

- [ ] **Step 8: Revalidate the final PR HEAD after the evidence commit**

Run:

```bash
EVIDENCE=docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json
python3 - <<'PY'
import json
import subprocess
from pathlib import Path
evidence = json.loads(Path(
    "docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json"
).read_text(encoding="utf-8"))
parent = subprocess.check_output(["git", "rev-parse", "HEAD^"], text=True).strip()
assert evidence["implementation_head_sha"] == parent
PY
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
python3 -m unittest \
  tests.test_project_identity_contract \
  tests.test_project_identity_guard \
  tests.test_repo_contract -v
python3 -m json.tool "$EVIDENCE" >/dev/null
git diff --check
test -z "$(git status --porcelain)"
printf 'FINAL_PHASE2A_HEAD=%s\n' "$(git rev-parse HEAD)"
```

Expected: all commands PASS and the worktree is clean. The PR body must report both the evidence-bound implementation HEAD (`HEAD^`) and the final PR HEAD (`HEAD`).


### Task 5: Open the governed Phase 2A PR and perform post-merge continuity

**Files:**
- No additional implementation files.

**Interfaces:**
- Consumes: exact validated Phase 2A branch.
- Produces: reviewed Phase 2A PR and, after human merge, a verified baseline for Phase 2B planning.

- [ ] **Step 1: Verify branch scope before push**

The diff against `origin/main` MUST be limited to:

```text
config/project_identity.json
config/legacy_identity_ledger.json
scripts/project_identity_guard.py
scripts/validate_repo.py
tests/test_project_identity_contract.py
tests/test_project_identity_guard.py
tests/test_phase2a_evidence_contract.py
tests/test_repo_contract.py
tests/test_ci_optimization_contract.py
.github/workflows/genoma-ngs-runtime-gate.yml
docs/PROJECT_IDENTITY_CONTRACT.md
docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json
```

The already-approved design spec and this implementation plan may also be present if they are being merged through the same documentation branch. No runtime surface may appear in the 2A implementation diff. The only workflow diff allowed is the two path-filter lines for `scripts/project_identity_guard.py` in `.github/workflows/genoma-ngs-runtime-gate.yml`, guarded by the normalized workflow fingerprint test.

- [ ] **Step 2: Push and create the PR as draft**

Run:

```bash
git push -u origin feat/omnigenis-phase2a-identity-contract
gh pr create --draft --base main --head feat/omnigenis-phase2a-identity-contract \
  --title "feat: add OmniGenis internal identity contract" \
  --body-file /tmp/omnigenis-phase2a-pr-body.md
```

The PR body must report the exact HEAD, contract/ledger hashes, legacy scan result, root-suite count, English-first result, runtime-boundary result, and explicitly state that no runner/GHCR/runtime mutation occurred.

- [ ] **Step 3: Mark Ready only after exact-HEAD local evidence is current**

Run:

```bash
PR_NUMBER="$(gh pr view --json number --jq .number)"
gh pr ready "$PR_NUMBER"
gh pr checks "$PR_NUMBER" --watch --interval 20
gh pr checks "$PR_NUMBER" --required
```

Expected: required checks become satisfiable under the existing rulesets. Do not weaken or remove a check to make the PR mergeable.

- [ ] **Step 4: Resolve reviewer findings with TDD and one coherent corrective push**

For every CodeRabbit/DeepSource/Semgrep/Snyk/GitGuardian finding:

1. verify it against the exact current code;
2. return the PR to draft before corrective mutation when appropriate;
3. write or extend a failing test where behavior changes;
4. run RED;
5. apply the smallest fix;
6. run focused GREEN plus complete applicable validation;
7. create one coherent corrective commit/push;
8. reply with exact SHA and evidence;
9. resolve the thread only after verification.

Do not dismiss a still-applicable finding and do not use auto-merge.

- [ ] **Step 5: Declare ready for manual merge only when every blocking gate is satisfied**

Required final evidence:

```text
PR not draft
mergeable = MERGEABLE
mergeStateStatus = CLEAN
unresolved review threads = 0
required checks satisfied/skipped only as allowed by existing classifier logic
identity guard PASS
legacy unclassified = 0
legacy over-budget = 0
runtime surface diff = empty
scientific/normative boundary diff = empty
English-first gates PASS
local HEAD = remote PR HEAD
rulesets 21303100 and 22347095 remain active and semantically unchanged
```

Stop before merge and request human merge.

- [ ] **Step 6: After human merge, run the Phase 2A post-merge gate**

After the user confirms merge:

```bash
git fetch origin --prune
git switch main
git reset --hard origin/main
python3 scripts/project_identity_guard.py --check
python3 scripts/validate_repo.py
gh api repos/$repo/rulesets --jq '.[] | [.id,.name,.enforcement] | @tsv'
```

Also verify repository ID `1212760346`, visibility `public`, default branch `main`, and capture the new `origin/main` SHA.

Expected: Phase 2A contract/ledger active on `main`; runtime identities still unchanged; only then may Phase 2B implementation planning/execution begin.
