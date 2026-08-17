# GENOMA v3.0 — private immutable template store

This directory defines the immutable source identities for the 11 user-approved GENOMA v3.0 PDF models.

## Contract

- Repository visibility must remain **private**.
- `MANIFEST.json` is the content-addressed identity contract.
- Report IDs `01`..`11` may not change filename, SHA-256, byte size or page count under version `v3.0`.
- Any byte-level template change requires a new suite version and new immutable manifest.
- No case, patient or genotype data may be stored here.
- The renderer must use only a template whose bytes verify against the manifest.

## Sealed source transport

The approved storage design uses a deterministic `tar.xz` encoded as fixed base64 parts under `sealed/parts/`. `scripts/verify_template_store.py` validates every part, reconstructs the archive, checks the archive hash and then checks all 11 PDF hashes before optional materialization.

The `--allow-sealed-only` mode is intentionally honest: when the source parts are absent from a checkout it returns `NÃO DISPONÍVEL` for binary materialization while still verifying the manifest-to-reference identity contract. It must never silently manufacture or substitute a PDF.

## Operational status

The template identities are **VERIFICADO** against the exact attached v3.0 model sources. Binary source transport is promoted to **VERIFICADO** only when every sealed part is present and passes the reconstruction check.
