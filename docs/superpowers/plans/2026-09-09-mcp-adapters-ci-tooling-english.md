# Stage 6 MCP, Adapters, CI, and Developer Tooling English Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the English-first migration for integration and developer-tooling surfaces without changing MCP/API payloads, required GitHub check identities, workflow semantics, secret/environment variable names, or localized/normative values.

**Architecture:** Treat current MCP/adapters/CI interfaces as compatibility contracts because their implementation is already English. Change only inventoried developer-facing CodeRabbit installer diagnostics. Add focused tests that prove the translated diagnostics remain semantically equivalent while MCP tool schemas, required status-check contexts, environment names, and intentional Portuguese CI/localized values stay unchanged.

**Tech Stack:** Bash, Python 3.12 unittest, TypeScript 5.9 / Node.js >=22, MCP SDK 1.30.0, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md` — PR 6.

## Global Constraints

- Preserve MCP tool names: `runtime_status`, `reference_status`, `run_synthetic_canary`, `audit_record`.
- Preserve the only MCP input field name `requestId`, including which tools require it.
- Preserve `PROJECT_ROOT`, `REF_ROOT`, `RESULTS_ROOT`, `AUDIT_ROOT`, `PORT`, and `MCP_BIND_HOST`.
- Preserve every protected-main required status-check context exactly.
- Preserve workflow semantics, job ids, secret names and environment-variable names.
- Preserve `NÃO DISPONÍVEL` and other normative values where they are serialized or deliberately shown as gate outcomes.
- Preserve pt-BR fixture content in visual QA and the Portuguese filename-pattern detector used by the SNP-array safety gate.
- No auto-merge; final merge remains human/manual.

---

### Task 1: Inventory and compatibility tests

**Files:**
- Create: `tests/test_integration_code_language.py`
- Modify: `mcp/test/server.test.ts`

**Interfaces:**
- Consumes: current CodeRabbit setup script, MCP listTools contract, governance ruleset, workflow/source text.
- Produces: failing English-diagnostic test plus green compatibility characterization for MCP/check/env contracts.

- [ ] **Step 1:** Add a bounded diagnostic scanner test for `scripts/codex/setup-coderabbit.sh` that rejects the inventoried Portuguese developer-facing terms while ignoring comments and contract values.
- [ ] **Step 2:** Run `python -m unittest tests.test_integration_code_language -v`; expect failure on the current Portuguese diagnostics.
- [ ] **Step 3:** Extend the existing MCP initialization test to assert exact input-schema property/required sets for all four tools; this should pass before production edits and becomes a contract lock.
- [ ] **Step 4:** Add assertions for the protected-main check-context set and MCP environment-variable names without renaming either surface.
- [ ] **Step 5:** Run the focused Python and MCP suites.

### Task 2: Translate only CodeRabbit developer diagnostics

**Files:**
- Modify: `scripts/codex/setup-coderabbit.sh`
- Modify: `tests/test_coderabbit_guardrails.py`

**Interfaces:**
- Consumes: exact existing control flow and exit codes.
- Produces: English human/developer diagnostics with unchanged branches, commands, hashes, URLs, plugin ids and exit statuses.

- [ ] **Step 1:** Translate every inventoried `fail`/`echo` diagnostic from Portuguese to English without changing conditionals or command arguments.
- [ ] **Step 2:** Update only output-text expectations in `tests/test_coderabbit_guardrails.py`.
- [ ] **Step 3:** Run CodeRabbit guardrail and HTTPS transport tests plus the new integration-language test.
- [ ] **Step 4:** Run `bash -n scripts/codex/setup-coderabbit.sh` and compare the script AST-equivalent control structure through a normalized shell-token diff where possible; otherwise document that only quoted diagnostics changed.

### Task 3: Document the bounded stage and preserved exceptions

**Files:**
- Create: `docs/INTEGRATION_CODE_LANGUAGE_INVENTORY.md`
- Modify: `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`

**Interfaces:**
- Consumes: reproducible grep/test inventory and fixed base commit `4d6a3ea247bfd6c009878914e1046e464648e79a`.
- Produces: explicit A-E classification of changed and preserved Portuguese occurrences.

- [ ] **Step 1:** Record that MCP/adapters/workflow display names were already English and therefore were not cosmetically rewritten.
- [ ] **Step 2:** Record intentional Portuguese exceptions: normative `NÃO DISPONÍVEL`, visual-QA pt-BR fixtures, SNP-array Portuguese filename detector, adapter serialized values.
- [ ] **Step 3:** Record protected MCP/check/env contracts and the exact validation commands.
- [ ] **Step 4:** Update migration status to stages 1-5 merged and stage 6 in implementation.

### Task 4: Exact-SHA verification and PR delivery

**Files:**
- No new production files unless a validation defect is found and separately tested.

- [ ] **Step 1:** Run `npm ci --prefix mcp --ignore-scripts` and `npm test --prefix mcp`.
- [ ] **Step 2:** Run integration/CodeRabbit/workflow/governance focused Python suites.
- [ ] **Step 3:** Run `python scripts/code_language_guard.py --check`, `python scripts/validate_repo.py`, `python scripts/verify_supply_chain_lock.py`, root unittest discovery, shell syntax and `git diff --check`.
- [ ] **Step 4:** Prove `.github/workflows/**`, `mcp/src/**`, adapters, MCP package/lock/config, and governance status-check contexts are unchanged from the base unless explicitly listed as test-only characterization files.
- [ ] **Step 5:** Commit one coherent implementation batch, rerun the same validation on the committed SHA, push a Draft PR, bind evidence to the exact SHA/tree, mark Ready, and request CodeRabbit review.
- [ ] **Step 6:** Stop before merge. Hand off only when applicable checks and review threads are clean; human approval/manual merge remains outstanding.
