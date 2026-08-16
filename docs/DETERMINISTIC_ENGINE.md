# Deterministic GENOMA engine v0.3.0

The runtime is split into four independently replaceable planes:

1. **Policy Control Plane** — verifies the canonical v3.3 ruleset, compiles 263 stable rule identities, applies deterministic gates and validates structured attestations for rules that cannot honestly become booleans.
2. **Scientific Data Plane** — Nextflow/container workflows own provenance, QC, references, alignment/calling and scientific execution. Real calling always requires a fresh current-session Runtime/Resource Gate.
3. **Evidence Plane** — portable evidence IDs, source versions/dates, content hashes and attestation traces. Databases are optional projections, not canonical truth.
4. **Audit Plane** — deterministic reports, JSONL hash-chain ledger, live deployment evidence, OCI image digests, SBOM and build provenance.

## Structured scientific attestation

Every analysis-relevant normative section is machine-addressable as `GENOMA-V3.3-S000` through `GENOMA-V3.3-S262` with a section SHA-256. A non-binary rule records applicability, one of the five operational statuses, a decision, justification, evidence references, actor/method/run, timestamp, input/output hashes and tool versions. `PROPOSTO` or `NÃO DISPONÍVEL` cannot claim `SATISFIED`.

## Single active ruleset without Git plaintext duplication

Git contains an inactive deterministic base64(gzip) transport under `normative/sealed/` plus the external raw SHA manifest. CI decodes it in memory and proves it is byte-exact to canonical SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`.

`scripts/materialize_ruleset.py` is the only activation path: exact identity + hash + section sequence are verified, the canonical filename is atomically materialized as `0444`, and production mounts it read-only. The repository contract still requires **zero active plaintext `VIGENTE` TXT files** at rest.

## Independent execution

```bash
python3 scripts/materialize_ruleset.py --output-dir /secure/genoma-normative
export GENOMA_RULESET_PATH=/secure/genoma-normative/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt
export GENOMA_RULESET_SHA_MANIFEST=$PWD/manifests/RULESET_V3.3.sha256
cd policy_engine
python -m unittest discover -s tests -v
python -m genoma_policy ruleset-check
python -m genoma_policy smoke
python -m genoma_policy serve --host 127.0.0.1 --port 8787
```

Container deployment and the canonical 15-case live ceremony are documented in `docs/PRODUCTION_CEREMONY.md`.

## Safety gates added in v0.3.0

`BUILD_HARMONIZATION_GATE` explicitly prevents GRCh37/GRCh38/chip-vs-VCF concordance claims before build, REF/ALT and strand harmonization. `CLINVAR_CONFLICT_GATE` explicitly rejects simple voting and requires review status, VCEP, condition matching, evidence, dates and a Conflict Dossier.

## Optional services

ChatGPT/MCP, Cloudflare, Temporal, Supabase, Vercel and microfn are optional adapters. The core has no OpenAI/LLM dependency and can run from Python/OCI on any compatible host.
