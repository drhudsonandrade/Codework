# One-shot private template transport

Upload exactly `GENOMA_REPORT_TEMPLATES_v3.0_DETERMINISTIC.zip` to this directory on this branch.

Required SHA-256: `2350111fa0dc26dd23515e0e3550748592c62147f480c11e09b12bca3557020b`.

The materialization workflow verifies the ZIP, the exact 11 filenames, PDF header, per-file size and SHA-256 against `template_store/v3.0/MANIFEST.json`; then it commits the 11 physical PDFs under `template_store/v3.0/materialized/`, writes `MATERIALIZATION_ATTESTATION.json`, and deletes this one-time inbox.

Do not place personal genotype files here.
