# Language Baseline and Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish an English-first technical-language policy and a deterministic repository guard that blocks new Portuguese Python implementation identifiers/comments while preserving canonical, localized, historical, and compatibility-bound Portuguese content.

**Architecture:** Add a small standard-library-only scanner under `scripts/` that separates policy, current findings, deliberate exceptions, and legacy debt. The scanner will start with Python identifiers/comments/docstrings because PR 2 immediately migrates Python internals; later migration PRs can add TypeScript, shell, Nextflow, and other language adapters without changing the baseline contract. `scripts/validate_repo.py` will call the scanner so CI enforces the policy through the existing repository contract instead of a parallel workflow.

**Tech Stack:** Python 3 standard library (`ast`, `tokenize`, `unicodedata`, `json`, `pathlib`, `dataclasses`), `unittest`, existing `scripts/validate_repo.py` repository gate.

**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`

## Global Constraints

- Behavior preservation first; this PR must not alter runtime/scientific behavior.
- The GENOMA v3.4 ruleset, exact bytes, filename, SHA-256, sealed transport, manifests, and normative semantics must remain unchanged.
- Existing serialized values such as `VIGENTE`, `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, and `NÃO DISPONÍVEL` remain valid external contract values.
- Existing evidence schemas, artifact names, report filenames, CLI/API/MCP fields, and historical records are not renamed in this PR.
- No broad path exclusion may be used to hide active implementation code from language scanning.
- Immutable/historical surfaces may be excluded only by explicit path plus reason in policy data.
- Existing Portuguese technical debt is tracked separately from deliberate exceptions.
- A resolved legacy finding must be removed from the baseline; stale baseline entries are errors.
- No external package or network dependency may be added.
- No auto-merge; human approval remains the final merge gate.
- Implementation must start from a fresh non-`main` branch created from current `main`. Before the first code commit, record `BASE_SHA=$(git rev-parse HEAD)`; that exact SHA is the provenance recorded in the initial legacy baseline.

---

## File structure

The PR should create or modify only these files unless a test demonstrates that another file is required for the guard to function:

- Create `scripts/code_language_guard.py` — scanner, policy loader, baseline comparison, deterministic CLI.
- Create `config/code_language_policy.json` — schema/version, Python scan scope, exact technical Portuguese lexemes, explicit contract literals, explicit excluded immutable/historical roots with reasons.
- Create `config/code_language_legacy_baseline.json` — exact grouped findings present on the PR base before migration begins; this is debt tracking, not a permanent exception list.
- Create `tests/test_code_language_guard.py` — unit, negative, fail-closed, baseline, and repository-clean tests.
- Create `docs/CODE_LANGUAGE_POLICY.md` — human-readable policy and classification A–E.
- Modify `scripts/validate_repo.py` — invoke the language guard as part of `repository_contract` validation.
- Modify `AGENTS.md` — require English for new technical implementation and require intentional baseline reduction during migration.

The scanner interface must remain independent of `validate_repo.py` so tests can exercise it on temporary repositories without invoking the full GENOMA contract.

---

### Task 1: Policy and baseline data contract

**Files:**
- Create: `config/code_language_policy.json`
- Create: `config/code_language_legacy_baseline.json`
- Create: `scripts/code_language_guard.py`
- Test: `tests/test_code_language_guard.py`

**Interfaces:**
- Consumes: repository root `Path` and two JSON files under `config/`.
- Produces: `LanguagePolicy`, `BaselineEntry`, `load_policy(root: Path) -> LanguagePolicy`, and `load_baseline(root: Path) -> tuple[BaselineEntry, ...]`.

- [ ] **Step 1: Write failing tests for the policy schema and fail-closed loading**

Add the first test module with a module-level JSON helper shared by all test classes:

```python
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.code_language_guard import LanguagePolicyError, load_baseline, load_policy


def _write_json(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


class LanguagePolicyLoadingTest(unittest.TestCase):
    def test_policy_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_policy.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language policy schema"):
                load_policy(root)

    def test_baseline_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_legacy_baseline.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language baseline schema"):
                load_baseline(root)
```

- [ ] **Step 2: Run the focused tests and verify the module is absent**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.LanguagePolicyLoadingTest -v
```

Expected: import failure because `scripts.code_language_guard` does not exist.

- [ ] **Step 3: Implement the policy dataclasses and strict loaders**

Create `scripts/code_language_guard.py` with these public types and constants:

```python
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

POLICY_SCHEMA = "genoma-code-language-policy-v1"
BASELINE_SCHEMA = "genoma-code-language-legacy-baseline-v1"
SHA40 = re.compile(r"^[0-9a-f]{40}$")


class LanguagePolicyError(RuntimeError):
    pass


@dataclass(frozen=True, order=True)
class BaselineEntry:
    path: str
    kind: str
    token: str
    count: int


@dataclass(frozen=True)
class ExcludedRoot:
    path: str
    reason: str


@dataclass(frozen=True)
class LanguagePolicy:
    schema: str
    scan_suffixes: tuple[str, ...]
    technical_terms: frozenset[str]
    contract_literals: tuple[str, ...]
    excluded_roots: tuple[ExcludedRoot, ...]
```

Implement `load_policy()` and `load_baseline()` so they:

- require the exact schema names above;
- require a 40-character lowercase hexadecimal `source_commit` in the baseline;
- require non-empty `reason` on every excluded root;
- reject absolute paths and `..` traversal in excluded roots and baseline entries;
- require `count >= 1` for every baseline entry;
- reject duplicate baseline keys `(path, kind, token)`;
- accept only `.py` in `scan_suffixes` for PR 1;
- reject an empty technical-term set;
- reject a missing policy/baseline file with `LanguagePolicyError` rather than silently disabling enforcement.

- [ ] **Step 4: Add the concrete policy files**

Create `config/code_language_policy.json` in this shape:

```json
{
  "schema": "genoma-code-language-policy-v1",
  "scan_suffixes": [".py"],
  "technical_terms": [
    "acao",
    "amostra",
    "arquivo",
    "atualizar",
    "buscar",
    "carregar",
    "configuracao",
    "conteudo",
    "dados",
    "erro",
    "executar",
    "gerar",
    "limite",
    "relatorio",
    "resultado",
    "validacao",
    "validar",
    "verificacao",
    "verificar"
  ],
  "contract_literals": [
    "VIGENTE",
    "EXECUTADO",
    "VERIFICADO",
    "INFERIDO",
    "PROPOSTO",
    "NÃO DISPONÍVEL"
  ],
  "excluded_roots": [
    {
      "path": "docs/history",
      "reason": "immutable historical evidence and superseded normative records"
    },
    {
      "path": "normative/sealed",
      "reason": "inactive byte-exact canonical normative transport"
    }
  ]
}
```

Create the baseline file initially with an empty `entries` list and the exact `BASE_SHA` captured before the first code commit:

```json
{
  "schema": "genoma-code-language-legacy-baseline-v1",
  "source_commit": "<BASE_SHA captured from current main>",
  "entries": []
}
```

When implementing, replace the angle-bracket example with the actual 40-hex `BASE_SHA`; do not commit the example text.

- [ ] **Step 5: Run loader tests**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.LanguagePolicyLoadingTest -v
```

Expected: PASS.

- [ ] **Step 6: Commit the policy contract**

```bash
git add scripts/code_language_guard.py config/code_language_policy.json config/code_language_legacy_baseline.json tests/test_code_language_guard.py
git commit -m "feat: define code language policy contract"
```

---

### Task 2: Deterministic Python scanner

**Files:**
- Modify: `scripts/code_language_guard.py`
- Modify: `tests/test_code_language_guard.py`

**Interfaces:**
- Consumes: `LanguagePolicy`, a repository root, Python source files.
- Produces: `LanguageFinding`, `scan_python_file(path: Path, root: Path, policy: LanguagePolicy) -> tuple[LanguageFinding, ...]`, `scan_repository(root: Path, policy: LanguagePolicy) -> tuple[LanguageFinding, ...]`.

- [ ] **Step 1: Write failing tests for identifier splitting, accents, comments, docstrings, contract literals, and excluded history**

Add:

```python
from scripts.code_language_guard import scan_repository


class PythonLanguageScannerTest(unittest.TestCase):
    def _repo(self, files: dict[str, str]) -> tuple[TemporaryDirectory, Path]:
        td = TemporaryDirectory()
        root = Path(td.name)
        policy = {
            "schema": "genoma-code-language-policy-v1",
            "scan_suffixes": [".py"],
            "technical_terms": ["arquivo", "amostra", "disponivel", "relatorio", "validar", "verificacao"],
            "contract_literals": ["VERIFICADO", "NÃO DISPONÍVEL"],
            "excluded_roots": [
                {"path": "docs/history", "reason": "historical evidence"},
                {"path": "normative/sealed", "reason": "sealed transport"}
            ]
        }
        _write_json(root, "config/code_language_policy.json", policy)
        for relative, source in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return td, root

    def test_snake_case_portuguese_identifier_is_reported(self):
        td, root = self._repo({"pkg/mod.py": "def validar_arquivo():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == "validar_arquivo" for f in findings), findings)

    def test_camel_case_portuguese_identifier_is_reported(self):
        td, root = self._repo({"pkg/mod.py": "class RelatorioBuilder:\n    pass\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "identifier" and f.token == "RelatorioBuilder" for f in findings), findings)

    def test_accented_comment_is_normalized_and_reported(self):
        td, root = self._repo({"pkg/mod.py": "# verificação do arquivo\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "comment" for f in findings), findings)

    def test_docstring_is_scanned(self):
        td, root = self._repo({"pkg/mod.py": 'def build():\n    """Validar a amostra antes da chamada."""\n    return 1\n'})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertTrue(any(f.kind == "docstring" for f in findings), findings)

    def test_contract_literal_is_removed_before_comment_word_scan(self):
        td, root = self._repo({"pkg/mod.py": "# external status remains NÃO DISPONÍVEL\nvalue = 1\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())

    def test_historical_root_is_not_scanned(self):
        td, root = self._repo({"docs/history/v3.3/example.py": "def validar_arquivo():\n    return True\n"})
        with td:
            findings = scan_repository(root, load_policy(root))
        self.assertEqual(findings, ())
```

- [ ] **Step 2: Run the scanner tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.PythonLanguageScannerTest -v
```

Expected: FAIL because scanning interfaces are not implemented.

- [ ] **Step 3: Implement normalized token matching without executing repository code**

Add:

```python
import ast
import tokenize
import unicodedata
from collections import Counter

SKIP_PARTS = frozenset({".git", "node_modules", "dist", "__pycache__", ".pytest_cache", ".venv"})


@dataclass(frozen=True, order=True)
class LanguageFinding:
    path: str
    line: int
    kind: str
    token: str
    matched_terms: tuple[str, ...]


def _normalize_word(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _identifier_words(identifier: str) -> tuple[str, ...]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return tuple(
        word
        for part in re.split(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9]+", expanded)
        if (word := _normalize_word(part))
    )
```

Implement AST traversal for identifiers from:

- `ast.Name.id`;
- function/async-function names and argument names;
- class names;
- attribute names;
- assignment targets;
- imported names and aliases (`ast.alias.name` / `asname`);
- keyword argument names;
- exception/global/nonlocal bindings;
- structural-pattern capture names.

Exact normative contract literals remain protected. Imported names are scanned because re-exports are part of repository implementation vocabulary; deliberate compatibility exceptions must remain explicit rather than becoming a broad import bypass.

Use `tokenize.generate_tokens()` for `COMMENT` tokens and AST first-statement string literals for module/class/function docstrings. Before comment/docstring word matching, remove exact `contract_literals` from the text. Do not scan ordinary string literals in PR 1.

`scan_repository()` must skip any path containing a `SKIP_PARTS` component and skip only the explicit `excluded_roots` loaded from policy. It must not silently add runtime-code directories to exclusions.

If a Python file cannot be read or parsed/tokenized, raise `LanguagePolicyError` with the relative path; the repository guard must fail closed rather than skip the file.

- [ ] **Step 4: Group duplicate occurrences only after scanning**

Keep `LanguageFinding` occurrence-level for diagnostics. Add:

```python
def group_findings(findings: tuple[LanguageFinding, ...]) -> tuple[BaselineEntry, ...]:
    counts = Counter((f.path, f.kind, f.token) for f in findings)
    return tuple(
        BaselineEntry(path=path, kind=kind, token=token, count=count)
        for (path, kind, token), count in sorted(counts.items())
    )
```

This makes baseline identity independent of line-number movement while still detecting partial cleanup through `count` changes.

- [ ] **Step 5: Re-run scanner tests**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.PythonLanguageScannerTest -v
```

Expected: PASS.

- [ ] **Step 6: Commit the scanner**

```bash
git add scripts/code_language_guard.py tests/test_code_language_guard.py
git commit -m "feat: detect Portuguese Python implementation language"
```

---

### Task 3: Legacy debt baseline with exact drift detection

**Files:**
- Modify: `scripts/code_language_guard.py`
- Modify: `config/code_language_legacy_baseline.json`
- Modify: `tests/test_code_language_guard.py`

**Interfaces:**
- Consumes: grouped current findings and grouped baseline entries.
- Produces: `BaselineDelta`, `compare_to_baseline(current: tuple[BaselineEntry, ...], baseline: tuple[BaselineEntry, ...]) -> BaselineDelta`, `validate_code_language(root: Path, errors: list[str]) -> None`, CLI modes `--check`, `--bootstrap-baseline --source-commit <sha>`, and reduction-only `--write-baseline --source-commit <sha>`.

- [ ] **Step 1: Write failing tests that distinguish new debt from resolved debt**

Add:

```python
from scripts.code_language_guard import BaselineEntry, compare_to_baseline


class LanguageBaselineTest(unittest.TestCase):
    def test_new_finding_is_unexpected(self):
        current = (BaselineEntry("pkg/a.py", "identifier", "validar_arquivo", 1),)
        delta = compare_to_baseline(current, ())
        self.assertEqual(delta.unexpected, current)
        self.assertEqual(delta.stale, ())

    def test_resolved_finding_makes_baseline_stale(self):
        baseline = (BaselineEntry("pkg/a.py", "identifier", "validar_arquivo", 1),)
        delta = compare_to_baseline((), baseline)
        self.assertEqual(delta.unexpected, ())
        self.assertEqual(delta.stale, baseline)

    def test_partial_cleanup_changes_count_and_requires_baseline_update(self):
        baseline = (BaselineEntry("pkg/a.py", "comment", "validar", 2),)
        current = (BaselineEntry("pkg/a.py", "comment", "validar", 1),)
        delta = compare_to_baseline(current, baseline)
        self.assertEqual(delta.unexpected, current)
        self.assertEqual(delta.stale, baseline)
```

- [ ] **Step 2: Run the baseline tests and verify they fail**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.LanguageBaselineTest -v
```

Expected: FAIL because `compare_to_baseline` is absent.

- [ ] **Step 3: Implement exact set comparison and the library validation entrypoint**

Add:

```python
@dataclass(frozen=True)
class BaselineDelta:
    unexpected: tuple[BaselineEntry, ...]
    stale: tuple[BaselineEntry, ...]

    @property
    def clean(self) -> bool:
        return not self.unexpected and not self.stale


def compare_to_baseline(
    current: tuple[BaselineEntry, ...],
    baseline: tuple[BaselineEntry, ...],
) -> BaselineDelta:
    current_set = set(current)
    baseline_set = set(baseline)
    return BaselineDelta(
        unexpected=tuple(sorted(current_set - baseline_set)),
        stale=tuple(sorted(baseline_set - current_set)),
    )


def validate_code_language(root: Path, errors: list[str]) -> None:
    policy = load_policy(root)
    baseline = load_baseline(root)
    current = group_findings(scan_repository(root, policy))
    delta = compare_to_baseline(current, baseline)
    errors.extend(
        f"new Portuguese technical language debt: {entry.path}: {entry.kind}: {entry.token}: {entry.count}"
        for entry in delta.unexpected
    )
    errors.extend(
        f"resolved language baseline entry must be removed: {entry.path}: {entry.kind}: {entry.token}: {entry.count}"
        for entry in delta.stale
    )
```

`validate_code_language()` deliberately raises `LanguagePolicyError` from invalid/missing policy, baseline, or source parsing so `validate_repo.py` can fail closed with a single integration wrapper in Task 4.

- [ ] **Step 4: Implement deterministic CLI behavior**

Implement:

```text
python3 scripts/code_language_guard.py --check
```

- exit 0 only when the current grouped findings exactly match the tracked legacy baseline;
- before comparison, in GitHub `pull_request` CI require `source_commit` to equal the runner-provided `pull_request.base.sha` exactly; outside pull-request CI require it to be a real ancestor commit; in all cases prove every baseline entry/count is supported by findings measured from that immutable Git tree;
- print each unexpected entry as `NEW_LANGUAGE_DEBT\t<path>\t<kind>\t<token>\t<count>`;
- print each stale entry as `RESOLVED_BASELINE_ENTRY\t<path>\t<kind>\t<token>\t<count>`;
- exit 1 on either kind of delta;
- exit 2 on invalid policy/baseline/provenance or unreadable/unparseable scanned source.

Implement two distinct baseline-writing modes:

```text
python3 scripts/code_language_guard.py --bootstrap-baseline --source-commit <40-hex-base-sha>
python3 scripts/code_language_guard.py --write-baseline --source-commit <40-hex-base-sha>
```

- require `--source-commit` in either writing mode and resolve it as a real Git commit that is an ancestor of `HEAD`;
- bootstrap findings from the Git tree of `source_commit`, never from the current worktree; if a baseline already exists, bootstrap may refresh detector coverage only for the same recorded source commit;
- normal `--write-baseline` is reduction-only: reject new keys and count increases relative to the tracked baseline;
- before writing a reduction, prove each retained current finding also exists in the explicitly supplied source commit at an equal or greater count;
- preserve schema and set `source_commit` only to the verified commit supplied explicitly;
- use `ensure_ascii=False`, `indent=2`, sorted entries, and a final newline.

- [ ] **Step 5: Generate the initial baseline against the recorded implementation base**

Confirm the recorded base is unchanged:

```bash
printf '%s\n' "$BASE_SHA"
git merge-base HEAD main
```

The merge-base must equal `BASE_SHA`; otherwise synchronize/restart the implementation branch before generating the initial baseline.

Then run:

```bash
python3 scripts/code_language_guard.py --bootstrap-baseline --source-commit "$BASE_SHA"
python3 scripts/code_language_guard.py --check
```

Expected: `--check` exits 0 immediately after deterministic baseline generation.

Review the generated file and confirm every entry references active `.py` code, not `docs/history/**` or `normative/sealed/**`.

- [ ] **Step 6: Add repository-level baseline regression**

Add:

```python
from scripts.code_language_guard import group_findings


class RepositoryLanguageBaselineTest(unittest.TestCase):
    def test_repository_matches_tracked_language_baseline(self):
        policy = load_policy(ROOT)
        baseline = load_baseline(ROOT)
        current = group_findings(scan_repository(ROOT, policy))
        delta = compare_to_baseline(current, baseline)
        self.assertTrue(delta.clean, delta)
```

- [ ] **Step 7: Run all language-guard tests**

Run:

```bash
python3 -m unittest tests.test_code_language_guard -v
```

Expected: PASS.

- [ ] **Step 8: Commit the baseline mechanism and generated debt inventory**

```bash
git add scripts/code_language_guard.py config/code_language_legacy_baseline.json tests/test_code_language_guard.py
git commit -m "test: pin legacy Portuguese code language debt"
```

---

### Task 4: Integrate the guard into the repository contract

**Files:**
- Modify: `scripts/validate_repo.py`
- Modify: `tests/test_code_language_guard.py`

**Interfaces:**
- Consumes: `validate_code_language(root: Path, errors: list[str]) -> None` from `scripts.code_language_guard`.
- Produces: language-policy violations as ordinary `validate_repo.py` errors, preserving the existing single repository-gate entrypoint.

- [ ] **Step 1: Write a failing integration test**

Add:

```python
from unittest import mock

import scripts.validate_repo as validate_repo


class ValidateRepoLanguageIntegrationTest(unittest.TestCase):
    def test_validate_repo_invokes_language_guard(self):
        errors: list[str] = []
        with mock.patch.object(
            validate_repo,
            "validate_code_language",
            side_effect=lambda root, out: out.append("language guard sentinel"),
        ) as guard:
            validate_repo.validate_language_policy(ROOT, errors)
        guard.assert_called_once_with(ROOT, errors)
        self.assertEqual(errors, ["language guard sentinel"])
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.ValidateRepoLanguageIntegrationTest -v
```

Expected: FAIL because the integration wrapper/import does not yet exist.

- [ ] **Step 3: Add the narrow `validate_repo.py` integration**

Import:

```python
from scripts.code_language_guard import LanguagePolicyError, validate_code_language
```

Add:

```python
def validate_language_policy(root: Path, errors: list[str]) -> None:
    try:
        validate_code_language(root, errors)
    except LanguagePolicyError as exc:
        errors.append(f"code language policy unavailable: {exc}")
```

Call `validate_language_policy(ROOT, errors)` in the existing validation sequence before the final `if errors:` decision. Do not create a separate GitHub Actions workflow.

`validate_code_language()` must append actionable messages for new/stale debt and must not print PASS itself when called as a library.

- [ ] **Step 4: Protect the executable policy files as required repository paths**

Add these active files to `REQUIRED_PATHS` in `scripts/validate_repo.py`:

```text
config/code_language_policy.json
config/code_language_legacy_baseline.json
scripts/code_language_guard.py
```

Do not add the documentation file in this task; Task 5 creates it and then adds it to `REQUIRED_PATHS`, keeping every task's committed state independently valid.

- [ ] **Step 5: Re-run integration and focused repository validation**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.ValidateRepoLanguageIntegrationTest -v
python3 scripts/code_language_guard.py --check
python3 scripts/validate_repo.py
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit repository-gate integration**

```bash
git add scripts/validate_repo.py tests/test_code_language_guard.py
git commit -m "ci: enforce code language baseline in repository validation"
```

---

### Task 5: Document the policy and agent rules

**Files:**
- Create: `docs/CODE_LANGUAGE_POLICY.md`
- Modify: `AGENTS.md`
- Modify: `scripts/validate_repo.py`
- Modify: `tests/test_code_language_guard.py`

**Interfaces:**
- Consumes: the approved spec classification A–E and scanner behavior.
- Produces: developer instructions that match executable enforcement exactly.

- [ ] **Step 1: Write a failing documentation-contract test**

Add:

```python
class LanguagePolicyDocumentationTest(unittest.TestCase):
    def test_agent_and_policy_docs_name_the_enforced_contract(self):
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        policy_doc = (ROOT / "docs" / "CODE_LANGUAGE_POLICY.md").read_text(encoding="utf-8")
        self.assertIn("English-first technical code", agents)
        self.assertIn("code_language_legacy_baseline.json", agents)
        self.assertIn("Category A — Private implementation identifier", policy_doc)
        self.assertIn("Category E — Immutable or historical evidence", policy_doc)
        self.assertIn("python3 scripts/code_language_guard.py --check", policy_doc)
```

- [ ] **Step 2: Run the documentation test and verify it fails**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.LanguagePolicyDocumentationTest -v
```

Expected: FAIL because the new documentation and AGENTS wording are absent.

- [ ] **Step 3: Create `docs/CODE_LANGUAGE_POLICY.md`**

The document must state these exact operational rules:

- implementation language is English;
- pt-BR remains valid for localized/user-facing report content;
- canonical normative values and hash-bound/historical artifacts are preserved;
- Category A = private implementation identifier;
- Category B = public or cross-module identifier;
- Category C = serialized or persisted contract;
- Category D = user-facing localized content;
- Category E = immutable or historical evidence;
- `config/code_language_policy.json` contains deliberate policy/exceptions;
- `config/code_language_legacy_baseline.json` contains temporary measured debt, not approved style;
- adding a baseline entry to make CI pass is forbidden unless the PR explicitly documents why the new occurrence cannot yet be migrated without breaking compatibility;
- normal development must run `python3 scripts/code_language_guard.py --check`;
- migration PRs that remove Portuguese debt run `--write-baseline --source-commit <base-sha>` only after reviewing the diff; the command rejects new keys/count increases and verifies retained entries against that Git source tree;
- PR 1 enforces Python only; the same policy applies to other languages, whose automated adapters are introduced before their bulk migration layers.

- [ ] **Step 4: Update `AGENTS.md`**

Under change-control/before-editing guidance, add a concise section containing:

```markdown
## Code language policy

- English-first technical code is required for new implementation identifiers, comments and docstrings.
- Portuguese remains valid only where it is an explicit normative, serialized compatibility, localized, canonical, or historical requirement.
- `config/code_language_legacy_baseline.json` records pre-migration debt; it is not permission to add new Portuguese implementation language.
- Run `python3 scripts/code_language_guard.py --check` for changes touching scanned languages.
- When a migration removes tracked debt, update the baseline in the same PR and review the generated diff.
```

- [ ] **Step 5: Protect the policy documentation as a required repository path**

Add:

```text
docs/CODE_LANGUAGE_POLICY.md
```

to `REQUIRED_PATHS` in `scripts/validate_repo.py` only after the file exists.

- [ ] **Step 6: Run the documentation and repository contract tests**

Run:

```bash
python3 -m unittest tests.test_code_language_guard.LanguagePolicyDocumentationTest -v
python3 scripts/validate_repo.py
```

Expected: PASS/exit 0.

- [ ] **Step 7: Commit documentation**

```bash
git add docs/CODE_LANGUAGE_POLICY.md AGENTS.md scripts/validate_repo.py tests/test_code_language_guard.py
git commit -m "docs: establish English-first code language policy"
```

---

### Task 6: Full validation, mutation checks, and PR evidence

**Files:**
- Modify only if a validation exposes a defect directly caused by PR 1.
- Review all files changed by Tasks 1–5.

**Interfaces:**
- Consumes: complete PR 1 diff.
- Produces: local validation evidence and a reviewable PR-ready branch; no merge.

- [ ] **Step 1: Prove the guard rejects new debt**

Create a temporary untracked file under a scanned active path:

```bash
cat > scripts/_language_guard_probe.py <<'PY'
def validar_arquivo():
    # verificar a amostra
    return True
PY
python3 scripts/code_language_guard.py --check
rm scripts/_language_guard_probe.py
```

Expected: exit 1 with at least one `NEW_LANGUAGE_DEBT` line naming `scripts/_language_guard_probe.py`. Do not add the probe to Git.

- [ ] **Step 2: Prove the guard detects stale debt**

Use a temporary synthetic entry without editing the tracked baseline:

```bash
python3 - <<'PY'
from scripts.code_language_guard import BaselineEntry, compare_to_baseline, load_baseline
from pathlib import Path

root = Path.cwd()
baseline = load_baseline(root)
synthetic = BaselineEntry(
    path='scripts/nonexistent.py',
    kind='identifier',
    token='validar_arquivo',
    count=1,
)
delta = compare_to_baseline((), (synthetic,))
assert delta.stale == (synthetic,), delta
print('STALE_BASELINE_DETECTION_PASS')
PY
```

Expected: `STALE_BASELINE_DETECTION_PASS`.

- [ ] **Step 3: Run the complete focused suite**

```bash
python3 -m unittest tests.test_code_language_guard -v
```

Expected: PASS.

- [ ] **Step 4: Run repository baseline validation required by `AGENTS.md`**

```bash
python3 scripts/code_language_guard.py --check
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 -m unittest discover -s tests -v
bash -n scripts/*.sh
```

Expected: all commands exit 0. Record the actual unittest count rather than predicting it in the PR body.

- [ ] **Step 5: Run policy-engine and MCP regression suites because repository-wide validation policy changed**

```bash
cd policy_engine
python -m unittest discover -s tests -v
python -m genoma_policy ruleset-check
cd ..
python -m compileall -q policy_engine/genoma_policy scripts
cd mcp
npm ci --ignore-scripts
npm test
cd ..
```

Expected: all available commands exit 0. If an environment-specific dependency prevents a command from running, report `NÃO DISPONÍVEL`/not executed accurately in the PR rather than weakening the check.

- [ ] **Step 6: Review canonical identity and artifact drift**

Run:

```bash
git diff main -- manifests normative template_store reporting/reference_v3_manifest.json
git diff --check
git status --short
git diff --stat main
git diff main
```

Expected:

- no changes under `manifests/`, `normative/`, or `template_store/`;
- no changes to `reporting/reference_v3_manifest.json`;
- no whitespace errors;
- implementation diff limited to the seven planned policy/guard/documentation files; design/plan documents may also appear if they intentionally travel with PR 1.

- [ ] **Step 7: Run CodeRabbit CLI only if installed and authenticated**

```bash
coderabbit review --agent --base main -c AGENTS.md
```

If unavailable or unauthenticated, record that state exactly and rely on the GitHub App after opening the PR, as required by repository governance.

- [ ] **Step 8: Create the PR without auto-merge**

PR title:

```text
chore: establish English-first code language guardrails
```

PR body must explicitly state:

- scope is policy/guardrails only; no bulk translation yet;
- Python is the first automated scan adapter;
- current Portuguese Python implementation debt is measured in a generated baseline;
- new debt and stale/resolved baseline entries both fail closed;
- normative, serialized, localized, canonical, and historical Portuguese content remains supported;
- canonical ruleset identity/hash and scientific behavior are unchanged;
- commands actually executed and exact results;
- CodeRabbit/CI status only after those checks actually run;
- merge remains manual and requires human approval.

---

## Self-review result

### Spec coverage

- English-first policy: Tasks 1 and 5.
- Explicit preservation of normative/localized/historical content: Tasks 1, 2, and 5.
- Legacy debt distinguished from deliberate exceptions: Tasks 1 and 3.
- New Portuguese technical identifiers/comments detectable: Task 2.
- Guard integrated into existing validation: Task 4.
- No broad suppression: policy loader and exact excluded-root reasons in Task 1; repository mutation tests in Task 6.
- Behavior/canonical compatibility: Global Constraints and Task 6.
- Rollback-friendly scope: independent PR 1 with no runtime rename.
- Human merge gate: Global Constraints and Task 6.

### Type/interface consistency

The plan uses one stable interface chain throughout:

`load_policy` → `scan_repository` → `group_findings` → `load_baseline` → `compare_to_baseline` → `validate_code_language` → `validate_repo.validate_language_policy`.

`BaselineEntry(path, kind, token, count)` is the only persisted finding identity. Line numbers remain diagnostic-only in `LanguageFinding`, so unrelated line movement cannot rewrite the baseline while count changes still expose partial cleanup.
