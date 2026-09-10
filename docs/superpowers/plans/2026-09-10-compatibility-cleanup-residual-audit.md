# Stage 8 Compatibility Cleanup and Residual Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the English-codebase migration by classifying every remaining Portuguese occurrence, removing only demonstrably private temporary aliases, and preserving every supported canonical, localized, historical, normative, or compatibility contract.

**Architecture:** Add a deterministic residual-language ledger keyed by exact tracked file, category, reason, detected-line count, and content fingerprint. The audit fails closed on any unclassified or drifted occurrence. Translate the remaining active reviewer-tooling prose in `.coderabbit.yaml`, review compatibility aliases conservatively, retain any alias whose removal widens unrelated scientific review scope, and publish the final migration inventory.

**Tech Stack:** Python 3.12/3.11-compatible standard library, `unittest`, Git, existing language scanners, YAML text configuration, GitHub Actions/CodeRabbit.

**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`

## Global Constraints

- Preserve runtime behavior and scientific semantics; language cleanup is subordinate to compatibility.
- Do not change canonical GENOMA v3.4 filename, version, date, sealed transport, hash, section count, or manifest identity.
- Do not translate normative wire/report values or pt-BR localized report content.
- Do not remove a public/cross-module compatibility alias unless supported consumers are proven absent.
- Do not modify real genomic data, generated scientific conclusions, thresholds, or evidence semantics.
- Keep `main` untouched; work only on `refactor/compatibility-cleanup-residual-audit` and require manual human merge.
- Keep auto-merge disabled and do not claim POST-DEPLOYMENT PASS.

---

### Task 1: Residual-language audit contract

**Files:**
- Create: `tests/test_residual_language_audit.py`
- Create: `scripts/residual_language_audit.py`
- Create: `config/residual_language_classification.json`

**Interfaces:**
- Consumes: tracked UTF-8 repository files and `config/code_language_policy.json`.
- Produces: deterministic findings keyed by exact file plus `category`, `reason`, `count`, and `fingerprint`; exit 0 only when every current occurrence matches the reviewed ledger.

- [ ] **Step 1: Write the failing tests**

```python
class ResidualLanguageAuditTest(unittest.TestCase):
    def test_current_repository_has_no_unclassified_residual(self):
        report = audit_repository(ROOT)
        self.assertEqual(report["unclassified"], [])
        self.assertEqual(report["drift"], [])

    def test_new_portuguese_tooling_prose_is_not_silently_classified(self):
        findings = detect_text("Revise apenas problemas introduzidos por este PR.")
        self.assertTrue(findings)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest tests.test_residual_language_audit -v`
Expected: FAIL because the audit module/ledger does not exist and `.coderabbit.yaml` is not an approved residual surface.

- [ ] **Step 3: Implement the deterministic detector and ledger comparison**

Use only the standard library. Scan `git ls-files` output, ignore binary/non-UTF-8 files, strip exact policy contract literals before prose detection, and combine policy technical terms with reviewed diacritic/ASCII heuristics. Fingerprint each file's sorted `(text, detected_tokens)` records so line movement alone does not invalidate the ledger.

The ledger schema is:

```json
{
  "schema": "genoma-residual-language-classification-v1",
  "entries": [
    {
      "path": "exact/tracked/path",
      "category": "localized",
      "reason": "English explanation of why Portuguese is intentionally retained.",
      "count": 1,
      "fingerprint": "64-hex-sha256"
    }
  ]
}
```

Allowed categories are exactly `normative`, `localized`, `historical`, `canonical`, and `compatibility-preserved`. Any new path, missing path, count drift, fingerprint drift, invalid category, duplicate entry, or empty reason is blocking.

- [ ] **Step 4: Generate the reviewed ledger from the post-cleanup repository state**

Generate entries only for files that still contain detected Portuguese. Do not add `.coderabbit.yaml`; it is active reviewer tooling and must become English. Assign the five approved categories according to the final inventory rationale, not by automatically trusting any new path.

- [ ] **Step 5: Run the focused audit test**

Run: `python -m unittest tests.test_residual_language_audit -v`
Expected after Tasks 2–3: PASS with zero unclassified/drifted findings.

### Task 2: Migrate active CodeRabbit reviewer instructions to English

**Files:**
- Modify: `.coderabbit.yaml`
- Test: `tests/test_residual_language_audit.py`
- Existing guard: `tests/test_coderabbit_guardrails.py`

**Interfaces:**
- Consumes: existing CodeRabbit schema/settings and repository review invariants.
- Produces: English technical review instructions with unchanged safety behavior; `language: "pt-BR"` remains as an explicit localization preference, not implementation prose.

- [ ] **Step 1: Add a failing configuration-language assertion**

```python
def test_coderabbit_technical_instructions_are_english(self):
    findings = findings_for_path(ROOT / ".coderabbit.yaml")
    self.assertEqual(findings, [])
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m unittest tests.test_residual_language_audit.ResidualLanguageAuditTest.test_coderabbit_technical_instructions_are_english -v`
Expected: FAIL on the current Portuguese `tone_instructions`, `path_instructions`, and `pre_merge_checks` prose.

- [ ] **Step 3: Translate only reviewer prose and display names**

Preserve every configuration key, boolean, numeric setting, path filter, path selector, check mode, auto-review control, and the `language: "pt-BR"` localization setting. Translate the technical instructions without weakening the four-plane architecture, canonical-ruleset, validation, evidence, supply-chain, scientific-runtime, MCP/adapters, reporting, or human-merge constraints.

- [ ] **Step 4: Re-run both language and CodeRabbit guardrails**

Run: `python -m unittest tests.test_residual_language_audit tests.test_coderabbit_guardrails -v`
Expected: PASS.

### Task 3: Review the private MOI alias without widening scientific scope

**Files:**
- Preserve byte-for-byte: `array_pipeline/clinical_findings.py`
- Test: `tests/test_residual_language_audit.py`

**Interfaces:**
- Consumes: `normalised_moi(label: Any) -> str` and its existing private `_normalised_moi` compatibility alias.
- Produces: an explicit decision to retain the thin alias in Stage 8 while keeping `normalised_moi` as the preferred implementation path.

- [ ] **Step 1: Add the failing compatibility-boundary test**

```python
def test_private_moi_alias_is_retained_for_scoped_compatibility(self):
    self.assertIs(clinical_findings._normalised_moi, clinical_findings.normalised_moi)
```

- [ ] **Step 2: Run and verify RED on the alias-removed candidate**

Run: `python -m unittest tests.test_residual_language_audit -v`
Expected: FAIL while the alias is absent.

- [ ] **Step 3: Restore `array_pipeline/clinical_findings.py` byte-for-byte to the Stage 8 base**

DeepSource analysis of the alias-removed candidate surfaced unrelated pre-existing line-length and imported-module typing debt. Do not expand Stage 8 into scientific maintenance and do not suppress those findings globally. Retain the existing thin alias and defer its removal to a separately scoped change.

- [ ] **Step 4: Run focused compatibility tests**

Run: `python -m unittest tests.test_residual_language_audit tests.test_clinical_findings_regressions tests.test_policy_language_compatibility tests.test_array_assembly_regressions -v`
Expected: PASS, with `array_pipeline/clinical_findings.py` byte-identical to `origin/main`.

### Task 4: Publish the final migration inventory

**Files:**
- Create: `docs/ENGLISH_CODEBASE_MIGRATION_FINAL_INVENTORY.md`
- Test: `tests/test_residual_language_audit.py`

**Interfaces:**
- Consumes: live audit report and the approved Stage 8 classification ledger.
- Produces: active English documentation stating what was translated, what remains Portuguese, why each category remains, which aliases were reviewed/retained, and the exact reproducible audit command.

- [ ] **Step 1: Add a failing inventory contract**

Require the document to name all five categories, `.coderabbit.yaml`, the retained `_normalised_moi` compatibility alias, retained policy enum aliases, retained GRCh37 aliases, canonical v3.4 identity, and the audit command.

- [ ] **Step 2: Run and verify RED**

Run: `python -m unittest tests.test_residual_language_audit -v`
Expected: FAIL because the final inventory does not exist.

- [ ] **Step 3: Write the final inventory from actual audit results**

Include detected file/line counts from the exact current audit, category counts, compatibility decisions, exclusions that are preservation rather than debt, limitations, and explicit statements that scientific behavior and POST-DEPLOYMENT status were not changed.

- [ ] **Step 4: Run the audit and documentation-language tests**

Run: `python -m unittest tests.test_residual_language_audit tests.test_developer_documentation_language -v`
Expected: PASS.

### Task 5: Exact-HEAD validation and draft PR

**Files:** no new implementation scope; validation/evidence only.

- [ ] **Step 1: Run full local validation with the runtime ruleset materialized into a temporary directory**

Run `scripts/validate_repo.py`, supply-chain verification, root `unittest`, shell syntax, policy-engine tests + `ruleset-check`, `compileall`, MCP `npm ci --ignore-scripts` + `npm test`, and `git diff --check`. Require the canonical materialized TXT to be mode `0444` and SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.

- [ ] **Step 2: Perform mutation checks**

Temporarily inject Portuguese technical prose into an unclassified tracked-like file and alter one ledger fingerprint in a disposable copy; require the audit to fail in both cases. Restore the clean worktree before continuing.

- [ ] **Step 3: Review the final diff against `origin/main`**

Require only Stage 8 plan, audit implementation/ledger/tests, code-language policy/docs/tests, `.coderabbit.yaml`, `scripts/validate_repo.py`, `tests/test_ci_optimization_contract.py`, `.github/workflows/genoma-ngs-runtime-gate.yml`, and the final migration inventory. Confirm the workflow change is limited to adding the residual-audit script to the explicit path-trigger dependency closure. Confirm `array_pipeline/clinical_findings.py` is byte-for-byte identical to `origin/main` and absent from the effective PR diff. Confirm no canonical ruleset, manifest, scientific evidence artifact, dependency, workflow job/permission/runtime behavior, or MCP payload changed.

- [ ] **Step 4: Commit one coherent locally validated block and push the branch**

Commit message: `refactor: complete English migration residual audit`

- [ ] **Step 5: Open the pull request as draft, record exact-HEAD local evidence, then mark ready for review**

The PR description must identify Stage 8 scope, alias decisions, canonical identity preservation, commands actually executed, local validation log SHA-256, CodeRabbit CLI unavailability if still absent, and manual-merge requirement.

- [ ] **Step 6: Wait for applicable CI and external reviewers**

If any blocking finding appears, return the PR to draft before corrective pushes, fix only supported findings locally, re-run affected tests, then revalidate the new exact HEAD. Never auto-merge.
