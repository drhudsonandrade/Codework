# Developer Documentation Language Inventory — Stage 7

## Baseline and scope

Base commit: `185996841b55669e42aa641896e2947748e04704` (manual merge of PR #62).
Stage-seven scope is defined by `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`: active developer documentation, architecture explanations, and non-normative runbooks.

The active language gate currently discovers 46 Markdown documents across repository-root developer docs, `docs/**`, adapter/MCP READMEs, policy-engine documentation, and active design specifications. Discovery is dynamic, so new active Markdown enters the gate automatically. It explicitly excludes `docs/evidence/**`, `docs/audits/**`, `docs/history/**`, `docs/superpowers/plans/**`, `docs/superpowers/checkpoints/**`, `docs/superpowers/evidence/**`, `normative/**`, `template_store/**`, and `vendor/**`. Generated/vendor directories such as `generated`, `node_modules`, `dist`, and `build` are also excluded. These are evidence, audit, history, execution-plan, continuity, canonical normative, template/vendor, or generated surfaces rather than active developer documentation. End-user/localized output remains a preservation boundary rather than a translation target.

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

`tests/test_developer_documentation_language.py` scans the dynamically discovered active developer-documentation surface across ordinary prose, blockquotes, fenced-code content, and inline backticks. Only Markdown fence-delimiter lines and explicit fixture-enumerated preservation exceptions are skipped. The six migrated documents remain a narrower compatibility-contract set for pinned commands, hashes, URLs, stable inline tokens, and numeric content. Positive fixtures and synthetic discovery tests prove both language detection and scope expansion behavior.

The same test also asserts that representative normative and localized values remain present, so the language migration cannot pass by translating wire/report contracts.

`tests/fixtures/developer_documentation_contract.json` was captured from the fixed base commit and pins SHA-256 literals, URLs, stable inline-code spans, non-comment executable lines from `bash`/`python` fenced blocks, and the multiset of numeric digit groups. Exact localized/normative labels and `docs/evidence/...` references are excluded from that frozen inline-code set: localized labels have dedicated preservation assertions, while evidence paths must exist in the current checkout and selected QA claims are checked against the status recorded by the referenced JSON artifact. `tests/test_developer_documentation_language.py` compares every migrated document with that split contract. Documentation prose and evidence references may be corrected; commands, pinned digests, stable code-like tokens, and non-evidence numeric content may not drift silently.

The documentation-language detector reuses the repository-wide technical-term vocabulary from `config/code_language_policy.json`, adds structural prose terms used by Markdown documentation, normalizes common plural/gender inflections back to known Portuguese terms, detects accented Portuguese words when they begin lowercase or are all-uppercase, and applies a dependency-free fallback to otherwise unknown all-ASCII prose. TitleCase accented proper names are not treated as a diacritic signal by themselves. Known inflections can be sufficient on their own; the unknown-ASCII fallback combines common Portuguese function words with characteristic verb and nominal endings and requires at least two independent hints. Exact policy contract literals and canonical ruleset filenames are removed longest-first before prose analysis. Email addresses are stripped as address syntax, and only a dotted `.com` suffix is neutralized for bare-domain false positives; dotted identifiers remain tokenized and test-covered. Positive fixtures cover accented prose, uppercase accented prose, dotted Portuguese identifiers, one-token headings, inflected ASCII prose, and multiple unknown all-ASCII sentences, while English, email, and domain negative controls protect against broad false positives. Markdown syntax is not an exemption: blockquotes, fenced-code comments, and prose inside backticks are scanned like other text. The whole-line preservation set contains **44 exact lines** with reviewed reasons `historical_quote` or `localized_example`; exactly **5 Portuguese inline-code literals** are separately enumerated, including one `safety_pattern`. Tests require every line/literal exception to occur exactly once, carry an allowed reason, and still trigger the detector if its explicit exemption is removed.


The editorial QA document is explicitly bounded to versioned evidence. The 200 DPI static PDF artifact from 2026-08-16 is `VERIFICADO`; the current versioned DOCX parity record is `NÃO DISPONÍVEL`; no current Poppler verdict is claimed without a versioned artifact.

The target-registry reproduction block is also bounded to entrypoints present in the checkout. The historical python3 scripts/curate_panelapp.py collector is absent, so fresh PanelApp recollection is not presented as reproducible; the committed `docs/evidence/PANELAPP_CURATION.json.gz` snapshot is used only as the explicit downstream input boundary. The contract fixture excludes that single retired invalid base command, while the active documentation test requires every executable `python`/`bash` `scripts/...` entrypoint it sees to exist in the current repository.

## Exclusions and stage 8

This is not the repository-wide residual audit. Stage 8 still owns the final classification of every remaining Portuguese occurrence, including compatibility aliases and any intentionally retained documentation content.

No scientific behavior, thresholds, patient/genomic data, canonical ruleset bytes, evidence artifact, workflow semantics, API/MCP payload, required check, dependency, or runtime configuration is changed by stage 7.
