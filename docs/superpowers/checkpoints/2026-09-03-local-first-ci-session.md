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
- Result: **22 tests, PASS**.
- `python scripts/validate_repo.py`
- Result: **FAIL on Windows only during JSON decoding**.

Root cause confirmed:

- `scripts/validate_repo.py` uses `path.read_text()` without an explicit encoding in the repository-wide JSON validation loop.
- Windows default `charmap` fails on tracked UTF-8 JSON bytes.
- The same file read with `encoding='utf-8'` parses successfully with `json.loads()`.
- Reproduction confirmed with `config/case_dossier.example.json`.

No workflow production code has been changed yet.

## Workflow optimization findings

Targeted already: NGS runtime gate, SNP-array, visual QA, PR30 regressions.

Broad PR execution still present in:

- `fallow.yml`
- `genoma-audit.yml`
- `genoma-policy-engine.yml` (PR trigger broad; main push already path-filtered)
- `scaffold-validation.yml`

Implemented optimization direction:

- use PR-number concurrency groups and unique `github.run_id` groups for non-PR runs;
- narrow Fallow to explicit JavaScript/TypeScript and required configuration surfaces;
- keep potentially protected policy/scaffold PR workflows unfiltered and make job-level classifiers fail closed;
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

Implemented and locally committed:

- deterministic UTF-8 JSON scanning in `scripts/validate_repo.py`, with RED/GREEN regression coverage;
- concurrency cancellation on eight PR validation workflows;
- narrow Fallow PR path filtering;
- Markdown-only skipping for the non-required four-plane audit;
- fail-closed job-level relevance classifier for policy checks, while Gitleaks remains unconditional;
- fail-closed Markdown-only classifier for `static` and `container-canary` without suppressing their check names;
- structural CI regression suite protecting triggers, job names, and scope semantics.

Executed results:

- `python scripts/validate_repo.py`: PASS.
- `python scripts/verify_supply_chain_lock.py`: PASS.
- workflow/repository focused Python tests: 32 tests, PASS.
- workflow structural block: 27 tests, PASS.
- `node --test tests/test_codacy_pr_comment.js`: 18 tests, PASS.
- Git for Windows Bash syntax check: PASS.
- `git diff --check main...HEAD`: PASS.

Full-suite comparison on the same NOAR Windows environment, same isolated venv, and `PYTHONUTF8=1`:

- `main`: 886 tests; 19 failures; 35 errors; 3 skipped.
- implementation branch: 892 tests; 19 failures; 35 errors; 3 skipped.
- Net: six new tests execute and pass; the pre-existing failure/error counts do not increase.

The pinned reporting dependencies were installed in the external local environment `C:\Users\noaruser\Documents\Codework-local-venv`, not inside the repository. This reduced raw environment errors from 70 to 35.

MCP local evidence:

- `npm ci --ignore-scripts`: completed; 0 vulnerabilities reported.
- TypeScript build: PASS.
- MCP Node suite on Windows: 35 pass, 9 fail, 1 skipped. The failures are POSIX/Linux assumptions (for example `/srv/...` path expectations, POSIX file modes, and Unix process spawning). MCP source code was not changed in this CI optimization.

Local Docker: NÃO DISPONÍVEL (`docker` executable not installed). Therefore Linux/container checks remain authoritative in GitHub Actions for the final pushed SHA, per the approved architecture.

No claim is made that the complete Windows test suite passes. The evidence supports that this branch adds no new full-suite failure/error count relative to the local `main` baseline and that all tests directly added/affected by this CI optimization pass locally.
