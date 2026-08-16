# GENOMA GRCh38 compute strategy

## Objective

Avoid a permanently running >=96 GiB physical runner without weakening the GENOMA v3.3 Runtime/Resource Gate.

## Why ordinary runners cannot simply be merged

BWA-MEM2 documents index creation as requiring `28N GB` of memory where `N` is reference size; for a human reference this is roughly an 80-90 GiB class operation. Its compressed human index is about 10 GB on disk/in memory after creation. GitHub standard private Linux runners are substantially smaller. Independent GitHub Actions jobs do not share one process address space, so adding many small runners does not create one 90 GiB heap.

Primary references:
- https://github.com/bwa-mem2/bwa-mem2/blob/master/README.md
- https://docs.github.com/en/actions/reference/runners/github-hosted-runners

## Supported strategies

### A. `self-hosted-build` - canonical high-memory build

Status until run: **NÃO DISPONÍVEL**.

1. Bring up any Linux x64 machine with the required RAM/disk only for the build window.
2. Install/register the GitHub runner labels `genoma-production,highmem` or execute the reviewed commands manually.
3. Validate the approved 9/9 GRCh38 source bundle before index creation.
4. Build the five BWA-MEM2 index files.
5. Create and independently review `BWA_MEM2.index.sha256.approved` binding the exact FASTA plus all five index files.
6. Execute `validate_grch38.sh`, `verify_prebuilt_bwa_mem2_bundle.py --run-functional`, and the full current-session Runtime/Resource Gate.
7. Publish only the content-addressed reference/index bundle to durable private storage; terminate the expensive VM.

This means high-memory compute can be **ephemeral**, not permanent.

### B. `prebuilt-verified` - no repeated high-memory build

Status until an actual bundle is supplied: **NÃO DISPONÍVEL**.

The system may consume an already-built BWA-MEM2 index only when:

- `Homo_sapiens_assembly38.fasta` and all five index files exist;
- `BWA_MEM2.index.sha256.approved` contains exactly those six basenames;
- all six SHA-256 values match;
- the regular GRCh38 source lock remains valid;
- `validate_grch38.sh` passes 9/9 resources/contigs/checksums;
- `validate_bwa_mem2_functional.sh` passes on the actual execution host;
- the Runtime/Resource Gate is rerun in the same session.

No index downloaded merely because it is labelled "hg38" is acceptable.

### C. Existing 24 GiB-class host + swap - emergency build path

Status: **PROPOSTO**, not the preferred route.

A machine with less physical RAM can sometimes complete a memory-heavy indexing job by adding a large swap file, provided virtual memory and free disk satisfy the gate. This is dramatically slower and less predictable than real RAM and must be treated as a one-time build experiment, not as a production performance assumption. The resulting index still must pass the same hashes and functional validation.

## Free/zero-permanent-cost conclusion

- A reliable **permanent** free 96 GiB GitHub runner is not part of the standard private-repository runner offering.
- A one-time free-trial/academic/borrowed high-memory VM can be used for the build if available, then destroyed; GENOMA does not depend on that provider afterwards.
- The most provider-independent architecture is therefore **one-time high-memory generation -> content-addressed private index bundle -> repeated prebuilt verification on future hosts**.
- If no high-memory machine or independently trusted matching prebuilt index is available, `full-grch38` remains `NÃO DISPONÍVEL`; the SNP-array lane remains independent and can still run.
