# Optional adapters — anti-lock-in contract

The GENOMA core has **zero required ingress, orchestration, projection, UI, glue or agent-interface runtime dependency**. Every optional service must call the same stable CLI/HTTP contracts and may disappear without changing scientific truth.

| Adapter | Optional role | What it may do | What it must never do |
|---|---|---|---|
| Cloudflare | ingress | Tunnel, Access, WAF, rate limiting | become policy authority; store canonical genomic evidence |
| Temporal | orchestration | retries, timers, durable long-running jobs | redefine policy decisions or hide activity outputs |
| Supabase | evidence projection | searchable index/materialized views with RLS | become the only copy of evidence/audit history |
| Vercel | UI | dashboard, reports, operator controls | run NGS calling or own normative state |
| microfn | glue | tiny health/webhook adapters | contain scientific rules or secrets by default |
| Agent interface (MCP-compatible client) | interface | translate user intent to manifests, explain deterministic results | satisfy gates by narrative; fabricate tool/data execution |

## Port contract

All adapters communicate through portable JSON over the core endpoints (`/v1/ruleset`, `/v1/catalog`, `/v1/evaluate`) or the CLI. Evidence crossing an adapter boundary must carry content hashes and the originating run/session ID. Optional adapter failure is never allowed to turn `NÃO DISPONÍVEL` into `EXECUTADO` or `VERIFICADO`.

## Supabase hardening when enabled

Use a non-exposed/private schema for canonical evidence projections where possible, expose only purpose-built API views, enable RLS on every exposed table/view, use least-privilege grants, and keep the service-role key server-side. The filesystem/content-addressed evidence bundle remains authoritative so the database can be rebuilt from artifacts.

## Temporal when enabled

Keep Workflow code deterministic and move network/database/file/LLM operations into Activities. Activity results must be content-addressed and written back into the GENOMA execution manifest/ledger. Temporal history is orchestration evidence, not scientific truth.

## Cloudflare when enabled

Place it in front of the HTTP adapter only. The origin remains able to bind to loopback/private networking and run without Cloudflare. Use Access/Tunnel/WAF as defense-in-depth, not as a required execution engine.
