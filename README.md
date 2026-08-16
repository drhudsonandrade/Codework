# GENOMA deterministic runtime

Private, reproducible genomics execution repository governed by the canonical GENOMA v3.3 ruleset.

## Architecture

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

- `policy_engine/` — deterministic policy engine, structured attestations, HTTP/CLI interface and tamper-evident audit ledger.
- `main.nf`, `nextflow.config`, `Dockerfile` — scientific data/runtime scaffold.
- `mcp/` — optional interface only; it is not a source of truth and is not required by the policy engine.
- `manifests/` — integrity/reference manifests, including the pinned SHA-256 of the normative ruleset.
- `docs/DETERMINISTIC_ENGINE.md` — independent execution and architecture guide.

## Normative source model

There must be exactly one active runtime copy of `REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt`. The repository deliberately does not duplicate the active TXT; it pins its verified SHA-256 in `manifests/RULESET_V3.3.sha256`. The canonical TXT is mounted read-only at runtime and the engine fails closed if identity, hash, version, date, filename or 0–262 section sequence diverges.

## Current project gate

`POST-DEPLOYMENT PENDENTE` remains mandatory until the ruleset-defined live post-deployment smoke suite is actually executed 15/15 with no critical failures.
