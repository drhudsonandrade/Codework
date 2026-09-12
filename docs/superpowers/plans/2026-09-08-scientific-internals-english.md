# Scientific Internals English Migration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to execute this approved stage task by task.

**Goal:** Finish the identified non-contractual scientific implementation-language debt without changing scientific execution or localized output.
**Architecture:** Reuse the Python language scanner for a bounded scientific-prose regression check. Translate only identified comments, docstrings and test names; preserve all runtime values, public imports, workflow names and shell contracts.
**Tech Stack:** Python 3.12 unittest/AST/tokenize; existing Nextflow and Bash contracts.
**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`, stage 3.
**Base:** `b46e2fae877d0f42896007bb681314861f366d62`, merged PR #58.

## Global constraints

- No change to calling behavior, QC thresholds, reference identity, evidence schemas, artifact filenames or Runtime/Resource Gate semantics.
- Preserve canonical v3.4 bytes, version/date, sealed transport and manifests.
- Preserve pt-BR runtime output and cross-module Portuguese constants; those are not private identifiers.
- No auto-merge; one coherent validated push followed by actual external review.
- Do not rename existing English Nextflow processes or Bash helpers merely to produce a diff.

## Task 1: Inventory and regression tests

Files: create `tests/test_scientific_code_language.py`; inspect `main.nf`, `workflows/*.nf`, `nextflow.config`, scientific shell scripts and scientific Python sources/tests.

- [x] Verify PR #58 merge and create an isolated branch from current main.
- [x] Run baseline: `python -m unittest discover -s tests -v` (950 tests, OK, one skipped).
- [x] Add scoped prose tests using `scan_python_file` and `dataclasses.replace(load_policy(ROOT), technical_terms=...)`, adding `termo`, `rotulo`, `controle`, `positivo` only in this test's local policy.
- [x] Require scientific test method names not to contain the private-name words `observado`, `nao`, `controle`, or `positivo`; do not apply this rule to public imported constants or wire values.
- [x] Include positive detection and localized-string acceptance fixtures so an empty/disabled scanner cannot silently pass.
- [x] Run `python -m unittest tests.test_scientific_code_language -v`; observe RED for the existing Portuguese prose/test names, not for syntax or import errors.

## Task 2: Scoped translation and analyzer hygiene

Files: modify `scripts/build_trait_targets.py`, `tests/test_completeness_regressions.py`, `tests/test_assessed_allele_presence.py` only as justified by the inventory.

- [x] Translate the two comments explaining `by_term.values()` while preserving that expression.
- [x] Translate the positive-control docstring in `test_a_single_base_assessed_allele_absent_from_the_genotype_is_not_detected` while retaining the `NÃO DETECTADO` wire-value quotation.
- [x] Rename the three private scientific tests from `observado` to `observed`; keep their assertions and imported values unchanged.
- [x] Check all consumers with `git grep` before renaming; no public symbol removal or alias introduction.
- [x] Address only blocking style/doc findings on touched files, using exact AST/runtime-literal comparison for formatting and the established standalone-script import pattern if required.
- [x] Run the new suite GREEN, existing completeness/assessed-allele/target-expansion tests and shell regressions.

## Task 3: Evidence, current stage and delivery

Files: create `docs/SCIENTIFIC_CODE_LANGUAGE_INVENTORY.md`; update only the current status in the approved design and the completed checklist here.

- [x] Record A-E classifications for every preserved surface, including localized diagnostics, public constants, serialized states and exact normative-header checks.
- [x] Record that this scanner checks known lexical debt, not a proof of natural-language completeness.
- [x] Compare executable ASTs against the base, allowing only documented test-method name changes and equivalent import bootstrap if needed.
- [x] Prove Nextflow, shell, thresholds/configuration, reference locks and canonical artifacts unchanged by Git blob comparison.
- [ ] Run `python scripts/code_language_guard.py --check`, `python scripts/validate_repo.py`, `python scripts/verify_supply_chain_lock.py`, full root unittest discovery, shell syntax, and compilation on final HEAD.
- [ ] Publish a Draft PR, then mark Ready only after local validation; inspect DeepSource, CodeRabbit and applicable CI on that exact SHA.
- [x] Record environmental limits honestly: Nextflow is not on this executor's PATH; Docker socket access is denied. Do not claim a local Nextflow/container canary or any real DNA analysis.
- [ ] Deliver a final checkpoint and leave human approval/manual merge outstanding.

## Reproducible validation evidence

The completed local checks below refer to the published implementation commit
`dcf49e582f6aed2d7601a35f3769664cb6c57976` (tree
`bde8260f7aa15843c003c4b3a532a14243114384`), not to a future merge or deployment.
Its exact-HEAD run recorded **955 root tests, OK (one skipped)**, the WGS
synthetic boundary regression PASS, source AST equivalence and 72 protected-file
byte comparisons. The earlier pre-commit 954-test run preceded the stream test;
it is historical evidence, not the final validation count.

From a full-history checkout of that commit, with Python 3.12 and the repository's
existing test dependencies installed, the commands are:

```bash
ROOT="$(git rev-parse --show-toplevel)"
python3 -m unittest discover -s tests -v
python3 -m unittest tests.test_scientific_code_language -v
PYTHON="$(command -v python3)"
(cd /tmp; "$PYTHON" -I "$ROOT/tests/test_assessed_allele_presence.py" -v)
bash tests/test_wgs_align_or_stage.sh
python3 scripts/code_language_guard.py --check
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
for script in scripts/*.sh; do bash -n "$script"; done
python3 -m compileall -q array_pipeline scripts policy_engine/genoma_policy reporting tests
```

Expected results at the named commit: 955 root tests (one skipped), five new
checks, 14 direct isolated assessed-allele tests and
`WGS alignment boundary regressions: PASS`. The 14-test isolated invocation and
the earlier 102-test focused invocation are recorded in `local-validation.log`;
all their tested existing source files are unchanged between that run and the
published implementation SHA. These counts are not additive independent suites.

### Local evidence locators and digests

Host: `legacy-operator` (Ubuntu). The retained evidence directory is:

`/srv/remote-desktop-commander-workspace/codework-audit/scientific-english-stage3/`

These local filesystem locators are **not public download URLs**. SHA-256 values
bind the retained files; the commands and portable comparison below let another
checkout reproduce the checks without access to this host. Retrieve PR #59 checks
at runtime with `repo=$(gh api repositories/1212760346 --jq .full_name); gh pr checks 59 --repo "$repo"`.

| File beneath that directory | SHA-256 | Recorded scope |
| --- | --- | --- |
| `final-validation.log` | `5b67ae33ae1b48a7320a6ce7dbd3005ba1a488df892d84a36a35dfa7b4a2565d` | Exact `dcf49e5` validation, 955 tests and compatibility checks |
| `compatibility.json` | `1b4c6e2474d07200ddca650c249b408208d02341d055ed85f3928d235d01729f` | Three normalized AST comparisons and the 72 file digests |
| `verify_compatibility.py` | `9d19c21517fe98cebe133902b4802270a73ecc594c4e91cd2a2c71489b3848cc` | Original host-bound comparison procedure |
| `local-validation.log` | `06407fd169123fbc334a385706f5141b1554f64c84d6592ba20bb6ddb6f99d2a` | Earlier 954-test tree, 102 focused tests, 14 isolated tests and WGS regression |
| `validation-afeb19d.log` | `28f6c278c1ef35907210428abac623d1c6a7569b15712dff79061db33f3acc6b` | Earlier published local commit `afeb19d`, before stream typing/test addition |

The later local static pass reproduced one ZIP/gzip assignment-type error in
`_open_associations`. The explicit local union annotation removed that diagnostic;
the plain/gzip/ZIP preservation test passed before and after the annotation.
The review follow-up additionally checks the underlying ZIP archive descriptor,
not only `stream.closed`; final follow-up evidence is recorded on the PR's new
exact SHA. Unchecked release items above remain pending until that evidence exists.

### Review-follow-up validation locator

The ZIP-descriptor assertion was tested on exact commit
`55057022f964e48f4f5934c52d132900936ca758`, tree
`b933146abbf2afb8886a4a56b7117a64d3dddeb6`.

Retained complete log on `legacy-operator`:
`/srv/remote-desktop-commander-workspace/codework-audit/scientific-english-stage3/review-final-validation.log`

SHA-256: `946177be7f9577ad46d83867864fab2e6edead10cac5845c239961481b6d30bf`.

Commands actually executed there include `python -m unittest discover -s tests -v`
(**955 tests, OK, one skipped**), the isolated assessed-allele invocation above
(**14 tests, OK**), and `bash tests/test_wgs_align_or_stage.sh` (**PASS**).
The root suite includes the strengthened ZIP archive-descriptor assertion.
To reproduce only that assertion, run from the root of the named checkout:

```bash
git rev-parse HEAD
python3 -m unittest tests.test_scientific_code_language.ScientificStreamCompatibilityTest -v
```

Expected result: one container-preservation test passes, including the ZIP-owner
closure assertion. The negative mutation evidence is retained at
`/srv/remote-desktop-commander-workspace/codework-audit/scientific-english-stage3/zip-close-mutation.log`
with SHA-256 `2d1bcb604b44805d1e7e072e33263360a1ae2862bbd0529f1f6ba807ea748a02`.
It records failure when only the text wrapper is closed and success with the
real implementation. This is distinct from the historical AST comparison below,
which is intentionally pinned to the original implementation revision.

These are completed historical execution records, not a claim about an untested
future commit. The same test commands apply to later corrective SHAs; the final
PR verification comment binds each latest execution to its actual HEAD, full
retained log path and SHA-256 without requiring a self-referential commit hash
inside this versioned plan. Pending release items remain pending until verified.

### Portable AST and protected-byte comparison

Run this read-only comparison from the repository root with full Git history.
It compares the named base and validated commit directly. It permits only the
three explicit private test renames, actual leading docstrings, the documented
bootstrap placement and the local stream annotation. Runtime literal values and
all remaining executable AST nodes must match. The protected bytes are compared
independently, without any normalization.

```bash
python3 - <<'PY_COMPARE'
"""Check stage-three source equivalence against the exact merged base."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path.cwd()
VALIDATED = 'dcf49e582f6aed2d7601a35f3769664cb6c57976'
BASE = 'b46e2fae877d0f42896007bb681314861f366d62'
RENAMES = {
    'test_a_genotype_carrying_one_of_the_alternates_is_observado':
        'test_a_genotype_carrying_one_of_the_alternates_is_observed',
    'test_a_locus_naming_no_base_stays_observado_and_says_so':
        'test_a_locus_naming_no_base_stays_observed_and_says_so',
    'test_observado_without_any_assessed_base_is_never_a_finding':
        'test_observed_without_any_assessed_base_is_never_a_finding',
}
PATHS = (
    'scripts/build_trait_targets.py',
    'tests/test_assessed_allele_presence.py',
    'tests/test_completeness_regressions.py',
)

def git(*args):
    return subprocess.check_output(['/usr/bin/git', '-C', str(ROOT), *args])

class StripDocs(ast.NodeTransformer):
    def visit_Module(self, node):
        return self.clean(node)
    def visit_ClassDef(self, node):
        return self.clean(node)
    def visit_FunctionDef(self, node):
        node.name = RENAMES.get(node.name, node.name)
        return self.clean(node)
    def clean(self, node):
        self.generic_visit(node)
        if node.body and isinstance(node.body[0], ast.Expr):
            value = node.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                node.body = node.body[1:]
        return node

results = []
for relative in PATHS:
    before = git('show', f'{BASE}:{relative}').decode('utf-8')
    after = git('show', f'{VALIDATED}:{relative}').decode('utf-8')
    if relative != 'tests/test_completeness_regressions.py':
        old = ('ROOT = Path(__file__).resolve().parents[1]\n'
               'if str(ROOT) not in sys.path:\n    sys.path.insert(0, str(ROOT))')
        new = ('if str(Path(__file__).resolve().parents[1]) not in sys.path:\n'
               '    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))')
        assert before.count(old) == 1, relative
        before = before.replace(old, new, 1)
        marker = 'DEFAULT_SCOPES = ROOT /' if relative.startswith('scripts/') else 'HEADER = ('
        assert before.count(marker) == 1, relative
        before = before.replace(marker, 'ROOT = Path(__file__).resolve().parents[1]\n\n' + marker, 1)
    if relative == 'scripts/build_trait_targets.py':
        before = before.replace('from typing import Any\n', 'from typing import Any, IO\n', 1)
        before = before.replace('    if path.suffix == ".zip":',
                                '    raw: IO[bytes] | gzip.GzipFile\n    if path.suffix == ".zip":', 1)
    original = StripDocs().visit(ast.parse(before))
    current = StripDocs().visit(ast.parse(after))
    assert ast.dump(original) == ast.dump(current), relative
    results.append({'path': relative, 'executable_ast_equivalent': True})
    print('EXECUTABLE_AST_EQ', relative)

protected = git('ls-files', 'main.nf', 'workflows', 'nextflow.config', 'array_pipeline',
                'scripts/*.sh', 'scripts/wgs_*.py', 'scripts/*runtime*gate*.py',
                'normative', 'manifests', 'config', 'environment.yml', 'Dockerfile').decode().splitlines()
identities = []
for relative in protected:
    before = git('show', f'{BASE}:{relative}')
    after = git('show', f'{VALIDATED}:{relative}')
    assert before == after, relative
    identities.append({'path': relative, 'sha256': hashlib.sha256(after).hexdigest()})
print('UNCHANGED_PROTECTED_FILES', len(identities))
output = {'base': BASE, 'source_comparisons': results, 'unchanged': identities}
serialized = (json.dumps(output, indent=2) + '\n').encode('utf-8')
digest = hashlib.sha256(serialized).hexdigest()
assert len(identities) == 72
assert digest == '1b4c6e2474d07200ddca650c249b408208d02341d055ed85f3928d235d01729f'
print('COMPATIBILITY_PASS', digest)
PY_COMPARE
```
