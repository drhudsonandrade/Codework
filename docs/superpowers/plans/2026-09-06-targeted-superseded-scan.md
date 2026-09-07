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
- RED: the anti-regression contract failed while the target method still called `validate`.
- GREEN: the target method calls only the superseded-identity scanner, and the runtime guard proves the full validator is not invoked.
- Baseline target test: 35.1 s on NOAR.
- Optimized target test: 1.7 s on NOAR.

## Expected CI effect
Ubuntu saving is expected to be smaller than NOAR but still material because the global validator is no longer executed twice for the same checkout.

## Review hardening
The final anti-regression contract is runtime-based rather than a static AST allowlist. It executes the real optimized test while blocking the imported, module-level, and `self.validate` global-validator paths with mocks.

## Runtime call guard
The imported targeted scanner is wrapped with a spy and must be called exactly once. Its first positional argument must be `ROOT`, its second positional argument must be a list, and it must receive no keyword arguments. The module-qualified scanner path must remain unused, while every guarded full-validator path must remain uncalled.
