## Scope

Describe one change and why it is necessary.

## Affected contracts/architecture

- [ ] Policy Control Plane
- [ ] Scientific Data Plane
- [ ] Evidence Plane
- [ ] Audit Plane
- [ ] Ruleset/manifest/hash
- [ ] MCP/adapters
- [ ] None of the above

## Intentionally changed files

List the main paths and justify broad changes.

## Local evidence

Commands actually executed and their results:

```text
<paste only real results; do not write PASS unless it was actually executed>
```

- [ ] `python3 scripts/validate_repo.py`
- [ ] `python3 scripts/verify_supply_chain_lock.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] component-specific tests
- [ ] pre-PR CodeRabbit CLI, if available/authenticated

## CodeRabbit

- [ ] No known blocking finding in the pre-PR review, when executed
- [ ] Wait for the automatic CodeRabbit GitHub App review after opening the PR
- [ ] Blocking findings will be corrected on this branch and reviewed again

## CI / GitHub Actions

During implementation, keep the PR in Draft and run corrections and validations locally.
To avoid iterative runner consumption, do not wait for required GitHub Actions checks while
the PR is in Draft.

- [ ] Confirm the exact HEAD is locally validated before the final round
- [ ] Mark the PR Ready for Review only when the exact HEAD is ready for final validation
- [ ] After Ready for Review, wait for all required GitHub Actions checks on the exact HEAD
- [ ] Do not use a nonexistent CI result as evidence

## Canonical change

Does this PR change the ruleset version/date/hash/name, manifest, sealed transport,
attestation, or evidence contract?

**Answer:** Yes / No

If yes, describe the coordinated migration and every updated consumer.

## Known limitations

List validations that could not be executed and why.

## Merge

- [ ] No auto-merge
- [ ] Manual merge only after CodeRabbit + CI + all other required checks
- [ ] If needed, use the owner's PR-only bypass only at the approval layer; never bypass Security & CI
