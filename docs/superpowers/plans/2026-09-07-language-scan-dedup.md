# PR51 — Deduplicate repository language scan

## Goal
Reduce static CI time without weakening the English-first language policy.

## Scope
- Remove the redundant full-checkout language baseline test.
- Add an anti-regression contract in the CI optimization suite.
- Keep production validator code unchanged.

## Safety
- `tests/test_repo_contract.py` still executes `validator.validate(root)` on the full checkout.
- `scripts/validate_repo.py` still invokes `validate_language_policy(root, errors)`.
- Scanner unit tests, baseline comparison tests, and provenance tests remain unchanged.
- No workflow, ruleset, lock, or permission changes.

## Evidence
- Ubuntu baseline for the redundant test: about 12.6 seconds.
- NOAR isolated baseline: 25.4 seconds wall time.
- RED: anti-regression contract detected `scan_repository(ROOT, ...)`.
- GREEN: no duplicate full-checkout scan remains in language tests.
