# GENOMA deterministic runtime

Private, reproducible genomics execution repository governed by the canonical GENOMA v3.4 ruleset.

## Architecture

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

- `policy_engine/` — deterministic policy engine, structured attestations, HTTP/CLI interface and tamper-evident audit ledger.
- `main.nf`, `nextflow.config`, `Dockerfile` — scientific data/runtime scaffold.
- `normative/sealed/` — inactive byte-exact transport of the canonical v3.4 TXT; plaintext is materialized only at runtime and mounted read-only.
- `mcp/` — optional interface only; not a source of truth and not required by the policy engine.
- `adapters/` — optional Cloudflare/Temporal/Supabase/Vercel/microfn/OpenAI integration contracts.
- `manifests/` — integrity/reference manifests.
- `docs/NORMATIVE_V3.4.md` — the vigent norm: identity, uniqueness rule, section-258 gates and the POST-DEPLOYMENT criterion.
- `docs/PRODUCTION_CEREMONY.md` — exact live-deployment and section-260 evidence procedure.

## Normative source model

There must be exactly one active runtime copy of `REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt`. Git stores only the expected raw SHA-256 and a sealed inactive transport. CI verifies the transport decodes byte-for-byte to SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`, then materializes it into an ephemeral runtime directory as mode `0444`.

## Execution modes

- **Core-only:** Python CLI/HTTP. No external service, LLM, database or edge provider required.
- **Policy container:** OCI/Docker with the canonical TXT mounted read-only.
- **Scientific workflow:** Nextflow/container runtime with a fresh Runtime/Resource Gate before real calling.
- **Optional interfaces:** MCP, web UI, Cloudflare ingress, Temporal orchestration and Supabase evidence index.

Post-deployment status is evidence-driven. Never infer it from README text; use the most recent `genoma-post-deployment-evidence-<commit>` artifact and the ruleset-defined gate.
