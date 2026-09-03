# Local-First CI Session Checkpoint

**Date:** 2026-09-03
**Repository:** `drhudsonandrade/Codework`
**Local path:** `C:\Users\noaruser\Documents\Codework`
**Branch:** `ci/local-first-actions-optimization`
**Last committed design:** local-first targeted CI architecture

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
