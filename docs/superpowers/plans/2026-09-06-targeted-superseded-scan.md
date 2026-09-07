# PR49 — Targeted superseded identity test

## Goal
Reduce static CI time without changing production validation behavior.

## Scope
- Change `tests/test_validate_repo_static_fstrings.py` and `docs/superpowers/plans/2026-09-06-targeted-superseded-scan.md`.
- Keep the full repository contract test unchanged.
- Replace one redundant `validate(ROOT)` call with the exact scanner that the test is asserting.

## Safety contract
- The registered-fixture test must call `validate_superseded_identity_locations`.
- That test must not call the global `validate` function.
- The full `tests/test_repo_contract.py` integration remains the proof that `validate(ROOT)` accepts the checkout.

## TDD evidence
- RED: AST contract fails while the target method still calls `validate`.
- GREEN: target method calls only the superseded-identity scanner.
- Baseline target test: 35.1 s on NOAR.
- Optimized target test: 1.7 s on NOAR.

## Expected CI effect
Ubuntu saving is expected to be smaller than NOAR but still material because the global validator is no longer executed twice for the same checkout.

## Review hardening
The anti-regression contract uses an exact allowlist of call terminals for the optimized test. Direct calls, attribute calls, import aliases, and local aliases such as `full_validate = validate` are rejected unless explicitly reviewed and added to the allowlist.

## Exact call-shape guard
The optimized test must make exactly one direct call `validate_superseded_identity_locations(ROOT, errors)`, with no keyword arguments. The scanner name and `ROOT` cannot be rebound locally, `errors` must be initialized exactly once as an empty list, and local imports are forbidden in that test. The imported scanner symbol is also checked by object identity against `scripts.validate_repo.validate_superseded_identity_locations`.
