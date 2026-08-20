# Optional adapters — anti-lock-in contract

The GENOMA core has **zero required ingress, orchestration, projection, UI, glue or agent-interface runtime dependency**. Every optional service must call the same stable CLI/HTTP contracts and may disappear without changing scientific truth.

Adapters are named by **capability**, never by supplier. A directory called after a vendor
reads as a dependency on that vendor, and there is none: each row below is a role that any
conforming implementation may fill, and every one of them may be deleted without changing a
scientific result.

| Adapter | Optional role | What it may do | What it must never do |
|---|---|---|---|
| `ingress/` | ingress | reverse tunnel, access proxy, WAF, rate limiting | become policy authority; store canonical genomic evidence |
| `orchestration/` | orchestration | retries, timers, durable long-running jobs | redefine policy decisions or hide activity outputs |
| `projection/` | evidence projection | searchable index/materialised views with row-level security | become the only copy of evidence/audit history |
| — | UI | dashboard, reports, operator controls | run NGS calling or own normative state |
| — | glue | tiny health/webhook adapters | contain scientific rules or secrets by default |
| — | interface | translate user intent to manifests, explain deterministic results | satisfy gates by narrative; fabricate tool/data execution |
| `ga4gh/` | interoperability | standard genomic exchange formats | replace the internal artefacts they are derived from |

## Port contract

All adapters communicate through portable JSON over the core endpoints (`/v1/ruleset`, `/v1/catalog`, `/v1/evaluate`) or the CLI. Evidence crossing an adapter boundary must carry content hashes and the originating run/session ID. Optional adapter failure is never allowed to turn `NÃO DISPONÍVEL` into `EXECUTADO` or `VERIFICADO`.

## Evidence projection hardening when enabled

Use a non-exposed/private schema for canonical evidence projections where possible, expose only purpose-built API views, enable RLS on every exposed table/view, use least-privilege grants, and keep the service-role key server-side. The filesystem/content-addressed evidence bundle remains authoritative so the database can be rebuilt from artifacts.

## Durable orchestration when enabled

Keep workflow code deterministic and move network, database and file operations into activities. Activity results must be content-addressed and written back into the GENOMA execution manifest and ledger. Orchestration history is orchestration evidence, not scientific truth.

## Ingress when enabled

Place it in front of the HTTP adapter only. The origin remains able to bind to loopback or private networking and run without any ingress layer. Use the tunnel, access proxy and WAF as defence in depth, not as a required execution engine.
