# GENOMA — high-memory runner and full-grch38

## Contract

`full-grch38` runs only on a GitHub Actions runner with these labels:

`self-hosted, linux, x64, genoma-production, highmem`

The workflow requires at least ~96 GiB of RAM, persistent storage for the bundle, Docker, and an external `GRCh38.lock.sha256.approved` under `REF_ROOT`.

## Provisioning

1. Provision or start a Linux x86_64 host with >=96 GiB RAM and enough persistent storage.
2. Register a GitHub Actions Runner for the repository/organization and apply exactly `genoma-production` and `highmem` in addition to the default labels.
3. Create `REF_ROOT` (default `/srv/genoma/refs/GRCh38`).
4. Obtain the 9 artifacts defined by `manifests/GRCh38.sources.tsv` using `scripts/fetch_grch38.sh` or an equivalent approved copy.
5. Generate the pending lock on the host. Independently review provenance and every SHA-256. **Only after that review**, install the lock as `GRCh38.lock.sha256.approved`. The example file is not approval.
6. Run the `GENOMA NGS Runtime Resource Gate` workflow with `mode=full-grch38`.

## What the workflow does

- resolves a current compatible candidate without changing the pinned environment;
- runs the direct functional canary, including the caller and editorial runtime;
- runs the same canary through Nextflow;
- promotes the session only when **both** canaries are PASS and the inventory is complete;
- updates and validates freshness for critical official sources;
- validates 9/9 resources, checksums, FASTA/FAI/dict, and contigs;
- builds BWA-MEM2 indexes only when they are missing;
- revalidates the five index files and executes the BWA-MEM2 functional canary;
- reruns the Runtime/Resource Gate in the current session.

The existence of this runbook does not mean that the runner is online or that `full-grch38` has been executed. Status may change only after workflow execution evidence exists.
