# OmniGenis private genome MCP

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

Use `http://127.0.0.1:3000/mcp` in MCP Inspector. The production VM binds the server to loopback through Docker Compose and connects it to ChatGPT with OpenAI Secure MCP Tunnel.

Never put genomic inputs or credentials in tool arguments. This first version deliberately limits execution to the synthetic canary.
