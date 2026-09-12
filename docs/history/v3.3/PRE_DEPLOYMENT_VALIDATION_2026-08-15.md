# Pre-deployment validation — 2026-08-15 UTC

## Result

`PRE-DEPLOYMENT VALIDATION NOT FULLY VERIFIED / POST-DEPLOYMENT PENDENTE`

This report combines historical local claims with GitHub-hosted execution evidence. It is not
target-host, GRCh38, WGS, GIAB or clinical validation.

The GitHub-hosted runs below remain recoverable through durable repository URLs and are used only for
the claims their logs actually support. Claims for which this historical record preserves no
recoverable execution log, immutable artifact locator or equivalent evidence are explicitly marked
`HISTÓRICO NÃO VERIFICÁVEL`; no missing locator, result or test count is inferred or invented. The
recovery bundle that was said to contain the synthetic-canary artifact likewise has no durable
locator, so this document cannot claim an overall PRE-DEPLOYMENT VALIDATION PASS.

Durable GitHub evidence used in this record:

- Static/container run: `repository_id=1212760346; run_id=31857676091`
- Static job: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`
- Container/canary job: `repository_id=1212760346; run_id=31857676091; job_id=94945373773`
- Fallow run: `repository_id=1212760346; run_id=31857676073`
- Fallow job: `repository_id=1212760346; run_id=31857676073; job_id=94945373658`
- PR #2: `repository_id=1212760346; pr_number=2`

## GitHub and source control

| Gate | Result | Evidence |
|---|---|---|
| GitHub App access | HISTÓRICO NÃO VERIFICÁVEL | The original report asserted authenticated admin/push/pull access, but no immutable authorization snapshot or execution artifact is preserved here. |
| Pull request | PASS | PR #2 is durably addressable at `repository_id=1212760346; pr_number=2`; GitHub records it as the source-control change that was later merged. Historical draft-state details are not used as proof. |
| Fallow workflow | PASS | Run `31857676073`: `repository_id=1212760346; run_id=31857676073`; job `94945373658` completed successfully. |
| Container/runtime workflow | PASS | Run `31857676091`: `repository_id=1212760346; run_id=31857676091`; both `static` and `container-canary` jobs completed successfully. |
| Genomic payload exclusion | PASS | The `static` job executed `python3 scripts/validate_repo.py` and recorded `PASS repository_contract`; locator: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. This supports the repository contract at that historical checkout, not a claim about later commits. |

## Repository and code gates

| Gate | Result | Evidence |
|---|---|---|
| Locked npm install | PASS | `npm ci --ignore-scripts` installed from the lockfile in the preserved `static` job: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. |
| TypeScript strict compile | PASS | `npm test` invoked the build `tsc -p tsconfig.json` successfully in the same `static` job: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. |
| MCP tests | PASS | TAP summary in the `static` job records 12 tests, 12 pass, 0 fail: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. |
| Python tests | PASS | The recoverable GitHub-hosted `static` job records **5/5**, not 6/6 (`Ran 5 tests ... OK`): `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. The separate historical 6/6 assertion is not used as evidence here. |
| Shell syntax | PASS | `bash -n scripts/*.sh` completed successfully in the `static` job: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. |
| Repository contract | PASS | `python3 scripts/validate_repo.py` recorded `PASS repository_contract`: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. |
| GRCh38 source manifest | PASS | The same validator recorded `PASS grch38_manifest 9/9`: `repository_id=1212760346; run_id=31857676091; job_id=94945373740`. This is manifest validation only; it does not prove the GRCh38 payload was installed. |
| Ruleset identity | HISTÓRICO NÃO VERIFICÁVEL | The original report asserted SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`, `VIGENTE`, v3.3, 14/08/2026. The recovered `static` log does not emit those exact identity fields, so this row is not retained as PASS solely from the historical assertion. |
| Fallow 3.16.0 quality | PASS | Job `94945373658` installed verified Fallow 3.16.0 and its audit gate ended with `ISSUES: 0`, `VERDICT: pass`: `repository_id=1212760346; run_id=31857676073; job_id=94945373658`. |
| Fallow security detail | EXECUTADO / HISTÓRICO NÃO VERIFICÁVEL | The Fallow job executed the security-summary command successfully, but the recovered log does not preserve the asserted detail “12 bounded candidates, 0 high” in-line. Locator for the execution: `repository_id=1212760346; run_id=31857676073; job_id=94945373658`. |

## GitHub-hosted runtime and calling evidence

The pinned container ran real commands in the GitHub-hosted `container-canary` job. Every PASS below
is anchored to the same durable job log:
`repository_id=1212760346; run_id=31857676091; job_id=94945373773`.

| Component | Result | Evidence locator |
|---|---|---|
| Java | PASS — 17.0.18 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| samtools | PASS — 1.24 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| bcftools | PASS — 1.24 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| bwa-mem2 | PASS — package 2.3 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| GATK | PASS — 4.6.2.0 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| Nextflow | PASS — 26.04.6 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| Snakemake | PASS — 7.32.4 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| bcftools synthetic calling | PASS — TP=3, FP=0, FN=0, F1=1.0, genotypes 3/3 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |
| GATK HaplotypeCaller synthetic calling | PASS — TP=3, FP=0, FN=0, F1=1.0, genotypes 3/3 | `repository_id=1212760346; run_id=31857676091; job_id=94945373773` |

The workflow uploaded artifact `synthetic-canary-a4a341fdc115deb693e015687e32fc607a639cf8` with Actions
digest `sha256:ec7fc74089ae4373540f3556f069429a35d459870a409cc07c979028b48064cc`; the upload log records
artifact ID `9239560781`, originally addressable at
`repository_id=1212760346; run_id=31857676091; artifact_id=9239560781`, with historical
expiration on 2026-08-29. The artifact was evidence only. The historical report stated that the
release handoff copied it into a durable recovery bundle, but no durable recovery-bundle locator is
preserved in this repository. That copy is therefore **NÃO DISPONÍVEL para verificação por este
registro histórico**, and the missing locator is why the overall result above is NOT FULLY VERIFIED.

## Local MCP transport evidence

No immutable local execution log or artifact locator for the following scratch-host observations is
preserved in this historical record. They are retained only as historical claims and are **not counted
as PASS evidence**:

- **HISTÓRICO NÃO VERIFICÁVEL** — `GET /healthz` was recorded as HTTP 200.
- **HISTÓRICO NÃO VERIFICÁVEL** — Streamable HTTP initialization was recorded with protocol `2025-06-18`.
- **HISTÓRICO NÃO VERIFICÁVEL** — `tools/list` was recorded with exactly `runtime_status`, `reference_status`, `run_synthetic_canary` and `audit_record`.
- **HISTÓRICO NÃO VERIFICÁVEL** — `GET /mcp` was recorded as HTTP 405 as designed.
- **HISTÓRICO NÃO VERIFICÁVEL** — canary arguments were recorded as `{ "requestId": "canary-nosensitive-20260815a" }`.
- **HISTÓRICO NÃO VERIFICÁVEL** — audit behavior was recorded as bounded arguments, PASS/FAIL, duration, sanitized error and file mode `0600`.
- **HISTÓRICO NÃO VERIFICÁVEL** — the scratch-host observation stated that no sensitive payload was used.

The historical scratch-host execution was expected to fail its runtime tool gate because the tools
lived in the container. The separate GitHub-hosted container/calling results above remain independently
recoverable from their job log and therefore keep their own PASS status.

## Blocking gates before post-deployment

1. Provision and harden the future target VM and persistent encrypted storage.
2. Pull the main-branch GHCR image by verified digest.
3. Install the nine GRCh38 artifacts, obtain independent external lock approval, build the five
   bwa-mem2 index files, and pass contig/faidx/query validation.
4. Connect the private MCP through Secure MCP Tunnel and execute a live non-sensitive canary.
5. Provide WGS input and complete the production germline workflow plus a GIAB benchmark.
6. Activate the canonical v3.3 ruleset/BOOTSTRAP CURTO in the interactive AI workspace.
7. Execute section 260 live and require 15/15 with no critical failure.

Until all seven gates pass, never record `POST-DEPLOYMENT PASS`.
