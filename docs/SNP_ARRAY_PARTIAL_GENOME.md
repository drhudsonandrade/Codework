# GENOMA v3.4 — Scientific Data Plane for partial SNP arrays

## Objective

This path exists for partial genotyping data (for example, commercial chips) and is deliberately separate from the WGS/FASTQ/BAM/CRAM pipeline. It performs QC, provenance, callability, and cross-source concordance without pretending to provide whole-genome coverage.

## Gate before interpretation

```bash
python3 scripts/run_snp_array.py \
  --input /caminho/privado/arquivo.csv.gz \
  --case-id CASE-PSEUDONIMIZADO \
  --build GRCh37 \
  --strand forward \
  --build-evidence 'fonte rastreável' \
  --strand-evidence 'fonte rastreável' \
  --output-dir /caminho/privado/resultados
```

Execution fails closed when build/strand lack explicit evidence, when the harmonized structure contains duplicate rsIDs, when called genotypes are invalid, or when configured callability/concordance gates fail.

Raw vendor files may contain more than one probe/record for the same rsID. Those records are not silently collapsed: they remain in provenance and must be resolved during harmonization. After harmonization, a duplicate rsID is blocking.

## Output

- `array-qc.json`: hashes, metadata, metrics, gates, limitations, and baseline observations.
- `baseline-marker-observations.tsv`: observations for the markers defined in the ruleset; **not a clinical report**.
- `SHA256SUMS`: hashes of output artifacts.

## Honest scope

`LIMITED_INTERPRETATION_GATE=PASS` authorizes interpretation only for loci that were actually interrogated and approved by QC. It does not authorize:

- excluding disease because a variant is absent from the chip;
- inferring CNV/SV, expansions, mosaicism, or deep intronic variants;
- complex diplotypes in CYP2D6/HLA and other loci that require CNV/phasing/specialized methods;
- using an SNP array as a substitute for WGS or clinical/orthogonal confirmation.

Markers present on both platforms and concordant receive stronger strand-orientation assurance. MyHeritage-only markers may use the forward (+) declaration from the source file when present. Genera-only markers remain `INFERIDO` for orientation until confirmation by reference/allele/build or other traceable evidence.

## Privacy

CI uses synthetic fixtures exclusively. Personal DNA is not sent to GitHub Actions, Cloudflare, Supabase, microfn, or any optional service. `.gitignore` patterns block common personal genetic-data filenames; the workflow also rejects fixtures with real-data filenames.

## Relationship to WGS

The WGS Runtime/Resource Gate remains independent and must be rerun in the real calling session. `full-grch38` and the high-memory runner are not prerequisites for partial SNP-array QC, but they remain mandatory before the corresponding WGS path.
