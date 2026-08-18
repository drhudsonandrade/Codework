# GENOMA GRCh38 compute strategy

## Objective

Eliminate the need for a permanently running >=96 GiB physical runner **without weakening** the GENOMA v3.4 Runtime/Resource Gate.

## Constraint verified from primary sources

BWA-MEM2 documents index creation as requiring `28N GB` of memory where `N` is reference size; for a human reference this is an ~80–90 GiB-class one-time operation. The current human index is about 10 GB on disk/in memory after construction. Standard GitHub-hosted Linux runners for private repositories provide 8 GB RAM and 14 GB SSD. Separate Actions jobs do not share one process address space, so multiple 8 GB runners cannot be combined into one 80–90 GB indexing process.

Primary references:
- `bwa-mem2/bwa-mem2` README and issue #118;
- GitHub Actions hosted-runner reference;
- GitHub Packages billing documentation;
- Broad/GATK public GRCh38 resource bundle documentation.

## Path 0 — do not align at all (the cheapest correct answer)

**Status: EXECUTADO em código.** This is the first thing to check, because for a
lab-delivered WGS it removes the constraint entirely rather than working around it.

The ~80 GiB build and the large resident index exist for **one** step: aligning FASTQ.
Ruleset section 3 lists the primary WGS source as `BAM + BAI ou CRAM + CRAI` alongside
FASTQ — that is, the laboratory usually delivers data **already aligned**.

`scripts/wgs_align_or_stage.sh` has three branches, and only one of them touches the
aligner:

| `input_type` | what runs | aligner index |
|---|---|---|
| `FASTQ` | `bwa-mem2 mem` + `samtools sort` | **required** |
| `BAM` | `samtools sort` | never read |
| `CRAM` | `samtools view -T ref` + `samtools sort` | never read |

The Runtime/Resource Gate used to demand `aligner_indexes` unconditionally, so a staged
run was blocked on a resource nothing opened. The gate now binds that requirement to the
real input mode:

```bash
# lab-delivered BAM/CRAM: no aligner index, no high-memory event
python3 scripts/runtime_resource_gate.py --alignment-mode stage --ref-root /refs --output gate.json
```

The exemption is narrow and self-checking, so it cannot be used to dodge the index:

- supplying `--fastq-r1/--fastq-r2` forces `align` regardless of the declared mode;
- the verifier rejects an attestation that declares `stage` while carrying FASTQ integrity
  evidence, or that declares `stage` while still asserting the index is required;
- an unknown mode is rejected outright.

What a staged run still requires, unchanged: FASTA, FAI, dictionary, contig/build
agreement, known-sites and annotation checksums, sample/read-group identity, BAM/CRAM
integrity and caller–reference compatibility. **Nothing about QC or evidence is relaxed.**

Residual limitation: staging trusts the laboratory's alignment. If you need an independent
alignment — a different aligner, a different reference, or a truth-set comparison under
ruleset section 55 — you are back to a real alignment and to Paths A–D below.

> The exact download sizes of the Broad bundle could not be measured from this session:
> the agent proxy returns 403 for `storage.googleapis.com`. The claim above is structural
> (which code path reads which resource), verified in the repository, and does not depend
> on those numbers.

## Recommended architecture when alignment is genuinely required

### Path A — prebuilt BWA-MEM2, content-addressed and verified

**Status until an actual approved bundle is supplied: NÃO DISPONÍVEL.**

This is the preferred zero-permanent-machine design already enforced by `scripts/verify_prebuilt_bwa_mem2_bundle.py`.

1. Build the BWA-MEM2 index once on any temporary >=96 GiB machine **or** obtain an independently trusted index that is demonstrably for the exact approved FASTA.
2. Bind the FASTA and all five BWA-MEM2 index files in `BWA_MEM2.index.sha256.approved`.
3. Run checksum, contig and functional alignment validation.
4. Publish the verified reference/index bundle as a content-addressed OCI artifact/image.
5. Destroy the high-memory builder.
6. Every future execution pulls by immutable digest and reruns the Runtime/Resource Gate in that session.

GitHub currently documents Container Registry image storage/bandwidth as free; therefore GHCR can serve as the durable reference-distribution layer without a permanently rented server. This billing condition is external and must be rechecked before relying on it long term.

### Path B — Broad prebuilt classic-BWA GRCh38 indices, no high-memory build at all

**Status: PROPOSTO; requires benchmark before replacing the current BWA-MEM2 production aligner.**

Broad/GATK publishes the classic-BWA GRCh38 index family for the same `Homo_sapiens_assembly38.fasta` (`.64.alt`, `.64.amb`, `.64.ann`, `.64.bwt`, `.64.pac`, `.64.sa`). A future validated lane can therefore download those official prebuilt files rather than run any indexing step.

Advantages:
- eliminates the >=80 GiB BWA-MEM2 index-construction event;
- avoids a permanent self-hosted runner;
- source artifacts are public scientific references and can be checksum-locked.

Trade-off:
- this changes the production aligner from BWA-MEM2 to classic BWA-MEM; it is **not** silently interchangeable. GENOMA must first benchmark mapping/QC and reproduce the canary/variant-calling acceptance criteria before promoting this lane from PROPOSTO to EXECUTADO/VERIFICADO.

### Path C — ephemeral high-memory foundry

**Status until run: NÃO DISPONÍVEL.**

If BWA-MEM2 must remain the aligner, provision high memory only for the indexing window, build and verify the content-addressed bundle, publish it, and terminate the machine. This converts the recurring infrastructure requirement into a one-time foundry event. A cloud free trial/academic credit/borrowed machine may cover that event, but availability is provider/account-specific and is never assumed by the code.

### Path D — sub-96 GiB host with large swap

**Status: PROPOSTO, emergency only.**

Swap may allow an under-RAM machine to complete indexing, but it is dramatically slower and less predictable. It cannot be represented as equivalent performance or as a VERIFIED route without a real successful run and the same downstream checks.

## What is and is not solved

**Solved architecturally / EXECUTADO in code:**
- a lab-delivered BAM/CRAM needs no aligner index at all (Path 0), so the high-memory event
  disappears entirely for that lane rather than being relocated;
- high-memory is no longer required to be permanent;
- prebuilt BWA-MEM2 indices are accepted only via exact FASTA/index checksum lock and functional validation;
- the full-grch38 gate remains separate from partial SNP-array readiness;
- GitHub Actions cannot infer success merely because an object is named `hg38`.

**NÃO DISPONÍVEL until evidence exists:**
- an actual approved BWA-MEM2 GRCh38 index bundle stored by immutable digest;
- a real full-grch38 Runtime/Resource Gate on the target execution session.

**PROPOSTO:**
- benchmark/promote the Broad classic-BWA prebuilt-index lane if the goal is to eliminate even the one-time high-memory foundry.
