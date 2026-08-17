# Private genomics runtime implementation plan — historical record

This file is retained as a provider-neutral record of the original infrastructure work.

## Goal

Prepare a private Linux VM to run an auditable germline genomics workflow through narrowly scoped deterministic interfaces.

## Architecture

- Git stores source code, version locks, manifests, CI and operational documentation.
- Persistent private storage holds GRCh38 resources, indexes, genomic inputs and outputs.
- The deterministic core exposes CLI/HTTP; MCP is an optional bounded tool interface.
- Any private ingress is an optional adapter and must authenticate before reaching the loopback service.

## Implemented principles

1. deny-by-default handling of genomic data in Git;
2. exact version/runtime checks;
3. checksum-locked GRCh38 lifecycle;
4. deterministic synthetic dual-caller canary;
5. narrow tool allowlist with no arbitrary shell or file operations;
6. redacted audit records and bounded identifiers;
7. private persistent mounts and restart-safe services;
8. self-hosted runner isolation from untrusted code;
9. pre-deployment evidence distinct from post-deployment proof;
10. no relevant step can be marked complete without execution evidence.

## Current governing rule

This historical plan never grants deployment status. The current repository contracts, Runtime/Resource Gate and exact-SHA Production Witness supersede historical implementation notes.
