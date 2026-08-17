# GENOMA deterministic engine

The GENOMA v3.3 core is a provider-neutral deterministic policy and audit engine.

## Required invariants

1. Canonical ruleset identity is `VIGENTE / v3.3 / 14/08/2026` with SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`.
2. The canonical plaintext ruleset is materialized read-only at runtime from the sealed transport.
3. Analysis-relevant operations require provenance, explicit consent scope, QC, current-session runtime/resource evidence, current evidence review and complete section attestation coverage.
4. `INFERIDO`, `PROPOSTO` and `NÃO DISPONÍVEL` can never be silently promoted to `VERIFICADO`.
5. A final report cannot be published unless all four planes and `FINAL_AUDIT_GATE` pass.
6. `POST-DEPLOYMENT PASS` is bound to an exact deployed Git SHA and the live section-260 15/15 witness.

## Interfaces

The stable core interfaces are Python CLI, HTTP and OCI container execution. MCP or any other human/agent interface is optional and has no authority over scientific truth, ruleset identity or audit status.

## Safety gates

`BUILD_HARMONIZATION_GATE` prevents GRCh37/GRCh38/chip-vs-VCF concordance claims before build, REF/ALT and strand harmonization. `CLINVAR_CONFLICT_GATE` rejects simple voting and requires review status, VCEP, condition matching, evidence, dates and a Conflict Dossier.

## Optional services

Edge ingress, durable orchestration, SQL projections, hosting, serverless glue and external user interfaces are adapters only. The core has no external-model or hosted-service dependency and can run from Python/OCI on any compatible host.
