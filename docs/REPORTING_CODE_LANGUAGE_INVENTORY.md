# Reporting Language and Presentation Ownership Inventory

## Scope and reference

Stage 5 follows the manual merge of PR #60. The fixed base is
`0a643128f3ac3e99a51428644c3012a2d638ab8b`.
The approved scope is implementation language and the presentation boundary;
report text is not translated into English.

A bounded inventory examined 33 Python files in `reporting/`, the report/template
scripts and associated tests. No candidate Portuguese implementation identifier
was found by the recorded token vocabulary. The 45 accented prose candidates
quote normative values, report names, historical examples or fixture data inside
otherwise English documentation. They are retained, not mechanically translated.
Reproduce the current count with
`python scripts/verify_reporting_language_migration.py --inventory` from a
full-history checkout. The result records base `0a643128f3ac3e99a51428644c3012a2d638ab8b`,
all 33 paths, the precise vocabulary/pattern and every match. The reproduced
45-line count replaces the earlier exploratory counts of 54 and 53; those are not
used as current execution evidence. This bounded scan is not a language proof.

## Ownership boundary

`reporting/locale_pt_br.py` owns 48 fixed presentation strings under English names.
`reporting/engine.py` and `reporting/editorial_v3_hifi.py` import it as `pt_br`.
It has no external dependency, selector, environment setting, fallback or network
lookup. The only implemented report language remains pt-BR.

The constants include fixed headings, finding-label prefixes, safety notices,
cover/table captions, the page-footer prefix and the HTML language tag. Their
values, punctuation, accents, Markdown markers and significant spaces match the
pre-migration values. The exact name/value inventory is recorded independently
in `tests/fixtures/reporting_language_baseline.json` and tested against the module.

Presentation defaults such as `UNAVAILABLE` and `PENDING` duplicate the existing
printed labels only. This module is not the owner of policy state semantics and
cannot introduce translated wire values. Catalog-driven titles/sections, payload
content, coordinate keys, consent domains and normative values retain their
existing owners. In particular, no caller-supplied locale field changes output.

## A-E compatibility classification

| Category | Decision |
| --- | --- |
| A: private implementation | Existing English identifiers remain; fixed display expressions reference English-named pt-BR constants. Missing docstrings and touched-file formatting are normalized. |
| B: public/cross-module | Existing renderer function names, signatures, default values and explicit exports remain. An unused `os` import in the programmatic module is removed; the direct-form query recorded in the implementation plan found no matching in-repository consumer; aliases, dynamic and external uses were not established by that query. |
| C: serialized contracts | JSON keys, metadata schema, normative labels, file names, Markdown/HTML bytes and artifact digests retain their baseline representation. No locale metadata field is added. |
| D: user-facing text | Fixed pt-BR strings receive an explicit presentation owner; report-specific catalog, payload and template text is not rewritten. |
| E: immutable/canonical | Ruleset, sealed transport, reference manifests, coordinate packs, templates and historical artifacts are untouched. |

The extraction does not change publication checks, provenance serialization,
report-identity binding or the explicit authorization required by the public
programmatic FINAL writer. Template rendering and its canonical identities remain
outside the implementation diff. The locale module is not a publication capability.

## Regression and reproduction

Run `PYTHONPATH=tests:. python -m unittest tests.test_reporting_language_compatibility -v`.
The original nine tests check the presentation owner, exact literal values, all eleven
MODEL/FINAL text bundles, absent-value formatting, reserved headings, unchanged
language selection behavior, and publication/authorization refusals.
Two additional tests pin the reference files and preserve the design dictionary/types.
All eleven tests are part of the root suite, not an additional independent total.

The golden fixture contains 22 public bundle cases (11 report IDs times two modes)
and one explicitly private formatting-only case. Each public case records exact
Markdown/HTML hashes, written JSON/Markdown/HTML file hashes and file names, and
metadata key names. The private case covers finding-label/default formatting but
is not described as a payload authorized for FINAL publication.

Baseline capture occurred before production edits, with `reporting/` still
byte-identical to the fixed base. The first test harness patched the wrong clock:
`provenance_block` uses `datetime.now` directly, so JSON generation timestamps
varied. That attempt was retained in local evidence, the fixture clock was fixed,
and the snapshot was recaptured while production bytes were still unchanged.
No post-refactor expectation was substituted to hide output drift.

Only generation timestamps are fixed by the fixtures. Actual publication checks,
provenance validation, authorization routing and serializers run normally.
All inputs explicitly describe synthetic layout QA, never patient measurements.

The [implementation plan](superpowers/plans/2026-09-09-reporting-english-locale.md)
contains exact commands plus the full executable AST/blob and binary-output probes.
The independent verifier reads the capture harness and golden fixture through
immutable commit `c87b336a292f6c9f2fb490a51d2853b74ab72749` and pinned digests.
The candidate must preserve both reference files bytewise. It checks newly added
and deleted tracked paths as well as protected baseline bytes. The AST proof
reverses only the documented extraction, docstrings, unused top-level `os` import,
and exact `_DesignTokens` declaration/`DESIGN` annotation. The TypedDict adds
private type metadata, not runtime conversions or a different dictionary.

Representative PDF/DOCX comparisons use reports 01 and 10 (multi-page and single-
page layouts). The probe compares page text, page dimensions, raster pixels and
all decompressed DOCX package entries. It does not assert whole-PDF file identity,
outer ZIP-container identity, universal cross-renderer parity, or equivalence to
the immutable template pack. Existing programmatic layout constraints, including
single-page shrinking in report 10, are not redesigned by this migration.

## Exact-commit evidence and remaining work

The [stage-five exact-HEAD evidence record](repository_id=1212760346; pr_number=61; comment_id=5601896618)
identifies the commit/tree actually tested, commands, results and retained log
hashes. Until it names the delivered HEAD, implementation validation is PENDING.
A source document cannot embed its own final Git SHA; the real linked record
avoids self-reference without inventing a revision or inheriting an old PASS.
External review, applicable CI and manual merge remain separate requirements.

This stage does not change clinical meaning, QC/calling/reference decisions,
permission settings or deployment status. It does not authorize real genomic
interpretation. The remaining planned stages are integration/tooling language,
developer documentation, and the residual compatibility audit.

## Static repository-gate consumer

The repository validator previously searched the renderer source for the inline
result caption. It now checks the exact literal in its locale owner and the
renderer import/reference relationship without executing source files. Every
`pt_br` attribute read in both renderer sources must have a declared locale
constant; undefined noncritical labels and engine-only reads are rejected.
The locale file is a required repository path. The prior colors, font, writer,
canonical and scientific checks remain enabled. This adaptation is covered by
`tests/test_reporting_presentation_gate.py`, including negative fixtures and an
integration test invoking the full validator; it is not a deleted safety check.
The complete procedure is documented in
[`2026-09-09-reporting-english-locale.md`](superpowers/plans/2026-09-09-reporting-english-locale.md).
The two renderer ASTs still match their baseline after only the stated
normalizations; the tested validator is excluded explicitly from the 388
byte-identical baseline files. Two additional source files have exact, separately
verified type-only corrections, as documented in the implementation plan. No data-flow or clinical validation is inferred from
this static check.
