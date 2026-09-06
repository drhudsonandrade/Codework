# Four-Plane Audit Static Dependency Design

**Date:** 2026-09-05
**Status:** Written spec approved; implementation complete; pending validation/review
**Repository:** `drhudsonandrade/Codework`

## Problem

`GENOMA v0.8 four-plane audit` currently runs independently on applicable pull requests and pushes to `main`.
The heavy `audit` job recently consumed about 366 seconds per run:

- repository and supply-chain contracts: about 40 seconds;
- seven architecture test modules: about 279 seconds;
- the four-plane audit itself: about 39 seconds;
- setup, evidence surfacing, artifact upload and teardown: a few seconds.

The required `static` job already executes `scripts/validate_repo.py` and the complete Python test suite with
`python3 -m unittest discover -s tests -v`. The audit workflow therefore repeats substantial work already
proven by a protected-main required check.
## Goals

1. Preserve `static` as the existing required check with the same name and ruleset semantics.
2. Prevent a valid four-plane audit artifact from being produced unless `static` succeeds for the same SHA.
3. Remove duplicated repository/supply-chain validation and duplicated architecture unit-test execution from the audit workflow.
4. Preserve the four-plane audit's own fail-closed checks, artifact contents, SHA binding and retention.
5. Reuse the existing draft-first and Markdown-safe classifier instead of allocating a second classifier runner.
6. Reduce GitHub Actions runner consumption without weakening scientific, security or governance gates.

## Non-goals

- Do not alter the 14 protected-main required checks.
- Do not rename, weaken, bypass or make `static` optional.
- Do not change `container-canary`, policy checks, Production Witness or merge policy.
- Do not broaden Markdown-safe skipping or add new path filters.
- Do not change `scripts/genoma_audit.py` audit semantics.
- Do not grant POST-DEPLOYMENT PASS; Production Witness remains the only authority for that state.
## Architecture

`scaffold-validation.yml` becomes the orchestration boundary for both required static validation and the four-plane audit.
The existing `changes` job remains the single Markdown-safe classifier for this validation family.

Applicable execution becomes:

`changes -> static -> four-plane-audit`

The four-plane audit is represented as a reusable workflow call from `scaffold-validation.yml`.
The caller job must declare `needs: [changes, static]` and may run only when all of the following are true:

- the PR is not Draft, or the event is not a PR;
- `changes.result == 'success'`;
- `changes.outputs.validation_required == 'true'`;
- `static.result == 'success'`.

If any prerequisite is false, the audit workflow is not invoked and no audit evidence package is produced.
## Reusable audit workflow

`.github/workflows/genoma-audit.yml` is converted from an independently triggered workflow into a reusable workflow exposed through `workflow_call`.
It must not retain direct `pull_request`, `push` or standalone `workflow_dispatch` entrypoints.

Manual full validation remains available through the existing `workflow_dispatch` on `Genome runtime scaffold`.
That manual path also executes `changes`, then `static`, and only then the reusable audit.

The reusable workflow keeps the audit runner and evidence-producing steps that are unique to the audit:

- checkout of the exact caller SHA;
- Python 3.12 setup;
- `python3 scripts/genoma_audit.py --allow-template-sealed-only --output audit.json`;
- explicit `verify_template_store.py --allow-sealed-only` output for `template-store-verification.json`;
- artifact upload named `genoma-v0.8-audit-${{ github.sha }}` with 365-day retention.

The reusable workflow must not repeat the seven architecture unit-test modules or the standalone repository/supply-chain contract step.
## Fail-closed semantics

The dependency on `static` is a safety boundary, not a scheduling optimization only.

- If the classifier fails or is cancelled, `static` remains responsible for surfacing the failure and the audit is not invoked.
- If `static` fails or is cancelled, the audit is not invoked and no new audit artifact exists for that SHA.
- If `static` succeeds but the audit core fails, the audit job fails and any partial artifact follows the existing `if: always()` evidence behavior; it cannot be interpreted as PASS.
- Safe Markdown-only changes continue to skip both `static` heavy validation and the audit according to the already-approved classifier contract.
- A skipped audit never means audit PASS and never changes POST-DEPLOYMENT status.

The artifact remains bound to `${{ github.sha }}`. No artifact from an older SHA may satisfy a newer commit.

## Relationship to protected main

`static` remains a required context in `GENOMA protected main` with strict status-check policy and no bypass.
This design does not add the four-plane audit as a required context and does not remove any existing required context.
The audit consumes the successful `static` result as a prerequisite; it does not replace or reinterpret that result.
## Test strategy

Implementation must use TDD and add executable workflow contracts that prove the orchestration boundary.
Required regression coverage includes:

1. `genoma-audit.yml` is reusable-only for automated use and has no direct PR/push trigger.
2. The scaffold workflow invokes the reusable audit only after `static` and the classifier.
3. Removing `static.result == 'success'` from the caller condition makes the contract fail.
4. The audit caller cannot run when `validation_required` is false or when classification fails.
5. `static` keeps its exact job name, test-suite command and repository validation command.
6. The reusable audit retains `genoma_audit.py`, template verification, artifact SHA naming and 365-day retention.
7. Duplicated architecture unit-test and standalone repository/supply-chain steps are absent from the reusable audit.
8. Draft-first job guards remain intact.

Fresh local validation must include workflow contracts, `validate_repo.py`, supply-chain verification, language guard, shell syntax and diff checks before any push.
## Expected cost effect

The latest measured audit job spent about 40 seconds on duplicated contracts and 279 seconds on duplicated architecture tests.
The audit core itself took about 39 seconds.

Removing those duplicate workflow steps is expected to save roughly 5 minutes 20 seconds per applicable audit execution.
For a typical applicable PR plus its merge-to-main push, the expected reduction is roughly 10 minutes 40 seconds of Ubuntu runner time.
The actual saving will be measured after merge using GitHub job timestamps; no fixed percentage is assumed in advance.

## Rollback

Rollback restores the previous independent audit workflow and its duplicated pre-audit validation steps from version control.
Rollback must not disable `static`, remove required checks, alter protected-main bypass policy or weaken audit checks.

A rollback is required if any of the following is observed:

- an audit artifact is produced for a SHA whose `static` job did not succeed;
- workflow-call context changes the SHA or artifact naming semantics;
- manual validation can bypass `static`;
- the reusable audit loses existing fail-closed behavior or evidence retention.
## Intended implementation scope

Expected files are limited to:

- `.github/workflows/scaffold-validation.yml`;
- `.github/workflows/genoma-audit.yml`;
- workflow/CI contract tests, primarily `tests/test_ci_optimization_contract.py` and existing workflow-contract coverage;
- this specification and the implementation plan generated after written-spec approval.

No application, scientific pipeline, policy engine, evidence adapter, normative artifact, runtime container or ruleset change belongs in this PR.

## Acceptance criteria

The implementation is acceptable only when the exact final SHA proves all of the following:

- `static` remains required and passes;
- the audit runner starts only after successful `static` for applicable non-Markdown changes;
- safe Markdown behavior remains unchanged;
- no direct PR/push/manual path can invoke the reusable audit without the scaffold prerequisite;
- audit evidence and SHA naming remain intact;
- protected-main rules remain unchanged;
- external reviewers have no unresolved valid findings;
- merge remains human-only.
