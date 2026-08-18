# Pre-deployment validation — 2026-08-15 UTC

> **HISTÓRICO — SUPERSEDED.** Evidence gathered against ruleset **v3.3 (14/08/2026)**. The repository
> is now governed by **v3.4 (17/08/2026)** and these checks were **not** re-executed under v3.4.
> Preserved unaltered as provenance; no PASS below is a current claim.

## Result

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE`

This report combines local static/MCP evidence and GitHub-hosted container execution. It is not
target-host, GRCh38, WGS, GIAB or clinical validation.

## GitHub and source control

| Gate | Result | Evidence |
|---|---|---|
| GitHub App access | PASS | Private `Codework` repository; authenticated integration has admin, push and pull access. |
| Pull request | PASS | Draft PR #2 from `codex/genome-runtime-mcp` to `main`; head `959b42c2d652899d8e6685773288551de3db8d2b` before the final recovery update. |
| Fallow workflow | PASS | Run `31857676073`. |
| Container/runtime workflow | PASS | Run `31857676091`. |
| Genomic payload exclusion | PASS | No personal FASTQ/BAM/CRAM/VCF, GRCh38 payload, credential or externally approved lock is committed. |

## Repository and code gates

| Gate | Result | Evidence |
|---|---|---|
| Locked npm install | PASS | Dependencies installed from `mcp/package-lock.json`. |
| TypeScript strict compile | PASS | `tsc -p mcp/tsconfig.json`. |
| MCP tests | PASS | 12/12. |
| Python tests | PASS | 6/6, including the micromamba-entrypoint regression guard. |
| Shell syntax | PASS | Every `scripts/*.sh` passed `bash -n`. |
| Repository contract | PASS | Required paths, payload exclusions, status label and lock rules. |
| GRCh38 source manifest | PASS | Exactly 9/9 declared artifacts; the payload remains unavailable until the future VM. |
| Ruleset identity | PASS | SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`; `VIGENTE`; v3.3; 14/08/2026. |
| Fallow 3.16.0 quality | PASS | 0 issues and no critical/high/moderate complexity finding. |
| Fallow security | REVIEWED | 12 bounded path-construction candidates, 0 high; candidates are not asserted vulnerabilities. |

## GitHub-hosted runtime and calling evidence

The pinned container ran the real commands in GitHub Actions:

| Component | Result |
|---|---|
| Java | PASS — 17.0.18 |
| samtools | PASS — 1.24 |
| bcftools | PASS — 1.24 |
| bwa-mem2 | PASS — executable 2.2.1, package 2.3 |
| GATK | PASS — 4.6.2.0 |
| Nextflow | PASS — 26.04.6 |
| Snakemake | PASS — 7.32.4 |
| bcftools synthetic calling | PASS — TP=3, FP=0, FN=0, F1=1.0, genotypes 3/3 |
| GATK HaplotypeCaller synthetic calling | PASS — TP=3, FP=0, FN=0, F1=1.0, genotypes 3/3 |

Artifact `synthetic-canary-a4a341fdc115deb693e015687e32fc607a639cf8` had Actions digest
`sha256:ec7fc74089ae4373540f3556f069429a35d459870a409cc07c979028b48064cc` and an original
expiration of 2026-08-29. The artifact is evidence only. The release handoff copies it into a durable
recovery bundle so Actions retention is not the sole copy.

## Local MCP transport evidence

- `GET /healthz`: PASS, HTTP 200.
- Streamable HTTP initialization: PASS, protocol `2025-06-18`.
- `tools/list`: PASS; exactly `runtime_status`, `reference_status`, `run_synthetic_canary` and
  `audit_record`.
- `GET /mcp`: PASS, HTTP 405 as designed.
- Canary arguments: `{ "requestId": "canary-nosensitive-20260815a" }`.
- Audit behavior: bounded arguments, PASS/FAIL, duration and sanitized error; file mode `0600`.
- Sensitive payload: none.

The local scratch-host execution was expected to fail its runtime tool gate because the tools live in
the container. The subsequent GitHub container run passed all seven runtime checks and both callers.

## Blocking gates before post-deployment

1. Provision and harden the future target VM and persistent encrypted storage.
2. Pull the main-branch GHCR image by verified digest.
3. Install the nine GRCh38 artifacts, obtain independent external lock approval, build the five
   bwa-mem2 index files, and pass contig/faidx/query validation.
4. Connect the private MCP through Secure MCP Tunnel and execute a live non-sensitive canary.
5. Provide WGS input and complete the production germline workflow plus a GIAB benchmark.
6. Activate the canonical v3.3 ruleset/BOOTSTRAP CURTO in the ChatGPT Project.
7. Execute section 260 live and require 15/15 with no critical failure.

Until all seven gates pass, never record `POST-DEPLOYMENT PASS`.
