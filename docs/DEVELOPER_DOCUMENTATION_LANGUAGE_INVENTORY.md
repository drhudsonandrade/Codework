# Developer Documentation Language Inventory — Stage 7

## Baseline and scope

Base commit: `185996841b55669e42aa641896e2947748e04704` (manual merge of PR #62).
Stage-seven scope is defined by `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`: active developer documentation, architecture explanations, and non-normative runbooks.

The audit covered the repository README, active `docs/*.md` developer documents, adapter/MCP READMEs, policy-engine documentation, and active design specifications. Historical evidence, `docs/history/**`, audit records, immutable evidence artifacts, canonical ruleset text, and end-user/localized output are preservation boundaries rather than translation targets.

## Documents migrated

The following active technical documents contained substantial Portuguese implementation prose and were migrated to English:

- `docs/ANCESTRY_REFERENCE_PANEL.md`
- `docs/EDITORIAL_V3_PIXEL_QA.md`
- `docs/HIGHMEM_GRCH38_RUNNER.md`
- `docs/PGX_ALLELE_DISCRIMINATION.md`
- `docs/SNP_ARRAY_PARTIAL_GENOME.md`
- `docs/TARGET_REGISTRY_EXPANSION.md`

`README.md`, `docs/DETERMINISTIC_ENGINE.md`, `docs/PRODUCTION_CEREMONY.md`, `docs/PROVENANCE_GATE.md`, adapter/MCP READMEs, branch-governance documentation, and the active architecture/design documents were already English-first and did not need cosmetic rewrites.

## Preserved Portuguese

Portuguese remains intentional when it is part of an established wire/report vocabulary, a localized fixture/example, or historical evidence. In this stage that includes:

- normative/report values such as `NÃO DISPONÍVEL`, `NÃO DETECTADO`, `NÃO TESTADO`, `NÃO REPORTÁVEL`, `EXECUTADO`, `VERIFICADO`, `INFERIDO`, and `PROPOSTO`, plus exact localized report labels `MODELO`, `RESULTADO`, `DATA`, and `VERSÃO`;
- PGS transferability labels `NÃO TRANSFERÍVEL SEM CALIBRAÇÃO`, `TRANSFERIBILIDADE INCERTA`, and `PARCIALMENTE TRANSFERÍVEL`;
- the report-02 historical caveat quoted in Portuguese in `ANCESTRY_REFERENCE_PANEL.md`; the document explicitly marks the validation artifact as a historical, non-reproducible snapshot because the former validation script is absent;
- the historical statement and pt-BR conditional-diplotype example preserved in `PGX_ALLELE_DISCRIMINATION.md`;
- blockquoted historical, non-verifiable measurements in `TARGET_REGISTRY_EXPANSION.md`;
- private/path examples inside command snippets where translation would alter the recorded example rather than developer prose.

These exceptions are deliberate and are not permission to add new Portuguese developer prose.

## Compatibility controls

`tests/test_developer_documentation_language.py` scans the six migrated active documents outside fenced code and blockquotes. It removes explicit preserved literals before testing prose, and a positive fixture proves that ordinary Portuguese developer prose is detected.

The same test also asserts that representative normative and localized values remain present, so the language migration cannot pass by translating wire/report contracts.

`tests/fixtures/developer_documentation_contract.json` was captured from the fixed base commit and pins SHA-256 literals, URLs, stable inline-code spans, non-comment executable lines from `bash`/`python` fenced blocks, and the multiset of numeric digit groups. Exact localized/normative labels and `docs/evidence/...` references are excluded from that frozen inline-code set: localized labels have dedicated preservation assertions, while evidence paths must exist in the current checkout and selected QA claims are checked against the status recorded by the referenced JSON artifact. `tests/test_developer_documentation_language.py` compares every migrated document with that split contract. Documentation prose and evidence references may be corrected; commands, pinned digests, stable code-like tokens, and non-evidence numeric content may not drift silently.


The editorial QA document is explicitly bounded to versioned evidence. The 200 DPI static PDF artifact from 2026-08-16 is `VERIFICADO`; the current versioned DOCX parity record is `NÃO DISPONÍVEL`; no current Poppler verdict is claimed without a versioned artifact.

## Exclusions and stage 8

This is not the repository-wide residual audit. Stage 8 still owns the final classification of every remaining Portuguese occurrence, including compatibility aliases and any intentionally retained documentation content.

No scientific behavior, thresholds, patient/genomic data, canonical ruleset bytes, evidence artifact, workflow semantics, API/MCP payload, required check, dependency, or runtime configuration is changed by stage 7.
