# Prepare private genomic analysis runtime and MCP

## Summary

- pin samtools 1.24, bcftools 1.24, bwa-mem2 2.3, GATK 4.6.2.0, Nextflow 26.04.6 and Snakemake 7.32.4 in a container;
- add a nine-artifact GRCh38 source manifest, external checksum approval gate, BWA index resource gate, contig validation, `samtools faidx`, and `bcftools query` checks;
- add a deterministic non-sensitive alignment and dual-caller canary;
- add a tool-only private MCP with four bounded tools, idempotency, redacted audit records, localhost binding, container hardening and OpenAI Secure MCP Tunnel runbook;
- add Fallow 3.16.0 PR auditing and GHCR publishing after protected main succeeds;
- add the external SHA-256 manifest for the canonical v3.3 ruleset without committing the ruleset text;
- add a recovery/activation runbook, 90-day CI evidence retention request, GHCR digest record and
  an explicit Conda package lock in successful canary artifacts;
- prevent container commands from bypassing the micromamba entrypoint.

## Local pre-deployment evidence

- Python: 6/6 PASS;
- MCP/TypeScript: 12/12 PASS;
- TypeScript strict compile: PASS after pinning `@types/express` 5.0.6;
- Fallow quality: 0 issues; 0 critical/high/moderate complexity findings;
- Fallow security: 12 bounded path-construction candidates manually reviewed; 0 high-severity candidates;
- repository contract: PASS, GRCh38 manifest 9/9;
- ruleset hash/header: PASS (`VIGENTE`, v3.3, 14/08/2026);
- MCP `/healthz`: PASS.
- live MCP initialize/tools-list transport canary: PASS; exactly four approved tools;
- non-sensitive execution canary: expected FAIL on this scratch host, with redacted `0600` audit evidence, because the NGS executables are absent;
- GitHub-hosted pinned container: runtime gate 7/7 PASS;
- GitHub-hosted bcftools and GATK HaplotypeCaller canary: both PASS, TP=3, FP=0, FN=0 and genotype concordance 3/3.

The full pinned container and synthetic GATK/bcftools calling canary were executed in GitHub
Actions. The scratch runtime is not the deployment target and does not need system-wide NGS installs.

## Status

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE`

Do not promote to `POST-DEPLOYMENT PASS` until the target VM is deployed, the externally approved GRCh38 lock is present, all runtime/reference/canary gates pass, the canonical v3.3 source and BOOTSTRAP CURTO are active in the ChatGPT Project, and the section 260 live suite passes 15/15 with no critical failure.
