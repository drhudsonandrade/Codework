# AGENTS.md — GENOMA Codework

## Purpose

This repository is a private, reproducible genomics runtime. Preserve the canonical
architecture and evidence model described by `README.md`:

`Policy Control Plane -> Scientific Data Plane -> Evidence Plane -> Audit Plane`

These instructions apply to Codex and any coding agent operating in this repository.
CodeRabbit also uses this file as a review guideline.

## Non-negotiable change-control rules

1. Never commit or push implementation changes directly to `main`.
2. Work on a dedicated branch and deliver changes through a pull request.
3. Never enable auto-merge. Final merge requires explicit human approval.
4. Do not modify unrelated files "while you are here".
5. Do not replace the current architecture with a simpler or monolithic transport
   unless the task explicitly requires a migration and compatibility is demonstrated.
6. Do not rename canonical manifests, ruleset files, sealed transport, public CLI/API
   contracts, evidence artifacts, or workflow outputs without tracing every consumer.
7. Do not weaken validators, tests, hashes, locks, runtime/reference gates, audit
   evidence, or fail-closed behavior in order to make a task pass.
8. Do not claim a bug is fixed, a gate is PASS, or deployment is complete without
   executing the relevant validation and reporting the evidence.
9. Never add real genomic/patient data, credentials, API keys, tokens, or secrets.
10. Optional interfaces (`mcp/`, `adapters/`, UI/orchestration integrations) must not
    become a source of truth or a mandatory dependency of the deterministic core.

## Before editing

- Read the relevant implementation, tests, manifests, workflows and documentation.
- Identify upstream/downstream consumers of every contract you plan to change.
- Check for version/hash/file-name coupling before changing canonical identifiers.
- Prefer the smallest change that satisfies the task.
- If the task touches a canonical contract, treat `scripts/validate_repo.py`,
  `scripts/materialize_ruleset.py`, manifests, policy engine and CI as one contract
  surface and verify consistency across them.

## Code language policy

- Post-migration invariant: English-only technical implementation is required for every new or modified implementation identifier, comment, docstring, internal technical message, test name, and developer-facing technical document.
- Portuguese remains valid only where it is an explicit normative, serialized compatibility, localized, canonical, or historical requirement; such exceptions must remain explicit and auditable.
- All new or modified code must follow the authoritative or de facto standard style guide and idiomatic conventions for the language in use, together with the repository-pinned formatter, linter, type-checker, compiler, and validation rules.
- There is no single cross-language "universal syntax". Use the standard development conventions of each language, and preserve repository contracts whenever a generic style recommendation would conflict with an explicit project invariant.
- `config/code_language_legacy_baseline.json` records pre-migration debt; it is not permission to add new Portuguese implementation language or new style debt.
- Run `python3 scripts/code_language_guard.py --check` for changes touching scanned languages.
- When a migration removes tracked debt, update the baseline in the same PR and review the generated diff.

## Required implementation sequence

1. Create or use a non-`main` branch.
2. Inspect the current behavior and establish a reproducible failure or gap.
3. Implement the smallest scoped change.
4. Add or update regression tests for changed behavior.
5. Run the relevant local validations listed below.
6. If CodeRabbit CLI is installed and authenticated, run:
   `coderabbit review --agent --base main -c AGENTS.md`
7. Review CodeRabbit findings critically. Do not blindly apply suggestions.
   Fix findings that are supported by code, tests, contracts or documentation.
8. Re-run affected tests after every corrective change.
9. Review the final diff against `main` for unrelated changes and contract drift.
10. Use a draft pull request for iterative remote checkpoints. Push only coherent blocks
    that already passed the applicable local validation; do not use GitHub Actions as an
    iterative debugger and do not push every small correction.
11. Keep the PR in draft while implementation is still changing. Draft PR validation
    jobs are intentionally gated before runner allocation.
12. When the exact current HEAD is locally ready, push the final coherent block and mark
    the PR ready for review. The `ready_for_review` event is the boundary for external
    review and the full applicable GitHub Actions pass.
13. If CodeRabbit, another reviewer, or CI raises a blocking issue, return the PR to draft
    before the next implementation push, batch the related fixes locally, re-run affected
    tests, then mark the new exact HEAD ready again for revalidation.
14. Never merge automatically. Human approval is the final gate.

If CodeRabbit CLI is unavailable or unauthenticated, do not claim a pre-PR CodeRabbit
review occurred. Continue with local tests, keep the PR draft during implementation, and
rely on the CodeRabbit GitHub App after the exact HEAD is marked ready for review.

## Baseline validation

For repository-wide or Python changes, run at minimum:

```bash
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 -m unittest discover -s tests -v
bash -n scripts/*.sh
```

For `policy_engine/**` changes, additionally run:

```bash
cd policy_engine
python -m unittest discover -s tests -v
python -m genoma_policy ruleset-check
cd ..
python -m compileall -q policy_engine/genoma_policy scripts
```

For `mcp/**` changes, additionally run:

```bash
cd mcp
npm ci --ignore-scripts
npm test
cd ..
```

For Docker/scientific-runtime/Nextflow changes, run the relevant build/canary when the
required runtime is available. If a full local canary cannot run, state that limitation
explicitly and rely on the corresponding GitHub Actions job; do not mark it PASS locally.

## Canonical ruleset discipline

- There must be one canonical active runtime copy, materialized from the sealed
  transport only after integrity verification.
- Preserve byte-exact identity and read-only runtime semantics.
- A ruleset version/date/hash/file-name change is a coordinated migration, not a
  search-and-replace.
- The validator, materializer, manifest, policy engine, containers, attestations,
  workflows, tests and operational docs must agree.
- Never create a second active plaintext canonical ruleset in Git.

## Policy Control Plane

For `policy_engine/**` and related scripts:

- Preserve deterministic behavior.
- Core-only operation must not require an LLM, database, MCP, network service, or
  external orchestrator.
- Preserve fail-closed semantics for invalid or missing canonical evidence.
- CLI and HTTP contract changes require compatibility analysis and tests.
- Audit/attestation output must remain traceable and tamper-evident where defined.

## Scientific Data Plane

For `main.nf`, `workflows/**`, `nextflow.config`, Docker and scientific scripts:

- Preserve tool/reference pinning and reproducibility.
- Preserve runtime/resource/reference gates.
- Use synthetic/non-sensitive canaries in CI.
- Calling/QC/reference changes require tests or canaries that exercise the modified path.
- Never smuggle policy decisions into the scientific data plane.

## Evidence and Audit Planes

- Evidence must be generated by execution, not prose.
- Do not alter evidence schemas, artifact names, retention assumptions or hash logic
  without tracing all consumers.
- `POST-DEPLOYMENT PASS` requires the project-defined live evidence contract; it cannot
  be inferred from README text or a successful unit-test run.
- Documentation must distinguish pre-deployment, CI validation and real deployment.

## GitHub Actions and supply chain

- Keep permissions least-privilege.
- Keep production publishing gated to protected `main` after required validations.
- Do not use `continue-on-error` for critical validation.
- Keep Actions/images/tools pinned according to the repository supply-chain policy.
- Never print secrets or sensitive genomic data to logs or artifacts.

## Test integrity

A test change is not automatically proof of a fix.

Flag and avoid:

- deleting a failing test without equivalent coverage;
- weakening assertions;
- changing expected values solely to match broken output;
- mocking away the behavior under test;
- broad exception handling that converts failure into success;
- tests that pass without executing the modified path.

Every behavior-changing bug fix should have a regression test that would fail before the
fix and pass after it whenever technically feasible.

## Pull request requirements

Every PR must describe:

- exact scope and reason for the change;
- architecture/contracts affected;
- files intentionally changed;
- tests/commands actually executed and their results;
- CodeRabbit review status;
- GitHub Actions status;
- known limitations or validations that could not run;
- whether any canonical version/hash/manifest/evidence contract changed.

Do not state "all tests pass" unless the relevant commands actually ran successfully.

## Code Review Rules

During review, prioritize:

1. correctness and regressions;
2. canonical ruleset/version/hash consistency;
3. validator/materializer contract consistency;
4. evidence integrity and false PASS claims;
5. supply-chain and permissions regressions;
6. scientific reproducibility;
7. test integrity;
8. compatibility of CLI/API/MCP/adapters;
9. unrelated scope expansion.

Formatting/style-only issues are secondary when CI can enforce them.
