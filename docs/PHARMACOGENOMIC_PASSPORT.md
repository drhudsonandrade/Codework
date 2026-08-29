# Pharmacogenomic passport (report 06 / PGX)

## Why this is the easiest report to falsify

Report 06 is the most clinically useful thing GENOMA can produce from data it already has,
and the easiest place to publish something false. The conventional output of a
pharmacogenomic panel is a **diplotype** (`CYP2C19 *1/*2`) and a **phenotype**
("metabolizador lento") — and a consumer SNP array can almost never support either.

Two facts make the usual shortcut wrong:

1. **`*1` is an assertion about positions that were never tested.** A star allele is defined
   by a set of positions. Observing three of CYP2C19's defining SNPs and finding none of
   them says *"nenhum dos alelos testados foi detectado"* — not `*1`. `*1` is the reference
   haplotype, a claim about *every* defining position including those the chip never
   carried. Reporting `*1/*1` from a partial panel converts NÃO TESTADO into NÃO DETECTADO,
   the exact substitution report 09 exists to prevent.
2. **A diplotype needs phase.** Two heterozygous calls in one gene are consistent with more
   than one diplotype, and array genotyping provides no read-level evidence to separate them.

## What the module does instead

`array_pipeline/pharmacogenomics.py` reports what was observed, states per gene exactly why
a diplotype could not be established, and refuses to emit a phenotype without one.

Scope is data-driven: a target is pharmacogenomic when the target registry routes it to a
PGx knowledge base (`clinpgx` / `cpic`). Extending the registry extends the passport without
editing the module. A ClinVar-only target such as `F5 rs6025` is clinical but not
pharmacogenomic, and stays out.

## The diplotype ladder

`_diplotype_for()` withholds a diplotype unless **every** precondition holds:

| condition | failure message |
|---|---|
| gene is not structurally unresolved | CYP2D6: variação estrutural não resolvida por array |
| a curated allele registry was supplied | registro curado não foi fornecido |
| the registry declares `complete_panel` for the gene | alelos não definidos permaneceriam indistinguíveis do haplótipo de referência |
| the registry names `reference_allele` | sem ele um portador heterozigoto não tem segundo elemento |
| every defining position is interpretable | posições definidoras não interpretáveis: … |
| at most one heterozygous position in the gene | fase não resolvida: N posições heterozigotas |
| at most one defined allele detected | genótipo composto: atribuição a cada cromossomo exige fase |

Even when all of them hold, the diplotype is `INFERIDO` — never `EXECUTADO`, because the
inference comes from genotypes rather than observed haplotypes. It always has exactly two
elements: a homozygous carrier gets `allele/allele`, a heterozygous carrier gets
`allele/reference`, and a non-carrier gets `reference/reference`. The reference haplotype is
whatever the registry *names* — this module will not coin `*1` on its own.

A phenotype is a function of a diplotype, so without one there is nothing to translate and
"normal metabolizer" would be an invented default. `genes_with_phenotype` is **counted** from
the gene records rather than asserted as a constant — hardcoding `0` would have stayed true
only until something emitted a phenotype, and then gone quietly wrong.

## What *is* reportable

With a curated registry, each defined allele gets a status that distinguishes the three
cases that matter:

- `DETECTADO` — every defining position interrogated, allele present;
- `NÃO DETECTADO` — every defining position interrogated, allele absent;
- `NÃO DISPONÍVEL` — at least one defining position not interpretable.

That third case is the one a conventional panel silently folds into the second.

## The allele-definition registry

Star-allele language may enter a report only through a curated registry, and the loader
refuses one that does not cite the source of its definitions — an uncited definition table
is an invented clinical assertion wearing a schema.

```json
{
  "schema": "genoma-pgx-registry-v1",
  "id": "...", "version": "...",
  "source": "citation for these allele definitions",
  "genes": {
    "BCHE": {
      "anesthesia_relevant": true,
      "anesthesia_note": "...",
      "alleles": {"BCHE*2": {"defining": [{"rsid": "rs1799807", "allele": "T"}]}}
    }
  }
}
```

The sourced registry ships as `config/pgx_allele_definitions.json` and can be regenerated
with `scripts/build_pgx_registry.py`. A run that does not supply a valid registry still
reports every diplotype as `NÃO DISPONÍVEL` rather than inventing definitions.

## The anaesthesia card

The card is emergency-facing, so it is the most dangerous surface in the report. It carries
observations only:

- it **never** states that anaesthesia is safe (`clearance_policy`);
- it states that absence of a finding does not exclude risk, because only assayed positions
  were interrogated;
- which genes belong on it is a clinical judgement read from the curated registry, not
  hardcoded — without a registry the card reports that its relevance list was never declared
  rather than guessing one;
- it is `NÃO DISPONÍVEL` when no relevant locus is interpretable **or** when the declared
  anaesthesia `scope.state` is not `COMPLETO`.

## Running it

```bash
python3 scripts/build_pharmacogenomic_report.py \
  --input array.csv.gz --qc array-qc.json \
  --targets config/partial_genome_annotation_targets.json \
  --annotation annotation.json \
  --pgx-registry config/pgx_allele_definitions.json \
  --pgx-panel config/pgx_panel_targets.json \
  --matrix-out completeness.json \
  --panel-matrix-out pgx-panel-completeness.json \
  --passport-out passport.json \
  --payload-out payload-06.json
```

`--annotation` and `--pgx-registry` are optional; without them the passport reports evidence
links and star alleles as `NÃO DISPONÍVEL` rather than omitting the question.

The payload is compiled through `PayloadCompiler` (see `docs/PROVENANCE_GATE.md`), so a
hand-written `"CYP2C19 *1/*1 — metabolizador normal"` pasted into the summary is refused at
render time rather than published.

## Worked example

**Illustrative, not verified.** There is no output artifact, input SHA-256 or pinned command
in `docs/evidence/` behind these numbers; they are not release evidence. The shape of the
output is the point, not the counts.

A demonstration array carrying 8 of the 19 pharmacogenomic loci produces:

```text
8 de 19 loci farmacogenômicos são interpretáveis (42.1%) em 10 genes.
Diplótipos estabelecidos: 0. Fenótipos emitidos: 0.

BCHE   (2/2): rs1799807=CT, rs1803274=CC   | diplótipo: NÃO DISPONÍVEL
CYP2C19(1/3): rs4244285=GG, rs12248560=NÃO TESTADO, rs4986893=NÃO TESTADO
DPYD   (0/4): todos NÃO TESTADO
```

The DPYD line is the point of the whole report: a patient about to receive
fluoropyrimidine has **no** DPYD coverage on this array, and the document says so instead of
staying silent.
