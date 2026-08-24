# Prepare private genomic analysis runtime and MCP

## Summary

- pin samtools 1.24, bcftools 1.24, bwa-mem2 2.3, GATK 4.6.2.0, Nextflow 26.04.6 and Snakemake 7.32.4 in a container;
- add a nine-artifact GRCh38 source manifest, external checksum approval gate, BWA index resource gate, contig validation, `samtools faidx`, and `bcftools query` checks;
- add a deterministic non-sensitive alignment and dual-caller canary;
- add a tool-only private MCP with four bounded tools, idempotency, redacted audit records, localhost binding, container hardening and OpenAI Secure MCP Tunnel runbook;
- add Fallow 3.16.0 PR auditing and GHCR publishing after protected main succeeds;
- add the external SHA-256 manifest for the canonical v3.4 ruleset without committing the ruleset text;
- add a recovery/activation runbook, CI evidence retention request, GHCR digest record and an explicit Conda package lock in successful canary artifacts;
- prevent container commands from bypassing the micromamba entrypoint.

## Current canonical ruleset

- status: `VIGENTE`
- version: `v3.4`
- effective date: `17/08/2026`
- canonical file: `REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt`
- raw SHA-256: `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`
- external manifest: `manifests/RULESET_V3.4.sha256`

## Validation evidence contract

Do not copy historical PASS claims forward. Record only results actually produced by the PR's current HEAD. Required evidence includes repository validation, policy/unit tests, sealed-transport verification, supply-chain checks, CodeRabbit disposition and GitHub Actions results.

## Status

`POST-DEPLOYMENT PENDENTE` until deployment from reviewed `main` succeeds.

Do not promote to `POST-DEPLOYMENT PASS` until CI for the exact merge candidate is green, CodeRabbit has no blocking findings, the reviewed commit is merged to `main`, and the Production Witness for the resulting `main` SHA proves all of the following:

- canonical `VIGENTE / v3.4 / 17/08/2026` identity;
- `total == 15`;
- `passed == 15`;
- `critical_failures == 0`;
- `post_deployment_status == "PASS"`.

The Runtime/Resource Gate for real NGS calling remains session-specific and cannot be inherited from historical runs.
