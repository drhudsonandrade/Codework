# Magalu + Private MCP Genomics Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a reviewable GitHub pull request that prepares a Magalu VM to run a private, auditable germline genomics workflow through a narrowly scoped MCP server.

**Architecture:** GitHub stores only source code, version locks, manifests, CI and operational documentation. The Magalu VM stores tools, GRCh38 resources, BWA indexes, WGS inputs and outputs on persistent block/object storage. A tool-only TypeScript MCP server exposes fixed, non-arbitrary status, validation and canary operations; OpenAI Secure MCP Tunnel connects outbound from the VM, so the MCP endpoint and genomic data are not publicly exposed.

**Tech Stack:** Docker, micromamba/conda-lock-style environment specification, Nextflow 26.04.6, samtools 1.24, bcftools 1.24, bwa-mem2 package 2.3/executable 2.2.1, GATK 4.6.2.0, Snakemake 7.32.4, TypeScript, MCP SDK, GitHub Actions and Fallow v3.16.0.

## Global Constraints

- Never commit DNA, FASTQ/BAM/CRAM/VCF outputs, GRCh38 binaries, credentials, API keys, tunnel profiles or logs containing genomic data.
- Keep `PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE` until the live section 260 suite is 15/15 with no critical failure.
- Do not claim a tool, reference, index, canary, deployment or MCP connection was executed unless a current command produced evidence.
- The external approval of `GRCh38.lock.sha256` is a human provenance gate; code may generate and verify a lock but may not self-approve it.
- Full `bwa-mem2 index` requires the host resource gate (96 GiB RAM or a separately validated lower-memory strategy) and persistent free disk.
- GitHub Actions runs only the synthetic canary; it must never download a full WGS or build the full human BWA index.

---

### Task 1: Repository safety and CI gates

**Files:**
- Create: `.gitignore`
- Create: `.github/workflows/fallow.yml`
- Create: `.github/workflows/scaffold-validation.yml`

**Interfaces:**
- Consumes: GitHub pull-request and push events.
- Produces: Fallow changed-code audit and deterministic static validation logs.

- [ ] **Step 1: Add deny-by-default genomic-data ignores**

Add patterns for `*.fastq*`, `*.bam`, `*.cram`, `*.vcf*`, references, indexes, `.env*`, tunnel profiles, work directories and results while keeping manifest and example lock files trackable.

- [ ] **Step 2: Add Fallow pull-request gate**

Pin `uses: fallow-rs/fallow@v3.16.0`, use read-only repository permissions, and run on pull requests. Do not enable telemetry.

- [ ] **Step 3: Add scaffold validation workflow**

Run JSON parsing, `bash -n`, TypeScript build, container build and the synthetic canary. Publish only small non-sensitive test artifacts.

- [ ] **Step 4: Verify workflow syntax locally**

Run `python3 scripts/validate_repo.py`. Expected: every required file exists, JSON/YAML parses, sensitive fixture patterns are absent, and the status label remains pending.

### Task 2: Reproducible NGS tool environment

**Files:**
- Create: `environment.yml`
- Create: `Dockerfile`
- Create: `scripts/check_versions.sh`
- Create: `scripts/validate_repo.py`

**Interfaces:**
- Consumes: exact version requirements from the vigente v3.3 ruleset.
- Produces: a versioned container image and a machine-readable version report.

- [ ] **Step 1: Specify exact tool versions**

Use isolated Bioconda/Conda Forge packages for Java 17, samtools 1.24, bcftools 1.24, bwa-mem2 2.3, GATK4 4.6.2.0, Nextflow 26.04.6 and Snakemake 7.32.4.

- [ ] **Step 2: Build a non-root container**

Install with micromamba, copy only repository scripts and workflow files, create `/refs`, `/data`, `/work` and `/results`, and use a non-root runtime user.

- [ ] **Step 3: Record versions without overclaiming**

`scripts/check_versions.sh` must fail on any missing executable or version mismatch and emit TSV/JSON-compatible lines for audit capture.

- [ ] **Step 4: Validate syntax**

Run `bash -n scripts/*.sh` and `python3 -m py_compile scripts/validate_repo.py`.

### Task 3: Versioned GRCh38 resource lifecycle

**Files:**
- Create: `manifests/GRCh38.sources.tsv`
- Create: `manifests/GRCh38.lock.sha256.example`
- Create: `scripts/fetch_grch38.sh`
- Create: `scripts/build_bwa_mem2_index.sh`
- Create: `scripts/validate_grch38.sh`

**Interfaces:**
- Consumes: authoritative HTTPS source URLs and persistent `REF_ROOT`.
- Produces: nine required artifacts, locally generated checksum lock, BWA indexes and a validation report.

- [ ] **Step 1: Declare nine sources and destinations**

List FASTA, FAI, dictionary, GENCODE v50 GTF, dbSNP 138 VCF/TBI, Mills + 1000G VCF/TBI and hg38 blacklist. Include provider and build notes.

- [ ] **Step 2: Implement resumable acquisition**

Require explicit `REF_ROOT`, verify HTTPS URLs, use temporary partial files plus atomic rename, and refuse to overwrite a non-matching existing file.

- [ ] **Step 3: Generate but do not approve the lock**

Write `GRCh38.lock.sha256.pending`; document that a reviewer compares provenance and renames/countersigns it outside the pipeline. Never generate an “approved” marker automatically.

- [ ] **Step 4: Gate full BWA indexing by resources**

Check available RAM and disk before `bwa-mem2 index`; refuse below configured thresholds. Verify the expected index files after exit 0.

- [ ] **Step 5: Validate contigs and functional access**

Use `samtools faidx` for a 101-base query; use `bcftools query` against dbSNP; compare VCF/GTF contigs with the FASTA dictionary and fail on incompatible primary contigs.

### Task 4: Deterministic synthetic calling canary

**Files:**
- Create: `scripts/generate_canary.py`
- Create: `scripts/run_canary.sh`
- Create: `main.nf`
- Create: `nextflow.config`

**Interfaces:**
- Consumes: no personal data; uses a generated synthetic reference and reads.
- Produces: sorted/indexed BAM, bcftools VCF, GATK VCF, truth comparison and execution manifest.

- [ ] **Step 1: Generate deterministic synthetic inputs**

Use a fixed seed and fixed gzip metadata. Emit a small FASTA, paired FASTQ, truth VCF and SHA-256 manifest.

- [ ] **Step 2: Execute both callers**

Run `bwa-mem2 mem`, `samtools sort/index/quickcheck`, `bcftools mpileup/call` and GATK HaplotypeCaller on the synthetic interval.

- [ ] **Step 3: Compare against truth**

Normalize variants and compute TP/FP/FN plus genotype concordance. A canary pass requires exit 0 and exact expected variants; it is not clinical validation.

- [ ] **Step 4: Wrap the canary in Nextflow**

Expose one `CANARY` process, pin resource limits suitable for GitHub Actions, and publish only the small report/manifests.

### Task 5: Private tool-only MCP server

**Files:**
- Create: `mcp/package.json`
- Create: `mcp/tsconfig.json`
- Create: `mcp/server.ts`
- Create: `mcp/tests/server.test.ts`
- Create: `mcp/README.md`

**Interfaces:**
- Consumes: fixed filesystem roots and fixed scripts; never arbitrary shell commands or raw genomic payloads.
- Produces: `/mcp` with `runtime_status`, `reference_status`, `run_synthetic_canary`, and `job_status` tools plus redacted audit records.

- [ ] **Step 1: Define narrow tools and annotations**

Mark status tools read-only. Mark canary submission non-destructive but state-changing and idempotent per caller-supplied request id. No delete, upload or free-form command tool.

- [ ] **Step 2: Validate all inputs server-side**

Use Zod enums and bounded identifiers. Resolve paths beneath configured roots and reject traversal. Never return secret values, full environment dumps or genomic contents.

- [ ] **Step 3: Add audit logging**

Record timestamp, tool name, redacted arguments, result status, duration and sanitized error. Use append-only JSONL with restrictive permissions.

- [ ] **Step 4: Add compile and contract tests**

Verify tool names, annotations, invalid input rejection and redaction. Confirm `/mcp` is present; host-loop testing remains pending until the Magalu VM and tunnel exist.

### Task 6: Magalu deployment and Secure MCP Tunnel runbook

**Files:**
- Create: `deploy/docker-compose.yml`
- Create: `deploy/genome-mcp.service`
- Create: `deploy/tunnel-client.service.example`
- Create: `docs/MAGALU_PRIVATE_MCP_SETUP.md`

**Interfaces:**
- Consumes: a user-provisioned Magalu VM, persistent volume/object storage and secrets entered on the VM.
- Produces: restart-safe services, outbound-only tunnel connectivity and operational validation steps.

- [ ] **Step 1: Define persistent mounts**

Mount `/srv/genome/refs`, `/srv/genome/data`, `/srv/genome/work`, `/srv/genome/results` and `/srv/genome/audit`. Keep inputs/results outside the container layer.

- [ ] **Step 2: Define resource and restart policy**

Run the MCP server on loopback only, configure CPU/RAM limits, health checks and `unless-stopped`/systemd restart behavior.

- [ ] **Step 3: Document secret-safe tunnel setup**

Create the tunnel in OpenAI Platform, associate it with the ChatGPT workspace, install `tunnel-client` on the VM, use `doctor`, then add the tunnel under ChatGPT Developer Mode. Secrets are entered directly on the VM or its secret manager.

- [ ] **Step 4: Document GitHub self-hosted runner safety**

Do not attach a self-hosted runner to a public repository. Make the repository private first, restrict runner labels and never run untrusted fork pull requests on the genomic VM.

### Task 7: Verification and draft PR

**Files:**
- Review all files above.

**Interfaces:**
- Consumes: local validation output and GitHub integration state.
- Produces: one feature branch and at most one draft pull request, or a precise permission handoff.

- [ ] **Step 1: Run fresh local verification**

Run repository validator, shell syntax checks, Python compile/tests, TypeScript build when dependencies are available, Fallow JSON audit and Docker/canary checks when runtime capacity permits. Report every skipped level explicitly.

- [ ] **Step 2: Inspect git scope**

Run `git status --short`, `git diff --check` and review every tracked path. Stage only confirmed project files.

- [ ] **Step 3: Publish one draft PR if authorized tools work**

Use branch `codex/genome-runtime-mcp`, base `main`, title `chore: scaffold private genomic analysis runtime`, and describe validation limits. Never retry an uncertain PR creation blindly.

- [ ] **Step 4: Preserve deployment status**

The PR and local tests can establish pre-deployment validation only. Keep `POST-DEPLOYMENT PENDENTE` until Magalu deployment, resource gates, live canary and section 260 smoke are executed.
