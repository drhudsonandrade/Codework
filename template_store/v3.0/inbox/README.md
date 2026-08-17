# One-time private template inbox

This directory exists only to receive the deterministic template transport file directly into the private GitHub repository.

Required filename:

`GENOMA_REPORT_TEMPLATES_v3.0_DETERMINISTIC.zip`

Required SHA-256:

`2350111fa0dc26dd23515e0e3550748592c62147f480c11e09b12bca3557020b`

When that exact file is uploaded to this branch, `.github/workflows/materialize-template-pdfs.yml` verifies the ZIP, verifies all 11 PDF identities against `template_store/v3.0/MANIFEST.json`, writes `MATERIALIZATION_ATTESTATION.json`, commits the exact PDF bytes under `template_store/v3.0/materialized/`, and removes this one-time inbox transport.

Do not upload personal genotype data here.
