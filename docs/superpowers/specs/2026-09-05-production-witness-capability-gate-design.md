# Production Witness Capability Gate Design

Date: 2026-09-05
Status: approved design, pending implementation plan
Base commit: `8788e49444e79fe4c91a108de86abb0bd1617a8f`

## 1. Problem

`GENOMA Production Witness` currently runs on every push to `main`.
The current platform cannot provide an authenticated machine-readable read of the authoritative persistent Project Instructions surface.
Accordingly, `PROJECT_BOOTSTRAP_INSTALLED` remains false and POST-DEPLOYMENT remains fail-closed.

Recent `main` witness runs repeatedly prove the scientific runtime path while failing only the external installation criterion.
The run after PR #42 executed all 15 section-260 scenarios with `passed=15`, `total=15`, and `critical_failures=0`, then correctly ended `POST-DEPLOYMENT PENDENTE` because `project_bootstrap_installed=false`.

The workflow therefore allocates a GitHub-hosted runner on every `main` commit even when a PASS is operationally impossible.

## 2. Goal and non-goals

Goal: avoid runner allocation while the external production-witness capability is unavailable, without weakening evidence semantics or changing what constitutes POST-DEPLOYMENT PASS.

Non-goals:
- do not remove the `push` trigger for `main`;
- do not add `paths` filters;
- do not convert absence of evidence into PASS;
- do not alter the 15 live scenarios, hashes, container hardening, evidence package, or publisher integrity;
- do not alter protected-main required checks;
- do not add a new manual witness mechanism in this change.

## 3. Architecture

The workflow remains subscribed to every `main` push so each `main` SHA still has a Production Witness workflow run associated with it.

The heavy `witness` job receives one job-level capability predicate:

```yaml
if: ${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}
```

The guard must be evaluated at the job boundary, before `runs-on` allocates a GitHub-hosted runner. A step-level guard is not acceptable because the runner would already have been allocated.

`GENOMA_PRODUCTION_WITNESS_ENABLED` is an operational capability flag, not evidence. The repository does not infer it from the owner-exported snapshot, ruleset state, test results, or prior witness output.

Exact semantics:
- variable absent: witness job skipped;
- variable present with any value other than exact string `true`: witness job skipped;
- variable equal to exact string `true`: witness job executes the existing full workflow;
- skipped witness: POST-DEPLOYMENT remains `PENDENTE`; it is never interpreted as PASS or failure evidence;
- executed witness: existing fail-closed verdict rules remain authoritative.

## 4. Evidence and publisher behavior

No evidence artifact is fabricated for a skipped witness. There is no `witness.json`, `failure.json`, or synthetic section-260 result for a run that never executed.

`publish-witness` keeps `needs: witness`. Therefore it cannot publish when the witness job is skipped or unsuccessful. Publication continues to require a real PASS witness bound to the exact `main` SHA.

The append-only `audit-evidence` branch contract, restricted deploy key, SHA binding, byte comparison, and `latest.json` checks remain unchanged.

## 5. Operational lifecycle

The default repository state is unarmed. This matches the current documented reality: the authoritative Project Instructions surface is not machine-readable and authenticated by the runtime.

The repository variable may be set to exact `true` only when the external capability needed to establish `PROJECT_BOOTSTRAP_INSTALLED` is actually available for the intended witness execution.

Enabling the variable does not grant PASS. It only permits the existing independent witness to allocate a runner and evaluate the full evidence chain.

Disabling or removing the variable restores the no-runner state without changing code, hashes, rulesets, or historical evidence.

## 6. Required implementation surface

Expected implementation files:
- `.github/workflows/genoma-production-witness.yml` — add the exact job-level capability guard only;
- `tests/test_workflow_contracts.py` — enforce main-push coverage plus exact job-level guard and mutation resistance;
- `scripts/validate_repo.py` — fail closed if the witness guard is missing, weakened, or moved away from the job boundary;
- `docs/PRODUCTION_CEREMONY.md` — document capability-gated execution and the meaning of skipped runs.

No other production workflow should be modified by this change.

## 7. Validation contract

TDD must demonstrate RED before the workflow guard is added, then GREEN after the minimal implementation.

The regression suite must prove all of the following:
- `push: branches: [main]` remains present;
- the push block still has no `paths:` filter;
- the `witness` job has the exact repository-variable predicate;
- removing the predicate fails the contract;
- weakening the comparison or accepting truthy alternatives fails the contract;
- placing the predicate only on a step fails the contract;
- `publish-witness` still depends on `witness`;
- current live-smoke CLI, evidence, deploy-key, and full-history contracts remain unchanged.

## 8. Failure handling and state interpretation

A skipped capability-gated run is an operational non-execution, not a successful production witness and not a replacement failure record.

Repository documentation and PR evidence must use `POST-DEPLOYMENT PENDENTE` while no successful exact-SHA witness exists. No check, script, report, or reviewer may infer `PROJECT_BOOTSTRAP_INSTALLED=true` from the enable variable itself.

If the variable is `true` and the witness executes, any existing runtime, evidence, bootstrap, integrity, or publication failure remains a real failure. The capability gate must never mask a failure after execution has begun.

## 9. Cost effect

The latest post-merge witness consumed roughly 46 seconds of a Linux GitHub-hosted runner before failing on the unavailable external bootstrap condition.

While the capability flag is absent or false, the heavy witness job should be skipped before runner allocation. The practical saving is approximately one billed Linux runner-minute per `main` push under the current run duration and billing granularity, subject to GitHub billing rules.

## 10. Rollback

Operational rollback does not require a code change: set `GENOMA_PRODUCTION_WITNESS_ENABLED=true` to restore full witness execution on subsequent eligible `main` pushes.

Code rollback, if needed, is a normal reviewed PR that removes the capability guard and its regression contract. Historical witness artifacts and the `audit-evidence` branch are never rewritten as part of rollback.

## 11. Local baseline limitation

On the exact base commit, the focused `tests.test_workflow_contracts` surface is usable, but two tests in `tests.test_post_merge_bootstrap_governance` fail on the NOAR Windows checkout because the committed bootstrap attestation digest does not match the observed local bytes before the tested semantic mismatch is reached.

This pre-existing Windows-local baseline failure must not be attributed to the capability gate and must not be hidden. The implementation PR must report focused passing evidence and use Linux GitHub CI as the authoritative complete validation for the exact final SHA.

## 12. Acceptance criteria

The change is acceptable only when:
- the exact guard is enforced at job level;
- draft PR behavior does not allocate repository-owned validation runners before Ready for Review;
- the final exact HEAD passes applicable required checks and external reviewers;
- no review thread remains blocking;
- disabled witness runs cannot be described as POST-DEPLOYMENT PASS;
- enabled witness runs preserve the current 15/15, evidence, and fail-closed requirements;
- merge remains human-only with auto-merge disabled.
