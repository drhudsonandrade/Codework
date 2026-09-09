# Target registry expansion

## What changed

| registry | targets | source |
|---|---:|---|
| `partial_genome_annotation_targets.json` | 29 | manual curation (ClinVar + CPIC + dbSNP) |
| `pgx_panel_targets.json` | 342 | CPIC defining positions |
| `targets_clinvar_plp.json.gz` | **54,845** | ClinVar bulk release, P/LP, 2★+ |
| `targets_clinvar_plp_1star.json.gz` | **123,551** | same source, also admitting one-star review |
| `targets_gwas_traits.json` | **733** | GWAS Catalog, declared terms |
| `targets_merged_panel.json.gz` | 55,916 | union using the 2★ threshold |
| **`targets_merged_panel_1star.json.gz`** | **124,621** | union using the 1★ threshold — **the default** |

The default moved to the 1★ registry because interpretation classifies by review level rather than simple membership: the level remains visible in the report instead of being diluted into the panel. In one demonstration execution the output contained 93 ACHADO PRELIMINAR versus 20 ACHADO ACIONÁVEL. That number is **illustrative and unverified** because no output artifact, input SHA-256, or pinned command under `docs/evidence/` supports it. The 2★ pair remains selectable through `--targets`/`--evidence` for an execution that should consider only curated consensus.

At the 1★ threshold there are **4,408 genes**, of which **3,895** have established gene-disease validity: 2,535 occur in recessive relationships, 1,602 in dominant relationships, and 163 in X-linked relationships. These categories overlap. The 4,300 occurrences represent 3,895 unique genes and are not disjoint sets.

At the 2★ threshold, which was the former default, the versioned target artifact `config/targets_clinvar_plp.json.gz` supports reproducible counts of **54,845 rsIDs and 3,082 genes**. That is the limit of what the current HEAD supports for this threshold.

> **Medição histórica não verificada — validade gene-doença no corte 2★.** Uma revisão
> anterior deste documento publicou **2.965 genes estabelecidos**, **117 sem relação
> estabelecida** e uma decomposição por ClinGen/GenCC/PanelApp/ClinGen Dosage/gnomAD. O
> repositório atual não contém um artefato de validade gene-doença para o mesmo universo de
> 3.082 genes que permita reproduzir essas contagens. `docs/evidence/GENE_DISEASE_VALIDITY.json`
> contém apenas **16 genes (7 estabelecidos, 9 não estabelecidos)** e, portanto, não é o
> denominador correspondente ao painel 2★. As contagens 2.965/117 e sua antiga tabela por
> fonte ficam preservadas apenas como histórico de uma execução não reproduzível e **não são
> evidência de release**. Elas só podem voltar como verificadas quando um artefato versionado,
> com SHA-256 e comando reproduzível, materializar esse mesmo corte.

For the **1★ artifact** that is actually versioned, validity counts are reproducible: **4,408 genes**, **3,895 with established validity**, **540 established only by PanelApp**, **3 only by GenCC**, **0 only by ClinGen Dosage**, **3,249** with PanelApp/GenCC overlap, and **103 established by ClinGen Gene-Disease Validity outside those PanelApp/GenCC categories**. This exhaustive decomposition closes to the **3,895** established genes. Separately, **1,289** have dosage curation, **3,990** have a gnomAD constraint metric, and **1,004** have pLI ≥ 0.90. These counts come from `docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz`. PanelApp submissions overlapping GenCC remain marked as one curation basis, and gnomAD still cannot establish a gene-disease relationship.

## Curated registries that decide what becomes a finding

None of them is ClinVar. ClinVar says what a **variant** is; these registries say whether the **gene** has an established relationship with disease. Without that second condition, the system does not convert a variant into a clinical finding.

| registry | what it states | counts as established when |
|---|---|---|
| ClinGen Gene-Disease Validity | an expert panel curated the relationship | Definitive or Strong classification |
| GenCC | multiple curators submitted the same relationship | ≥2 independent submitters at Definitive/Strong |
| **PanelApp** (Genomics England + Australia) | a health service tests the gene in practice | **green** gene in at least one diagnostic panel |
| **ClinGen Dosage Sensitivity** | copy loss or gain is the mechanism | score 3 for haploinsufficiency or triplosensitivity |
| gnomAD v4.1 constraint | how intolerant the gene is to loss of function | **never** — constraint is not gene-disease validity |

Each gene records its supporting sources in `established_by`. “Definitive by a ClinGen expert panel” and “green in an NHS panel” carry different evidentiary weights, and flattening them into one boolean would hide that distinction.

**PanelApp is not independent of GenCC.** The GenCC export already aggregates submissions from both PanelApp instances. Where both establish the same gene, that is one body of curation appearing twice, not two agreeing sources. `panelapp_overlaps_gencc` marks those genes, and report 01 writes the caveat in the uncertainty section.

**The scan, measured.** Across the two instances there are 68,991 gene-panel entries covering **657 panels** — 414 from Genomics England and 243 from PanelApp Australia — of which 652 contain at least one green gene. The index contains 7,239 genes and **5,004 green genes**. PanelApp is live: across two scans a few hours apart, Australian counts moved from 36,485 to 36,491 entries. The artifact therefore records date and counts instead of citing them from memory. A short read is refused rather than published: a partial crawl is not a smaller registry; it is a registry that silently omits panels sorted later.

**Green, and only green.** Amber means insufficient evidence for reporting, while red means the curators considered and rejected the gene. Treating amber as evidence would place in a report a gene the panel explicitly declined to endorse. Both categories remain in the artifact; only green establishes validity.

**Dosage scores are not a scale.** The values 30 and 40 are numerically larger than 3 but not stronger evidence. A score of 3 means “sufficient evidence for dosage pathogenicity”; 30 means the curator wrote “gene associated with autosomal recessive phenotype” *instead of* scoring, and 40 means “dosage sensitivity unlikely.” Treating 30 as greater than 3 would establish 599 genes that ClinGen never established. Here, 3 establishes validity, 30 contributes AR inheritance mode without establishing validity, and 40 contributes nothing.

**Population constraint is carried but never establishes.** A gene may be highly intolerant of loss of function without a curated disease relationship, and a Definitive disease gene may be unconstrained. CFTR has pLI around 0 because carriers are common and healthy. Constraint appears in the report so that a “no established validity” row may still state whether the gene is constrained, and for no other purpose.

## PGS Catalog: 6,972 scores and the two conditions that determine whether any can be used

PGS Catalog publishes 6,972 polygenic scores across 807 mapped traits, far more traits than the GWAS Catalog route reaches. What it **does not** publish is permission to apply every score to a specific person. Two fields decide whether application is defensible; both are computed rather than estimated.

**Ancestry of the cohorts in which the score was built.** A polygenic score is a set of weights fitted in one population, and its accuracy falls — often by half — when transferred to another population with different allele frequencies and linkage disequilibrium. For an admixed Brazilian genome this is not a footnote but a dominant error source:

| class | scores |
|---|---:|
| **NÃO TRANSFERÍVEL SEM CALIBRAÇÃO** (cohorts ≥90% European) | **4,361** |
| TRANSFERIBILIDADE INCERTA | 2,393 |
| **PARCIALMENTE TRANSFERÍVEL** (≥20% Hispanic/Latino, African, or Native) | **202** |
| ancestry not declared by the catalog | 16 |

**Number of variants versus how many an array can read.** The median score contains 123,613 variants and the largest contains 10.3 million; a consumer array carries about 700,000 positions across the whole genome. Summing weights only for present variants while treating missing variants as dosage zero is vacuous truth in its purest form: it produces a finite, plausible, wrong number, and nothing in the output reveals that most of the score was missing. Below **95%** coverage the system refuses rather than emits a score.

No score weights are copied into this repository. Each score is cited by the harmonized-file URL and by its **own license**, which is not uniform: 6,879 are citation-only, 31 are CC BY-NC-ND, 7 are academic use only, 1 is research restricted, and 54 declare no license in the catalog. Flattening these terms into one registry-level license could authorize a use forbidden by the score author.

## ClinVar review level travels with the target

The registry can be built from 2★ (curated consensus) or 1★ (single submitter), and every target declares its own `clinvar_review_stars`. That is what makes the broader registry safe:

| threshold | rsIDs | genes | genes reachable only at this threshold |
|---|---:|---:|---:|
| 2★+ | 54,845 | 3,082 | — |
| 1★ only | 68,706 | — | 1,326 |
| union | **123,551** | **4,408** | |

These counts are **derived from versioned artifacts**, not transcribed. They come from `config/targets_clinvar_plp.json.gz` and `config/targets_clinvar_plp_1star.json.gz`; their SHA-256 values are published below. Reproduce them with:

```bash
python3 - <<'PY'
import json, gzip
from pathlib import Path
def load(p):
    raw = Path(p).read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
two = load("config/targets_clinvar_plp.json.gz")
one = load("config/targets_clinvar_plp_1star.json.gz")
def genes(document):
    values = set()
    for target in document["targets"]:
        target_genes = target.get("genes", [])
        if isinstance(target_genes, str):
            target_genes = [target_genes]
        if isinstance(target_genes, list):
            values.update(gene for gene in target_genes if isinstance(gene, str) and gene)
    return values
r2 = {t["rsid"] for t in two["targets"]}; r1 = {t["rsid"] for t in one["targets"]}
print(len(r2), len(genes(two)))
print(len(r1 - r2), len(genes(one) - genes(two)))
print(len(r1), len(genes(one)))
PY
```

The previous table published 54,801 / 74,161 / 123,541 and gene counts that did not correspond to any artifact field. `só 1★` is the one-star-exclusive tier (`target_statistics.tier_1_star`), not the total size of the 1★ file; 54,845 + 68,706 = 123,551 closes exactly to the published total.

A one-star locus **never** becomes an actionable finding or carrier state. Interpretation downgrades it to `ACHADO PRELIMINAR`, with report text stating that a single-submitter assertion is one laboratory’s opinion rather than curated consensus. Without that downgrade, lowering the threshold would report tens of thousands of single opinions as findings, which is precisely why review level travels with each target. The default application panel is the 1★ union declared at the start of this document; the generator keeps 2★ as its fail-closed default and requires `--min-review-stars 1` to materialize the expanded alternative explicitly.

## Why the bulk release instead of the API

The E-utilities route requires many requests and may terminate partially under traffic limits without producing one artifact that materializes the consulted release. `variant_summary.txt.gz` provides the same kind of data in one materializable download: either the complete file is available or execution must refuse. The same principle applies to the GenCC and GWAS Catalog artifacts used here.

## ClinVar filters and why each is a refusal rather than convenience

> **Medição histórica não verificada:** a cadeia de contagens publicada anteriormente não
> fechava aritmeticamente entre 62.367 linhas e 54.845 alvos e não citava um artefato de
> saída com SHA-256. Os números intermediários foram removidos. O filtro reproduzível é:
> GRCh38, SNV, classificação P/LP exata, limiar explícito de estrelas, rsid presente e
> alelos A/C/G/T; as contagens devem ser lidas de `scan_statistics`,
> `target_statistics` e `totals` nos artefatos gerados pela execução.

Of the 54,845 targets, **50,515** have one assessed allele and **4,330** do not. ClinVar asserts more than one alternate base at the same coordinate for the latter group, and choosing one would be arbitrary. Those loci can reach OBSERVADO but never NÃO DETECTADO.

## Coordinate joining in both routes

The API route finds records through **text search** by rsID, which may return variants unrelated to the intended locus. Those records do not carry their own coordinate and are admitted only when the accession is already present in the verified set at the target coordinate.

The bulk route reads accession, classification, and coordinate from the **same release row**. There is no cross-source join to misalign, and the record carries the coordinate, so it enters only when it matches the locus coordinate. This is a check performed in code, not a flag that an evidence file can set to excuse itself: a record without a coordinate falls back to the accession list regardless of what provenance the file declares.

## Trait scope: the only judgment-based component

GWAS Catalog labels each association with an ontology term but **does not publish thematic categorization**; nothing in the catalog says that lactose intolerance is nutritional. That decision lives in `config/trait_scopes.json`, with the ontology ID for each term and a written justification. Everything downstream — which loci, which risk allele, effect size, and discovery cohort — comes from the catalog.

`scripts/build_trait_targets.py` **refuses** a declared term with no genome-wide significant association in the release. Two terms were caught by that guard:

| term | reason |
|---|---|
| `GO_0050916` sweet taste perception | 56 associations, strongest p = 4e-07 — below genome-wide significance. Popular consumer-report trait, with no established locus. |
| `MONDO_0100345` lactose intolerance | zero mapped associations in the annotated release. Lactase persistence enters through `EFO_0801753` (rs4988235) and `OBA_VT0015043`, both verified. |

## Conflict found by the merge

`rs3918290` is **multiallelic** at chr1:97450058 (GRCh38, reference C):

* **C>T** = `c.1905+1G>A` = **DPYD\*2A**, classified by ClinVar as *drug response*; this is the allele CPIC defines;
* **C>G** = `c.1905+1G>C`, a **different** variant at the same position, and this one is P/LP.

Both sources are correct about distinct variants. An rsID **does not identify one variant** at a multiallelic site. Arbitrating between them would score a genotype against the wrong base at a fluoropyrimidine-toxicity locus. The merge therefore removes the assessed allele and records the divergence.

The cost is small and correct: the pharmacogenomic passport is unaffected because it tests against the allele from **its own** CPIC registry, not the target’s `assessed_allele`. Only the NÃO DETECTADO completeness-matrix class is withheld at that locus, which is correct because “not detected” is ambiguous when two clinically distinct variants occupy one position.

## Scale observed in a demonstration execution

Quantitative benchmarks from the historical execution were removed from this document because the repository does not contain the output artifact, input SHA-256 values, environment versions, and pinned command needed to reproduce them. They are not evidence for the current HEAD and cannot be used as performance claims.

The reproducible behavior preserved from that investigation is compressed-evidence support: `build_clinical_findings` reads the manifest through `read_manifest_text`, which detects compression from file contents. The contract is exercised by `tests/test_clinical_findings_regressions.py::test_the_gene_disease_evidence_may_arrive_compressed`. Run only that suite with:

```bash
python3 -m unittest discover -s tests -p test_clinical_findings_regressions.py
```

Old execution narratives for reports 05 and 09 also remain outside the verifiable set for this HEAD: there is no versioned artifact and corresponding reproducer here that authorizes quantitative results to be attributed to those paths.

## Detection rate, the original objective

Report 03 emits, for every execution, the numerator of interrogated variants and the denominator of the applicable catalog. Historical values from a local execution were removed because no output artifact, input SHA-256, and pinned command allow them to be reproduced on this HEAD. The verifiable contract is that numerator and denominator are derived from artifacts belonging to the execution itself and that output describes them as variant counts rather than allele frequency.

## Reproduce

The GWAS slice used for this curation is the release dated **2026-08-24**. Download the two exact files and verify their bytes before running the builder:

```bash
curl -fLO https://ftp.ebi.ac.uk/pub/databases/gwas/releases/2026/08/24/gwas-catalog-associations_ontology-annotated-full.zip
curl -fLO https://ftp.ebi.ac.uk/pub/databases/gwas/releases/2026/08/24/gwas-catalog-download-ancestries-v1.0.3.1.txt
printf '%s  %s\n' \
  9109f1aa0f7a4e9a808dd277c2a321c82d98c86f199ff6bfc04c81e5f4d4ec20 \
  gwas-catalog-associations_ontology-annotated-full.zip \
  afcc1cb6e2c7230577e955436dd597a8fd730176e418ba71c14b29604d235f26 \
  gwas-catalog-download-ancestries-v1.0.3.1.txt | sha256sum --check --strict
```

```bash
curl -O https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
curl -O https://ftp.clinicalgenome.org/ClinGen_gene_curation_list_GRCh38.tsv
curl -O https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv
python3 scripts/curate_panelapp.py            # scans both instances; refuses a short read
python3 scripts/expand_clinvar_targets.py \
    --clinvar-bulk variant_summary.txt.gz \
    --panelapp docs/evidence/PANELAPP_CURATION.json.gz \
    --clingen-dosage ClinGen_gene_curation_list_GRCh38.tsv \
    --gnomad-constraint gnomad.v4.1.constraint_metrics.tsv \
    --min-review-stars 1 \
    --targets-out config/targets_clinvar_plp_1star.json.gz \
    --evidence-out docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz
python3 scripts/build_trait_targets.py \
    --associations gwas-catalog-associations_ontology-annotated-full.zip \
    --ancestries gwas-catalog-download-ancestries-v1.0.3.1.txt
python3 scripts/merge_target_manifests.py \
    config/partial_genome_annotation_targets.json \
    config/pgx_panel_targets.json \
    config/targets_clinvar_plp_1star.json.gz \
    config/targets_gwas_traits.json \
    --output config/targets_merged_panel_1star.json.gz
```

## Provenance of published counts

The URLs above **do not pin a release or digest**. ClinVar, ClinGen, gnomAD, and PanelApp are mutable sources: running the block on another date may produce records and counts different from those published here. That is not a reproduction defect; it is the nature of the sources.

What remains fixed is the other side of the comparison. Every count in this document was read from the artifacts below as versioned in this commit. Recounting from those artifacts is deterministic; recollecting from upstream sources is not.

| Artifact | SHA-256 |
| --- | --- |
| `config/targets_clinvar_plp.json.gz` | `8afcfa91ffe98407ca16685a2d85a2794bf54984c9120aa46c38307b462e97fd` |
| `config/targets_clinvar_plp_1star.json.gz` | `dfee157e673bad8611076ea5d3f57037fc7cc38b8dc4731f8be918e1d2b852f8` |
| `config/targets_merged_panel.json.gz` | `955cfe674d02c85eb9b5f18a726f1a60f392caf4f26f138d9d218699d903dbc9` |
| `config/targets_merged_panel_1star.json.gz` | `d9d57f109c212c5248bd680e5044e093dee352a13fa11c0731cf731e35e2c40a` |
| `config/targets_gwas_traits.json` | `920ee4ad18ca5c17546a240ba89b1e226d20d18ee280352d37ee1879c6cd18e9` |
| `docs/evidence/PANELAPP_CURATION.json.gz` | `ed5d495c68ec50782848873f5c7960d8532db30cd3045605157aea4c9449d54c` |
| `docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz` | `39aedaa763db55812ee4bf230e8c02068da012b034ffa7d78d23fff64c42a925` |
| `docs/evidence/PGS_CATALOG_REGISTRY.json.gz` | `a3f4c61c672850e0f18d915d6e4460d7731ca859e2e2f3de25aa9d959f024cbd` |

The SHA-256 values in this table are hashes of the **versioned file bytes**. Some JSON documents also carry an internal `sha256` field for the logical payload; that internal digest has a different scope and does not replace the hash of the stored `.json`/`.json.gz` file. The two new file hashes were rerun on this HEAD with `sha256sum`.

To compare a new collection with what is published, generate the artifacts, compare SHA-256 against the table, and treat any difference as an updated source rather than a reproduction error.
