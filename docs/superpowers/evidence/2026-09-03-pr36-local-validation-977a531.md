# PR #36 Local Validation Evidence — 977a531

**Validated code SHA:** `977a531e02b412488b01ade9c40597d28d355147`
**Immutable PR base SHA:** `67b3133b6dd881a120ebee2edd9435458674fef8`
**Host:** NOAR Windows VM
**Log path:** `%USERPROFILE%\Documents\Codework-validation-977a531.log`
**Log SHA-256:** `3903E534CAB45908B52ED4C09DB3564EA0C5E1B4BAB0EECB4DB9BA447B3FD829`

The verification log is external to the repository so the run cannot dirty the validated checkout. The complete log bytes are integrity-pinned above.

## Verified commands and results

1. `python scripts/validate_repo.py` — exit `0`.
2. `python scripts/verify_supply_chain_lock.py` — exit `0`.
3. `python -m unittest tests.test_ci_optimization_contract tests.test_workflow_contracts tests.test_codacy_workflow_security tests.test_repo_contract -v` — `37` tests, `0` failures/errors.
4. `bash tests/test_ci_changed_paths.sh` — exit `0`; null-base, non-null diff, and deletion paths exercised.
5. `node --test tests/test_codacy_pr_comment.js` — `18` passed, `0` failed.
6. `npm run build` in `mcp/` — exit `0`.
7. `bash -n scripts/*.sh tests/test_wgs_align_or_stage.sh tests/test_ci_changed_paths.sh` — exit `0`.
8. `python -m py_compile scripts/ci_change_classifier.py` — exit `0`.
9. Classifier source scan — no `subprocess` reference in the implementation.
10. `git diff --check 67b3133b6dd881a120ebee2edd9435458674fef8...HEAD` — exit `0`.
11. `git status --porcelain` — empty; validated checkout clean.

The external log terminates with `WORKTREE_CLEAN=true` and `VERIFICATION_EXIT=0`.

## Scope and limitations

Docker is not installed on NOAR. Linux/container runtime checks are therefore not claimed as locally executed; GitHub Actions remains authoritative for those checks on the final pushed SHA.

The native-Windows complete repository suite has known POSIX-specific baseline failures documented in the project checkpoint. This evidence claims only the commands above.

## Review-driven coverage added

- `scripts/ci_changed_paths.sh` centralizes null/non-null `push` path preparation.
- `tests/test_ci_changed_paths.sh` executes normal diff, null-base full-tree, and deletion behavior in a temporary Git repository.
- Pull-request trust guards still compute their initial diff inline and force the affected heavy gates if the helper, classifier, or controlling workflow changes.
- Workflow test parsing is shared through `tests/workflow_test_utils.py`.
