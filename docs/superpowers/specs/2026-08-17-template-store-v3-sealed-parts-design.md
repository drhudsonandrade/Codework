# GENOMA v3.0 Sealed Template Transport — Design

## Goal

Complete the existing immutable GENOMA v3.0 private template store by adding the 48 sealed Base64 transport parts already declared by `template_store/v3.0/MANIFEST.json`, without changing any pinned v3.0 PDF byte identity, report metadata, ruleset transport, reporting engine contract, or current v3.4/v3.1 assets.

## Existing contract

The repository already defines:

- `template_store/v3.0/MANIFEST.json` as the content-addressed identity contract;
- 11 exact GENOMA v3.0 PDF filenames, SHA-256 values, byte sizes, and page counts;
- deterministic transport mode `sealed-tar-xz-base64-chunks`;
- `part_count = 48`;
- target directory `template_store/v3.0/sealed/parts`;
- decoded archive name `GENOMA_V3_TEMPLATE_PACK.tar.xz`;
- decoded archive size `1726200` bytes;
- decoded archive SHA-256 `3717f35b6eb0b82fc24f275cb216595c9d3281dc96558103ae791bc9bcf7174a`;
- Base64 payload size `2301600` bytes;
- per-part names, sizes, and SHA-256 values in the manifest;
- validation through `scripts/verify_template_store.py`;
- a fail-closed `--allow-sealed-only` mode when binary source transport is unavailable.

The repository also contains `reporting/reference_v3_manifest.json`, which independently pins the same 11 v3.0 template identities and requires exact SHA-256 verification before use.

## Source of truth

The only acceptable inputs for building the 48 parts are the exact 11 GENOMA v3.0 PDFs whose SHA-256 values already appear in `template_store/v3.0/MANIFEST.json`.

Before packaging, every candidate PDF must match all pinned properties available in the manifest:

1. filename;
2. SHA-256;
3. byte size;
4. page count.

If any exact v3.0 PDF is unavailable or any property differs, packaging must stop with `NÃO DISPONÍVEL` or integrity failure. No v3.1 PDF, corrected PDF, regenerated PDF, visually equivalent PDF, or inferred replacement may be substituted.

## Immutability boundary

The v3.0 package is historical and immutable.

Therefore the implementation must not:

- edit references embedded in the v3.0 PDFs, including historical ruleset wording;
- replace them with current v3.1 models;
- normalize, optimize, linearize, resave, or otherwise rewrite any PDF before packaging;
- change `template_store/v3.0/MANIFEST.json` to accommodate different bytes;
- modify the 13-chunk ruleset transport or its `MANIFEST.json` contract;
- alter current v3.4 ruleset files, v1.2 prompt files, reporting catalog metadata, or current report templates.

Any byte-level template update requires a new template-suite version rather than mutation of v3.0.

## Deterministic packaging flow

The package must be produced from a temporary staging directory containing only the exact 11 validated v3.0 PDFs.

The deterministic build flow is:

1. validate all 11 source files against `template_store/v3.0/MANIFEST.json`;
2. create `GENOMA_V3_TEMPLATE_PACK.tar.xz` using the repository's established deterministic ordering and metadata normalization expected by the current manifest;
3. verify the resulting archive size is exactly `1726200` bytes;
4. verify the resulting archive SHA-256 is exactly `3717f35b6eb0b82fc24f275cb216595c9d3281dc96558103ae791bc9bcf7174a`;
5. Base64-encode the exact archive bytes without introducing transport ambiguity;
6. verify Base64 payload size is exactly `2301600` bytes;
7. split the Base64 payload according to the 48 manifest part entries, producing `tplpart-000` through `tplpart-047`;
8. verify the byte size and SHA-256 of every part against the manifest;
9. reconstruct the Base64 payload from all 48 parts in manifest order;
10. decode and verify the reconstructed archive hash and size;
11. extract into a temporary validation directory;
12. verify all 11 reconstructed PDFs again against filename, SHA-256, byte size, and page count;
13. run the repository verifier against the sealed transport;
14. only after every check passes, add the 48 parts to the feature branch.

The implementation may use the repository's existing packaging or verification scripts where they already encode the exact deterministic contract. It must not invent a second incompatible archive format or manifest naming scheme.

## Files to add

Exactly these transport files are expected under the existing manifest contract:

- `template_store/v3.0/sealed/parts/tplpart-000`
- `template_store/v3.0/sealed/parts/tplpart-001`
- ...
- `template_store/v3.0/sealed/parts/tplpart-047`

No materialized PDFs are committed by this task unless the existing repository policy explicitly requires them. Temporary archive, Base64 aggregate, staging files, and reconstructed validation files remain build artifacts and must not be committed.

## Files allowed to change

Primary implementation scope:

- add the 48 files under `template_store/v3.0/sealed/parts/`.

Conditional changes are allowed only if validation reveals an actual compatibility defect in an existing verifier or test, and only after preserving the existing manifest contract. Such a defect must be documented before changing code.

The following are explicitly out of scope:

- `template_store/v3.0/MANIFEST.json` identity values;
- `reporting/reference_v3_manifest.json` identity values;
- the 13-chunk GENOMA ruleset transport;
- report-generation content or layout;
- current ruleset v3.4 or prompt v1.2;
- v3.1 report PDFs.

## Validation gates

The task is complete only when all gates pass.

### Gate A — Source identity

All 11 input PDFs exactly match the current manifest.

### Gate B — Aggregate archive identity

The generated `tar.xz` matches both the expected byte size and SHA-256 already pinned in the manifest.

### Gate C — Part identity

All 48 part names exist exactly once, in the expected directory, and each part matches its manifest byte size and SHA-256.

### Gate D — Round-trip integrity

Concatenating the 48 parts, Base64-decoding, extracting, and hashing the 11 PDFs reproduces the original manifest identities exactly.

### Gate E — Repository verifier

`scripts/verify_template_store.py` must report successful sealed binary transport verification in normal strict mode. `--allow-sealed-only` must remain fail-honest and must not be used to claim the 48-part package is complete.

### Gate F — Regression safety

Existing repository tests relevant to template storage, reporting identity, manifests, and sealed transport must pass. The 13-chunk ruleset architecture must remain unchanged.

## Operational status language

Before all 48 parts and all validation gates pass, binary template transport status remains `NÃO DISPONÍVEL` or incomplete as appropriate.

After successful reconstruction and validation, the binary source transport may be recorded as `VERIFICADO`.

This task does not by itself authorize `POST-DEPLOYMENT PASS` for the broader GENOMA system. That status remains governed by the project's separate live post-deployment ceremony.

## Security and privacy

The repository must remain private, as required by the template-store README and manifest. The sealed package contains only reusable model PDFs; no case, patient, genotype, credential, or personal data may be added.

## Success criteria

The feature is accepted when:

- all 48 declared sealed parts are present on the implementation branch;
- every part matches the current immutable manifest;
- the reconstructed aggregate archive matches the current immutable archive hash;
- all 11 extracted v3.0 PDFs match their current immutable hashes;
- the repository's strict template-store verifier passes;
- relevant regression tests pass;
- no unrelated files or contracts are modified.
