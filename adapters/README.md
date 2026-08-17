# Optional adapters

GENOMA's deterministic core does not require any external edge provider, workflow orchestrator, database, hosting service, AI system or tool-interface vendor.

Adapters are intentionally replaceable and may be removed without changing scientific results, policy semantics or audit evidence.

| Adapter class | Purpose | Core authority |
|---|---|---|
| Edge/tunnel | authenticated private ingress | none |
| Durable workflow | retry/history orchestration | none |
| SQL projection | searchable projection of portable evidence | none |
| Hosting | optional UI/API hosting | none |
| Tool interface | optional human/agent-facing invocation surface | none |
| GA4GH | future WES/TES/DRS interoperability | none |

## Rules

1. The canonical ruleset and deterministic policy engine remain authoritative.
2. Scientific data must never become canonical only because it is stored by an adapter.
3. Adapter outages must not alter prior evidence or scientific conclusions.
4. No adapter may grant `POST-DEPLOYMENT PASS`.
5. Credentials must remain outside the repository and outside genomic/audit payloads.
6. Real genomic analysis must remain executable without any optional adapter.
