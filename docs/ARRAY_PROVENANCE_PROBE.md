# Deriving array provenance from the array itself

## The problem real data exposed

A real harmonized consumer-array export (Genera + MyHeritage, 719,762 rows) carries **no**
`##reference=` and no `##strand=` header. `BUILD_STRAND_GATE` therefore blocks it, and
nothing downstream can run — the completeness matrix, the pharmacogenomic passport and both
reports all stop at `NÃO DISPONÍVEL`.

That left two options, and both were bad:

- leave the data permanently unusable, or
- hand-write an attestation asserting a build and strand nobody had checked.

The second is exactly the unsupported claim this project exists to prevent, and it would
have been invisible: the attestation format is structurally validated, not fact-checked.

## Both facts are derivable, and the derivation is falsifiable

`array_pipeline/provenance_probe.py` reads them out of the file's own content.

### Build — coordinate concordance

Marker coordinates differ between GRCh37 and GRCh38. The probe compares the observed
position of each marker against both assemblies and counts. A build is declared only when
one assembly matches at least `MIN_BUILD_MARKERS` (3) times **and the other matches zero**.
A file half-lifted between assemblies is inconclusive, not "majority wins".

### Strand — allele-set discrimination

For a SNP whose two plus-strand alleles are known, a reverse-strand export reports their
complements. `rs429358` has plus alleles T/C, so a flipped file shows A/G. Observing only
letters from the plus set — and none from the complement set — is positive evidence.

**Palindromic SNPs are excluded automatically.** A strand flip maps A↔T and C↔G, so an A/T
or C/G site reads identically on both strands and carries no orientation information. The
marker table must flag them, and `load_markers` *refuses a table* that leaves a palindromic
pair unflagged — unflagged, it would cast a meaningless vote.

A reverse-strand file is reported as `reverse`, never as `forward`. That is the
consequential failure: treating a flipped file as forward inverts every allele downstream.

## Result on the real file

```
BUILD : VERIFICADO -> GRCh37   (GRCh37=11  GRCh38=0,  threshold 3)
FITA  : VERIFICADO -> forward  (plus=9     minus=0,   threshold 3)
```

with `rs738409` (C/G) and `rs17580` (A/T) correctly recorded as non-informative.

## The marker table is curated and needs verification

`config/array_provenance_markers.json` carries `verification_status: "PROPOSTO"` and a
`source` field that says so plainly. The table was curated by hand; **an error in it would
produce an incorrect provenance attestation**, which is the one place in this design where a
mistake propagates silently into every downstream report.

The attestation the probe emits records that status in its own trace
(`marker_table_verification_status`), so a reader can see the derivation rests on an
unverified table. Verifying the eleven entries against dbSNP is a small, bounded task and
should be done before any clinical use.

## What the probe deliberately does not do

- It does not guess. Weak or contradictory evidence yields `NÃO DISPONÍVEL`, and
  `attestation_from_probe` returns `None` rather than letting silence become an attestation.
- It does not lower the gate. The attestation goes through the same
  `_verified_provenance` check as any other, is bound to the input SHA-256, and fails
  against a different file.
- It does not establish that the vendor's own pipeline was correct — only what convention
  this file uses.

## Running it

```bash
python3 - <<'PY'
from pathlib import Path
from array_pipeline.provenance_probe import probe, attestation_from_probe
from array_pipeline.qc import inspect_array

r = probe(Path("array.csv.gz"), Path("config/array_provenance_markers.json"))
qc = inspect_array(
    Path("array.csv.gz"), case_id="CASE-001",
    build=r["build"]["value"], strand=r["strand"]["value"],
    build_evidence=attestation_from_probe(r, "reference_build"),
    strand_evidence=attestation_from_probe(r, "strand"),
)
PY
```
