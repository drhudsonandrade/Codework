# Magalu VM + private MCP setup

## Status boundary

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE`

Repository creation, CI success and a synthetic canary do not establish post-deployment status. Promotion requires deployment on the target VM, current runtime/resource gates, a live MCP canary, and the section 260 suite at 15/15 with no critical failure.

The external ruleset manifest is `manifests/RULESET_V3.4.sha256`, and the sealed 13-part transport composition is defined by `normative/sealed/MANIFEST.json`. The executable normative source is that sealed repository transport materialized at runtime by the reviewed materializer; do not maintain a second active ruleset TXT in ChatGPT Project sources or another operational path. The ChatGPT Project may retain only procedural bootstrap instructions plus the canonical identity/digest needed to verify the runtime source.

To verify a securely materialized runtime copy when operating on the target host:

```bash
scripts/verify_ruleset.sh /secure/runtime/REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt
```

This confirms the hash and the `VIGENTE`/`v3.4`/`17/08/2026` header but deliberately leaves deployment pending. In the ChatGPT Project, remove superseded active rulesets and avoid adding a duplicate executable ruleset; keep the current **BOOTSTRAP CURTO** in Project Instructions with the canonical filename/version/date/digest, then run the 15 live prompts in section 260 only against the runtime-materialized source.

## 1. GitHub access

You do not need to create folders in advance. Git creates paths such as `.github/workflows` when files are committed.

1. Open <https://github.com/settings/installations> while signed in to the GitHub account that owns the public `OmniGenis` repository.
2. Locate the ChatGPT/OpenAI GitHub App and choose **Configure**.
3. Under repository access, choose **Only select repositories** and select `OmniGenis`, or choose all repositories if that broader scope is intentional.
4. Confirm the requested permissions include repository contents and pull requests. GitHub App permissions are defined by the app; if write permissions are not requested, reconnecting cannot upgrade them.
5. Open the repository's **Settings → Actions** page and allow Actions for the repository.
6. The repository is public. Never route untrusted pull-request or fork code to the genomic VM; reserve the private `omnigenis-isolated` runner for trusted protected-`main` execution under the existing workflow gates.

If ChatGPT still shows the repository but calls return `Unknown tool`, start a new ChatGPT conversation after reconnecting. If GitHub returns `403 Resource not accessible by integration`, re-open the installation page and verify that `OmniGenis` is selected; this is an installation-scope problem, not a missing repository folder.

## 2. Target VM and persistent storage

Recommended starting point for full GRCh38 indexing and one WGS at a time:

- 96–128 GiB RAM.
- 12–24 vCPU.
- 1–2 TiB encrypted NVMe/block storage mounted at `/srv/genome`.
- Ubuntu 24.04 LTS or another supported Linux distribution.
- Object storage for encrypted raw FASTQ/archive copies; do not route 60+ GiB genomic files through ChatGPT.

Create a dedicated `genome` system user and persistent directories:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin genome
sudo install -d -o genome -g genome -m 0750 \
  /srv/genome/refs /srv/genome/data /srv/genome/work \
  /srv/genome/results /srv/genome/audit /var/lib/omnigenis-tunnel
```

Enable disk encryption and restrict SSH/firewall access before copying any personal data.

## 3. Repository and container

Clone the public repository on the VM and build or pull an immutable image. Set the owner at execution time instead of hard-coding a personal account name:

```bash
export GITHUB_REPOSITORY_OWNER='<github-owner>'
sudo install -d -o genome -g genome -m 0750 /opt/omnigenis
sudo -u genome git clone "https://github.com/${GITHUB_REPOSITORY_OWNER}/OmniGenis.git" /opt/omnigenis
cd /opt/omnigenis
docker build --tag omnigenis-genome:local .
```

After the main-branch workflow publishes GHCR, prefer a digest-pinned image in `/etc/omnigenis/genome-mcp.env`:

```text
GENOME_IMAGE=ghcr.io/<github-owner>/omnigenis-genome@sha256:REPLACE_WITH_VERIFIED_DIGEST
MCP_MEMORY_LIMIT=12g
MCP_CPU_LIMIT=4
```

Do not commit that environment file.

## 4. GRCh38 acquisition and external approval

Run acquisition in the container with the persistent reference mount. It creates a pending lock and never self-approves it:

```bash
docker run --rm -it \
  -e REF_ROOT=/refs \
  -v /srv/genome/refs:/refs \
  omnigenis-genome:local \
  /opt/omnigenis/scripts/fetch_grch38.sh
```

Do not override the image entrypoint. The upstream micromamba entrypoint activates the pinned
environment before the script starts; forcing `/bin/bash` bypasses that activation and makes the
installed executables appear to be missing.

External approval procedure:

1. A reviewer or second trusted host independently verifies every URL in `manifests/GRCh38.sources.tsv` and reacquires or checks the nine artifacts.
2. Compare all 64-character SHA-256 values with `GRCh38.lock.sha256.pending`.
3. Record reviewer identity, date and source evidence outside the repository.
4. Only after agreement, install the reviewed plain lock as `/srv/genome/refs/GRCh38.lock.sha256.approved`, mode `0440`, owned by `root:genome`. A detached GPG/minisign signature is recommended for provenance.

The pipeline is intentionally unable to create an `approved` file.

## 5. Full BWA index and resource gate

Run on the high-memory VM, not on GitHub-hosted Actions:

```bash
docker run --rm -it \
  --memory=110g --cpus=16 \
  -e REF_ROOT=/refs \
  -v /srv/genome/refs:/refs \
  omnigenis-genome:local \
  /opt/omnigenis/scripts/build_bwa_mem2_index.sh
docker run --rm -it \
  -e REF_ROOT=/refs \
  -v /srv/genome/refs:/refs:ro \
  omnigenis-genome:local \
  /opt/omnigenis/scripts/validate_grch38.sh
```

Both commands must exit 0. The second command verifies 9/9 artifacts, the approved checksum lock, primary contigs, five BWA index files, a 101-base `samtools faidx` query and a functional dbSNP `bcftools query`.

## 6. Non-sensitive canary

```bash
docker run --rm -it \
  -v /srv/genome/results:/results \
  omnigenis-genome:local \
  /opt/omnigenis/scripts/run_canary.sh /results/canary-initial
```

A pass requires real alignment, BAM validation, GATK HaplotypeCaller and bcftools calling, plus exact comparison with the three-SNP truth set. It proves only executability, not clinical validity.

## 7. Start the private MCP

```bash
sudo install -d -m 0750 /etc/omnigenis
sudo cp deploy/genome-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now genome-mcp.service
curl --fail http://127.0.0.1:3000/healthz
```

Inspect `http://127.0.0.1:3000/mcp` with MCP Inspector before connecting ChatGPT.

## 8. OpenAI Secure MCP Tunnel

1. In OpenAI Platform tunnel settings, create a tunnel and associate both the Platform organization and the target ChatGPT workspace.
2. Grant the operator **Tunnels Read + Use**; creating or editing the tunnel also needs **Read + Manage**.
3. Download the current public `tunnel-client` release from the Platform page; do not hard-code a floating binary URL in automation.
4. Enter the runtime API key directly in the VM secret store or `/etc/omnigenis/tunnel-client.env` with mode `0600`. Never paste it into ChatGPT, GitHub, logs or command arguments.
5. Initialize the HTTP profile using the real tunnel id and local MCP URL:

```bash
tunnel-client init \
  --profile omnigenis-genome \
  --tunnel-id tunnel_REPLACE \
  --mcp-server-url http://127.0.0.1:3000/mcp
tunnel-client doctor --profile omnigenis-genome --explain
```

6. Install `deploy/tunnel-client.service.example` as a reviewed systemd service and keep `tunnel-client run --profile omnigenis-genome` healthy.
7. In ChatGPT web, enable **Settings → Security and login → Developer mode**. Go to ChatGPT Plugins, choose **+**, select **Tunnel**, and select or paste the `tunnel_id`.
8. Review the four discovered tools and keep confirmation enabled for `run_synthetic_canary`.

The private tunnel is for developer-mode/internal use, not public plugin-directory submission.

## 9. Personal WGS arrival

Upload FASTQ/BAM/CRAM directly to encrypted object or block storage using resumable transfer. Store only object keys and checksums in job metadata; never upload a 60+ GiB WGS through ChatGPT. Before calling variants, confirm input type, sample model, GRCh38 compatibility, read groups, sex/ploidy assumptions, known-sites resources, coverage and contamination/QC requirements.

For a full clinical-grade workflow, add and validate `nf-core/sarek`/GATK gVCF/BQSR/joint-calling and a GIAB benchmark in a separate reviewed change. The synthetic canary is not a substitute.

## Deferred components

- Cloudflare is not needed for the first private-tunnel deployment and cannot run the high-memory genomics workload at the edge.
- Temporal can later provide durable job orchestration, but Nextflow is the current workflow engine and keeps the first deployment smaller.
- Supabase can later index redacted job metadata; genomic files remain in private object/block storage.
- Flower and micro-function tooling do not resolve GitHub App permissions or GRCh38 compute requirements, so they are not in the initial runtime.
