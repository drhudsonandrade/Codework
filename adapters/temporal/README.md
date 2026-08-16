# Temporal adapter — optional

Temporal may orchestrate long-running scientific jobs, retries and human approval waits. Workflow code should remain deterministic; external operations (Nextflow invocation, databases, HTTP, optional LLM calls) belong in Activities whose outputs are content-addressed and written into GENOMA manifests/ledger.

Temporal Event History is orchestration evidence, not the normative source and not the only copy of scientific evidence. The core CLI/HTTP remains directly executable without Temporal.
