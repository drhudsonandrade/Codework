# GENOMA Policy Engine v0.3.0

Deterministic, vendor-neutral executable policy for the canonical GENOMA v3.4 ruleset.

The engine is intentionally not a genomic caller and not an LLM. It is the **Policy Control Plane** that validates execution/evidence manifests produced by the Scientific Data Plane and interfaces.

Key properties:

- 263 normative sections are compiled into stable rule IDs and section hashes.
- Objective invariants use deterministic gates.
- Scientific judgement that cannot honestly be reduced to `true/false` requires structured attestation with status, evidence, justification and trace.
- Current-session Runtime/Resource Gate is mandatory before real calling.
- Dedicated build-harmonization and ClinVar-conflict gates cover section-260 cases 3 and 4 explicitly.
- Canonical v3.4 bytes are activated from an inactive sealed transport only at runtime and mounted read-only.
- Independent regression smoke and live post-deployment section-260 smoke are distinct; only the latter can satisfy `POST_DEPLOYMENT_GATE`.
- CLI and HTTP work without ChatGPT, OpenAI keys, Cloudflare, Temporal, Supabase or any other external service.

See root `docs/PRODUCTION_CEREMONY.md` and `docs/PORTABILITY_MATRIX.md`.
