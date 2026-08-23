# Recovery and activation runbook

## Status boundary

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE`

This repository is the reproducible control plane for the genomics runtime. It contains source,
version pins, workflow definitions, tests, manifests and operating instructions. It intentionally
contains no personal DNA, no GRCh38 payload, no approved external lock and no credentials.

Do not record `POST-DEPLOYMENT PASS` until the target deployment is online and the section 260 live
suite proves `passed == 15`, `total == 15`, `critical_failures == 0` and
`post_deployment_status == "PASS"` on the exact merged `main` SHA.

## Durable sources of truth

| Layer | Source of truth | Retention rule | Recovery role |
|---|---|---|---|
| Source and configuration | Private GitHub repository, protected `main` | No fixed workflow-artifact expiry; retained while the repository/account is retained | Rebuild every component from reviewed source |
| Executable environment | `ghcr.io/<github-owner>/codework-genome` pinned by digest | Retained under the repository owner's package policy | Pull the exact tested container without resolving packages again |
| Build/test evidence | Recovery bundle in the project's persistent document store | Retained until the owner deletes it or an account/workspace policy removes it | Preserve the synthetic canary ZIP, checksums and release evidence beyond Actions retention |
| GitHub Actions artifacts | `synthetic-canary-*` and `ghcr-image-reference-*` | Requested retention: 90 days, capped by repository/org policy | Convenient CI evidence only; never the sole backup |
| Future genomic data | Encrypted VM block/object storage plus an independent encrypted backup | Provider lifecycle policy controlled by the owner | Store FASTQ/BAM/CRAM/VCF and GRCh38; never commit or upload them through ChatGPT |
| Work scratch filesystem | Temporary ChatGPT Work runtime | May be reclaimed after inactivity | Build staging only; never a durable source of truth |

No hosted service can honestly be promised to remain available forever. Durability comes from
keeping at least two independent copies and retaining the manifests needed to verify them.

## What is already reproducible

- Container toolchain pinned in `environment.yml` and verified by `scripts/check_versions.sh`.
- npm dependency graph pinned in `mcp/package-lock.json`.
- Fallow Action pinned to `fallow-rs/fallow@45fd28766199acb1f939f6862274a37aad12770b`; Fallow CLI pinned to `3.16.0`.
- GRCh38 acquisition targets declared in `manifests/GRCh38.sources.tsv`.
- External ruleset identity pinned in `manifests/RULESET_V3.4.sha256` for canonical `VIGENTE / v3.4 / 17/08/2026`.
- Synthetic FASTQ, BAM and dual-caller VCF generation is deterministic.
- Successful protected-main workflows can build SHA-tagged GHCR images and record immutable digests.
- A successful canary includes an explicit Conda package lock generated from the built image.

## Clean recovery from GitHub and GHCR

Use a trusted Linux host with Docker. Replace the placeholders with the current private repository owner and the digest recorded by the successful main-branch workflow or the recovery manifest.

```bash
export GITHUB_REPOSITORY_OWNER='<github-owner>'
git clone "https://github.com/${GITHUB_REPOSITORY_OWNER}/Codework.git"
cd Codework
git switch main
python3 scripts/validate_repo.py
python3 -m unittest discover -s tests -v
npm ci --prefix mcp --ignore-scripts
npm test --prefix mcp

docker pull "ghcr.io/${GITHUB_REPOSITORY_OWNER}/codework-genome@sha256:REPLACE_WITH_VERIFIED_DIGEST"
docker run --rm \
  "ghcr.io/${GITHUB_REPOSITORY_OWNER}/codework-genome@sha256:REPLACE_WITH_VERIFIED_DIGEST" \
  /opt/codework/scripts/check_versions.sh
```

If GHCR is unavailable, rebuild from the pinned source and immediately capture the resulting image
digest. A rebuild is a new artifact and must pass the same gates; it must not inherit the prior
digest or approval.

```bash
docker build --tag codework-genome:recovered .
docker run --rm codework-genome:recovered /opt/codework/scripts/check_versions.sh
```

## Non-sensitive recovery canary

The container's micromamba entrypoint must remain active. Do not override it in these commands.

```bash
mkdir -p recovery-canary
chmod 0777 recovery-canary
docker run --rm \
  --volume "$PWD/recovery-canary:/results" \
  codework-genome:recovered \
  /opt/codework/scripts/run_canary.sh /results/canary
jq -e '.status == "PASS"' recovery-canary/canary/report.json
```

Required canary result:

- runtime gate 7/7;
- valid sorted/indexed BAM;
- bcftools: TP=3, FP=0, FN=0, genotype concordance 3/3;
- GATK HaplotypeCaller: TP=3, FP=0, FN=0, genotype concordance 3/3;
- no personal or sensitive data.

## Private MCP recovery

The MCP server exposes only `runtime_status`, `reference_status`, `run_synthetic_canary` and
`audit_record`. It does not expose arbitrary shell execution, uploads, deletes or raw genomic
contents.

After the target VM exists:

1. Start `deploy/docker-compose.yml` with a digest-pinned `GENOME_IMAGE`.
2. Verify `GET http://127.0.0.1:3000/healthz` and inspect `/mcp` locally.
3. Create the OpenAI Secure MCP Tunnel and associate the correct Platform organization and ChatGPT
   workspace.
4. Run `tunnel-client doctor --profile codework-genome --explain`.
5. In ChatGPT developer mode, add a Tunnel connection and review exactly four tools.
6. Run a canary with a bounded request id and record tool, redacted arguments, result and sanitized
   error in `/srv/genome/audit`.

ChatGPT plugins are installed in ChatGPT, not in GitHub. Fallow is also represented in GitHub by the
pinned Fallow Action. Cloudflare, Supabase, Temporal, Flower, Vercel and research connectors are not
dependencies of the genomic data plane and therefore are not copied into the repository or container.

## Future GRCh38 and WGS activation

These steps are deliberately blocked until the high-memory target host is provisioned:

1. Mount encrypted persistent storage at `/srv/genome` with at least 1 TiB free for one WGS run.
2. Run `scripts/fetch_grch38.sh`; require 9/9 artifacts.
3. Have a second trusted reviewer independently verify provenance and checksums, then install
   `GRCh38.lock.sha256.approved`. The pipeline cannot self-approve it.
4. Run `scripts/build_bwa_mem2_index.sh` with the 96 GiB RAM gate and persistent free disk.
5. Run `scripts/validate_grch38.sh`; require 9/9, approved checksums, compatible contigs, five BWA
   index files, a 101-base `samtools faidx` result and a functional `bcftools query` result.
6. Transfer the WGS directly to encrypted block/object storage with resumable transfer. Do not send a
   60+ GiB file through ChatGPT.
7. Record the WGS object key, size and SHA-256 in restricted job metadata; keep a second encrypted
   copy under a separate lifecycle policy.
8. Run the validated germline WGS workflow and a Genome in a Bottle benchmark before interpreting
   personal results. The three-SNP canary is an executability test, not clinical validation.

## Evidence manifest requirements

Every durable recovery bundle must contain:

- final source archive and source SHA-256;
- GitHub repository, PR, main commit and successful workflow URLs;
- GHCR immutable reference and digest;
- synthetic canary artifact and SHA-256;
- tool versions and canary scores;
- ruleset SHA-256;
- explicit statement of the current deployment status;
- a list of pending VM/WGS/external-review gates.

Validate the bundle after copying it:

```bash
sha256sum --check RECOVERY_BUNDLE.sha256
```

The checksum detects corruption; it does not itself establish external provenance or clinical
validity.
