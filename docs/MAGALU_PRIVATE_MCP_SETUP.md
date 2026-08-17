# Private MCP deployment runbook

This runbook covers the optional private MCP interface on a Linux VM. It is not part of the scientific authority chain.

## Preconditions

- exact approved GENOMA image digest;
- canonical ruleset mounted read-only;
- reference bundle validated by current-session Runtime/Resource Gate;
- loopback-only MCP listener unless an authenticated private ingress is separately configured;
- no personal genomic data in logs, tool arguments or repository files.

## Start

Use `deploy/docker-compose.yml` with a digest-pinned image. Do not override the image entrypoint with an interactive shell in production.

After start, verify:

```bash
curl -fsS http://127.0.0.1:3000/healthz
```

Inspect the MCP endpoint locally with an MCP-compatible inspector. Only the allowlisted tools may appear.

## Security requirements

1. No arbitrary shell tool.
2. No arbitrary file read/write/upload/delete tool.
3. Per-request idempotency and immutable redacted audit records.
4. Bounded identifiers and path containment.
5. Private ingress, if used, must authenticate before reaching loopback service.
6. The interface must never change policy or scientific status by itself.

## Recovery

If the VM or optional ingress is unavailable, the deterministic CLI/HTTP/OCI core remains the supported execution path. Recreate the interface only after verifying image digest, ruleset identity, current runtime resources and synthetic canary evidence.

`POST-DEPLOYMENT PASS` can only be granted by the exact-SHA live Production Witness; interface availability alone never grants it.
