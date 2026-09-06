# Static Validation Deduplication Design

## Goal

Reduce GitHub Actions time in the required `static` job without reducing repository validation coverage.

## Observed duplication

On the post-merge `main` run for PR #45, `static` took 302 seconds. The standalone `Validate repository contract` step took 25 seconds, followed by `python3 -m unittest discover -s tests -v`.

The discovered suite includes `tests/test_repo_contract.py`, whose `RepoContractTest.test_contract_accepts_repository_scaffold` calls `validate(root)` against the real repository and therefore exercises the same repository contract in the same job.

## Approved change

Remove only the standalone `python3 scripts/validate_repo.py` step from `.github/workflows/scaffold-validation.yml`.

Add a structural regression proving that `static` still runs the complete unittest discovery and that the repository-contract test remains present and calls the real validator.

## Invariants

- Preserve the required check name `static` exactly.
- Preserve the 14 protected-main required checks and `GENOMA protected main` ruleset behavior.
- Preserve the classifier, draft gate, `container-canary`, reusable Four-plane audit dependency, MCP validation, shell checks, WGS trust-boundary checks, supply-chain verification elsewhere, and human-only merge.
- Do not change scientific, policy, normative, production-witness, publication, or application code.
- Keep failure behavior fail closed: if the unittest suite or repository-contract regression fails, `static` fails.
- Use an isolated branch and draft-first PR; never auto-merge.

## Expected effect

Based on the measured PR #45 and post-merge #45 executions, the removed duplicate step costs about 25–39 runner seconds whenever `static` executes. Realized savings must be measured after merge rather than inferred from this estimate.
