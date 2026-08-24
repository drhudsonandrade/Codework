# Genome Completeness & Blind Spots (report 09 / GCM)

## Why this report is the one that matters most

`reporting/catalog.json` has declared report 09 since v3.0 and its approved template is
sealed in the store, but nothing computed its content. That gap was more consequential than
a missing document.

Without report 09, *"rs6025 does not appear in the report"* and *"rs6025 was tested and the
variant is absent"* are the same sentence to a reader. That is the single most damaging
false negative a SNP array can produce, and it happens silently.

## The five classes

`array_pipeline/completeness.py` places every target in the registry into exactly one class:

| class | meaning | interpretable |
|---|---|---|
| `OBSERVADO` | assayed, called, usable | yes |
| `NÃO DETECTADO` | assayed, called, assessed allele absent | yes |
| `NO-CALL` | on the chip, no valid genotype in this sample | no |
| `NÃO TESTADO` | not on this array at all | no |
| `NÃO REPORTÁVEL` | observed but excluded — unresolved conflict, or unverified strand | no |

Only `NÃO DETECTADO` licenses a statement of absence, and only for that locus.

## `NÃO DETECTADO` requires a declared assessed allele

A genotype read without knowing which allele was being looked for cannot establish absence.
The classifier therefore promotes a locus to `NÃO DETECTADO` **only** when the target
registry declares `assessed_allele` for it:

```json
{"rsid": "rs4149056", "gene": "SLCO1B1", "scope": "CLINICO",
 "assessed_allele": "C", "queries": {...}}
```

Where `assessed_allele` is absent the locus stays `OBSERVADO`, and the matrix states the
reason in its `basis` field. In version `2026-08-19.1`,
`config/partial_genome_annotation_targets.json` declares sourced `assessed_allele` values
for **28 of 29** targets; the remaining target stays unscored. The registry carries the
source/status per target, and `tests/test_target_expansion.py` rejects stale refusal metadata
beside a declared allele.

## Strand orientation is checked for every target

An earlier revision of this module read orientation back from the QC artifact's
`baseline_marker_observations` list. That list covers only the 14 baseline rsids, so every
other target skipped the strand check and an unoriented locus could be classified
`OBSERVADO` — a fail-open, since the reported allele may be the complement of the true one.

Orientation is now derived per row via `array_pipeline.qc._orientation` for **all**
targets. `VERIFICADO` and `INFERIDO` remain interpretable; anything else is
`NÃO REPORTÁVEL`.

## A non-interpretable locus does not carry its genotype

A conflicting or unoriented record still *has* a called value. Keeping it in the entry meant
every consumer that printed `genotype or classification` displayed it exactly like a usable
call — the arbitration the `NÃO REPORTÁVEL` class exists to refuse. The genotype is now
withheld (`genotype: null`, `genotype_withheld: true`) unless the locus is interpretable, and
the report printers decide independently as well, so a regression here degrades a line to its
classification rather than publishing an arbitrated call.

## Duplicate rows are not arbitrated

`qc.inspect_array` deliberately allows a raw vendor export to carry duplicate RSID rows,
retained as provenance for the harmonizer. Keeping only the first row silently picked a
winner whenever two rows disagreed. All rows for a target are now collected; if their
canonical genotypes differ the locus is `NÃO REPORTÁVEL` and the basis names the competing
values. Duplicates that agree are not penalised.

## Structural blind spots

Some variant classes are invisible to an array at *every* locus — CNV, SV, repeat
expansions, HLA typing, CYP2D6 structural/hybrid/copy-number diplotyping, mosaicism from
read-level evidence, deep intronic variation. These are reported separately from the
per-locus matrix, because they are limits of the platform rather than gaps in this sample.

## Running it

```bash
python3 scripts/build_completeness_report.py \
  --input array.csv.gz \
  --qc array-qc.json \
  --targets config/partial_genome_annotation_targets.json \
  --matrix-out completeness.json \
  --payload-out payload-09.json
```

The payload is compiled through `PayloadCompiler`, so every printed value is anchored (see
`docs/PROVENANCE_GATE.md`) and a hand-edited count is refused at render time.

The matrix is `VERIFICADO` only when the array's `LIMITED_INTERPRETATION_GATE` passed:
coverage is a measurement and cannot outrank the QC that established it.

## Worked example

The following is a **historical illustrative example**. Its input and output artifacts are
not committed with hashes, so the numbers are not independently reproducible evidence and
must not be used as a release measurement:

```text
8 de 29 alvos do registro são interpretáveis (27.6%).
21 não foram testados, 0 sem chamada e 0 não reportáveis.
```

with 21 structured findings, one per blind spot — including `F5 rs6025` and `F2 rs1799963`
as `NÃO TESTADO`, never as an absent variant.
