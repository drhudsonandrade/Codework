# Policy, Evidence and Audit Language Inventory — Stage 4

## Scope and status

The approved English-codebase migration reached stage four after PR #59 merged
at `fe916c5f567380b5756dcdeab2df6af6767f296b`. This inventory records the narrow
policy/evidence/audit implementation migration. Local implementation and review
preparation do not constitute merge, clinical validation or production deployment.
Exact-SHA test results and external review status are recorded in the stage-four PR.

Inspected surfaces: `policy_engine/genoma_policy`, `policy_engine/tests`,
`evidence_adapters`, their repository consumers, normative manifests and policy
schemas. Existing comments, helpers and diagnostics were already English apart
from intentional normative quotations. They are not gratuitously rewritten.

## Compatibility decisions

| Category | Surface | Decision |
| --- | --- | --- |
| A — private | Three policy test methods | Rename to English; preserve assertions, fixtures and test count. |
| B — public/cross-module | Fourteen enum member access names | Add English aliases; retain all legacy names and enum class identities. |
| C — serialized | State, nature and domain values; diagnostic quotations | Preserve exact spelling, accents, encoding and accepted value sets. |
| D — localized | Existing pt-BR content and user-facing ruleset errors | Preserve; reporting locale separation belongs to stage five. |
| E — immutable/historical | Ruleset transport, hashes, evidence, schema and historical identity fixtures | Preserve byte-for-byte; do not regenerate for translation. |

### Preferred English access

| Enum | Preferred access | Retained access | Unchanged wire value |
| --- | --- | --- | --- |
| OperationalStatus | EXECUTED | EXECUTADO | EXECUTADO |
| OperationalStatus | VERIFIED | VERIFICADO | VERIFICADO |
| OperationalStatus | INFERRED | INFERIDO | INFERIDO |
| OperationalStatus | PROPOSED | PROPOSTO | PROPOSTO |
| OperationalStatus | UNAVAILABLE | NAO_DISPONIVEL | NÃO DISPONÍVEL |
| ClaimNature | CONFIRMED_FACT | FATO_CONFIRMADO | FATO CONFIRMADO |
| ClaimNature | INFERENCE | INFERENCIA | INFERÊNCIA |
| ClaimNature | ASSOCIATION | ASSOCIACAO | ASSOCIAÇÃO |
| ClaimNature | HYPOTHESIS | HIPOTESE | HIPÓTESE |
| ClaimNature | UNKNOWN | DESCONHECIDO | DESCONHECIDO |
| Domain | CLINICAL | CLINICO | CLÍNICO |
| Domain | PREDISPOSITION | PREDISPOSICAO | PREDISPOSIÇÃO |
| Domain | RESEARCH | PESQUISA | PESQUISA |
| Domain | CURIOSITY | CURIOSIDADE | CURIOSIDADE |

Legacy declarations deliberately remain first. Both names resolve to the **same
member object**. Existing `.name`, `str`, `repr`, iteration order, cardinality,
value lookup, equality, hashing and pickle round trips remain compatible.
`Enum.__members__` intentionally gains fourteen additional keys; code inspecting
that mapping sees the additive API. This is not a claim of identical introspection
for the expanded mapping. No legacy key is removed or reordered.

English names are preferred for new implementation access, not new wire values.
For example, `OperationalStatus.EXECUTED.value` is still `EXECUTADO`;
`OperationalStatus("EXECUTED")` is invalid. Moving English aliases ahead of the
legacy declarations would change canonical member names and is intentionally
avoided. Removing or reversing the compatibility layer requires a separate
consumer-aware decision, not an automatic stage-eight deletion.

### Consumers and retained boundaries

Repository searches found `OperationalStatus` iteration in shared gate and
attestation tables; `ClaimNature` and `Domain` previously had only declarations.
No repository source accessed their legacy member attributes directly. The public
module can nevertheless have external or reflective consumers, so absence of a
static import is **not** used as permission to remove old names.

Shared nature/domain membership sets now derive from their existing enums.
Attestation satisfying-state and performed-proof comparisons use English aliases
with `.value`, retaining plain-string sets, reason text and branch logic. These
are the only executable changes apart from adding aliases and renaming tests.
No gate condition, evidence requirement or timestamp/hash validation is weakened.

Private test renames:

- `test_duplicate_vigente_fails_closed` → `test_duplicate_active_ruleset_fails_closed`.
- `test_ruleset_gate_rejects_non_vigente_status` → `test_ruleset_gate_rejects_inactive_status`.
- `test_ruleset_requires_vigente_status` → `test_ruleset_requires_active_status`.

Full-repository text search found only their original declarations before this
migration. Fixture values such as `VIGENTE` and `PENDENTE` remain intact.

## Validation design

`tests/test_policy_language_compatibility.py` contains nine tests. Its closed
vocabularies are independent literal fixtures, not expectations derived from the
production enums. It exercises all 100 valid status/nature/domain combinations,
rejects all fourteen English names as wire values, verifies alias identity and
legacy iteration, compares exact Unicode serialization and manifest/ledger
payload digests, and checks real attestation refusal when evidence is missing or
the state cannot satisfy a rule. It also compares public/internal evaluation
serialization and checks the three test-name replacements.

Reproduction procedure:
[`docs/superpowers/plans/2026-09-09-policy-evidence-audit-english.md`](superpowers/plans/2026-09-09-policy-evidence-audit-english.md),
using `python -m unittest tests.test_policy_language_compatibility -v`.
The historical pre-implementation RED run used the merged base plus the new test
overlay and produced 38 assertion/subtest failures for missing aliases and old
names; three baseline-characterization tests already passed. Its retained log
SHA-256 is `bde556d5deecea5ba16d0f64ee41dde35c611e30d4976f8e4f1fd281ec85ab48`.
This RED run is not described as a nonexistent committed revision.

The positive exact-HEAD execution ran on commit
`270580ec85129f2e9a89ef8c2950d6309aa30cd9`, tree
`a7999bca24cab207c0aaf0ee399c81d9e18133b7`: all nine tests passed, with no
additional count beyond the root suite that includes them. The combined log
SHA-256 is `066e9d0e4dd375079e9518dc90833cb9c63825b9c88b4d875793eaf645f1bc2a`.
Commands, results, digests and subsequent correction validation are bound in the
exact-HEAD evidence record. Resolve it at runtime with
`repo=$(gh api repositories/1212760346 --jq .full_name); gh api "repos/$repo/issues/comments/5596016415"`.
For any later HEAD, validation is PENDING until that linked record names the
matching commit and tree with actual results. Historical PASS is not inherited.

The wire-rejection test uses `zip(..., strict=True)` so adding or removing an
enum cannot silently reduce field coverage. The original normative value tests
and all nine existing regression methods are retained.

Documentation/style hygiene is limited to the five touched existing Python
files: add missing English docstrings and reflow long statements without changing
runtime literals. Compatibility comparison removes docstrings and normalizes only
the documented aliases, set expressions and three method renames. All other
existing AST statements and all out-of-scope tracked blobs must match the base.
The implementation plan includes the reproducible comparison procedure.

## Retained debt and next boundary

Intentional Portuguese enum declarations, serialized taxonomies, quoted rules,
canonical filenames and historical records are not unexplained implementation
debt. The production language baseline is neither expanded nor weakened.
The next planned stage is reporting implementation and explicit locale ownership;
current pt-BR reports and canonical report asset identities remain unchanged.

No real genomic data, WGS calling, clinical interpretation, reference download or
post-deployment approval is part of this refactor. Synthetic test passes do not
grant `POST-DEPLOYMENT PASS`.
