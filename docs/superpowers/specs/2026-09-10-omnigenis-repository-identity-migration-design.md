# OmniGenis Repository Identity Migration Design

**Date:** 2026-09-10
**Status:** Approved design, pre-implementation
**Repository before migration:** `repository_id=1212760346; historical_repository_name=Codework`
**Repository after migration:** `repository_id=1212760346; repository_name=OmniGenis`
**Baseline commit:** `ae3cd2166d1f6ed5875fdb8be7d82543c962ee54`

## 1. Objective

Rename the existing GitHub repository from `Codework` to `OmniGenis` without creating a replacement repository, while preserving repository history, Git object identity, branch governance, CI behavior, scientific reproducibility, and the canonical GENOMA v3.4 evidence contracts.

The migration is intentionally split into two phases. This specification authorizes only Phase 1: repository identity and active repository-address migration. Internal runtime identifiers that contain `codework` remain stable until a separately scoped Phase 2 proves each consumer and compatibility path.

## 2. Current verified state

At the design baseline, the GitHub repository ID is `1212760346`, the default branch is `main`, and `origin/main` points to `ae3cd2166d1f6ed5875fdb8be7d82543c962ee54`. There are no open pull requests.

The repository is currently public. The GitHub description already begins with `OmniGenis is a Scientific and versioned genomics platform...`, while the repository name remains `Codework`.

Two active GitHub rulesets govern `main`: `GENOMA approval gate` and `GENOMA protected main`. The protected-main ruleset requires the established static, container, policy, reviewer, and security status contexts. Phase 1 must not weaken or recreate those controls unless GitHub itself requires an identity refresh after the rename.

## 3. Repository inventory relevant to the rename

The baseline contains 415 tracked files. A deterministic scan found 46 tracked files containing `Codework`/`codework` references. These references are not equivalent and must not be changed by blind search-and-replace.

Phase 1 distinguishes four classes:

1. **Repository-address identity** — `repository_id=1212760346; historical_repository_name=Codework`, clone URLs, installation instructions, active repository links, and documentation that instructs operators to select the repository by name. These are Phase 1 migration targets.
2. **Current human-facing repository identity** — active headings or prose that call the repository `Codework` as its present name. These may become `OmniGenis` where they describe current state rather than history.
3. **Historical evidence** — old PR URLs, prior run URLs, checkpoints, audits, and documents whose truth depends on recording the name used at that time. These remain unchanged unless a new explanatory note is needed.
4. **Internal technical contracts** — `/opt/codework`, `/etc/codework`, `codework-genome`, `codework-isolated`, `codework-genome-mcp`, `codework-private-genome`, `codework-codex`, `CODEWORK_CODERABBIT_BIN_DIR`, and `codework/genome-runtime`. These are explicitly deferred to Phase 2.

## 4. Non-negotiable invariants

Phase 1 must preserve the existing Git repository rather than copying it to a new repository. Repository history, commits, branches, tags, issues, pull requests, releases, and the stable GitHub repository ID must remain associated with the same repository object.

The canonical GENOMA v3.4 identity is not renamed. `GENOMA-RULESET-v3.4`, the normative filename, version `v3.4`, formal date `2026-08-17`, sealed transport, SHA-256, evidence schemas, report taxonomies, and scientific semantics remain byte- and behavior-compatible.

No patient or personal genomic data may be introduced. No scientific threshold, reference, caller behavior, evidence interpretation, report output, or POST-DEPLOYMENT status may change as a consequence of this repository-name migration.

## 5. Chosen migration approach

### Phase 1A — pre-rename capture

Immediately before the GitHub rename, capture and record the repository ID, `main` SHA, default branch, visibility, active ruleset IDs and definitions, required status contexts, open PR count, branch list, remote URL, and current repository description.

The rename must be aborted if `main` has moved since the implementation branch was prepared without first rebasing/revalidating the migration plan against the new HEAD, or if an unexpected open PR or governance change creates ambiguity.

### Phase 1B — GitHub repository rename

Use GitHub's supported repository rename operation on the existing repository object: `Codework` → `OmniGenis`. Do not create a second repository and do not mirror-push history.

After the mutation, verify that the repository ID remains `1212760346`, `main` resolves to the same commit SHA that existed immediately before the rename, visibility remains public as explicitly approved, and the two active rulesets remain attached and enforced.

Verify that the old repository URL redirects to the new repository and that the new canonical repository URL is `https://github.com/repository_id=1212760346; repository_name=OmniGenis`.

### Phase 1C — local remote migration

Update the authorized Ubuntu workspace remote from `https://github.com/repository_id=1212760346; historical_repository_name=Codework.git` to `https://github.com/repository_id=1212760346; repository_name=OmniGenis.git`. Verify fetch resolution and that the stable repository history is unchanged.

### Phase 1D — active repository-reference update

Create a dedicated implementation branch from the post-rename `main`. Update only active references whose meaning is the current GitHub repository identity. Candidate surfaces include `AGENTS.md`, `README.md` if needed, `docs/BRANCH_GOVERNANCE.md`, `docs/GITHUB_MOBILE_IMPORT.md`, `docs/MAGALU_PRIVATE_MCP_SETUP.md`, `docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md`, active setup instructions, and any executable code that hard-codes `repository_id=1212760346; historical_repository_name=Codework` as a repository address.

Do not rewrite historical PR/run URLs merely because GitHub redirects them. Their original path is historical evidence and remains valid as evidence of what existed when the record was created.

No internal technical identifier is renamed in Phase 1 solely because it contains `codework`. Tests must explicitly prove that `/opt/codework`, the current runner label, image/package names, MCP package identity, plugin marketplace identity, and environment-variable names remain unchanged in this phase.

### Phase 1E — external integration verification

After the GitHub rename, verify the repository association for installed review/security integrations that participate in protected-main status checks. At minimum inspect CodeRabbit, GitGuardian, DeepSource, Snyk, Semgrep, and GitHub Actions status production on the renamed repository.

A repository rename must not be declared complete merely because GitHub redirects browser URLs. The protected-main required status contexts must still be satisfiable on a test pull request against `OmniGenis`.

If an external integration loses repository authorization or reports only against the old repository identity, stop before merge and repair/re-authorize that integration without weakening required checks.

## 6. GitHub Actions and package behavior

The current repository uses relative reusable workflow invocation (`./.github/workflows/genoma-audit.yml`) rather than `uses: repository_id=1212760346; historical_repository_name=Codework/...`. Therefore the known GitHub limitation for renamed repositories referenced as external reusable actions is not currently a blocking dependency.

Phase 1 preserves the existing GHCR package/image names such as `codework-genome` and `genoma-policy-engine`. The repository rename changes the source repository identity, not package naming contracts. Any package rename belongs to Phase 2 and requires an explicit compatibility and retention plan.

Workflow expressions based on `${{ github.repository }}` should naturally resolve to `repository_id=1212760346; repository_name=OmniGenis` after the rename. Hard-coded repository-address literals must be identified and reviewed individually.

The self-hosted runner label `codework-isolated` is an execution-routing contract and is not renamed in Phase 1. Changing a runner label at the same time as the repository rename would create an unnecessary CI availability risk.

## 7. Pull-request implementation model

The post-rename repository-reference cleanup must use the normal governed development path:

1. create a non-`main` branch from the exact renamed `main`;
2. add characterization tests for repository identity and preservation boundaries before changing active references;
3. make the smallest repository-address/documentation changes required;
4. run local repository validation and relevant contract tests;
5. create a draft PR for `OmniGenis`;
6. mark the exact validated HEAD ready for external review;
7. require all protected-main checks and review-thread resolution;
8. leave the final merge to explicit human action.

Auto-merge remains disabled.

## 8. Verification gates

The migration is successful only when all applicable gates are verified with fresh evidence. Repository-level checks include stable repository ID, expected `main` SHA continuity, correct new name, public visibility unchanged, no duplicate replacement repository, active rulesets present, and old-to-new URL redirect behavior.

Local Git checks include the new `origin` URL, successful fetch, identical expected commit history, clean worktree, and no unexpected remote divergence.

Code validation must at minimum execute `python3 scripts/validate_repo.py`, `python3 scripts/verify_supply_chain_lock.py`, the relevant root regression tests, documentation/language guards, `git diff --check`, and any tests introduced specifically for rename boundaries. If the implementation touches MCP, policy-engine, Docker, or workflow behavior beyond repository-address literals, run the corresponding AGENTS.md validation set and treat that as scope escalation.

The test PR after the rename must demonstrate that the required GitHub checks can be produced under `repository_id=1212760346; repository_name=OmniGenis`, including CodeRabbit, GitGuardian, DeepSource, Snyk, Semgrep, static validation, container-canary, and policy checks applicable to the PR.

## 9. Rollback and failure handling

Before the rename, record the exact pre-mutation repository metadata and governance state. If the rename itself causes an unrecoverable integration failure, the primary rollback is to rename the same repository object back to `Codework`, not to create or restore from a second repository.

Rollback must preserve the repository ID and pre-rename `main` SHA. Local remotes changed to `OmniGenis` must be returned to `Codework` only if the GitHub repository name is actually rolled back.

A temporary external-integration failure is not permission to remove a required status check, bypass protected `main`, disable security review, or merge through an alternate repository.

## 10. Phase 2 explicitly deferred

Phase 2 will evaluate whether internal technical identities should be renamed from `codework-*` to `omnigenis-*`. That later migration may include container image names, runtime paths, environment names, MCP identities, runner labels, plugin marketplace identifiers, temporary-directory prefixes, and environment variables.

Phase 2 requires a consumer graph, compatibility policy, transition aliases where justified, TDD characterization, package-retention decisions, and a separate approval. Nothing in Phase 1 implies that these internal names are obsolete or safe to change.

## 11. Success criteria

Phase 1 is complete only when the same GitHub repository object is canonically named `OmniGenis`, `main` and governance continuity are verified, the authorized Ubuntu checkout uses the new remote URL, current repository-address references are migrated through a reviewed PR, historical evidence remains truthful, internal technical contracts remain deliberately stable, and all required protected-main checks operate on the renamed repository.

The migration does not change or assert genomic analysis status, scientific conclusions, canonical ruleset identity, or POST-DEPLOYMENT completion.
