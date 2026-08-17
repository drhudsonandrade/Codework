# GENOMA GRCh38 compute strategy

## Objective

Eliminate the need for a permanently running >=96 GiB physical runner **without weakening** the GENOMA v3.3 Runtime/Resource Gate.

## Constraint verified from primary sources

BWA-MEM2 documents index creation as requiring `28N GB` of memory where `N` is reference size; for a human reference this is an ~80–90 GiB-class one-time operation. The current human index is about 10 GB on disk/in memory after construction. Standard GitHub-hosted Linux runners for private repositories provide 8 GB RAM and 14 GB SSD. Separate Actions jobs do not share one process address space, so multiple 8 GB runners cannot be combined into one 80–90 GB indexing process.

Primary references:
- `bwa-mem2/bwa-mem2` README and issue #118;
- GitHub Actions hosted-runner reference;
- GitHub Packages billing documentation;
- Broad/GATK public GRCh38 resource bundle documentation.

## Recommended architecture: no permanent high-memory machine

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
- high-memory is no longer required to be permanent;
- prebuilt BWA-MEM2 indices are accepted only via exact FASTA/index checksum lock and functional validation;
- the full-grch38 gate remains separate from partial SNP-array readiness;
- GitHub Actions cannot infer success merely because an object is named `hg38`.

**NÃO DISPONÍVEL until evidence exists:**
- an actual approved BWA-MEM2 GRCh38 index bundle stored by immutable digest;
- a real full-grch38 Runtime/Resource Gate on the target execution session.

**PROPOSTO:**
- benchmark/promote the Broad classic-BWA prebuilt-index lane if the goal is to eliminate even the one-time high-memory foundry.
