# GENOMA Policy Engine v0.2.0

Deterministic, vendor-neutral execution layer for the canonical GENOMA ruleset v3.3.

## Normative identity

The engine fails closed unless the externally mounted canonical TXT resolves to:

- `STATUS NORMATIVO: VIGENTE`
- `VERSÃO NORMATIVA: v3.3`
- `DATA FORMAL DE EMISSÃO E VIGÊNCIA: 14/08/2026`
- SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`
- exactly 263 top-level sections numbered 0–262

The TXT remains the normative source. Code is an enforcement layer, not a substitute for scientific judgement.

## Four planes

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

The Python engine owns deterministic policy evaluation and structured attestations. Existing Nextflow/container workflows own scientific execution. Evidence records are referenced by stable IDs and hashes. Audit events can be recorded in a tamper-evident JSONL hash chain.

ChatGPT, MCP, web UIs, Cloudflare, Temporal, Supabase or any future model/vendor are **optional adapters**. The core runtime requires none of them.

## Structured attestations

Scientific/normative rules that cannot honestly be reduced to `true/false` must contain canonical `rule_id` and `rule_sha256`, applicability, one of the five operational statuses, decision, non-empty justification, explicit evidence references, and a trace object with actor, method, run ID, timestamp, input/output SHA-256 and tool versions.

`PROPOSTO` and `NÃO DISPONÍVEL` cannot claim `SATISFIED`. `UNRESOLVED` blocks an analysis-relevant operation. `NOT_APPLICABLE` still requires explicit justification and trace.

## CLI and API

```bash
python -m genoma_policy ruleset-check
python -m genoma_policy catalog --output catalog.json
python -m genoma_policy scaffold --case-id CASE-001 --output manifest.json
python -m genoma_policy evaluate manifest.json --output report.json
python -m genoma_policy smoke --output smoke.json
python -m genoma_policy ledger-append audit.jsonl POLICY_EVALUATED report.json
python -m genoma_policy ledger-verify audit.jsonl
python -m genoma_policy serve --host 127.0.0.1 --port 8787
```

HTTP: `GET /healthz`, `GET /v1/ruleset`, `GET /v1/catalog`, `POST /v1/evaluate`, `POST /v1/smoke`. The server defaults to loopback and does not log request bodies.

## Docker

```bash
docker build -f policy_engine/Dockerfile -t genoma-policy-engine:0.2.0 .
GENOMA_RULESET_PATH=/secure/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt \
GENOMA_RULESET_SHA_MANIFEST=$PWD/manifests/RULESET_V3.3.sha256 \
  docker compose -f policy_engine/docker-compose.yml up --build
```

The ruleset is mounted read-only and must match the repository-pinned SHA manifest. GitHub Actions performs a real Docker build/run test even if a local environment has no Docker daemon.

## POST-DEPLOYMENT

Unit tests, CI, Docker smoke, OPA and the independent 15-case safety smoke do **not** grant `POST-DEPLOYMENT PASS`. That status remains controlled by the canonical ruleset and requires the real post-deployment 15/15 live smoke with no critical failure.
