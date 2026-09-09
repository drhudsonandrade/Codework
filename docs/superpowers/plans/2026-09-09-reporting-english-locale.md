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

## Evidence and continuity

The checklist is planned work, not execution evidence. Completed results must identify
commit/tree, actual commands, results and retained log digests in the PR. This avoids
self-referential commit hashes. Later commits never inherit earlier validation.
Evidence root: `/srv/remote-desktop-commander-workspace/codework-audit/reporting-english-stage5/`.
This is a local locator, not a download URL. The initial planning PR identifies the active
writer to reduce concurrent work; no other branch should overwrite this implementation.
