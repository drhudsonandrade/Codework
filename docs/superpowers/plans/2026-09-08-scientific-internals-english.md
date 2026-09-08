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

## Local implementation evidence

The pre-commit tree passed 954 root tests (one skipped), 102 focused tests,
14 direct isolated test executions, the existing WGS shell regression,
the source-equivalence check and 72 protected-file byte comparisons.
Release checkboxes remain open here; final exact-SHA validation and external
review are recorded in the PR instead of rewriting this plan after every check.

The later local static pass reproduced one ZIP/gzip assignment-type error in
`_open_associations`. Its explicit local union annotation is covered by a
plain/gzip/ZIP preservation test; no scientific rule or runtime output changes.
