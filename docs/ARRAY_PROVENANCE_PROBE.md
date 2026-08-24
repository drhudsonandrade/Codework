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

### The verdict is knowledge, not permission

`reverse` is a determinate answer, and for a while that was enough to make it dangerous.
`attestation_from_probe` used to render *any* VERIFICADO verdict as a full
`VERIFICADO/SATISFIED` attestation — including one whose justification read
"Veredito: reverse". Handed to `run_snp_array.py --strand forward` (the only strand the CLI
offers) it validated on every count: right status, right decision, correctly bound to the
input's SHA-256. `BUILD_STRAND_GATE` passed and the run published
`operational_status: VERIFICADO` over a file whose every allele is the complement of what
the registries mean — rs6025 `CT`, a Factor V Leiden carrier, reads `GA` and classifies as
NÃO DETECTADO. The probe's own honest finding was the credential that certified its opposite.

Three independent checks now close that, and each fails on its own:

1. `attestation_from_probe` emits a strand attestation only for `forward`. A `reverse`
   verdict returns `None`, exactly as an inconclusive one does — the file's orientation is
   known, and what is known is that it cannot pass.
2. Every attestation carries `asserted_value`, and `qc._verified_provenance` refuses one
   that names a different value than the one being declared. An attestation that names *no*
   value verifies nothing: the absent field is "no way to disagree", not "no disagreement".
3. `inspect_array` counts the same plus/minus vote over the markers the file itself carries
   and blocks the gate when the file contradicts the declared strand. Only a contradiction
   blocks — agreement is not treated as proof, and a file with too few informative markers
   is neither confirmed nor refused. This is what stops a *hand-written* attestation, which
   nothing else checks, from certifying a flipped file.

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
- It does not flip the file. A determinate `reverse` verdict makes complementing every call
  a well-defined operation, and the probe still refuses to do it: the output would be a
  genotype set nobody can re-derive from the delivered file, and "repaired" and "intact"
  would read the same downstream. The file is refused and re-exported instead.
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
