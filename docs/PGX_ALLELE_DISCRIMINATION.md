# Allele discrimination, residual risk, and sequencing requisition

## The problem as it had been stated

The prior wording is preserved as historical context:

> A array cobre 1 a 4 das 40 a 80 posições definidoras por gene do CPIC. Nenhum diplótipo
> farmacogenético sairá dela além do VKORC1. Isso pede sequenciamento dirigido dos genes de
> interesse, não mais código.

Two claims were embedded in that sentence. One was an artifact of this pipeline. The other was real, but admitted a much better answer than “it cannot be done.”

## First cause: coverage measured the target list, not the array

`config/partial_genome_annotation_targets.json` lists 29 hand-selected loci. The completeness matrix classifies exactly those 29. The passport then compared CPIC defining positions against that matrix, so **every CPIC position outside those 29 returned `NÃO TESTADO` by construction**, whether the array actually assayed it or not.

CPIC publishes 342 unique defining positions for the ten genes in the registry. A consumer array assays hundreds of thousands of genomic positions. How many of the 342 it actually carries had never been measured; it had only been assumed.

`scripts/build_pgx_panel.py` derives a second target manifest containing **all** 342 positions, with GRCh38 coordinates and reference accessions. Running the completeness matrix over that manifest turns the question into a measurement:

```bash
python3 scripts/build_pgx_panel.py
python3 scripts/build_pharmacogenomic_report.py \
    --input DNA.csv.gz --qc array-qc.json \
    --targets config/partial_genome_annotation_targets.json \
    --pgx-registry config/pgx_allele_definitions.json \
    --pgx-panel config/pgx_panel_targets.json \
    --matrix-out matrix.json --panel-matrix-out panel-matrix.json \
    --passport-out passport.json --payload-out payload-06.json
```

Without `--pgx-panel`, the passport still works and **states on its face** that coverage measures only the curated targets (`panel_matrix.status = NÃO DISPONÍVEL`). Absence of the panel never means complete coverage.

## Second cause: the refusal was binary while the data are quantitative

`_diplotype_for` refuses a call if *any* defining position for the gene is not interpretable. The refusal is correct — `*1` asserts the reference base at every defining position, including positions the chip never read — but it is all-or-nothing. It fires identically for a gene missing one extremely rare allele and for a gene missing forty common alleles, leaving the reader unable to distinguish those cases.

`array_pipeline/allele_discrimination.py` replaces that binary decision with a measurement.

### 1. Partition

For each gene, CPIC alleles are separated into **discriminable** (every defining position is interpretable in this sample) and **non-discriminable** (at least one is not). An allele with no defining position in the registry never counts as discriminable: `all()` over an empty requirement is true, which is exactly the kind of vacuous truth this project repeatedly guards against.

### 2. Residual risk

Non-discriminable alleles are weighted using CPIC’s own allele-frequency table by biogeographic group:

```text
residual = P(one chromosome carries an altered-function allele that this panel cannot see)
```

Because the sample ancestry is not established, the system reports the **highest-risk group**, not the average. An average could underestimate risk for the population to which the person actually belongs.

Two flags preserve the honesty of the number:

| field | meaning |
|---|---|
| `computable` | CPIC publishes a frequency for at least one allele not excluded |
| `bounded` | CPIC publishes a frequency for **all** of them, so the number is the residual rather than a lower bound |

A residual of zero because everything was excluded and a residual of zero because nothing could be priced are opposite situations. The two flags exist so they can never look the same.

A clinical-function label outside the vocabulary published by CPIC — including null — counts as **uncertain**, never normal. If CPIC renames a status, residual risk increases; it does not silently shrink.

### 3. Conditional diplotype

This is emitted in its own field (`discrimination.conditional_diplotype`), **never** in `diplotype.value`. A consumer that already reads an established diplotype therefore cannot silently begin reading a conditional one.

The second element is not `*1`. It is `[NÃO DETECTADO]` — report-09 vocabulary that means “interrogated and absent,” which is what is actually known:

```text
CYP2C19*2/[NÃO DETECTADO]
  "*2 detectado em um cromossomo; o outro cromossomo não carrega nenhum dos 15 alelos
   discrimináveis, e permanece indistinguível de 30 alelos não interrogados"
  conditional_on: nenhum dos 30 alelos do catálogo CPIC não interrogados está presente
  residual: 0,0321 (Sub-Saharan African), limite inferior
```

Every precondition for the unconditional diplotype remains in force: non-structural gene, named reference haplotype, at most one detected allele, and at most one heterozygous defining position. The only replaced requirement is panel completeness, exchanged for an **explicit and quantified** closed-world assumption. Status is always `INFERIDO`.

An empty discriminable set does not produce a call: a “reference/reference” result from zero interrogated positions would be precisely the conversion from NÃO TESTADO to NÃO DETECTADO that report 09 exists to prevent.

### 4. Conditional phenotype

The phenotype is looked up in the CPIC table, never composed. It requires a `computable` residual; bounded is **not** required, because a small number of CPIC alleles have no published frequency in any population and that would otherwise block every gene, but the limitation is never hidden. The phenotype record carries `residual_bounded`, `residual_worst_altered`, `residual_unpriced_alleles`, and a prose `caveat`, so the label cannot be quoted separately from the assumption supporting it.

### 5. Targeted-sequencing requisition

“Targeted sequencing is needed” is a conclusion, not an instruction. `sequencing_requisition` turns it into an instruction: a greedy selection over uncovered positions, ordered by the frequency mass recovered at each position, with GRCh38 coordinates and the residual after each step.

The following example is **illustrative and unverified**. There is no output artifact, input SHA-256, or pinned command under `docs/evidence/` supporting these numbers, so they are not release evidence:

| gene | missing positions | 1st position | recovered mass |
|---|---|---|---|
| NAT2 | 31 | rs1208 (chr8:18400806) | 0.684 |
| SLCO1B1 | 26 | rs2306283 (chr12:21176804) | 0.150 |
| CYP3A5 | 5 | rs10264272 (chr7:99665212) | 0.193 |

In the example, the CYP3A5 row illustrates the point: `rs10264272` is `*6`, common in African populations, which is why a CYP3A5 call based only on `rs776746` is unsafe for that group. The algorithm is designed to derive that prioritization from the CPIC table; the table above remains illustrative until an execution materializes and pins the artifacts.

## What remains true

Sequencing the listed positions does **not** resolve structural alleles (duplications, hybrids, deletions), does **not** establish phase, and an allele that CPIC does not catalogue remains indistinguishable from the reference haplotype even with complete coverage. Every requisition states this in `scope_note`.

CYP2D6 still has no diplotype in any scenario because its clinically relevant variation is structural.

## Where each component lives

| file | role |
|---|---|
| `scripts/build_pgx_registry.py` | retrieves CPIC definitions, clinical functions, **population frequencies**, and **GRCh38 coordinates** |
| `scripts/build_pgx_panel.py` | derives the target manifest containing all 342 defining positions |
| `array_pipeline/allele_discrimination.py` | partitioning, residual risk, conditional diplotype/phenotype, requisition |
| `array_pipeline/pharmacogenomics.py` | integrates per gene; conditional totals remain separate from established totals |
| `tests/test_allele_discrimination.py` | each guard with its negative control |
