# PR49 — Targeted superseded identity test

## Goal
Reduce static CI time without changing production validation behavior.

## Scope
- Change only `tests/test_validate_repo_static_fstrings.py`.
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
