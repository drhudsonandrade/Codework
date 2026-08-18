# Deterministic GENOMA engine v0.3.0

The runtime is split into four independently replaceable planes:

1. **Policy Control Plane** — verifies the canonical v3.4 ruleset, compiles 263 stable rule identities, applies deterministic gates and validates structured attestations for rules that cannot honestly become booleans.
2. **Scientific Data Plane** — Nextflow/container workflows own provenance, QC, references, alignment/calling and scientific execution. Real calling always requires a fresh current-session Runtime/Resource Gate.
3. **Evidence Plane** — portable evidence IDs, source versions/dates, content hashes and attestation traces. Databases are optional projections, not canonical truth.
4. **Audit Plane** — deterministic reports, JSONL hash-chain ledger, live deployment evidence, OCI image digests, SBOM and build provenance.

## Structured scientific attestation

Every analysis-relevant normative section is machine-addressable as `GENOMA-V3.4-S000` through `GENOMA-V3.4-S262` with a section SHA-256. A non-binary rule records applicability, one of the five operational statuses, a decision, justification, evidence references, actor/method/run, timestamp, input/output hashes and tool versions. `PROPOSTO` or `NÃO DISPONÍVEL` cannot claim `SATISFIED`.

## Single active ruleset without Git plaintext duplication

Git contains an inactive deterministic base64(gzip) transport under `normative/sealed/` plus the external raw SHA manifest. CI decodes it in memory and proves it is byte-exact to canonical SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.

`scripts/materialize_ruleset.py` is the only activation path: exact identity + hash + section sequence are verified, the canonical filename is atomically materialized as `0444`, and production mounts it read-only. The repository contract still requires **zero active plaintext `VIGENTE` TXT files** at rest.

## Runtime/Resource Gate cannot be inherited

Ruleset v3.4 section 259 ends the RUNTIME/RESOURCE LOCK with *"Não herdar o PASS de outra
sessão."* A gate artifact declaring `inherited_from_previous_session: false` does not satisfy
that on its own, because the producer writes that flag unconditionally and the file can be
copied anywhere.

`scripts/runtime_resource_gate.py` therefore stamps a `session_binding` carrying the kernel
`boot_id`, hostname, platform and creation time. `scripts/verify_runtime_gate_manifest.py`
re-derives the boot identity at verification time and refuses an attestation that came from a
different boot or host, or that is older than `--max-age-seconds` (default 24h). The boot id is
shared by containers on one host, so a gate produced and consumed inside the same pipeline
still verifies, while a stale or foreign artifact fails closed.

Consequences worth knowing before an operator hits them:

- A `--runtime_gate_manifest` produced on another machine is rejected. Re-run the gate on the
  machine that will do the calling; that is the rule, not a defect.
- Gate artifacts produced before this contract have no `session_binding` and fail closed.
- On hosts without `/proc/sys/kernel/random/boot_id`, `--allow-unbound-session` accepts the
  weaker basis and records it as `session_binding_basis: unbound` in the evidence.

## Independent execution

```bash
python3 scripts/materialize_ruleset.py --output-dir /secure/genoma-normative
export GENOMA_RULESET_PATH=/secure/genoma-normative/REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt
export GENOMA_RULESET_SHA_MANIFEST=$PWD/manifests/RULESET_V3.4.sha256
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
