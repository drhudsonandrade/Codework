# Code Language Policy

## Purpose

GENOMA uses English as the implementation language for technical source code while preserving compatibility, canonical identities, scientific semantics, and localized pt-BR content.

The governing principle is behavior preservation first. Language normalization must not change policy decisions, scientific thresholds, evidence semantics, hashes, artifact identity, fail-closed behavior, or supported external contracts.

## Operational rule

New implementation identifiers, comments, and docstrings must use English.

Portuguese remains valid when it is required by an explicit normative contract, serialized compatibility surface, localized user-facing output, canonical identity, or immutable historical evidence.

For PR 1, automated enforcement scans Python source only. The policy applies to other implementation languages as well, but automated adapters must be introduced before their bulk migration layers begin.

Ordinary runtime string literals are not scanned by the PR 1 Python adapter. This prevents the language guard from treating pt-BR output or established serialized text as implementation-language debt.

## Classification A–E

### Category A — Private implementation identifier

Examples include local variables, private helpers, private classes, and internal test helpers.

Action: rename directly to English, update known consumers, and validate behavior.

### Category B — Public or cross-module identifier

Examples include imported functions, documented methods, CLI-callable functions, exported symbols, and widely imported constants.

Action: make the English name canonical internally. Retain a Portuguese compatibility alias when needed, test both paths, and remove the alias only after supported consumers are proven absent.

### Category C — Serialized or persisted contract

Examples include JSON keys, enum values, evidence states, artifact filenames, report manifest entries, and workflow outputs.

Action: preserve the established external representation. Internal English names may map to the existing serialized value through explicit adapters.

Established contract literals such as `VIGENTE`, `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, and `NÃO DISPONÍVEL` remain unchanged where they are part of a supported contract.

### Category D — User-facing localized content

Examples include report headings, pt-BR messages, explanatory text, and template content.

Action: preserve Portuguese content. Locale ownership may be made more explicit only when doing so is non-disruptive and does not alter canonical artifact identity.

### Category E — Immutable or historical evidence

Examples include prior audit evidence, historical report artifacts, signed or hash-bound records, and archived documentation that records what occurred.

Action: do not rewrite for cosmetic translation. New English documentation may explain the historical item without modifying the original evidence.

## Executable enforcement

`config/code_language_policy.json` defines the executable policy, including scanned suffixes, technical terms, preserved contract literals, and explicitly excluded immutable or historical roots with reasons.

`config/code_language_legacy_baseline.json` records measured pre-migration debt. It is temporary debt inventory, not approved style and not permission to introduce new Portuguese implementation language.

The current Python scanner analyzes identifiers, comments, and module/class/function docstrings without executing repository code. It uses a deterministic technical Portuguese vocabulary plus conservative plural and verb-inflection normalization, splits snake_case/CamelCase/acronym/digit boundaries, preserves exact contract literals, and fails closed on unreadable, unparseable, or untokenizable scanned Python source.

Baseline identity is `(path, kind, token, count)`. Line numbers are diagnostic only, so unrelated line movement does not rewrite the baseline, while partial cleanup changes the count and requires an explicit baseline update.

Normal development touching scanned languages must run:

```bash
python3 scripts/code_language_guard.py --check
```

The repository-level gate also runs the same enforcement through:

```bash
python3 scripts/validate_repo.py
```

New debt causes the guard to fail. Removing tracked debt also requires updating the baseline, preventing stale debt entries from becoming permanent allowances.

## Baseline update rule

Adding a baseline entry merely to make CI pass is forbidden unless the pull request explicitly documents why the new occurrence cannot yet be migrated without breaking a supported compatibility requirement.

The initial detector inventory is bootstrapped only from an explicit Git source tree:

```bash
python3 scripts/code_language_guard.py --bootstrap-baseline --source-commit <base-sha>
```

Bootstrap resolves `<base-sha>` as a real ancestor commit and scans that commit tree, not the current worktree. If a baseline already exists, bootstrap may refresh detector coverage only for the same recorded source commit.

Migration pull requests that remove tracked Portuguese debt use the reduction-only update mode:

```bash
python3 scripts/code_language_guard.py --write-baseline --source-commit <base-sha>
```

The update command rejects new baseline keys and count increases, and every retained finding must also be supported by the supplied source commit. Before committing a regenerated baseline, review the diff and verify the recorded base SHA.

Neither writing mode infers provenance from a mutable branch name.

Within policy schema v1, `technical_terms` is monotonic across pull requests: when the trusted PR base already contains the language policy, the current policy must retain every normalized technical term present at that base. New terms may be added, but removing a term requires an explicit future policy-schema migration rather than a baseline rewrite.

Every `--check` and repository-level validation revalidates the tracked baseline provenance. In a GitHub `pull_request` run, the runner-provided `pull_request.base.sha` is the trusted boundary and the recorded `source_commit` must be that commit or an ancestor of it; a commit introduced after the trusted base is rejected. Outside pull-request CI, `source_commit` must still resolve to a real ancestor of `HEAD`. Every baseline entry/count must be supported by the Python findings measured from the historical `source_commit`; during pull-request validation it must also be supported by findings measured from the trusted PR base using the current detector and policy. This second support check prevents debt removed before the PR from being reintroduced by restoring an older baseline entry, while a legitimately older immutable `source_commit` remains valid across future PRs.

## Scope progression

PR 1 enforces Python only. Future language adapters must preserve the same policy categories and fail-closed baseline semantics before TypeScript, shell, Nextflow, or other implementation layers are migrated in bulk.

Do not use broad exclusions to hide active implementation code. An excluded root must be deliberate policy data with a non-empty reason and must represent a justified immutable or historical surface.

No mass search-and-replace is authorized by this policy. Public-looking identifiers require consumer analysis, compatibility decisions, and regression testing before legacy names are removed.
