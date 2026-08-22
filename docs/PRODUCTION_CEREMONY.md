# GENOMA v3.4 production ceremony

This ceremony converts an inactive, content-addressed normative transport into a real runtime instance without committing a second active plaintext `VIGENTE` source.

## 1. Normative activation

`scripts/materialize_ruleset.py` decodes the sealed transport entirely under a controlled runtime path, verifies the transport SHA-256, gzip SHA-256, raw canonical SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`, exact normative identity and sequential sections 0–262. It atomically writes exactly `REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt` as mode `0444`.

The repository continues to contain zero active plaintext rulesets. `scripts/validate_repo.py` decodes the transport **in memory** during CI and verifies that it is byte-exact before any activation.

## 2. Real instance

`.github/workflows/genoma-production-ceremony.yml` builds the policy OCI image from the exact Git commit and starts a real hardened Linux container with:

- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- canonical TXT mounted `:ro`;
- external SHA manifest mounted `:ro`;
- HTTP bound only to `127.0.0.1`.

The workflow captures `docker inspect`, image ID, mount mode, health response and live ruleset identity.

## 3. Section-260 live smoke

`scripts/run_live_post_deployment_smoke.py` sends all 15 canonical scenarios through the **running HTTP service**, not through an in-process unit fixture. Each case records the canonical natural-language prompt, expected behavior, expected blocking gate, observed gate and SHA-256 of the full HTTP response.

The suite can report PASS only with `total=15`, `passed=15` and `critical_failures=0`. It then submits the external post-deployment criteria to the live engine and requires `POST_DEPLOYMENT_GATE=PASS` and `post_deployment_status=PASS`.

The independent `genoma-policy smoke` suite remains separate and can never grant post-deployment status.

## 4. Bootstrap attestation

`deploy/attestations/bootstrap-project-v3.4.json` is consumed only through `scripts/bootstrap_attestation.py`. The verifier binds the exact attestation bytes to a pinned SHA-256, checks the complete expected bootstrap-check set and requires the canonical `v3.4/VIGENTE/17/08/2026` identity. Self-declared JSON status alone cannot grant PASS.

The core does not depend on ChatGPT; the bootstrap attestation closes the project-specific bootstrap criterion and must be renewed when Project Instructions change.

## 5. Evidence package

The ceremony uploads a 365-day artifact named `genoma-post-deployment-evidence-<commit>` containing the materialization record, container metadata, live ruleset response, all 15 case results, container log, and a sorted SHA-256 manifest.

A post-deployment result is therefore tied to a precise Git commit, container image, canonical ruleset hash and execution run. A later model/UI/provider cannot retroactively alter it.

## 6. Regression rule

Any relevant change to policy logic, ruleset, deployment architecture or safety gates triggers the production ceremony again on `main`. A failed ceremony remains a failed audit; it must never be bypassed to obtain green status.
