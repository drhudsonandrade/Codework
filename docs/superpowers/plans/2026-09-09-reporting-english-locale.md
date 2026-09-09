# Reporting English Implementation and pt-BR Ownership Plan

> **For agentic workers:** Use superpowers:executing-plans with test-first verification.

**Goal:** Complete stage 5 without translating report output or changing publication behavior.
**Architecture:** Keep English implementation names; extract fixed presentation text from the Markdown/HTML engine and programmatic PDF/DOCX renderer into a static pt-BR module. No locale selector, fallback, schema change or new dependency is introduced.
**Tech Stack:** Python standard library, existing ReportLab/python-docx/PyMuPDF, unittest.
**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`, stage 5.
**Base:** `0a643128f3ac3e99a51428644c3012a2d638ab8b` (manual merge of PR #60).

## Global constraints

- Preserve all pt-BR output strings, punctuation, whitespace, order and HTML escaping.
- Preserve callable signatures, public import names, metadata keys, filenames and digests.
- Keep publication/provenance checks and explicit programmatic FINAL authorization intact.
- Do not translate normative states, wire keys, catalog/coordinate keys or sealed content.
- Do not edit clinical/genomic data, canonical report assets, templates or historical evidence.
- No real genomic interpretation, calling, deployment, permission change or auto-merge.
- Local output comparisons use synthetic fixtures only and do not grant publication approval.

## Inventory and decisions

A bounded inspection covers 33 Python files in reporting, its generator scripts and
report/editorial/template tests. No candidate Portuguese implementation identifiers were
found by the recorded token vocabulary. Accented prose candidates quote normative values,
report names or test data and remain unchanged. This is not proof over all natural language.

The useful change is explicit presentation ownership. `reporting/locale_pt_br.py` owns
fixed captions, headings and notices used by `reporting/engine.py` and
`reporting/editorial_v3_hifi.py`. For example:

```python
# reporting/locale_pt_br.py
PURPOSE = "Finalidade"
# renderer
Paragraph(pt_br.PURPOSE, styles["Section"])
```

Report-specific content remains owned by the unchanged catalog, upstream payload and
canonical template pack. Serialized operational states and renderer-disclosure contracts
remain where their validators own them. No unsupported English-output mode is advertised.

## Task 1: Characterize the existing boundary and write RED tests

- [ ] Create `tests/reporting_language_fixtures.py` with deterministic synthetic payloads.
- [ ] Capture baseline Markdown/HTML and serialized bundle hashes for models 01..11 in
  MODEL and FINAL modes in `tests/fixtures/reporting_language_baseline.json` before edits.
- [ ] Pin these baseline results to the base SHA; never regenerate expectations to hide drift.
- [ ] Add `tests/test_reporting_language_compatibility.py`: exact output snapshots, explicit
  locale imports and English constant names, unchanged defaults/escaping, protected output
  metadata, publication refusals and programmatic authorization behavior.
- [ ] Run `python -m unittest tests.test_reporting_language_compatibility -v`.
  Expected RED: locale ownership is absent. Existing-output characterization must pass.

## Task 2: Extract presentation text without changing its value

- [ ] Create the static `reporting/locale_pt_br.py` with English names and exact old values.
- [ ] Replace only inventoried presentation literals in `reporting/engine.py` and
  `reporting/editorial_v3_hifi.py`; keep runtime keys, normative values and business logic.
- [ ] Keep catalog-driven content in the catalog, not copied into a second catalog.
- [ ] Apply only necessary touched-file documentation/style hygiene; compare executable
  ASTs after reversing the documented literal extraction and removing docstrings.
- [ ] Run the targeted suite GREEN. Mutate one label and restore it to prove drift is caught.

## Task 3: Independent comparison and release evidence

- [ ] Compare baseline/candidate Markdown, HTML, JSON and output filenames for all 11 models.
- [ ] Render representative synthetic programmatic PDFs/DOCX before and after; compare PDF
  page text/geometry/raster and DOCX package XML, excluding only nondeterministic metadata.
  No claim of parity with the canonical template pack follows from programmatic comparisons.
- [ ] Verify every tracked file outside the explicit change list byte-identical to the base.
- [ ] Run root tests, language/repository/supply-chain gates, compileall, shell syntax and
  applicable touched-file style checks. Record unavailable runtime explicitly.
- [ ] Create `docs/REPORTING_CODE_LANGUAGE_INVENTORY.md` and update design progress.
- [ ] Commit, rerun exact-SHA validation, publish a coherent block to the Draft PR, then
  mark Ready and verify actual CodeRabbit review and applicable CI on the same SHA.
- [ ] Leave approval and merge manual. Do not bypass gates or generate redundant pushes.

## Repository-validator consumer adaptation

The full repository gate exposed a source-location dependency: it required
`RESULTADO GENÔMICO` literally inside `editorial_v3_hifi.py`. The display string
now belongs to `locale_pt_br.py`, so a comment containing that phrase would be a
false fix. `scripts/validate_repo.py` instead requires the locale file and checks
its unique literal-string declarations with AST parsing, never importing it.
It preserves the exact result caption and `pt-BR` tag, checks the renderer absolute-import
binding, and requires references to the caption in both `_pdf` and `_docx`.
The existing color/font/writer markers and every other repository gate remain.
This is a static presentation contract, not a general Python data-flow proof.

Additional intentional files: `scripts/validate_repo.py` and
`tests/test_reporting_presentation_gate.py`. The latter contains six tests for
acceptance, missing/changed/duplicate/computed literals, incorrect imports,
missing use, nonexecution of source, required-path registration, and dispatch
through the full repository validator. Five test methods failed before the
helper existed; the full-dispatch characterization was then added and checked
by temporarily replacing the callback with a no-op in memory. No runtime guard
or assertion is disabled in the repository.

Reproduce the actual targeted suites with:

```bash
python -m unittest tests.test_reporting_language_compatibility tests.test_reporting_presentation_gate -v
python scripts/validate_repo.py
```

The renderer AST comparison still covers the same two source files. The validator
is now an explicitly tested change rather than an unchanged-file claim, leaving
390 protected baseline files. The earlier 391-file comparison remains in the
local historical log; it predates the validator adaptation and is not final
release evidence. No protected scientific or canonical file was excluded to
conceal a change.

## Evidence and continuity

The checklist is planned work, not execution evidence. Completed results must identify
commit/tree, actual commands, results and retained log digests in the PR. This avoids
self-referential commit hashes. Later commits never inherit earlier validation.
Evidence root: `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/`.
This is a local locator, not a download URL. The initial planning PR identifies the active
writer to reduce concurrent work; no other branch should overwrite this implementation.

## Delivered-HEAD evidence binding

The [exact-HEAD evidence record](https://github.com/drhudsonandrade/Codework/pull/61#issuecomment-5601896618)
is the authoritative locator for completed validation. It must name the tested
commit and tree, actual command results and retained log SHA-256 digests. Until
it names the delivered HEAD, that HEAD's validation is PENDING. The planning
commit or the baseline suite cannot certify a later implementation commit.

Historical RED and mutation logs describe worktree tests, not fictitious committed
revisions. Golden output expectations were captured with the reporting source
unchanged from the fixed base; test clock correction preceded implementation.

## Portable source and protected-asset comparison

From a full-history checkout of the commit being reviewed, execute the following
standard-library-only procedure. It expects the documented literal extraction,
not arbitrary normalization of new logic. A later unrelated main is not the same
comparison target. The expected scope is two existing source ASTs and 390
out-of-scope tracked files; validate the actual count rather than assuming it.

```bash
python - <<'PY'
"""Reproduce stage-five source and protected-byte equivalence from a full-history clone."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path.cwd()
BASE = "0a643128f3ac3e99a51428644c3012a2d638ab8b"
MIGRATED = ("reporting/engine.py", "reporting/editorial_v3_hifi.py")
EXPECTED_CHANGES = set(MIGRATED) | {
    "reporting/locale_pt_br.py",
    "scripts/validate_repo.py",
    "tests/test_reporting_presentation_gate.py",
    "tests/reporting_language_fixtures.py",
    "tests/test_reporting_language_compatibility.py",
    "tests/fixtures/reporting_language_baseline.json",
    "docs/REPORTING_CODE_LANGUAGE_INVENTORY.md",
    "docs/superpowers/plans/2026-09-09-reporting-english-locale.md",
    "docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md",
}
record = json.loads((ROOT / "tests/fixtures/reporting_language_baseline.json").read_text(encoding="utf-8"))
assert record["base_sha"] == BASE
texts = record["presentation_text"]
locale_tree = ast.parse((ROOT / "reporting/locale_pt_br.py").read_text(encoding="utf-8"))
actual = {statement.targets[0].id: ast.literal_eval(statement.value)
          for statement in locale_tree.body if isinstance(statement, ast.Assign)}
assert actual == texts, "presentation values differ from the recorded original values"


class RestorePresentation(ast.NodeTransformer):
    """Reverse only the documented extraction, docstrings and unused os import."""

    def visit_ImportFrom(self, node):
        if node.module == "reporting" and [(item.name, item.asname) for item in node.names] == [
            ("locale_pt_br", "pt_br")
        ]:
            return None
        return node

    def visit_Import(self, node):
        if [(item.name, item.asname) for item in node.names] == [("os", None)]:
            return None
        return node

    def visit_Attribute(self, node):
        if isinstance(node.value, ast.Name) and node.value.id == "pt_br":
            assert node.attr in texts, node.attr
            return ast.copy_location(ast.Constant(texts[node.attr]), node)
        return self.generic_visit(node)

    def visit_JoinedStr(self, node):
        self.generic_visit(node)
        merged = []
        for item in node.values:
            if (isinstance(item, ast.FormattedValue) and item.conversion == -1
                    and item.format_spec is None and isinstance(item.value, ast.Constant)
                    and isinstance(item.value.value, str)):
                item = item.value
            if (merged and isinstance(item, ast.Constant)
                    and isinstance(merged[-1], ast.Constant)):
                merged[-1].value += item.value
            else:
                merged.append(item)
        node.values = merged
        return node

    def _without_docstring(self, node):
        self.generic_visit(node)
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            node.body.pop(0)
        return node

    visit_Module = _without_docstring
    visit_FunctionDef = _without_docstring
    visit_ClassDef = _without_docstring


matched = []
for relative in MIGRATED:
    original = subprocess.check_output(["git", "show", f"{BASE}:{relative}"])
    candidate = (ROOT / relative).read_bytes()
    before = RestorePresentation().visit(ast.parse(original))
    after = RestorePresentation().visit(ast.parse(candidate))
    assert ast.dump(before) == ast.dump(after), f"executable AST differs: {relative}"
    matched.append(relative)

protected = []
files = subprocess.check_output(["git", "ls-tree", "-rz", "--name-only", BASE]).split(b"\0")
for name in files:
    if not name:
        continue
    relative = name.decode("utf-8")
    if relative in EXPECTED_CHANGES:
        continue
    original = subprocess.check_output(["git", "show", f"{BASE}:{relative}"])
    assert original == (ROOT / relative).read_bytes(), f"out-of-scope bytes differ: {relative}"
    protected.append({"path": relative, "sha256": hashlib.sha256(original).hexdigest()})
result = {"base": BASE, "ast_matches": matched, "protected_files": protected}
digest = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
print(json.dumps({"base": BASE, "ast_matches": len(matched), "protected_files": len(protected),
                  "comparison_sha256": digest}, indent=2))
PY
```

The comparison record digest observed during implementation is
`cd81d90e1d03d2d645ce286973d3673779a04a9393a644f7334d37a46e6aaa92`.
This digest identifies the fixed base and protected byte list; a candidate must
still execute the comparisons. It is not proof that an untested later SHA passed.

## Portable output replay against the actual base

Use the repository's pinned reporting dependencies in the selected Python
interpreter. This replays the same test fixture helper against the original
production source as well as the candidate; it does not regenerate golden
expectations from modified production code.

```bash
set -eu
repo=$(git rev-parse --show-toplevel)
base=0a643128f3ac3e99a51428644c3012a2d638ab8b
work=$(mktemp -d)
mkdir "$work/base"
git archive "$base" | tar -x -C "$work/base"
cp tests/reporting_language_fixtures.py "$work/base/tests/"
for checkout in "$work/base" "$repo"; do
  (cd "$checkout" && PYTHONPATH=tests:. python - <<'PY'
import json
from tests.reporting_language_fixtures import output_snapshot
print(json.dumps(output_snapshot(), ensure_ascii=False, sort_keys=True, indent=2))
PY
  ) > "$work/$(test "$checkout" = "$repo" && echo candidate || echo base).json"
done
cmp "$work/base.json" "$work/candidate.json"
sha256sum "$work/base.json" "$work/candidate.json"
printf 'Retained synthetic output comparisons: %s\n' "$work"
```

The golden test is a separate direct check against the recorded pre-migration
hashes, including the 22 public cases and one private formatting case:

```bash
PYTHONPATH=tests:. python -m unittest tests.test_reporting_language_compatibility -v
```

## Representative PDF/DOCX comparison

After the base/candidate setup above, create the following temporary probe.
It passes explicit synthetic-QA authorization to the existing public writer;
it never claims a patient report or template-pixel parity. The DOCX comparison
checks decompressed package entries, not ZIP timestamps. PDF comparison checks
page text, geometry and raster bytes, not volatile file identifiers/timestamps.

```bash
cat > "$work/artifact_probe.py" <<'PY'
"""Capture synthetic PDF raster/text and DOCX package contents for before/after QA."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import fitz

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))
from reporting import editorial_v3, provenance
from tests.reporting_language_fixtures import FixtureClock, render_fixture

output = Path(sys.argv[2])
output.mkdir(exist_ok=False)
records = {}
for report_id in ("01", "10"):
    rendered = render_fixture(report_id, "FINAL")
    with patch.object(provenance, "datetime", FixtureClock):
        files = editorial_v3.write_editorial_bundle(
            rendered, output / report_id,
            programmatic_final_authorization="synthetic before/after locale QA only",
        )
    with fitz.open(files["pdf"]) as document:
        pages = []
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            pixmap.save(str(output / report_id / f"page-{index+1}.png"))
            pages.append({"rect": list(page.rect), "text": page.get_text(),
                          "pixel_size": [pixmap.width, pixmap.height],
                          "pixel_sha256": hashlib.sha256(pixmap.samples).hexdigest()})
    with zipfile.ZipFile(files["docx"]) as package:
        parts = {name: hashlib.sha256(package.read(name)).hexdigest()
                 for name in sorted(package.namelist())}
    records[report_id] = {"pdf_pages": pages, "docx_parts": parts,
                          "filenames": {key: value.name for key, value in files.items()}}
(output / "snapshot.json").write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"reports": list(records), "pages": {key:len(value["pdf_pages"]) for key,value in records.items()}}))
PY
python "$work/artifact_probe.py" "$work/base" "$work/artifacts-base"
python "$work/artifact_probe.py" "$repo" "$work/artifacts-candidate"
cmp "$work/artifacts-base/snapshot.json" "$work/artifacts-candidate/snapshot.json"
sha256sum "$work/artifacts-base/snapshot.json" "$work/artifacts-candidate/snapshot.json"
```

Use the same interpreter, pinned libraries and available fonts for both sides.
The two reports contain three pages total in the test fixture. All page images
are saved by the probe for visual inspection. The initial before/after record
matched with digest `60b6e2492fc89bd83b0a74ef46a5a0f149cea37317111c7c44953be0ad98b9a1`;
platform or font differences may change that digest, but a same-environment
base/candidate comparison must agree. Final exact-SHA results belong in the linked
record rather than being inferred from this initial implementation comparison.

## Mandatory local checks

```bash
python scripts/code_language_guard.py --check
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
PYTHONPATH=tests:. python -m unittest discover -s tests -v
python -m compileall -q reporting scripts tests
for source in scripts/*.sh; do bash -n "$source"; done
git diff --check
```

Style checks apply to the six renderer/locale and fixture/test sources using pycodestyle with
100 columns, pydocstyle pep257 and Ruff E/F/B905 targeting Python 3.11. This stage changes no style
configuration. Additional Pylint/mypy results must distinguish pre-existing
production diagnostics from new issues; neither baseline equivalence nor a
scoped check implies whole-repository typing cleanliness. Tests deliberately
call private formatting helpers to characterize their existing contract.

No local Docker canary, production deployment or canonical-template rendering
is claimed without a separately executed result. Final applicable CI and actual
CodeRabbit approval are checked only on the delivered commit; skipped review
statuses and service quota notices are not completed reviews.

The static import check also requires absolute import level zero. A negative fixture
using `from .reporting import locale_pt_br as pt_br` passed the earlier check
unexpectedly; after adding the import-level comparison it is rejected. That fixture
remains in the existing six-method presentation-gate suite. No renderer output or
scientific control changes in this correction. The RED and GREEN logs are retained
as `absolute-import-red.log` and `absolute-import-green.log` in the evidence root;
final commit-bound results belong in the linked exact-HEAD record.

## Python 3.11 syntax compatibility

The runtime environment still pins `python=3.11`. A resumption check found
quote-reusing f-strings in the uncommitted engine extraction: they parse on
Python 3.12 but `ruff check --target-version py311 --select F` rejected them.
The engine was reformatted for the existing 3.11 target. Its executable AST
remained identical before/after that formatting, and the targeted syntax check
then passed. The before/after diagnostics are retained with release evidence.

`ast.parse(feature_version=(3, 11))` on the 3.12 executor did not reject these
f-strings, so that best-effort result is not used as compatibility proof.
This executor has Python 3.12.3 only: the Ruff target check is a static syntax
check, not a claim that the whole suite ran on a Python 3.11 interpreter. No
Python-version pin or dependency file was changed.

```bash
python -m ruff check --target-version py311 --select E,F,B905 --line-length 100 reporting/engine.py reporting/editorial_v3_hifi.py reporting/locale_pt_br.py tests/reporting_language_fixtures.py tests/test_reporting_language_compatibility.py tests/test_reporting_presentation_gate.py
```
