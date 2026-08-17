# GENOMA production ceremony

The production ceremony proves one exact deployed revision. It must never be inferred from CI success on another SHA.

## 1. Exact revision

Record the exact Git SHA, OCI image identity, canonical ruleset SHA and deployment/run id.

## 2. Live deterministic service

Materialize the canonical v3.3 ruleset read-only, start the hardened service/container and verify `/healthz`, `/v1/ruleset` and the 263-rule catalog.

## 3. Section-260 witness

`scripts/run_live_post_deployment_smoke.py` sends all 15 canonical scenarios through the running HTTP service, not through an in-process fixture. Each case records the canonical prompt, expected behavior, expected blocking gate, observed gate and SHA-256 of the full HTTP response.

The suite can report PASS only with 15/15 and zero critical failures. It then submits the external post-deployment criteria to the live engine and requires `POST_DEPLOYMENT_GATE=PASS`.

The independent `genoma-policy smoke` suite remains separate and can never grant post-deployment status.

## 4. Bootstrap attestation

`deploy/attestations/bootstrap-project-v3.3.json` is a provider-neutral structured record of the v3.3 bootstrap contract. It must be renewed whenever the bootstrap instructions or deployment semantics change. The deterministic core verifies ruleset identity and execution evidence independently of any user interface.

## 5. Evidence package

The ceremony uploads a long-retention artifact containing materialization evidence, container metadata, live ruleset response, all 15 case results, sanitized container log and a sorted SHA-256 manifest.

A post-deployment result is tied to a precise Git commit, container image, canonical ruleset hash and execution run. A later UI/provider change cannot retroactively alter it.

## 6. Regression rule

Any relevant change to policy logic, ruleset, deployment architecture or safety gates triggers the production ceremony again on `main`. A failed ceremony remains a failed audit; it must never be bypassed to obtain green status.
