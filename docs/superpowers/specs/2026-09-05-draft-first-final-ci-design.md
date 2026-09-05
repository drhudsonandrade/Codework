# Draft-First Final CI Architecture Design

**Date:** 2026-09-05
**Status:** Approved for implementation
**Repository:** `drhudsonandrade/Codework`

## Objective

Reduce GitHub Actions runner consumption during iterative development while preserving exact-head CI, external review, protected `main`, and human-only merge.

The development loop becomes:

`edit/test on NOAR -> batch coherent local changes -> push to draft PR -> no PR runner allocation -> local fixes -> mark ready -> one final applicable CI pass -> human merge`

## Core decision

Pull-request validation workflows remain registered on GitHub but runner-consuming jobs do not execute while the pull request is a draft. Each workflow explicitly subscribes to `ready_for_review`, so changing the PR from draft to ready retriggers validation for the exact current HEAD.

This design deliberately does not depend on `[skip ci]`. Native skip directives can leave required checks absent or pending and are unnecessary once draft jobs are gated before runner allocation.

## Scope

The draft gate applies to runner-consuming PR jobs in:

- `fallow.yml`
- `genoma-audit.yml`
- `genoma-ngs-runtime-gate.yml`
- `genoma-policy-engine.yml`
- `genoma-snp-array.yml`
- `genoma-visual-qa-candidates.yml`
- `pr30-regressions.yml`
- `scaffold-validation.yml`

Manual-only production workflows and `push` validation on protected `main` are unchanged.

## Required behavior

Every affected `pull_request` trigger includes `ready_for_review` in addition to the normal opened/synchronize/reopened events.

Every PR job capable of allocating a runner must include this fail-closed draft condition:

```yaml
${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}
```

Existing job-specific predicates are combined with the draft condition; they are not weakened or replaced. Jobs used only by `workflow_dispatch` or protected-main publishing retain their existing semantics.

## Safety properties

- Draft pushes do not allocate GitHub-hosted runners for the affected validation jobs.
- Marking the exact final HEAD ready for review starts applicable CI without another code change.
- Required check names do not change.
- Existing path classifiers, path filters, scientific gates, hashes, locks, evidence semantics, and fail-closed logic do not change.
- `push` validation for `main` remains authoritative after merge.
- External GitHub Apps may still review draft PRs; they do not consume repository GitHub Actions minutes.
- Auto-merge remains prohibited.

## Operator workflow

Open implementation PRs as drafts. Run targeted tests and repository validation on NOAR before each remote checkpoint. Batch fixes locally instead of pushing each small correction. When the branch is locally ready, push the coherent final block and mark the PR ready. If review finds a defect, return the PR to draft before the next implementation push, fix and validate locally, then mark ready again for exact-head revalidation.

## Success criteria

Structural regression tests prove all affected workflows retrigger on `ready_for_review` and gate runner jobs while draft. Local repository validation remains green. A real draft PR demonstrates skipped runner jobs before the PR is marked ready; the same exact HEAD then receives the full applicable CI after `ready_for_review`.
