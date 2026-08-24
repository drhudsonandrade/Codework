# GENOMA Reference Foundry

The human GRCh38/BWA-MEM2 indexing requirement is treated as a **one-time manufacturing step**, not a permanent requirement of every genomic analysis.

## Why

BWA-MEM2 indexing of the project FASTA is intentionally gated behind a high-memory host. The foundry workflow requires at least 96 GiB RAM and 100 GiB free disk, downloads exactly the nine declared project reference resources, emits a content-addressed candidate source lock, and stops. Nothing is called “approved” simply because a download succeeded.

A second `publish` dispatch requires the exact SHA-256 of the candidate lock file produced by the prior discovery run. Only after that independent approval does the workflow create the BWA-MEM2 indexes, run the reference validator, generate a complete bundle lock, and publish two separate immutable OCI artifacts:

- `genoma-ngs-runtime@sha256:…` — executable pinned NGS toolchain.
- `genoma-grch38-reference@sha256:…` — data-only GRCh38 resources and indexes.

Separating executable tools from reference data means the reference artifact can be replaced or mirrored without rebuilding the policy engine, and the toolchain can be upgraded without silently changing GRCh38.

## No recurring 96 GiB requirement

A normal private production runner pulls both images by digest. `scripts/materialize_reference_image.sh` extracts the data-only OCI image to a local read-only cache and verifies `GRCh38.bundle.sha256`. It **does not rebuild indexes**. The per-sample Runtime/Resource Gate mounts this verified cache read-only into the exact tools image.

The high-memory host is therefore required for first manufacture or whenever the reference/index definition intentionally changes, not for every downstream analysis.

## Private sample boundary

`.github/workflows/genoma-sample-runtime-gate.yml` resolves sample files only from `/srv/genoma/samples/<pseudonymous-id>` on a self-hosted production runner. Raw FASTQ/BAM/CRAM files are never uploaded as GitHub artifacts. Only a redacted gate manifest and its SHA-256 are uploaded.

For FASTQ, the workflow performs a pre-alignment integrity/reference/toolchain gate and deliberately leaves final calling readiness unavailable until alignment produces BAM/CRAM with explicit read-group/sample metadata. For BAM/CRAM, every required current-session gate must be `EXECUTADO` before `ready_for_real_calling=true`.

## Optional service boundary

Cloudflare, Temporal, Supabase, Vercel, microfn, MCP and ChatGPT may be placed around this workflow as ingress, orchestration, indexing or UI. None is required to materialize the reference, verify it, run the policy engine, or execute the per-sample gate.
