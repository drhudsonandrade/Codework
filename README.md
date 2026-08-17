# GENOMA deterministic runtime

Private, reproducible genomics execution repository governed by the canonical GENOMA v3.3 ruleset.

## Architecture

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

- `policy_engine/` — deterministic policy engine, structured attestations, HTTP/CLI interface and tamper-evident audit ledger.
- `main.nf`, `nextflow.config`, `Dockerfile` — scientific data/runtime scaffold.
- `normative/sealed/` — inactive byte-exact transport of the canonical v3.3 TXT; plaintext is materialized only at runtime and mounted read-only.
- `mcp/` — optional generic tool interface only; never a source of truth and never required by the policy engine.
- `adapters/` — optional edge, orchestration, database, hosting and tool-interface contracts.
- `manifests/` — integrity/reference manifests.
- `docs/PRODUCTION_CEREMONY.md` — exact live-deployment and section-260 evidence procedure.

## Normative source model

There must be exactly one active runtime copy of `REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt`. Git stores only the expected raw SHA-256 and a sealed inactive transport. Runtime materialization must decode byte-for-byte to SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a` and expose the runtime file read-only.

## Execution modes

- **Core-only:** Python CLI/HTTP. No external service, model, database or edge provider required.
- **Policy container:** OCI/Docker with the canonical TXT mounted read-only.
- **Scientific workflow:** Nextflow/container runtime with a fresh Runtime/Resource Gate before real calling.

## Safety rule

No interface, provider or operator can promote `INFERIDO`, `PROPOSTO` or `NÃO DISPONÍVEL` to `VERIFICADO`. Real analysis must fail closed whenever consent, provenance, input integrity, reference identity, current-session runtime resources, evidence freshness or required audit evidence is unresolved.
