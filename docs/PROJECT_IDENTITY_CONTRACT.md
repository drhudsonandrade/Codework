# OmniGenis Project Identity Contract

## Purpose

`config/project_identity.json` is the canonical target identity registry for the Phase 2 internal-name migration. It does not dynamically configure every runtime consumer; repository guards compare active literals against the approved contract during later cutover phases.

## Canonical repository authority

The canonical repository identity is owner-neutral: repository ID `1212760346` and repository name `OmniGenis`. Provider-qualified repository names are resolved only at runtime when required and are never persisted as canonical identity. Canonical future runner names are `omnigenis-runner-01` and `omnigenis-runner-02`.

## Phase 2A behavior

Phase 2A changes no runtime identity. `config/legacy_identity_ledger.json` records reviewed active legacy-identity compatibility occurrences. Counts may decrease but may not increase, and an unclassified occurrence fails `scripts/validate_repo.py`.

## Transitional historical scope

During Phase 2A only, migration specifications, implementation plans, evidence, checkpoints, and `docs/history/` are outside the active compatibility ledger. Phase 2D replaces these broad transitional exclusions with an exact final historical/provenance allowlist.

## Scan scope

The official identity guard scans Git-tracked files only. Local untracked files do not affect the repository gate. Phase 2A requires the exact reviewed `scan_suffixes` and `historical_prefixes` values recorded in the ledger; a weakened or broadened scope fails closed. A tracked file selected by that scope must be valid UTF-8 or the scan fails closed.


## Editing rule

Do not update the ledger to make a failing new legacy occurrence pass. First determine whether the occurrence is an approved migration compatibility need. A new runtime identity requires a design/spec change; historical evidence remains immutable.

## Phase boundaries

2A defines and guards identities. 2B cuts repository-controlled runtime/build identities over. 2C migrates live self-hosted runners. 2D removes temporary compatibility and seals zero active legacy identity.

## Phase 2B status

Phase 2C routes trusted protected-main jobs through the canonical `omnigenis-isolated` pool. The live runners remain dual-labeled until a real post-merge protected-main canary succeeds; legacy labels are rollback-only during that transition.

`OMNIGENIS_CODERABBIT_BIN_DIR` is canonical. The legacy CodeRabbit bin-directory variable remains a deprecated compatibility fallback through Phase 2D; conflicting canonical and legacy values fail closed.

Historical repository URLs and archived runtime bundle names remain provenance records. Historical GHCR package state is not claimed as inspected when package-read capability is unavailable.
