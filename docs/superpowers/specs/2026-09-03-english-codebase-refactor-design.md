# GENOMA English Codebase Refactor — Compatibility-Preserving Design

**Date:** 2026-09-03
**Status:** PR 1 implementation started; guardrails implemented in PR #38
**Strategy:** Progressive migration by layers
**Repository:** `drhudsonandrade/Codework`
**Implementation reference:** `scripts/code_language_guard.py`
**Reproducible validation:** `python3 -m unittest tests.test_code_language_guard -v` and `python3 scripts/code_language_guard.py --check`

## 1. Objective

Refactor the GENOMA codebase so that technical source code is consistently written in English while preserving runtime behavior, scientific semantics, evidence integrity, compatibility, and the current canonical GENOMA contracts.

This is a language and maintainability refactor, not a scientific, clinical, policy, schema, or product-behavior migration.

The implementation must never claim equivalence merely because code compiles. Every migrated layer must preserve observable behavior through tests, contract checks, and repository validation.

## 2. Design principles

1. **Behavior preservation first.** Translation is subordinate to functional compatibility.
2. **Public-contract stability.** Existing public APIs, CLI surfaces, serialized fields, evidence artifacts, workflow outputs, canonical filenames, normative values, and external identifiers remain compatible unless a separately reviewed migration explicitly proves that no consumer depends on them.
3. **Canonical integrity.** The GENOMA v3.4 ruleset, its exact bytes, identity, filename, SHA-256, sealed transport, manifests, and attestation semantics are not translated or rewritten by this refactor.
4. **Scientific integrity.** No scientific thresholds, QC rules, variant logic, evidence semantics, or fail-closed behavior may change as a side effect of language normalization.
5. **Progressive migration.** Changes are divided into small pull requests with independently reviewable scopes.
6. **No mass search-and-replace.** Renames are semantic, consumer-aware, and tested.
7. **Compatibility before cleanup.** Public or cross-module Portuguese identifiers may temporarily remain available through aliases or compatibility wrappers while new internal code uses English.
8. **Traceability.** Every changed public-looking name must have a documented consumer analysis and an explicit compatibility decision.
9. **No auto-merge.** All pull requests follow repository governance and require human approval.

## 3. Language policy

### 3.1 English is required for new technical code

The following should be English after migration and for all new work:

- Python function, method, class, variable, parameter, and private constant names;
- TypeScript identifiers;
- shell local variables and helper function names;
- Nextflow internal process/helper names when they are not externally stable workflow contracts;
- internal module/package names when a safe migration path exists;
- comments and docstrings;
- developer-facing test names and descriptions;
- internal error messages that are not contractual output;
- developer documentation;
- implementation notes and non-normative operational documentation;
- new internal configuration names that do not form an external contract.

### 3.2 Portuguese is preserved where it is part of the product or contract

The following are deliberately not translated by this refactor:

- the canonical GENOMA v3.4 normative ruleset text;
- canonical ruleset filename, version, effective date, identifiers, and hashes;
- sealed normative transport and integrity manifests;
- existing external evidence artifact names and schemas;
- historical evidence and immutable audit records;
- serialized normative values such as `VIGENTE`, `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, and `NÃO DISPONÍVEL` where they are part of an established contract;
- existing canonical report filenames whose identity is tied to manifests or hashes;
- Portuguese report content intended for pt-BR users;
- regulated/scientific terminology where the canonical source defines the exact value;
- externally consumed CLI/API/MCP field names unless a dedicated compatibility migration is separately approved;
- exact strings used as contract fixtures when changing them would change what is being validated.

### 3.3 Localization boundary

User-facing content must be separated from implementation language.

The long-term rule is:

- implementation language: English;
- user-facing report language: locale-driven;
- initial preserved locale: pt-BR;
- future locales may be added without renaming core implementation symbols.

This refactor does not require translating the current reports to English.

## 4. Compatibility classification

Before renaming a Portuguese symbol or string, classify it into one of five groups.

### A. Private implementation identifier

Examples: local variables, private helper functions, private classes, internal test helpers.

**Action:** rename directly, update all known consumers, and validate behavior.

### B. Public or cross-module identifier

Examples: imported functions, documented methods, CLI-callable functions, exported TypeScript symbols, widely imported constants.

**Action:** introduce the English name as canonical implementation, retain the Portuguese name as a compatibility alias when needed, test both paths, and remove the alias only in a later cleanup after proving there are no supported consumers.

### C. Serialized or persisted contract

Examples: JSON keys, enum values, evidence states, artifact filenames, report manifest entries, workflow outputs.

**Action:** preserve the existing external representation. Internal code may use English names while serialization/deserialization adapters keep the established wire value.

### D. User-facing localized content

Examples: report headings, pt-BR messages, explanatory text, template content.

**Action:** preserve Portuguese content. Move toward explicit locale ownership only when useful and non-disruptive.

### E. Immutable or historical evidence

Examples: prior audit evidence, historical report artifacts, signed/hash-bound records, archived documentation recording what actually occurred.

**Action:** never rewrite for cosmetic translation. New explanatory documentation may describe the historical item in English without altering the original evidence.

## 5. Migration architecture

The migration is divided into eight pull requests. Each PR is independently testable and must not depend on an unmerged later PR to remain functional.

### PR 1 — Language baseline and guardrails

Purpose: define and enforce the English-code policy before broad renaming begins.

Scope:

- add the repository language policy;
- add an inventory tool or check capable of detecting likely Portuguese technical identifiers and comments while supporting an explicit allowlist for normative/user-facing/historical exceptions;
- add tests for the guardrail;
- document classification A–E;
- do not rename major runtime surfaces yet.

Acceptance criteria:

- repository behavior unchanged;
- new Portuguese technical identifiers are detectable;
- expected Portuguese contract/content values are allowlisted explicitly rather than hidden by a broad exclusion.

### PR 2 — Internal Python implementation

Purpose: migrate private Python implementation symbols first.

Scope:

- private functions and methods;
- local variables and parameters;
- private classes/constants;
- comments and docstrings;
- test helper names;
- internal-only module names where all imports can be traced safely.

Compatibility:

- documented/public/cross-module names are not removed without aliases;
- serialized keys and normative values remain unchanged.

### PR 3 — Scientific pipeline internals

Purpose: normalize non-contractual internals of WGS, SNP-array, Nextflow, and shell workflow code.

Scope:

- internal helper names;
- local shell variables;
- internal process/helper names where not artifact/API contracts;
- comments and developer-facing messages;
- scientific test descriptions.

Non-goals:

- no change to variant calling behavior;
- no change to QC thresholds;
- no change to reference identity;
- no change to evidence schema or artifact filenames;
- no change to Runtime/Resource Gate semantics.

### PR 4 — Policy, evidence, and audit internals

Purpose: make implementation code English while preserving normative wire values.

Pattern:

```python
EXECUTED = "EXECUTADO"
UNAVAILABLE = "NÃO DISPONÍVEL"
```

This pattern is valid when the left side is implementation vocabulary and the right side is an established external normative value.

Scope:

- implementation identifiers;
- private helpers;
- comments/docstrings;
- internal diagnostics not consumed as contracts;
- tests for serialization compatibility.

Non-goals:

- no translation of normative state values;
- no change to policy decisions;
- no change to audit hashes or historical evidence;
- no change to fail-closed semantics.

### PR 5 — Reporting implementation and locale boundary

Purpose: separate English implementation from Portuguese report output.

Scope:

- renderer/generator implementation identifiers;
- internal helpers;
- comments/docstrings;
- explicit pt-BR ownership for user-facing text where doing so does not alter canonical artifact identity;
- compatibility tests for report data inputs and outputs.

Non-goals:

- do not rename hash-bound canonical report files;
- do not regenerate historical artifacts only to translate labels;
- do not alter report scientific meaning;
- do not convert normative values in final reports without a separate schema/version migration.

### PR 6 — MCP, adapters, CI, and developer tooling

Purpose: normalize implementation and developer-facing language in integration surfaces.

Scope:

- private MCP/adapters identifiers;
- internal TypeScript symbols;
- comments and developer diagnostics;
- test names;
- workflow/job/step display names when not used as required external check identities;
- CI documentation.

Compatibility:

- preserve required status-check names if branch governance or external integrations depend on them;
- preserve MCP/API payload contracts;
- preserve secret/environment variable names unless proven private and safely migratable.

### PR 7 — Developer documentation

Purpose: make technical documentation primarily English.

Scope:

- README and developer docs;
- architecture explanations;
- runbooks that are not themselves normative or immutable evidence;
- examples and contribution guidance.

Preserve:

- quotations from canonical Portuguese rules;
- historical records;
- pt-BR end-user documentation when it serves a user-facing purpose.

### PR 8 — Compatibility cleanup and residual audit

Purpose: finish migration without deleting compatibility blindly.

Scope:

- full residual Portuguese inventory;
- classify every remaining occurrence as intentional or defect;
- remove temporary aliases only when repository and documented consumer analysis show they are safe to remove;
- add explicit exceptions for remaining normative, historical, localized, or externally stable values;
- publish final migration inventory in documentation.

Acceptance criteria:

- no unexplained Portuguese technical implementation identifiers remain;
- every preserved Portuguese occurrence has a documented category/reason;
- baseline validation is green;
- no supported external contract was broken.

## 6. Rename method

Every rename must follow this sequence:

1. identify the declaration;
2. find static consumers in the repository;
3. inspect dynamic consumers where relevant, including reflection, string-based lookup, subprocess invocation, workflow references, shell interpolation, configuration, and serialized data;
4. classify the symbol A–E;
5. decide direct rename vs. compatibility alias vs. preservation;
6. add or adjust tests before removing the old path;
7. perform the rename;
8. run targeted tests;
9. run repository-level validation before the PR is considered ready.

No rename is justified solely because a search tool found no direct import.

## 7. Compatibility mechanisms

Approved mechanisms include:

- Python aliases for supported legacy imports;
- thin wrapper functions with identical behavior;
- explicit serializer mappings between English internal enums and Portuguese external values;
- locale dictionaries/resources for user-facing content;
- compatibility tests exercising both legacy and English access paths;
- deprecation documentation when an old public identifier is retained temporarily.

Compatibility layers must be narrow. The project must not maintain two independent implementations of the same logic.

## 8. Testing strategy

Each PR must run the repository validations required by `AGENTS.md` for the surfaces it changes.

At minimum for repository-wide/Python changes:

```bash
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
python3 -m unittest discover -s tests -v
bash -n scripts/*.sh
```

Additional suites are required when their surfaces change:

```bash
cd policy_engine
python -m unittest discover -s tests -v
python -m genoma_policy ruleset-check
cd ..
python -m compileall -q policy_engine/genoma_policy scripts
```

and:

```bash
cd mcp
npm ci --ignore-scripts
npm test
cd ..
```

Scientific-runtime changes require the relevant synthetic canaries or GitHub Actions evidence. Lack of a local runtime must be reported as a limitation, never converted into PASS.

### Contract-focused regression checks

The migration also requires tests that prove:

- normative serialized values remain byte-for-byte unchanged where required;
- canonical report filenames remain unchanged where manifest-bound;
- expected hashes are unchanged when no artifact content is intentionally changed;
- CLI/API/MCP payloads preserve existing supported fields;
- audit/evidence schemas remain compatible;
- legacy aliases return the same results as new English names where aliases are retained;
- no alias weakens fail-closed behavior;
- translated internal error text is not used by programmatic consumers.

## 9. Change-control and pull-request discipline

For every migration PR:

- branch from current protected `main`;
- keep scope limited to one migration layer;
- do not combine unrelated bug fixes unless required to preserve behavior and separately explained;
- document files intentionally changed;
- document contracts inspected;
- report commands actually executed and their exact results;
- state CodeRabbit and CI status accurately;
- never auto-merge;
- require human approval before merge.

A later PR must rebase/synchronize on the newly merged `main` rather than assuming earlier branch state remains current.

## 10. Rollback strategy

Each PR must be reversible independently.

If a compatibility regression is found:

1. stop the current migration layer;
2. do not compensate by weakening tests or validators;
3. revert the affected PR or restore the legacy alias/adapter;
4. reproduce the regression with a test;
5. redesign the rename boundary;
6. resume only after the compatibility test passes.

Canonical ruleset, evidence, report manifests, and historical artifacts are not rollback targets for this language refactor because they are outside its modification scope.

## 11. Risks and mitigations

### Dynamic string consumers

Risk: names referenced via strings, reflection, configuration, shell, workflow expressions, or subprocess commands can evade static search.

Mitigation: consumer analysis must include textual and runtime-oriented searches plus regression tests.

### Accidental contract translation

Risk: replacing Portuguese strings globally could alter evidence or policy semantics.

Mitigation: no global replacement; explicit A–E classification; serializer compatibility tests.

### Huge diffs hiding defects

Risk: broad formatting/translation changes can conceal functional modifications.

Mitigation: eight scoped PRs; avoid unrelated formatting; review final diff against `main` for each PR.

### Canonical artifact drift

Risk: changing report filenames or content can invalidate stored hashes/manifests.

Mitigation: hash-bound artifacts and names are preserved by default.

### Compatibility alias accumulation

Risk: temporary aliases can become permanent clutter.

Mitigation: track them explicitly and review them in PR 8; removal requires evidence of safety, not a deadline alone.

## 12. Definition of done

The migration is complete only when all of the following are true:

1. technical implementation is English by default across Python, TypeScript, shell, Nextflow, CI/tooling, and developer documentation;
2. remaining Portuguese occurrences are explicitly classified as normative, localized, historical, canonical, or compatibility-preserved;
3. there are no unexplained Portuguese technical identifiers in active implementation code;
4. canonical GENOMA v3.4 identity and integrity are unchanged;
5. scientific behavior and QC semantics are unchanged except for separately approved fixes;
6. existing supported CLI/API/MCP/evidence contracts remain compatible;
7. pt-BR reports continue to render correctly;
8. repository, policy-engine, MCP, and relevant scientific validations pass on the final migration state;
9. all PRs received required review and human merge approval;
10. no `POST-DEPLOYMENT PASS` or equivalent claim is inferred from the refactor unless the project-specific live deployment evidence was actually executed.

## 13. Implementation order

The approved order is:

`PR 1 baseline → PR 2 Python → PR 3 scientific pipeline → PR 4 policy/evidence/audit → PR 5 reporting → PR 6 MCP/adapters/CI → PR 7 documentation → PR 8 cleanup`

This order establishes guardrails before bulk changes, migrates low-risk internals before contract-sensitive layers, and leaves compatibility cleanup until the repository has already operated successfully with English-first implementation names.
