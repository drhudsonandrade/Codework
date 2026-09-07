# PR51 — Deduplicate language scan and keep cache at publish

## Goal
Reduce static CI time and remove Buildx overhead from the required canary.

## Scope
- Remove the redundant full-checkout language baseline test.
- Restore `container-canary` to the proven plain `docker build` path.
- Keep Buildx/GHA cache exclusively in `publish-ghcr`.
- Add anti-regression contracts for both properties.

## Language safety
- `tests/test_repo_contract.py` still executes `validator.validate(root)` on the full checkout.
- `scripts/validate_repo.py` still invokes `validate_language_policy(root, errors)`.
- Fixture language tests import the raw scanner privately and reject repository `ROOT` at runtime.
- The CI contract forbids attribute bypasses and raw scanner use outside that wrapper.
- Scanner unit tests, baseline comparison tests, and provenance tests remain unchanged.

## Container safety
- Canary remains required and runs the same local SHA-tagged image.
- Canary has no Buildx/cache and no `packages: write`.
- Publisher remains gated by `needs: [static, container-canary]`.
- Publisher alone owns Buildx, GHA cache, GHCR login, and `packages: write`.

## Evidence
- Duplicate language scan: ~12.6s on Ubuntu; 25.4s wall on NOAR.
- Warm-cache canary experiment was rejected: Buildx build alone took 115s.
- RED→GREEN contracts pin the corrected architecture and scanner boundary.
