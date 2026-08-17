# GENOMA deterministic runtime

Private, reproducible genomics execution repository governed by the canonical GENOMA v3.3 ruleset.

## Architecture

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

- `policy_engine/` — deterministic policy engine, structured attestations, HTTP/CLI interface and tamper-evident audit ledger.
- `main.nf`, `nextflow.config`, `Dockerfile` — scientific data/runtime scaffold.
- `normative/sealed/` — inactive byte-exact transport of the canonical v3.3 TXT; plaintext is materialized only at runtime and mounted read-only.
- `mcp/` — optional interface only; not a source of truth and not required by the policy engine.
- `adapters/` — optional Cloudflare/Temporal/Supabase/Vercel/microfn/OpenAI integration contracts.
- `manifests/` — integrity/reference manifests.
- `docs/PRODUCTION_CEREMONY.md` — exact live-deployment and section-260 evidence procedure.

## Normative source model

There must be exactly one active runtime copy of `REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt`. Git stores only the expected raw SHA-256 and a sealed inactive transport. CI verifies the transport decodes byte-for-byte to SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`, then materializes it into an ephemeral runtime directory as mode `0444`.

## Execution modes

- **Core-only:** Python CLI/HTTP. No external service, LLM, database or edge provider required.
- **Policy container:** OCI/Docker with the canonical TXT mounted read-only.
- **Scientific workflow:** Nextflow/container runtime with a fresh Runtime/Resource Gate before real calling.
- **Optional interfaces:** MCP, web UI, Cloudflare ingress, Temporal orchestration and Supabase evidence index.

Post-deployment status is evidence-driven. Never infer it from README text; use the most recent `genoma-post-deployment-evidence-<commit>` artifact and the ruleset-defined gate.
