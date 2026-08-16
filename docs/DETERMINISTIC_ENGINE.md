# Deterministic GENOMA engine

The runtime is split into four independently replaceable planes.

1. **Policy Control Plane** — verifies the externally mounted canonical v3.3 ruleset, compiles 263 stable rule identities, applies deterministic gates and validates structured attestations for rules that cannot honestly become booleans.
2. **Scientific Data Plane** — Nextflow/container workflows own input provenance, QC, references, calling and other scientific execution. Real calling always requires a fresh current-session Runtime/Resource Gate.
3. **Evidence Plane** — evidence is represented by portable IDs, mutable-source versions/dates, content hashes and attestation traces. A database may project/index those records, but is not required by the core engine.
4. **Audit Plane** — deterministic reports, JSONL hash-chain ledger, CI artifacts, OCI image digests and supply-chain provenance.

## Structured scientific attestation

Every analysis-relevant normative section is machine-addressable as `GENOMA-V3.3-S000` through `GENOMA-V3.3-S262` with a section SHA-256. A non-binary rule must record applicability, one of the five operational statuses, a decision, justification, evidence references, actor/method/run, timestamp, input/output hashes and tool versions. `PROPOSTO` or `NÃO DISPONÍVEL` cannot be used to claim `SATISFIED`; unresolved or blocked sections prevent the analysis-relevant operation from being ready.

## One active ruleset

The normative TXT is an external immutable runtime input, mounted read-only. The repository stores the expected canonical SHA-256 but not a second active copy. `GENOMA_RULESET_PATH` and `GENOMA_RULESET_SHA_MANIFEST` may point to controlled local paths. The resolver fails closed on missing/conflicting identity.

## Independent execution

```bash
export GENOMA_RULESET_PATH=/secure/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt
export GENOMA_RULESET_SHA_MANIFEST=$PWD/manifests/RULESET_V3.3.sha256
cd policy_engine
python -m unittest discover -s tests -v
python -m genoma_policy ruleset-check
python -m genoma_policy smoke
python -m genoma_policy serve --host 127.0.0.1 --port 8787
```

Container:

```bash
docker build -f policy_engine/Dockerfile -t genoma-policy-engine:0.2.0 .
GENOMA_RULESET_PATH=/secure/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt \
GENOMA_RULESET_SHA_MANIFEST=$PWD/manifests/RULESET_V3.3.sha256 \
  docker compose -f policy_engine/docker-compose.yml up --build
```

ChatGPT, MCP, Cloudflare, Temporal, Supabase and any future UI/orchestrator are optional adapters. The deterministic engine has no OpenAI or LLM dependency.

## CI guarantees and limits

`.github/workflows/genoma-policy-engine.yml` uses a clearly marked synthetic v3.3 fixture to test the parser/263-rule infrastructure contract without publishing a duplicate normative TXT. Separately, the repository manifest pins the verified canonical SHA-256. CI runs Python tests, independent 15-case deterministic safety smoke, OPA/Rego, Gitleaks, real Docker build/runtime smoke and publishes an immutable GHCR image after merge to `main`.

For supply-chain traceability, the image is published with BuildKit registry-native OCI provenance (`mode=max`) plus SBOM and the workflow verifies that attached attestation manifests exist in the resulting OCI index. This does not depend on GitHub's repository-attestation storage API, which is not available for this user-owned private repository configuration.

CI infrastructure smoke is not the section-260 live project smoke and never grants `POST-DEPLOYMENT PASS`.
