# Codework private genome MCP

This is a tool-only, streamable-HTTP MCP server. It exposes no arbitrary command, file upload, file read or deletion tool.

Tools:

- `runtime_status`: exact executable/version gate.
- `reference_status`: approved checksum, contig, BWA index, `samtools faidx` and `bcftools query` gate.
- `run_synthetic_canary`: deterministic non-sensitive GATK/bcftools canary; requires a bounded `requestId`.
- `audit_record`: reads the immutable redacted record for a request id.

Local contract validation:

```bash
npm ci --ignore-scripts
npm test
npm start
npx @modelcontextprotocol/inspector@latest
```

Use `http://127.0.0.1:3000/mcp` in MCP Inspector. A production VM should keep this service on loopback or behind a separately authenticated private ingress. The MCP layer is optional and has no scientific or policy authority.

Never put genomic inputs or credentials in tool arguments. This interface deliberately limits execution to bounded, audited operations.
