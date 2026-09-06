# Four-plane Audit Test Deduplication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce required `static` runner time by eliminating repeated full four-plane audits inside unit tests without changing production audit behavior.

**Architecture:** Keep one real successful audit snapshot per Python test process and return isolated deep copies to read-only contract tests. Failure-specific tests continue calling `audit()` directly, but stub the unrelated successful repository-contract subprocess when the scenario under test is ruleset or GRCh38 failure.

**Tech Stack:** Python 3 standard library, unittest/mock, GitHub Actions.

**Global Constraints:**
- Modify no production code.
- Keep fail-closed assertions unchanged.
- Preserve at least one real full successful `audit()` execution.
- Never cache or reuse mocked failure results.
- Keep each test isolated from mutations in another test.
- Merge remains manual.

### Task 1: Cache the successful integration snapshot

- [ ] Add a regression proving a baseline holder calls its runner once and returns independent copies.
- [ ] Verify RED before adding the holder.
- [ ] Implement the minimal test-only baseline holder.
- [ ] Route only identical successful-read tests through it.
- [ ] Verify `tests.test_genoma_audit` assertions remain unchanged.
### Task 2: Isolate unrelated expensive success work in failure tests

- [ ] Add a helper that returns a synthetic PASS only for the `validate_repo.py` command and delegates every other command to the real runner.
- [ ] Use it only in the ruleset-failure and GRCh38-failure audit tests.
- [ ] Keep the repository-contract failure test unchanged so it still exercises that failure explicitly.
- [ ] Verify all failure assertions still pass.

### Task 3: Measure and hand off

- [ ] Run the audit test module and compare elapsed time with the 410.4 s Windows baseline, allowing only the existing path-separator failure.
- [ ] Run CI/workflow contracts, repository validation, supply-chain validation, language guard, and diff check.
- [ ] Commit once after local validation.
- [ ] Push once and open Draft PR #48.
- [ ] Use external reviewers first; mark Ready only on the final SHA.
- [ ] Measure `static` duration on Ubuntu and require all protected checks before manual merge.