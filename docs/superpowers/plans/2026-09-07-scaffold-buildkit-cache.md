# PR50 — Share BuildKit cache between canary and GHCR publish

## Goal
Reduce GitHub Actions time on main without weakening the canary or publication gates.

## Scope
- Update `.github/workflows/scaffold-validation.yml`.
- Add a CI optimization contract in `tests/test_ci_optimization_contract.py`.
- Reuse only actions already pinned in `locks/actions-lock.json`.

## Design
- `container-canary` uses pinned `docker/setup-buildx-action` with the docker-container driver.
- The canary uses pinned `docker/build-push-action`, `load: true`, and the existing local SHA tag.
- The canary only restores `type=gha` cache under `codework-genome-scaffold-v1`; it never exports cache.
- `publish-ghcr` restores that cache and, only after `static` + canary pass, refreshes it with `mode=min` and `ignore-error=true`.
- `publish-ghcr` remains the only job with `packages: write`; cache availability is not a correctness gate.
- Publication still waits for both `static` and `container-canary`.

## Safety invariants
- No image is pushed before the canary and static jobs pass.
- PR canary runs do not write the shared cache.
- The canary still executes `/opt/codework/scripts/run_canary.sh` from the locally loaded image.
- Immutable GHCR digest recording is unchanged.
- No new third-party action identity is introduced.
