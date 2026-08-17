# GENOMA executable architecture

## Design invariant

The canonical ruleset is data; the policy engine is deterministic software; scientific workflows are separate executors; evidence and audit are portable records. No external model or hosted interface is trusted as the source of truth.

## Plane 1 — Policy Control Plane

Responsibilities: verify ruleset identity/uniqueness/SHA-256; expose all 263 sections as stable IDs; enforce objective safety invariants; validate structured attestations for non-boolean scientific rules; fail closed on unresolved or contradictory attestations.

## Plane 2 — Scientific Data Plane

Responsibilities: input provenance/transformation lineage; consent/scope; QC-first execution; session-specific Runtime/Resource Gate before real calling; Nextflow/containerized scientific tooling. `requires_real_calling=true` forces current-session resource evidence.

## Plane 3 — Evidence Plane

Evidence is identified by stable IDs. Mutable sources carry version and checked-at metadata. Section attestations reference evidence IDs and contain input/output SHA-256 values. Portable JSON is the default; a database can index the same records without changing semantics.

## Plane 4 — Audit Plane

The engine emits deterministic reports and an optional tamper-evident JSONL hash chain. CI records tests, independent safety smoke, policy parity, secret scanning, real container build/run and immutable OCI image digest/provenance.

## Optional interfaces

CLI, HTTP and OCI are first-class. MCP, web UIs, private ingress, durable workflow services, SQL projections and future interfaces are adapters only. Their disappearance must not prevent local policy execution.

## Failure behavior

- Ruleset conflict → fail closed.
- Missing evidence/justification/trace → fail closed for analysis-relevant attestation coverage.
- `PROPOSTO` or `NÃO DISPONÍVEL` claiming satisfaction → fail closed.
- Missing current-session runtime proof for real calling → fail closed.
- POST-DEPLOYMENT conditions absent → PENDING and never promoted by ordinary CI.
