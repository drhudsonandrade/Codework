# English Codebase Migration — Final Inventory

## Scope

Stage 8 closes the approved English-first refactor without translating stable user-facing, normative, canonical, historical, or compatibility data. The executable implementation remains English-first while retained Portuguese is explicit, classified, and fingerprinted.

The deterministic audit is:

```bash
python3 scripts/residual_language_audit.py --check
```

At the Stage 8 implementation state used to create the classification ledger, the audit records **252 tracked files** containing **7,602 detected lines**. Every detected file has one exact ledger entry with a reviewed category, reason, count, and content fingerprint.

## Closed classification categories

The only permitted categories are:

- `normative` — closed taxonomies, policy/workflow values, and runtime identifiers whose spelling is part of a governed contract.
- `localized` — pt-BR report, operator, or runtime explanatory text intentionally kept for user-facing behavior.
- `historical` — versioned audit, evidence, and implementation-plan records preserved as historical artifacts.
- `canonical` — sealed bytes, integrity identifiers, attestations, and template artifacts whose identity must not be translated.
- `compatibility-preserved` — existing serialized data, fixtures, safety patterns, wire values, or reviewed documentation quotations that must remain stable.

The reviewed ledger distributes those lines as follows:

| Category | Files | Detected lines |
| --- | ---: | ---: |
| `canonical` | 13 | 31 |
| `compatibility-preserved` | 108 | 4,861 |
| `historical` | 27 | 766 |
| `localized` | 68 | 1,740 |
| `normative` | 36 | 204 |

These are detected lines, not a claim that each line is independent prose. A line can contain more than one governed Portuguese token, and the fingerprint binds the complete detected line plus its token set.

## Stage 8 cleanup decisions

`.coderabbit.yaml` was the remaining active reviewer-tooling surface with Portuguese technical instructions. Its technical prompts and custom-check display names are now English. All review controls, paths, blocking modes, auto-review settings, safety constraints, and `language: "pt-BR"` localization preference remain unchanged.

The private `_normalised_moi` alias is retained in Stage 8. Repository-wide consumer analysis found only same-module calls, but removing the shim causes the changed scientific module to pull unrelated pre-existing style and typing debt from its import graph into the review surface. Stage 8 does not hide, ignore, or repair that unrelated debt. The scientific module is therefore restored byte-for-byte to the Stage 8 base, `normalised_moi` remains the preferred implementation path, and alias removal is deferred to a separately scoped scientific-maintenance change.

Public compatibility surfaces were deliberately retained. English policy access names such as `OperationalStatus.EXECUTED` remain identity-equal to their legacy members because changing the canonical enum member order/names would alter reflection, iteration, pickling, and compatibility behavior. The GRCh37 aliases `CHROMOSOME_KB` and `AUTOSOME_KB` also remain because they are public module-level compatibility constants.

The `scripts.materialize_ruleset.materialize` wrapper also remains: `reporting/policy_control.py` imports it directly, multiple policy tests bind to that callable, and workflows/documentation depend on the CLI file. It is therefore an active compatibility surface, not a temporary migration alias.

## Canonical identity and scientific behavior

This stage does not change the canonical ruleset identity: `GENOMA-RULESET-v3.4`, version `v3.4`, formal date `2026-08-17`, and SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580` remain unchanged.

No scientific threshold, evidence interpretation, report taxonomy, MCP payload, dependency, reference, or genomic result is changed by Stage 8. The residual-language ledger classifies preserved text; it does not promote or reinterpret it.

## Fail-closed behavior

`config/residual_language_classification.json` uses exact tracked-file entries plus one aggregate classification for the immutable `docs/history` tree. The historical root is not an unguarded exclusion: its file count, detected-line count, exact constituent paths, detected line content, and token sets are bound into one SHA-256 fingerprint. This avoids copying superseded normative identifiers into an active configuration file while still making additions, removals, or content drift under history detectable.

For direct entries, the ledger stores the reviewed category and reason together with the detected-line count and a SHA-256 fingerprint over the sorted detected line content and token set.

The audit fails when:

- a new tracked file contains unexplained Portuguese;
- a classified direct file disappears while its ledger entry remains;
- a file is added to, removed from, or changed inside the classified historical root;
- detected content changes without an explicit ledger update;
- a category is outside the closed five-value vocabulary;
- a reason, count, file count, or fingerprint is invalid;
- direct paths or aggregate roots are duplicated or overlap.

The existing Python implementation-language guard and active Markdown documentation guard remain independent gates. This Stage 8 audit complements them by making the intentionally retained residual surfaces explicit instead of treating them as unexplained debt.

## Operational limitation

The detector is a deterministic lexical guard, not a natural-language classifier. It intentionally favors reviewability and fail-closed drift detection over probabilistic language inference. A legitimate localized or canonical text change therefore requires an explicit ledger review/update.

Stage 8 is a source-code migration only. It does not execute a production genomic workflow and does not establish `POST-DEPLOYMENT` completion; that state remains governed by the separate live evidence contract.
