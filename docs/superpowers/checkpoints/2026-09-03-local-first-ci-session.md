# Local-First CI Session Checkpoint

**Date:** 2026-09-03
**Repository:** `drhudsonandrade/Codework`
**Local path:** `C:\Users\noaruser\Documents\Codework`
**Branch:** `ci/local-first-actions-optimization`
**Last committed design:** `3f37ea1 docs: design local-first targeted CI architecture`

## Completed

- GitHub CLI installed and authenticated as `drhudsonandrade`.
- Codex CLI installed but intentionally not used for this architecture.
- Remote Desktop Commander access expanded to Desktop, Documents, and Downloads.
- `Codework` cloned locally from GitHub.
- VS Code opened on the local repository.
- Local-first CI architecture design written and committed.
- Current workflow inventory reviewed.
- Live GitHub ruleset checked: currently requires `Codacy Static Code Analysis`.

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

Planned optimization:

- add PR-safe concurrency/cancellation to validation workflows;
- narrow Fallow to JavaScript/TypeScript/MCP-related changes;
- mirror policy-engine main `paths` onto PRs;
- skip audit/scaffold for documentation-only changes;
- preserve production witness, production ceremony, reference foundry, canonical names, hashes, and fail-closed behavior.

## Exact resume point

1. Add a failing regression test proving repository JSON validation must decode UTF-8 explicitly on Windows.
2. Run the test and confirm RED.
3. Change only the repository-wide JSON `read_text()` call in `scripts/validate_repo.py` to `read_text(encoding='utf-8')`.
4. Re-run the focused test and `scripts/validate_repo.py`.
5. Only after the local baseline is green, write the CI optimization implementation plan and begin workflow TDD changes.
6. Keep development local; do not push iterative fixes.
7. Push only a coherent validated block, then open a PR for CodeRabbit/Codacy/GitHub Actions.

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
