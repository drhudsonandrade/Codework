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
It also collects every `pt_br.<name>` read in both renderer sources and rejects
undefined names, including noncritical labels and Markdown/HTML-engine reads.
It preserves the exact result caption and `pt-BR` tag, checks the renderer absolute-import
binding, and requires references to the caption in both `_pdf` and `_docx`.
The existing color/font/writer markers and every other repository gate remain.
This is a static presentation contract, not a general Python data-flow proof.

Additional intentional files: `scripts/validate_repo.py` and
`tests/test_reporting_presentation_gate.py`. The current suite contains nine test methods for
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
is an explicitly tested change. The current proof checks 388 unchanged baseline
files and separately requires the exact enumerated type-only edits in
`reporting/deployment_target.py` and `reporting/provenance.py`. These two files
are not described as byte-identical. Earlier 391/390-file records remain historical
and cannot certify this expanded, explicitly bounded correction.

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

## Independent source, reference and protected-asset comparison

The proof is implemented in `scripts/verify_reporting_language_migration.py`.
Run it from a full-history checkout of the candidate SHA:

```bash
python scripts/verify_reporting_language_migration.py
python -m unittest tests.test_reporting_migration_verifier -v
```

The full-history proof requires both fixed Git objects to be present and fails
rather than substituting a missing reference. The verifier reads bytes from the immutable first publication
`c87b336a292f6c9f2fb490a51d2853b74ab72749`, not from the current candidate:

| Reference path | Required SHA-256 |
| --- | --- |
| `tests/fixtures/reporting_language_baseline.json` | `9cc84c09512dc0c0bea15ef4dc4da1fa41efb387eda61fc4eb727146fe66c2c8` |
| `tests/reporting_language_fixtures.py` | `58316c45089f8354cc8ce7007237fa27544185b7f0b550147591ad0eb7318fd0` |

Those files were captured using the unchanged base reporting source and first
published in that implementation commit. The reference commit is **not** falsely
presented as a pre-implementation commit. The runtime source baseline remains
`0a643128f3ac3e99a51428644c3012a2d638ab8b`. The verifier checks both historical
reference digests and candidate equality to those bytes. Changing a candidate
capture harness together with its expectations does not redefine the reference.

The verifier checks additions and deletions across the base and candidate tracked
path sets before comparing every out-of-scope baseline file bytewise. An unexpected
new tracked path is a failure, not an omission from a baseline-only loop.
Two renderer ASTs must match after reversing only the exact locale extraction,
docstrings, unused top-level `os` import, and the documented design type declaration.
The new private `_DesignTokens` TypedDict and the annotation on `DESIGN` describe
the original ten string colors, integer A4 tuple and two float measurements; their
precise fields are verified before normalization. No other class, annotation,
value conversion or executable statement is normalized away.

The expected scope is two renderer AST matches, 388 byte-identical baseline
files and two exact type-only source transformations. The validator and new proof utility are explicit tested modifications, not
claimed unchanged assets. The proof uses AST parsing and local Git reads and does
not import the historical renderers or access the network.

## Reproducible bounded lexical inventory

```bash
python scripts/verify_reporting_language_migration.py --inventory
```

The command names the fixed base, exact 33 paths, finite identifier vocabulary,
accent pattern and individual matches. Its rerun found no identifier candidate
under that vocabulary and 45 accented comment/docstring lines. This supersedes
the earlier exploratory counts of 54 and 53 for documented quantitative claims; the old
local exploratory JSON remains historical and is not the current measurement.
These lines are reviewed quotations of normative/display/test text in otherwise
English prose. Neither the fixed vocabulary nor this count proves the language
of every possible identifier or string outside this bounded inventory.

## Portable output replay against the actual base

Use the repository's pinned reporting dependencies in the selected Python
interpreter. The pinned historical capture harness is replayed against the original
production source and the candidate (whose harness must have identical bytes); it does not regenerate golden
expectations from modified production code.

```bash
set -eu
repo=$(git rev-parse --show-toplevel)
base=0a643128f3ac3e99a51428644c3012a2d638ab8b
work=$(mktemp -d)
mkdir "$work/base"
git archive "$base" | tar -x -C "$work/base"
python scripts/verify_reporting_language_migration.py
reference=c87b336a292f6c9f2fb490a51d2853b74ab72749
git show "$reference:tests/reporting_language_fixtures.py" > "$work/base/tests/reporting_language_fixtures.py"
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

Style checks apply to the eight renderer/locale, fixture/test and migration-verifier sources using pycodestyle with
100 columns, pydocstyle pep257 and Ruff E/F/B905/SIM117 targeting Python 3.11. This stage changes no style
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
was added during the historical six-method stage; the current suite contains nine methods. No renderer output or
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
files=(
  reporting/engine.py
  reporting/editorial_v3_hifi.py
  reporting/locale_pt_br.py
  tests/reporting_language_fixtures.py
  tests/test_reporting_language_compatibility.py
  tests/test_reporting_presentation_gate.py
  scripts/verify_reporting_language_migration.py
  tests/test_reporting_migration_verifier.py
)
python -m pycodestyle --max-line-length=100 "${files[@]}"
python -m pydocstyle --convention=pep257 "${files[@]}"
python -m ruff check --target-version py311 --select E,F,B905,SIM117 \
  --line-length 100 "${files[@]}"
python -m pylint --load-plugins=pylint.extensions.no_self_use \
  --disable=all --enable=no-self-use scripts/verify_reporting_language_migration.py
```

## Review correction boundaries

The four initial CodeRabbit requests are implemented for validation by a command-linked baseline
inventory, an independently pinned reference, a bidirectional tracked-path check,
and detection of missing locale attributes in both renderers. Regression tests
exercise corrupted references, added/deleted out-of-scope paths and precise AST
normalization. The full Git proof runs separately through the committed command;
unit tests do not require a full-history CI checkout. Negative missing-caption tests exercise both the helper and full gate.

The DeepSource typing corrections do not convert values: `DESIGN` remains the
same plain dictionary with exactly the original values, described by a private
TypedDict. The locale-declaration loop and renderer AST walk use distinct local
names so a statement-only inferred type is not incorrectly reused for all AST
nodes. Both raw runtime values and final artifact/text comparisons are tested.

The initial published commit `c87b336a292f6c9f2fb490a51d2853b74ab72749`, tree
`a9d9d532f960ceffe39c28a2071e54b40b7bdabc`, remains historical: its 979-test
execution log has SHA-256
`0378fb0385e3408f1181e7ce464b8dc31e4f9e6f5d46de7650ae8db7a6d2424c`.
It cannot certify the correction. Correction validation remains PENDING until the
linked exact-HEAD record names the matching commit/tree, command outcomes and
new retained log digests. No reviewer approval or merge follows from this note.

### Exact comparison digest and reference trust boundary

`verify_reporting_language_migration.py` rejects a proof whose canonical JSON
record does not match the expected comparison SHA-256
`697ed0716e46ced219856a77af5f50bd46bcd10f74e487cdb9474e84f3bc37ac`.
The digest is checked, not merely printed. A unit test exercises acceptance and
rejection by the same binding helper without comparing a future repository HEAD
to this stage-specific scope. The complete CLI proof remains mandatory when
validating this stage's delivered SHA.

The two reference digests above are independently reviewable against the first
published Git commit. They establish reproducibility, not a malicious-maintainer
trust guarantee: changing the verifier, its pins and its tests together still
requires human review. Full Git history containing both fixed commits is a
prerequisite; missing reference objects fail rather than downloading or replacing
them automatically. Do not rewrite/squash away the referenced commit history
when retaining this historical proof.

For the removed incidental `os` module attribute, this literal source query was
executed on the fixed base:

```bash
git grep -nE 'editorial_v3_hifi\.os|from reporting\.editorial_v3_hifi import .*\bos\b' \
  0a643128f3ac3e99a51428644c3012a2d638ab8b -- '*.py'
```

It returned exit 1 (no matches), not a Git execution error. This checks only the
named direct forms. Aliased, dynamic and external consumers were not established
by that query; no claim of their absence follows. The renderer's explicit public
functions and signatures are unchanged.

The correction also checks the absolute `pt_br` import and rejects rebinding in
both renderers. Four negative engine-import cases failed before the shared
per-renderer binding check and passed afterward. The source is never imported by
that static gate. Logs are retained as `engine-import-red.log` and
`engine-import-green.log` at the exact retained locations and digests listed below.

## Reconciled test scope and historical log locators

The current targeted suite contains **30 tests**: 11 reporting-language tests,
9 presentation-gate tests, and 10 migration-verifier tests. They are included
in the root suite, not an additional independent total. The six-method and
eight-method counts described earlier snapshots; neither is the current count.
Run all three test modules together to reproduce the current targeted count:

```bash
python -m unittest tests.test_reporting_language_compatibility \
  tests.test_reporting_presentation_gate tests.test_reporting_migration_verifier -v
```

Current presentation-gate methods:

- `test_owned_marker_used_by_both_renderers_is_accepted`
- `test_missing_or_changed_locale_contract_is_rejected`
- `test_comments_wrong_imports_and_missing_renderer_use_are_rejected`
- `test_repository_validation_never_executes_the_locale_source`
- `test_full_repository_validator_dispatches_the_presentation_check`
- `test_repository_gate_requires_the_locale_file`
- `test_every_used_locale_attribute_is_defined_in_both_renderers`
- `test_full_gate_rejects_an_undefined_engine_presentation_name`
- `test_engine_locale_binding_cannot_be_missing_relative_or_shadowed`

The following log files were actually read and hashed in the correction
resumption. They describe pre-commit RED/GREEN worktree tests and must not be
represented as full exact-HEAD release validation. Paths are local locators on
`drhudson`, not public download URLs. The [exact-HEAD evidence record](https://github.com/drhudsonandrade/Codework/pull/61#issuecomment-5601896618)
links these historical results to their later corrected implementation; a later
commit still requires its own validation log.

| Historical log | Exact retained path | SHA-256 |
| --- | --- | --- |
| `absolute-import-red.log` | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/absolute-import-red.log` | `9100ee6fb64215c1f3830ec4c016d31eb124e0c19a5ed0a2a0aa0c6b1c920897` |
| `absolute-import-green.log` | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/absolute-import-green.log` | `42c6662eb0ddf47fdbec5a6d4389c753ccb81327b5544e9f26f390af2c1bef8b` |
| `engine-import-red.log` | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/correction-resume-20260909T141824Z/engine-import-red.log` | `713fc3fb3a798ed380b854b4935196d8a7b8ccbab8a6cfe79f21d3e6b261bb31` |
| `engine-import-green.log` | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/correction-resume-20260909T141824Z/engine-import-green.log` | `ecf1eeb11e9325dfc2374ceabfebe9b0b6166d5e1df0796c1967938510c7f170` |

## Remaining DeepSource diagnostics on the second correction

The dashboard for the reviewed `61963e3f40174238da33f1cf61eae14b233a80a1`
reported eight issues, including five type diagnostics in two formerly unchanged
reporting modules. That source is the
[commit-specific DeepSource run](https://app.deepsource.com/gh/drhudsonandrade/Codework/run/41339631-e574-4456-bee9-18d4da27b19d/python/).
This is a narrow review-driven scope extension, not a change to scientific,
publication or post-deployment decisions.

The verifier's `TYPING_ONLY_EDITS` lists every allowed old/new byte fragment in
`reporting/deployment_target.py` and `reporting/provenance.py`. It reads the exact
source base, requires each old fragment once, applies only those substitutions,
and requires the candidate bytes to equal that result. No generic cast stripping
or arbitrary normalization is permitted. The two renderer AST comparisons remain
separate, and the remaining 388 baseline files stay byte-identical.

The three casts preserve values without conversion: the resolver already promises
address strings; the findings expression already checks the list branch; status
entries are already selected by membership in the status-rank mapping. The SHORT
mapping annotation explicitly permits the existing nullable lookup. No runtime
filter, new status, string coercion or validation suppression is introduced.
Python documents that [cast returns its value unchanged](https://docs.python.org/3.11/library/typing.html#typing.cast).
The [socket address contract](https://docs.python.org/3.11/library/socket.html#socket.getaddrinfo)
describes the host/address position used by this resolver. These type annotations
are not new runtime checks or new evidence of a deployment.

The current comparison record includes the two type-only source identities and
therefore has digest `697ed0716e46ced219856a77af5f50bd46bcd10f74e487cdb9474e84f3bc37ac`.
It was computed from the fixed base plus the enumerated edits, not learned from
unconstrained candidate output. The prior `cd81d90e1d03d2d645ce286973d3673779a04a9393a644f7334d37a46e6aaa92`
record remains historical for the earlier 390-byte-identical-file scope.

`validate_report_presentation` is decomposed into focused literal, reference,
import/shadowing and result-caption checks. Diagnostic order and refusal behavior
are preserved. Its earlier Ruff C901 failure is reproduced at complexity 18 with
a limit of 15; the helper decomposition passes that same scoped check. No metric
threshold or analyzer configuration is relaxed.

The Git reader resolves Git with `shutil.which`, rejects an unavailable executable,
and passes an absolute path to subprocess without a shell. This addresses
[Bandit B607](https://bandit.readthedocs.io/en/latest/plugins/b607_start_process_with_partial_path.html)
without a machine-specific hard-coded path. The existing PATH remains the discovery
trust boundary; executable resolution is not a claim of binary attestation.

The two executable-discovery tests and one exact-transformation test are included
in the current 30-method targeted suite. The evidence directory is
`/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z` (a local locator, not a public download URL).
`git-executable-red.log`, `typing-proof-red.log`, `complexity-red.log` and their
GREEN counterparts retain the actual pre-implementation observations. The primary
exact-HEAD PR record must name the final commit, full results and digests; these
worktree observations alone cannot certify that commit.

The separate behavioral comparison in `compare_behavior.py` uses the retained
pre-correction source in the same unchanged repository context. It compares 512
presentation-gate cases, 13 qualifier cases, seven resolver cases and 66 provenance
payload cases, including refusals and exception outcomes. These are synthetic,
finite comparisons, not an exhaustive proof. The 23 existing target-binding and
provenance regression tests are also run; no real DNS or patient input is needed.

## Auditable behavioral comparison record

The finite behavioral counts above refer to this **historical executed comparison**:
base `61963e3f40174238da33f1cf61eae14b233a80a1` (tree `8e72c815c6abd8809f42e6ca573dd9e0ab8d03ff`),
candidate `051685845bafe15b84a8671c3218f963f40168f7` (tree `3d0dda9c36c016bdf869a4409907315f874b6698`). The Git identities
bind all transitive repository context, not only the listed files. A later HEAD
must be tested independently and recorded in the primary exact-HEAD PR comment;
it does not inherit this result. The spacing-only follow-up preserves the Python
AST but still receives its own full exact-commit validation.

Executed command (Python 3.12.3, no live DNS, synthetic inputs only):

```bash
/srv/remote-desktop-commander-workspace/codework-audit/.venv-python-english/bin/python /srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z/compare_behavior.py /srv/remote-desktop-commander-workspace/codework-audit/Codework/.worktrees/refactor-reporting-english-locale /srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z
```

| Evidence | Exact retained locator | SHA-256 |
| --- | --- | --- |
| Executed comparison script | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z/compare_behavior.py` | `63e6a9c6894abb57e40f88094df2a11118ced4b47b70def3ecb2f82a8fd607d9` |
| Exact-commit full execution log, including that command | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z/validation-051685845bafe15b84a8671c3218f963f40168f7.log` | `6d28479f940904efe83be0af938e243452d09e878a7de094b4a4ef2379fa2cbf` |
| Comparison result JSON | `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z/behavioral-comparison.json` | `e5722eceeb1bd6be5c3532df4d7205223a54a99444ad2e400b2c19ca8eeadedf` |

These remote filesystem paths are retention locators, not public download links.
The complete script and direct-input digests are also versioned below so a
full-history clone can reproduce the comparison without access to that VM.
The original input source was retained under `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/deepsource-followup-20260909T153345Z/before/`; its digests
are checked below against Git objects, not treated as trusted because it exists.
The helper intentionally sets each loaded module's `__file__` to the pinned
candidate context to resolve the same unchanged repository registry. It executes
the historical bytes from `before/`, not the candidate substitute. The original
failed setup log remains historical and is not used as the successful result.

### Direct-input digest manifest

<!-- reporting-behavior-inputs:start -->
```json
[
  {
    "commit": "61963e3f40174238da33f1cf61eae14b233a80a1",
    "path": "scripts/validate_repo.py",
    "sha256": "1b45123d016a5a523755d2a3dd32ae84dcc62ed22ddf2e941c4d40fd5cf85289"
  },
  {
    "commit": "61963e3f40174238da33f1cf61eae14b233a80a1",
    "path": "reporting/deployment_target.py",
    "sha256": "f2c2e916d68994c6c74b74d216f2496d6edc6e5ec90eb88e2865497153e843e1"
  },
  {
    "commit": "61963e3f40174238da33f1cf61eae14b233a80a1",
    "path": "reporting/provenance.py",
    "sha256": "53c45e2b0dbdbe1a38f8b98802f4e32ee5ab60e6ad3ba33d56fb7d782ba6edb0"
  },
  {
    "commit": "051685845bafe15b84a8671c3218f963f40168f7",
    "path": "scripts/validate_repo.py",
    "sha256": "dfdb5e1510d1b7439f00dcb289f3186a69b8e7b677fd3423497c45ee2a3a4332"
  },
  {
    "commit": "051685845bafe15b84a8671c3218f963f40168f7",
    "path": "reporting/deployment_target.py",
    "sha256": "ad1ae2fa45c1aed3ff2a937b8be54a9fce06ed7f33a72e74459ec01163a3fa39"
  },
  {
    "commit": "051685845bafe15b84a8671c3218f963f40168f7",
    "path": "reporting/provenance.py",
    "sha256": "3a5bc0048a05f49177b2bbe6b8ee90487ed6bef7bba5a33430c47a3f9efa8e54"
  },
  {
    "commit": "051685845bafe15b84a8671c3218f963f40168f7",
    "path": "tests/test_reporting_presentation_gate.py",
    "sha256": "bcb64394763662209964b863a6c9259acffcae987ab2c79a9bef922f44417037"
  },
  {
    "commit": "051685845bafe15b84a8671c3218f963f40168f7",
    "path": "tests/reporting_language_fixtures.py",
    "sha256": "58316c45089f8354cc8ce7007237fa27544185b7f0b550147591ad0eb7318fd0"
  }
]
```
<!-- reporting-behavior-inputs:end -->

### Portable historical reproduction

Use the repository's pinned reporting dependencies in the same Python runtime.
This command validates script/input digests, extracts the fixed candidate and
historical base sources, runs the exact historical probe and checks its output
hash. The resulting counts do not assert exhaustive equivalence.

```bash
set -euo pipefail
repo=$(git rev-parse --show-toplevel)
work=$(mktemp -d)
base=61963e3f40174238da33f1cf61eae14b233a80a1
candidate=051685845bafe15b84a8671c3218f963f40168f7
mkdir "$work/candidate" "$work/evidence"
git archive "$candidate" | tar -x -C "$work/candidate"
python - "$repo" "$work" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path

repo, work = map(Path, sys.argv[1:])
plan = (repo / "docs/superpowers/plans/2026-09-09-reporting-english-locale.md").read_text()
section = plan.split("\n<!-- reporting-behavior-probe:start -->\n", 1)[1]
section = section.split("<!-- reporting-behavior-probe:end -->", 1)[0]
script = section.partition("```python\n")[2].rsplit("```", 1)[0]
expected = "63e6a9c6894abb57e40f88094df2a11118ced4b47b70def3ecb2f82a8fd607d9"
if hashlib.sha256(script.encode()).hexdigest() != expected:
    raise RuntimeError("Historical behavioral probe digest mismatch")
(work / "compare_behavior.py").write_text(script)
section = plan.split("\n<!-- reporting-behavior-inputs:start -->\n", 1)[1]
section = section.split("<!-- reporting-behavior-inputs:end -->", 1)[0]
records = json.loads(section.partition("```json\n")[2].rsplit("```", 1)[0])
for row in records:
    raw = subprocess.check_output(["git", "-C", str(repo), "show", row["commit"] + ":" + row["path"]])
    if hashlib.sha256(raw).hexdigest() != row["sha256"]:
        raise RuntimeError("Historical input digest mismatch: " + row["path"])
    if row["commit"] == "61963e3f40174238da33f1cf61eae14b233a80a1":
        target = work / "evidence/before" / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    elif (work / "candidate" / row["path"]).read_bytes() != raw:
        raise RuntimeError("Candidate archive differs from its pinned Git object")
PY
python "$work/compare_behavior.py" "$work/candidate" "$work/evidence" > "$work/replay.log" 2>&1
cat "$work/replay.log"
python - "$work/evidence/behavioral-comparison.json" <<'PY'
import hashlib
import sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes()
expected = "e5722eceeb1bd6be5c3532df4d7205223a54a99444ad2e400b2c19ca8eeadedf"
if hashlib.sha256(raw).hexdigest() != expected:
    raise RuntimeError("Historical behavioral output digest mismatch")
print("HISTORICAL_BEHAVIOR_REPLAY_PASS")
PY
printf 'Retained reproduction directory: %s\n' "$work"
```

### Exact executed probe source

<!-- reporting-behavior-probe:start -->
```python
"""Compare the existing and decomposed gate and type-only functions on synthetic inputs."""
import copy
import importlib.util
import itertools
import json
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

root, evidence = map(Path, sys.argv[1:])
sys.path.insert(0, str(root))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    module.__file__ = str(root / path.parent.name / path.name)
    spec.loader.exec_module(module)
    return module


old_gate = load("scripts._fp_original_gate", evidence / "before/scripts/validate_repo.py")
new_gate = load("scripts._fp_candidate_gate", root / "scripts/validate_repo.py")
from tests.test_reporting_presentation_gate import ENGINE, RENDERER, LOCALE

locales = [LOCALE, None, LOCALE.replace("pt-BR", "en-US"), LOCALE + "raise RuntimeError()\n",
           LOCALE + 'GENOMIC_RESULT="duplicate"\n', LOCALE + "BROKEN=[\n",
           LOCALE.replace('"pt-BR"', "None"), '"""Description."""\n' + LOCALE]
engines = [ENGINE, "", ENGINE.replace("from reporting", "from .reporting"),
           ENGINE.replace("from reporting", "from unrelated"), ENGINE + "\npt_br=1\n",
           ENGINE + "\ndef extra(pt_br): return pt_br.UNKNOWN\n",
           ENGINE + "\ndef extra(): return pt_br.MISSING\n", ENGINE + "\ndel pt_br\n"]
renderers = [RENDERER, "", RENDERER.replace("from reporting", "from .reporting"),
             RENDERER.replace("return pt_br.GENOMIC_RESULT", "return 'missing'", 1),
             RENDERER + "\npt_br=1\n", RENDERER + "\ndef _pdf(): return pt_br.GENOMIC_RESULT\n",
             RENDERER + "\ndef extra(pt_br): return pt_br.UNKNOWN\n", RENDERER + "\nBROKEN=[\n"]
records = []
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)
    (folder / "reporting").mkdir()
    for index, (locale, engine, renderer) in enumerate(itertools.product(locales, engines, renderers)):
        target = folder / "reporting/locale_pt_br.py"
        if locale is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(locale, encoding="utf-8")
        (folder / "reporting/engine.py").write_text(engine, encoding="utf-8")
        (folder / "reporting/editorial_v3_hifi.py").write_text(renderer, encoding="utf-8")
        before, after = ["pre-existing-error"], ["pre-existing-error"]
        old_gate.validate_report_presentation(folder, before)
        new_gate.validate_report_presentation(folder, after)
        if before != after:
            raise AssertionError((index, before, after))
        records.append({"case": index, "errors_equal": True, "error_count": len(before)})

old_target = load("reporting._fp_original_target", evidence / "before/reporting/deployment_target.py")
new_target = load("reporting._fp_candidate_target", root / "reporting/deployment_target.py")
old_provenance = load("reporting._fp_original_provenance", evidence / "before/reporting/provenance.py")
new_provenance = load("reporting._fp_candidate_provenance", root / "reporting/provenance.py")
from tests.reporting_language_fixtures import render_fixture


def outcome(function, value):
    try:
        return {"return": function(copy.deepcopy(value))}
    except Exception as exc:
        return {"exception": type(exc).__name__, "message": str(exc)}


def same(first, second, value):
    before, after = outcome(first, value), outcome(second, value)
    if before != after:
        raise AssertionError((value, before, after))
    return before


qualifier_cases = []
for network_class in [None, "", "loopback", "private-network", "public-host", "unresolved", "unknown", 5, [], {}]:
    value = {"network_class": network_class, "authority": "https://example.invalid:443"}
    qualifier_cases.append(same(old_target.qualifier, new_target.qualifier, value))
for value in [None, {}, "unexpected"]:
    qualifier_cases.append(same(old_target.qualifier, new_target.qualifier, value))
resolver_cases = []
for addresses in [[], ["127.0.0.1"], ["::1", "127.0.0.1", "::1"], [7]]:
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]
    with patch.object(socket, "getaddrinfo", return_value=infos):
        first = old_target._resolve("synthetic.invalid", 443)
        second = new_target._resolve("synthetic.invalid", 443)
    if first != second:
        raise AssertionError((first, second))
    resolver_cases.append(first)
for error in [socket.gaierror, UnicodeError, OSError]:
    with patch.object(socket, "getaddrinfo", side_effect=error("synthetic resolver error")):
        if old_target._resolve("synthetic.invalid", 443) != new_target._resolve("synthetic.invalid", 443):
            raise AssertionError(error)
    resolver_cases.append(error.__name__)
provenance_cases = []
for report_id in [f"{index:02}" for index in range(1, 12)]:
    data = render_fixture(report_id, "FINAL")["data"]
    provenance_cases.append(same(old_provenance.provenance_blockers, new_provenance.provenance_blockers, data))
    for findings in [None, [], [None], [{}], [{"id": "synthetic", "status": "UNKNOWN"}]]:
        mutated = copy.deepcopy(data)
        mutated["findings"] = findings
        provenance_cases.append(same(old_provenance.provenance_blockers, new_provenance.provenance_blockers, mutated))
result = {"presentation_cases": len(records), "qualifier_cases": len(qualifier_cases),
          "resolver_cases": len(resolver_cases), "provenance_cases": len(provenance_cases), "result": "PASS"}
(evidence / "behavioral-comparison.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result))
```
<!-- reporting-behavior-probe:end -->
