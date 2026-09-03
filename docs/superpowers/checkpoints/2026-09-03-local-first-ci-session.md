# Local-First CI Session Checkpoint

**Date:** 2026-09-03
**Repository:** `drhudsonandrade/Codework`
**Local path:** `%USERPROFILE%\Documents\Codework`
**Branch:** `ci/local-first-actions-optimization-impl`
**Last committed design:** `3f37ea1 docs: design local-first targeted CI architecture`

## Completed

- GitHub CLI installed and authenticated as `drhudsonandrade`.
- Codex CLI installed but intentionally not used for this architecture.
- Remote Desktop Commander access expanded to Desktop, Documents, and Downloads.
- `Codework` cloned locally from GitHub.
- VS Code opened on the local repository.
- Local-first CI architecture design written and committed.
- Current workflow inventory reviewed.
- GitHub governance was inspected from both the live ruleset API and the tracked desired-state file; the live query must be repeated before merge because enforcement can change independently of repository documentation.

## Baseline evidence

Executed locally on NOAR:

- `python -m unittest tests.test_workflow_contracts tests.test_codacy_workflow_security -v`
- Historical pre-implementation result recorded before the SHA-bound evidence workflow; it is not used as final merge evidence.
- `python scripts/validate_repo.py`
- Result: **FAIL on Windows only during JSON decoding**.

Root cause confirmed:

- `scripts/validate_repo.py` uses `path.read_text()` without an explicit encoding in the repository-wide JSON validation loop.
- Windows default `charmap` fails on tracked UTF-8 JSON bytes.
- The same file read with `encoding='utf-8'` parses successfully with `json.loads()`.
- Reproduction confirmed with `config/case_dossier.example.json`.

At that baseline stage, no workflow production code had been changed yet.

## Original pre-implementation workflow findings

At the time of the baseline capture, NGS runtime gate, SNP-array, visual QA, and PR30 regressions were already targeted.

Broad PR execution at that stage was present in:

- `fallow.yml`
- `genoma-audit.yml`
- `genoma-policy-engine.yml` (PR trigger broad; main push already path-filtered)
- `scaffold-validation.yml`

Implemented optimization direction:

- use PR-number concurrency groups and unique `github.run_id` groups for non-PR runs;
- narrow Fallow to explicit JavaScript/TypeScript and required configuration surfaces;
- keep potentially protected policy PR and scaffold PR/main-push workflows unfiltered and make job-level classifiers fail closed;
- make policy rename-aware and include direct ruleset/classifier dependencies;
- skip audit/scaffold heavy jobs only for proven-safe Markdown additions/modifications with no deletions;
- preserve production witness, production ceremony, reference foundry, canonical names, hashes, and fail-closed behavior.

## Exact resume point

1. Finish the current review-fix batch locally on `ci/local-first-actions-optimization-impl` without another intermediate push.
2. Run the CI classifier behavioral/structural tests, repository validator, supply-chain verifier, Node regression, MCP TypeScript build, Bash syntax check, and `git diff --check`.
3. Commit the code/review fixes and record that exact code SHA.
4. Create a repository evidence note that records the exact validated SHA, commands, exit codes/test counts, and a SHA-256 of the local verification log.
5. Commit only that evidence/documentation update, then push the batch once to PR #36.
6. Re-read all review threads and final-sha checks; resolve only findings that are demonstrably fixed or obsolete.
7. Do not merge automatically. Final human merge approval remains mandatory.

No auto-merge. Manual human approval remains the final merge gate.

## Implementation validation — 2026-09-03

Current implementation branch: `ci/local-first-actions-optimization-impl`.

The review-hardened code was validated at exact SHA `595328650830206f3d6d6f5e0a2ea5fed6665ece`. Reproducible command lines, exit codes, test totals, scope limitations, the external log path, and the log SHA-256 are recorded in `docs/superpowers/evidence/2026-09-03-pr36-local-validation-5953286.md`.

That evidence records successful repository-contract and supply-chain commands, `35` focused Python tests with zero failures/errors, `18` Node regression tests with zero failures, the MCP TypeScript build, Bash syntax validation, `git diff --check`, and a clean worktree. Its external log is integrity-pinned by SHA-256 `0E882329AEF91A0B9C3EFA247C3330C19E617445543FE7AA652A2DD197FB4511`.

The evidence deliberately does not claim a complete native-Windows suite pass. Docker is not installed on NOAR, and Linux/container checks remain authoritative in GitHub Actions for the final pushed SHA.

## Emergency restart checkpoint — 2026-09-03 16:24 BRT

Machine restart expected within ~15 minutes. This section is a continuity checkpoint, not a final validation claim.

- Branch: `ci/local-first-actions-optimization-impl`.
- Remote PR: `#36`.
- Last remote/local HEAD before this checkpoint: `b1ca539c95e032709b3567ba95db31c4ac18364e`.
- Current uncommitted review-fix files: `genoma-audit.yml`, `genoma-policy-engine.yml`, `scaffold-validation.yml`, implementation plan/spec, `scripts/ci_change_classifier.py`, `tests/test_ci_optimization_contract.py`, and `tests/test_repo_contract.py`.
- The review hardening that followed `b1ca539` made `.github/governance/**` policy-relevant, moved checked rename-aware Git diff generation into the workflows, kept the shared Python classifier process-free, added null-push-base handling with `git ls-tree` of HEAD and no deletions, and strengthened the UTF-8 regression to reject non-UTF-8 encodings.
- The emergency pre-commit focused run is retained only as continuity history and is not used as merge evidence because the working tree was uncommitted.
- Post-restart validation supersedes the emergency partial run; final merge evidence must remain bound to a committed SHA and immutable log hash.
- The historical evidence now uses immutable PR base SHA `67b3133b6dd881a120ebee2edd9435458674fef8`; any later code change requires a fresh final-SHA validation log.
- Do not merge automatically. Final human approval remains required.

## PR #36 review follow-up — executable push contract

The CodeRabbit push-contract finding was addressed in code commit `977a531e02b412488b01ade9c40597d28d355147`.

- Added process-free shell helper `scripts/ci_changed_paths.sh` for trusted `main` push path preparation.
- Added executable regression `tests/test_ci_changed_paths.sh` covering non-null diff, null-base full HEAD tree, and deletion output.
- Pull-request workflows continue to compute the initial diff inline and force validation if the helper, classifier, or controlling workflow is modified.
- Extracted shared workflow job parser to `tests/workflow_test_utils.py` and consolidated job-gate assertions to address Codacy maintainability comments.
- SHA-bound validation evidence is stored at `docs/superpowers/evidence/2026-09-03-pr36-local-validation-977a531.md`.
- External log SHA-256: `3903E534CAB45908B52ED4C09DB3564EA0C5E1B4BAB0EECB4DB9BA447B3FD829`.
- Final merge remains manual; do not auto-merge.
