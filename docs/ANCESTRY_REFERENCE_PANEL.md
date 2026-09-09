# Population reference panel (report 02)

## What was missing

Report 02 previously refused to estimate ancestry, and that refusal was correct: allele frequency separates populations in aggregate but does not position an individual. What was missing was a **genotype** panel with named populations that could be cited.

## What was found

| source | samples | role |
|---|---:|---|
| 1000 Genomes, **Affymetrix 6.0** chip | 3,450 | AFR, EUR, EAS, SAS, AMR |
| **AADR** v66.p1, present-day Human Origins genotypes | 97 | AMR-NAT-AMAZONIA, AMR-NAT-ANDES, AMR-NAT-MESOAMERICA |

The Mao et al. Native American panel (43 individuals) was **replaced** by AADR for two reasons that point in the same direction; see “Why AADR replaced Mao et al.” below.

Karitiana and Surui are **Tupí peoples from Rondônia in the Brazilian Amazon**; Piapoco are from the Orinoco-Amazon basin. This is the local reference that was missing. The limitation stated in the previous version of this document was precisely that Nahua, Maya, Quechua, and Aymara are Mesoamerican and Andean, so the Indigenous component of a Brazilian genome was being estimated against related but non-local populations.

Without a Native American reference, the only available alternative would be the 1000 Genomes AMR group, which is **itself admixed**. Estimating the Indigenous component of a Brazilian person against PEL would therefore measure it with a ruler partly made of the quantity being measured.

## Why AADR replaced Mao et al.

The two references are alternatives, not additive. Mao et al. uses Affymetrix 6.0 while AADR uses Human Origins, and requiring both would intersect three platforms.

| intersection with the 1000 Genomes Affy 6.0 release | coordinates |
|---|---:|
| Mao et al. (Affy 6.0) | 51,263 |
| **AADR (Human Origins)** | **162,289** |
| all three together | 12,889 |

AADR wins on both criteria at once: **three times more markers** and Brazilian Amazonian populations where Mao et al. provides only Mesoamerican and Andean groups. Keeping both would cost 92% of the markers.

The three Native American groups enter **separately**, not as one “AMR-NAT” bucket. Combining them is exactly what caused an Amazonian genome to be measured against Andean references.

| group | n | peoples |
|---|---:|---|
| AMR-NAT-AMAZONIA | 24 | Karitiana, Surui (Brazil), Piapoco (Colombia) |
| AMR-NAT-ANDES | 11 | Quechua (Peru), Bolivian |
| AMR-NAT-MESOAMERICA | 62 | Mayan, Mixe, Mixtec, Pima, Zapotec (Mexico) |

Only **present-day** individuals with Human Origins genotypes are included. Individuals that the source curators themselves marked as *discovery*, *outlier*, or *QC-remove* are excluded; placing an individual explicitly flagged by the source inside a reference centroid would turn an outlier into part of the reference.

## Two defects exposed by reading AADR

**Row displacement.** `packedancestrymap` is documented as padding the header to a full row, but this file does not. Its 3.8 GB size is exactly `48 + linha × indivíduos`, 145,985 bytes shorter than the documented layout. Reading it according to the convention shifted every genotype read by almost a full row, serving each individual a scrambled mixture of two people: data that decompressed without error, had plausible call rate, and were wrong. The layout is now **derived from the actual file size**; a size that matches neither candidate layout is refused instead of being rounded to the nearest one.

**Allele orientation.** The two bits per genotype count copies of one of the two alleles in `.snp`, and which allele they count is a convention. The script does not assume it. It measures the encoding by comparing allele frequencies for French, Han, and Yoruba AADR samples with EUR, EAS, and AFR superpopulations from 1000 Genomes on the same markers. A reversal appears as correlation close to −1.

```text
measured correlations: −0.985 (EUR)  −0.989 (EAS)  −0.966 (AFR)  →  INVERTED
```

The same check exposed the row displacement: with the wrong header interpretation the correlations were −0.002, −0.004, and −0.000. Correlation near zero is not strand orientation to correct; it is a bad join, and the panel is refused in that state.

## Construction

```text
584,131 Human Origins markers (AADR v66.p1, GRCh37)
→ 579,720  autosomal
→ 162,289  coordinate intersection with the 1000 Genomes Affy 6.0 release
→ 162,286  after excluding palindromic (1) and divergent-allele markers (2)
→ 149,753  after MAF >= 0.05 and missingness <= 2%
→  80,801  after LD pruning (window 50, step 5, r² < 0.2)
→  60,000  after deterministic thinning, uniform across the genome
```

Versus 12,914 markers in the previous panel: **4.6× more**.

**Join by coordinate, not ID column.** Only 29% of IDs in the 1000 Genomes release are rsIDs; the rest are probe identifiers (`SNP1-524110`). An rsID-only join would discard seven out of ten markers.

**Palindromic markers excluded.** A/T and C/G do not carry strand information. Both Native American panels already contain **zero** palindromic markers because their authors removed them, and the script removes them again rather than trusting that assumption. That is why the excluded count is 1 rather than the roughly 15% present in the Affy 6.0 release alone.

**The 188 orientation controls leave the panel** after answering their question. French, Han, and Yoruba AADR samples are included only to measure allele encoding. Keeping them would duplicate the same populations across two platforms, shifting those centroids and encouraging a principal component that describes the assay rather than the people.

## The panel separates populations

| population | n | PC1 | PC2 |
|---|---:|---:|---:|
| AFR | 655 | +117.1 | +7.3 |
| AMR | 347 | −37.2 | −16.2 |
| **AMR-NAT-AMAZONIA** | **24** | **−67.1** | **+47.9** |
| AMR-NAT-ANDES | 11 | −63.4 | +37.4 |
| AMR-NAT-MESOAMERICA | 62 | −64.2 | +43.0 |
| EAS | 501 | −59.4 | +82.2 |
| EUR | 502 | −41.0 | −65.2 |
| SAS | 487 | −41.6 | −14.4 |

The three Native American groups remain close to each other, as expected for related populations. PC9 is what separates them: Amazonia is +76.0 versus −12.8 for the Andes and −5.2 for Mesoamerica.

## Validation: eleven known individuals, including what the panel gets wrong

Historical validation was produced by the now-absent `scripts/validate_ancestry_panel.py` and is retained as the snapshot `docs/evidence/ANCESTRY_PANEL_VALIDATION.json`. These names identify the provenance of a historical, non-reproducible record rather than an available procedure. The snapshot **includes panel errors**, because a validation record listing only successful cases would be marketing rather than validation.

| sample | known population | closest | residual | composition |
|---|---|---|---:|---|
| NA19625 | Yoruba, Nigeria | AFR ✓ | 7% | AFR 67%; **AMR-NAT-MESOAMERICA 20%**; EUR 9% |
| NA12878 | CEU, Utah | EUR ✓ | 12% | EUR 99% |
| NA18525 | Han, Beijing | EAS ✓ | 8% | EAS 97% |
| HG01565 | Peruvian, Lima | AMR-NAT-ANDES ✓ | 6% | AMR-NAT-ANDES 65%; EUR 26%; AMR-NAT-AMAZONIA 4% |
| NA20502 | Tuscan, Italy | EUR ✓ | 23% | EUR 94%; SAS 5% |
| HG02461 | Gambia | AFR ✓ | 27% | AFR 100% |
| HGDP00995 | **Karitiana, Brazil** | AMR-NAT-AMAZONIA ✓ | 16% | AMR-NAT-AMAZONIA 100% |
| HGDP00832 | **Surui, Brazil** | AMR-NAT-AMAZONIA ✓ | 6% | AMR-NAT-AMAZONIA 100% |
| HGDP00702 | Piapoco, Colombia | AMR-NAT-ANDES ✓ | 7% | ANDES 48%; AMAZONIA 28%; MESOAMERICA 24% |
| NA11200 | Quechua, Peru | AMR-NAT-ANDES ✓ | 11% | AMR-NAT-ANDES 100% |
| HGDP00854 | Mayan, Mexico | AMR-NAT-MESOAMERICA ✓ | 3% | MESOAMERICA 60%; ANDES 32% |

All eleven fall within the correct population family. Karitiana and Surui project as 100% Amazonian, which is the important test for a Brazilian genome. The Lima Peruvian projects as 65% Andean and 26% European: that reflects the real Lima profile rather than a model artifact. AMR populations in 1000 Genomes are admixed by definition, and counting that true ancestry as error would inflate the only metric this file is intended to report honestly.

## The honest artifact: 19.8%

**NA19625 is Yoruba and receives a 20% Mesoamerican Native American component.** That is not ancestry; it is the fit distributing weight along directions that the reference basis does not separate well in that part of the space. It is the largest measured spurious component, and it is the value report 02 cites.

The previous panel produced 17.5% in the same individual with a 28% residual, and the system warning was tied to residual: above 15%, “small components may be artifacts.” **That warning stopped working.** With 60,000 markers the same Yoruba sample fits with only 7% residual — “good” fit quality — while still receiving a 20% spurious component. Residual and artifact do not move together, so a guard tied to residual misses the exact case for which it was written.

The correction is that the minority-component caveat is now **unconditional**, and the size it cites is **measured rather than stipulated**. It comes from the validation artifact stamped into the panel itself. If a panel has no validation data, the text says that the typical size of a spurious component has not been measured instead of inheriting a number from another construction.

> Componentes abaixo de 20% não são estabelecidos por esta projeção.

**None of these individuals is held out from the panel.** All contributed to the loadings, so the projections are optimistic. This measures internal consistency and artifact detection, not out-of-sample accuracy, and the artifact records this explicitly as `held_out: false`.

## Projection guards

| guard | behavior |
|---|---|
| build | a GRCh38 case against a GRCh37 panel **refuses**; the rsID join would otherwise run silently |
| minimum markers | below 2,000 markers it emits nothing because the projection becomes noise-driven |
| overlap | below 7,500 shared markers it emits affinity but **withholds proportions** because shrinkage grows as overlap falls |
| strand | an allele pair matching neither panel nor complement is discarded and counted |
| residual | measures how far the person lies from the mixture described by the weights, with a warning above 15% |
| minority component | **unconditional** caveat citing the largest spurious component measured in the panel (19.8%) |

The proportion threshold is **absolute, with the fraction as a secondary floor**, correcting a defect introduced by the reconstruction itself. 60% of a 12,914-marker panel is 7,748 markers, while 60% of a 60,000-marker panel is 36,000. An array that qualified for proportions against the smaller panel would be refused by the better panel despite carrying strictly more information. Shrinkage depends on how many markers were used, not on how many the panel contains.

## What this is not

**These are not ADMIXTURE proportions.** They are constrained least-squares weights for the projected point over reference-population centroids: a geometric statement about principal components, not a mixture-likelihood estimate, and they do not decompose the genome into local-ancestry segments.

## Remaining limitations

- **Overlap with a consumer array has never been measured.** The panel comes from the Affy 6.0 × Human Origins intersection; how much of it a consumer Illumina chip carries is unknown until a real case is projected. The guard exists and withholds proportions below 7,500 shared markers, but refusing is not the same as proving that it works. No projection from a real consumer array has been executed against this panel or the prior panel.
- The Amazonian reference contains **24 individuals** from three peoples. Karitiana and Surui are from Rondônia; there is no reference for peoples from Northeast Brazil, the South, Xingu, or the Atlantic coast, and Brazilian Indigenous diversity cannot be represented by three peoples.
- All 97 Native American individuals come from Human Origins, a platform with its own **ascertainment**. Markers were selected using criteria that are not population-neutral, affecting absolute distances more than affinity ordering.
- The 1000 Genomes AFR group mixes continental Africans with African American and Afro-Caribbean samples that are admixed; its AFR centroid is not a pure African anchor.
- 958 samples in the release have no label in the population file. They enter the PCA, improving the axes, but remain outside the centroids.
- Coordinates are GRCh37.
- Genetic ancestry is not identity, culture, nationality, or family history.

## Reproducibility

The pinned result is stored in `docs/evidence/ANCESTRY_PANEL_VALIDATION.json`; `cases[].closest_matches_expected` is true for all 11 cases and supports the “eleven of eleven” statement. The current checkout **does not include** the former `fetch_aadr_genotypes.py`, `build_ancestry_panel.py`, or `validate_ancestry_panel.py` scripts. Historical commands that cited them were therefore removed. The artifact is an inspectable evidence snapshot, but regeneration is not reproducible from this repository and must not be presented as such.

The committed panel contains loadings, reference samples, centroids, orientation, and the validation summary that current consumers validate structurally before projection.
