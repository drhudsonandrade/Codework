# Orchestration adapter — optional

A durable workflow engine may orchestrate long-running scientific jobs, retries and waits for
human approval. Workflow code should remain deterministic; external operations — invoking the
pipeline, databases, HTTP — belong in activities whose outputs are content-addressed and
written into GENOMA manifests and the ledger.

The engine's event history is orchestration evidence. It is not the normative source and not
the only copy of scientific evidence. The core CLI and HTTP interface remain directly
executable without any orchestrator.

The system must continue to run with this directory deleted.
