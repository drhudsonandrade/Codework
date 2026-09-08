# Scientific implementation-language inventory — stage 3

**Base:** `b46e2fae877d0f42896007bb681314861f366d62` (PR #58 merged).
**Scope:** stage 3 of `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`.
**Status:** implementation and compatibility checks; completion still requires external checks and human merge.

## Findings and changes

The inventory inspected Python declarations, comments and docstrings in the scientific modules and their tests; it also inspected the active Nextflow/configuration and scientific shell surfaces. Most implementation vocabulary was already English after the previous stages. This stage does not rename already-English code to manufacture a migration diff.

| Surface | Classification | Decision |
| --- | --- | --- |
| Two explanatory comments beside `by_term.values()` in `scripts/build_trait_targets.py` | A: private implementation prose | Translate to English; retain the iteration and cutoff unchanged. |
| Positive-control description in `tests/test_completeness_regressions.py` | A: developer-facing test prose | Translate the description; preserve the quoted `NÃO DETECTADO` result and all assertions. |
| Three test method names containing `observado` in `tests/test_assessed_allele_presence.py` | A: private test identifiers | Rename to `observed`; repository search found only their declarations. |
| `OBSERVADO`, `NAO_TESTADO`, `NAO_REPORTAVEL`, `NAO_DETECTADO` in completeness and `NAO_INTERROGADO` in clinical findings | B: cross-module compatibility names; C: corresponding wire labels | Preserve these public/imported names in this stage. Consumers include scientific modules and reporting/test code. Any future English aliases require their own consumer-aware compatibility step; no alias was added or removed here. |
| Scientific classification strings, genotype labels, schemas, JSON keys and emitted filenames | C: serialized contracts | Preserve byte-for-byte. |
| pt-BR result explanations, report-facing diagnostics, and exact quotations of those outputs in tests/comments | D: localized output or exact contract quotation | Preserve; this is not a report-language migration. |
| Scientific source descriptions, curated releases, historical evidence, reference locks and canonical normative bytes | C/E: identity-bound or historical material | Do not regenerate or rewrite. |

## WGS, Nextflow and shell boundaries

The following surfaces were inspected and are intentionally unchanged:

- `main.nf`, `workflows/wgs.nf`, `workflows/array.nf`, `nextflow.config`: process/workflow/channel names and developer diagnostics are already English; `NÃO DISPONÍVEL` quotations and serialized gate values are deliberate contracts.
- `scripts/build_bwa_mem2_index.sh`, `scripts/check_versions.sh`, `scripts/fetch_grch38.sh`, `scripts/materialize_reference_image.sh`, `scripts/run_canary.sh`, `scripts/validate_bwa_mem2_functional.sh`, `scripts/validate_grch38.sh`, `scripts/wgs_align_or_stage.sh`: existing English helpers/variables remain untouched; the `NÃO DISPONÍVEL` diagnostic prefix is preserved.
- `scripts/verify_ruleset.sh`: exact Portuguese canonical-header checks are necessary identity checks, not untranslated implementation prose.
- `scripts/runtime_resource_gate.py`, `scripts/latest_runtime_resource_gate.py`, WGS input/consent/materialization scripts and all `array_pipeline/` implementation files: no logic, threshold, identity or public-name changes in this stage.

Portuguese developer-tooling messages in `scripts/codex/setup-coderabbit.sh` belong to the later MCP/adapters/CI/tooling stage, not this scientific migration. Policy/evidence/audit and reporting localization work likewise retain their separate planned stages.

## Tests and equivalence

`tests/test_scientific_code_language.py` reuses `scan_python_file` with a **test-local** extension of the known prose terms (`termo`, `rotulo`, `controle`, `positivo`). It checks only the three migrated sources and separately checks their private test method names. A positive fixture proves comment/docstring detection runs; a localized-string fixture proves ordinary runtime strings remain permitted. The production language policy and its empty legacy baseline are unchanged.

Observed RED: three failing subtests identified the two untranslated prose locations and the three old test names. After translation the four-test suite is GREEN. Existing scientific tests remain the behavioral oracle; the new lexical test is not clinical or scientific validation.

Analyzer hygiene is restricted to touched files: five overlong statements, the existing script/test path bootstrap placement and a missing method separator. Runtime string values are preserved. The import bootstrap follows the already-used audit-script pattern and is checked by direct isolated execution from outside the checkout. Local mypy also exposed a pre-existing ZIP/gzip variable-type conflict in this touched loader; an explicit `IO[bytes] | gzip.GzipFile` local annotation resolves it without changing executable behavior. A separate preservation test reads and closes plain, gzip and ZIP fixtures before and after this annotation.

An executable-AST comparison permits only docstring removal, the three explicit test renames and the documented equivalent path bootstrap normalization and the explicit local stream annotation. All remaining executable nodes must match the base. Git blob identities separately establish that scientific workflow/shell/configuration, reference and normative surfaces were not changed.

## Limits and evidence

The lexical regression detects known terms; it is not a full natural-language proof that every remaining string is English. Intentional quotations and localized content are not defects. Zero Python legacy-baseline entries is not a claim of zero Portuguese in the repository.

Local execution is on the Ubuntu `drhudson` executor. At inspection time Nextflow was not on its PATH, and Docker socket access returned permission denied. No permission changes were attempted. No local Nextflow or container canary, real genomic calling, clinical interpretation, or deployment is claimed. Existing synthetic Python and shell tests and applicable external CI are reported separately in the PR with the exact SHA and actual outcomes.

The immutable validation logs, before/after comparisons and runtime gate observations are kept outside Git in the stage-three evidence directory; their hashes and final check links are recorded in the PR. No personal genetic data or regenerated scientific artifacts are included in this change.
