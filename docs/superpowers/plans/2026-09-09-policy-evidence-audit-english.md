# Policy, Evidence and Audit English Access Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task.
> Steps use checkbox syntax; remote release evidence belongs in the PR.

**Goal:** Complete stage four of the approved English refactor without changing
normative wire values, policy decisions, canonical assets or audit hashes.

**Architecture:** Add English access aliases to the existing string enums.
Retain legacy members first, preserving `.name`, iteration, repr and pickling.
Use the same enums in shared taxonomy tables and attestation status selection.
No duplicate implementation, new state, schema or compatibility wrapper is needed.

**Tech Stack:** Python standard library, unittest, Git and existing validators.

**Spec:** `docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md`

## Global constraints and verified starting point

- Base: `fe916c5f567380b5756dcdeab2df6af6767f296b`, merged PR #59.
- Dedicated branch: `refactor/policy-evidence-audit-english`.
- Keep canonical GENOMA v3.4 bytes, identity, hashes and manifests unchanged.
- Keep public legacy access, serialized values, fail-closed decisions and pt-BR.
- New aliases intentionally add keys to `Enum.__members__`; they do not change
  existing keys, canonical member names, iteration order or the value set.
- Do not replace quoted normative strings in diagnostics or fixtures.
- No real genomic data, clinical interpretation, calling or deployment.
- No permission changes, no direct implementation commit to main, no auto-merge.
- Prior executor workspace was inaccessible to the `operator` account. Work uses a
  separate full-history GitHub clone and worktree; old evidence is not overwritten.

## Evidence scope of completed checkboxes

Completed implementation checkboxes below refer to the initial implementation
commit `270580ec85129f2e9a89ef8c2950d6309aa30cd9`, tree
`a7999bca24cab207c0aaf0ee399c81d9e18133b7`, or to explicitly labeled historical
RED/mutation worktree runs. They do not certify a later correction commit.
The [exact-HEAD evidence record](repository_id=1212760346; pr_number=60; comment_id=5596016415)
binds subsequent validation to the actual tested commit, tree, commands and log
digests. Until the record matches the delivered HEAD, its validation is PENDING.
Review completion and merge are separate from local validation.

## Task 1: Add regression evidence before changing implementation

**Create:** `tests/test_policy_language_compatibility.py`.
**Consumes:** existing models, taxonomy gate, attestation validator and ledger.
**Produces:** nine bounded compatibility tests with independent legacy fixtures.

- [x] Add the exact 14-entry English/legacy/wire mapping in `ENUM_CASES`.
- [x] Check aliases using `assertIn(name, enum_type.__members__)` before lookup,
  making missing names assertion failures rather than import errors.
- [x] Preserve member identity, `.name`, iteration, value lookup, repr and pickle.
- [x] Exercise 100 real taxonomy combinations; reject English identifiers as wire.
- [x] Check exact Unicode JSON bytes and manifest/ledger payload digests.
- [x] Check public/internal report serialization and attestation refusal for
  proposed/unavailable states or missing proof.
- [x] Require the three intended private test names, retaining existing assertions.
- [x] Run `python -m unittest tests.test_policy_language_compatibility -v`.
  Expected RED: English names and renamed private tests are absent. Legacy-value
  characterization tests are expected to pass before the refactor.

## Task 2: Apply the narrow compatibility migration

**Modify:** `policy_engine/genoma_policy/models.py`,
`policy_engine/genoma_policy/gates_common.py`,
`policy_engine/genoma_policy/attestation.py`,
`policy_engine/tests/test_policy_engine.py`,
`policy_engine/tests/test_schema_contract.py`.

**Produces:** preferred English access to the same pre-existing enum objects.

- [x] Append the following aliases after the legacy declarations in each class:

```python
# OperationalStatus
EXECUTED = EXECUTADO
VERIFIED = VERIFICADO
INFERRED = INFERIDO
PROPOSED = PROPOSTO
UNAVAILABLE = NAO_DISPONIVEL
# ClaimNature
CONFIRMED_FACT = FATO_CONFIRMADO
INFERENCE = INFERENCIA
ASSOCIATION = ASSOCIACAO
HYPOTHESIS = HIPOTESE
UNKNOWN = DESCONHECIDO
# Domain
CLINICAL = CLINICO
PREDISPOSITION = PREDISPOSICAO
RESEARCH = PESQUISA
CURIOSITY = CURIOSIDADE
```

- [x] Import `ClaimNature` and `Domain` in shared gates and replace only the
  redundant nature/domain literal sets with `{item.value for item in ClaimNature}`
  and `{item.value for item in Domain}`. Preserve both public constant names.
- [x] In attestation, use `OperationalStatus.EXECUTED.value`,
  `OperationalStatus.VERIFIED.value` and `OperationalStatus.INFERRED.value` in
  the satisfying set; use the first two in the applicable-proof check. Retain
  reason strings, branching, required fields and evidence-reference checks.
- [x] Rename the three test methods exactly as `TEST_RENAMES` records.
- [x] Document compatibility decisions. Apply only touched-file docstring/style
  hygiene where needed, verifying executable AST equivalence after normalization.
- [x] Rerun the new suite; expected GREEN with all nine tests passing.

## Task 3: Validate and publish one coherent reviewable block

**Create:** `docs/POLICY_CODE_LANGUAGE_INVENTORY.md`.
**Update:** approved design progress without rewriting historical evidence.

- [x] Compare every tracked file outside the explicit modification list against
  the base and report the count; protect normative, manifests, schemas, workflows,
  scientific implementations, report assets and ledger implementation bytewise.
- [x] Compare existing Python ASTs after stripping docstrings, reversing only the
  three test renames, removing the 14 additive aliases and folding the documented
  enum-value set expressions back to their exact old string constants.
- [x] Run the new suite, root suite, policy suite and ruleset-check; materialize
  only a temporary verified read-only ruleset using the repository tool.
- [x] Run `scripts/code_language_guard.py --check`, `scripts/validate_repo.py`,
  `scripts/verify_supply_chain_lock.py`, compileall and shell syntax checks.
- [x] Mutation checks must reject a changed alias target and a translated wire
  value. Restore exact bytes after each local mutation and rerun the valid tests.
- [x] Bind initial implementation validation to the recorded commit/tree below;
  keep correction validation PENDING until the linked evidence record matches it.
- [ ] Commit on the feature branch and push one locally validated block. Create a
  Draft PR, then mark Ready only after exact-HEAD checks. Recheck actual CI and
  reviewer output. Any corrective push returns to Draft first.
- [ ] No merge or automatic approval. Unavailable review/runtime is not PASS.

## Reproduction commands

Use Python 3.11 or later and a full-history clone. Install the existing
`reporting/requirements.txt` with `pip --require-hashes` in a disposable venv.
From the checkout root:

```bash
python -m unittest tests.test_policy_language_compatibility -v
PYTHONPATH=tests:. python -m unittest discover -s tests -q
python scripts/code_language_guard.py --check
python scripts/validate_repo.py
python scripts/verify_supply_chain_lock.py
python -m compileall -q policy_engine/genoma_policy scripts evidence_adapters
for path in scripts/*.sh; do bash -n "$path" || exit; done
git diff --check
```

For canonical policy tests, use `scripts/materialize_ruleset.py --output-dir`
with an empty temporary directory; set `GENOMA_RULESET_PATH` to its canonical
file and `GENOMA_EXPECT_CANONICAL_SHA=1`, then run from `policy_engine`:

```bash
python -m unittest discover -s tests -q
python -m genoma_policy ruleset-check
```

Remove only that temporary materialization after validation; do not modify or
copy the old executor's canonical runtime. No post-deployment PASS is implied.


## Portable executable-equivalence check

Run the following from this stage-four checkout in a full-history clone. It
uses only the Python standard library and Git; it does not import or execute
the historical production sources. The expected result before unrelated future
changes is five AST matches and 385 protected-file byte matches. The recorded
comparison digest is `bc7d994a47ec89974747eb1886c224e486c30bab2e23ddf06703926e50fbcfcb`.
Run it on the PR SHA, not on a later main containing further changes.

```bash
python - <<'PY'
"""Compare only the explicitly approved stage-four transformations to their base."""
import ast
import hashlib
import json
import pathlib
import subprocess

BASE = 'fe916c5f567380b5756dcdeab2df6af6767f296b'
EXISTING = (
    'policy_engine/genoma_policy/models.py',
    'policy_engine/genoma_policy/gates_common.py',
    'policy_engine/genoma_policy/attestation.py',
    'policy_engine/tests/test_policy_engine.py',
    'policy_engine/tests/test_schema_contract.py',
)
DOCS = {
    'docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md',
    'docs/POLICY_CODE_LANGUAGE_INVENTORY.md',
    'docs/superpowers/plans/2026-09-09-policy-evidence-audit-english.md',
}
ALIASES = {
    'OperationalStatus': dict(EXECUTED='EXECUTADO', VERIFIED='VERIFICADO',
        INFERRED='INFERIDO', PROPOSED='PROPOSTO', UNAVAILABLE='NAO_DISPONIVEL'),
    'ClaimNature': dict(CONFIRMED_FACT='FATO_CONFIRMADO', INFERENCE='INFERENCIA',
        ASSOCIATION='ASSOCIACAO', HYPOTHESIS='HIPOTESE', UNKNOWN='DESCONHECIDO'),
    'Domain': dict(CLINICAL='CLINICO', PREDISPOSITION='PREDISPOSICAO',
        RESEARCH='PESQUISA', CURIOSITY='CURIOSIDADE'),
}
RENAMES = {
    'test_duplicate_active_ruleset_fails_closed': 'test_duplicate_vigente_fails_closed',
    'test_ruleset_gate_rejects_inactive_status': 'test_ruleset_gate_rejects_non_vigente_status',
    'test_ruleset_requires_active_status': 'test_ruleset_requires_vigente_status',
}
SETS = {
    'ALLOWED_NATURE': ('{nature.value for nature in ClaimNature}',
        '{"FATO CONFIRMADO", "INFERÊNCIA", "ASSOCIAÇÃO", "HIPÓTESE", "DESCONHECIDO"}'),
    'ALLOWED_DOMAIN': ('{domain.value for domain in Domain}',
        '{"CLÍNICO", "PREDISPOSIÇÃO", "PESQUISA", "CURIOSIDADE"}'),
}


def dump(node):
    return ast.dump(node, include_attributes=False)


class Normalize(ast.NodeTransformer):
    def __init__(self, path, current):
        self.path = path
        self.current = current
        self.alias_count = 0

    def generic_visit(self, node):
        node = super().generic_visit(node)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body.pop(0)
        return node

    def visit_ClassDef(self, node):
        if self.current and self.path.endswith('/models.py') and node.name in ALIASES:
            aliases = ALIASES[node.name]
            body = []
            seen = set()
            for statement in node.body:
                if (isinstance(statement, ast.Assign) and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                        and statement.targets[0].id in aliases):
                    name = statement.targets[0].id
                    assert dump(statement.value) == dump(ast.Name(id=aliases[name], ctx=ast.Load()))
                    seen.add(name)
                    self.alias_count += 1
                else:
                    body.append(statement)
            assert seen == set(aliases), (node.name, seen)
            node.body = body
        return self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if self.current and '/tests/' in self.path and node.name in RENAMES:
            node.name = RENAMES[node.name]
        return self.generic_visit(node)

    def visit_ImportFrom(self, node):
        if self.current and self.path.endswith('/gates_common.py') and node.module == 'models':
            node.names = [item for item in node.names if item.name not in {'ClaimNature', 'Domain'}]
        return node

    def visit_Assign(self, node):
        if self.current and self.path.endswith('/gates_common.py') and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in SETS:
                expected, original = SETS[target.id]
                assert dump(node.value) == dump(ast.parse(expected, mode='eval').body)
                node.value = ast.parse(original, mode='eval').body
        return self.generic_visit(node)

    def visit_Attribute(self, node):
        if self.current and self.path.endswith('/attestation.py'):
            if (node.attr == 'value' and isinstance(node.value, ast.Attribute)
                    and isinstance(node.value.value, ast.Name)
                    and node.value.value.id == 'OperationalStatus'):
                name = node.value.attr
                assert name in {'EXECUTED', 'VERIFIED', 'INFERRED'}, name
                return ast.Constant(value=ALIASES['OperationalStatus'][name])
        return self.generic_visit(node)


root = pathlib.Path.cwd()
matched = []
for path in EXISTING:
    old = subprocess.check_output(['git', 'show', f'{BASE}:{path}']).decode('utf-8')
    new = (root / path).read_text(encoding='utf-8')
    before = Normalize(path, False).visit(ast.parse(old))
    normalizer = Normalize(path, True)
    after = normalizer.visit(ast.parse(new))
    if path.endswith('/models.py'):
        assert normalizer.alias_count == 14
    assert dump(before) == dump(after), f'Unexpected executable change: {path}'
    matched.append(path)

protected = {}
paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', BASE]).decode().splitlines()
for path in paths:
    if path in EXISTING or path in DOCS:
        continue
    before = subprocess.check_output(['git', 'show', f'{BASE}:{path}'])
    after = (root / path).read_bytes()
    assert before == after, f'Protected blob changed: {path}'
    protected[path] = hashlib.sha256(after).hexdigest()
result = {'base': BASE, 'ast_matches': matched, 'protected_file_count': len(protected),
          'protected_files': protected}
raw = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
print(json.dumps({'base': BASE, 'ast_match_count': len(matched),
    'protected_file_count': len(protected), 'comparison_sha256': hashlib.sha256(raw).hexdigest()}, indent=2))
PY
```


## Complete canonical-test command

From the checkout root with the selected Python on PATH, this block materializes
only a disposable, byte-verified copy and removes only that temporary directory.
It never replaces the installed runtime or commits plaintext normative content.

```bash
set -eu
REPO_ROOT="$PWD"
RULESET_TMP=$(mktemp -d)
trap 'rm -rf -- "$RULESET_TMP"' EXIT
python scripts/materialize_ruleset.py --output-dir "$RULESET_TMP"
export GENOMA_RULESET_PATH="$RULESET_TMP/REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
export GENOMA_RULESET_SHA_MANIFEST="$REPO_ROOT/manifests/RULESET_V3.4.sha256"
export GENOMA_EXPECT_CANONICAL_SHA=1
head -4 "$GENOMA_RULESET_PATH"
stat -c '%a' "$GENOMA_RULESET_PATH"
sha256sum "$GENOMA_RULESET_PATH"
(cd policy_engine && python -m unittest discover -s tests -q)
(cd policy_engine && python -m genoma_policy ruleset-check)
```

## Historical exact-HEAD validation: initial implementation

**Tested commit:** `270580ec85129f2e9a89ef8c2950d6309aa30cd9`
**Tested Git tree:** `a7999bca24cab207c0aaf0ee399c81d9e18133b7`
**Base:** `fe916c5f567380b5756dcdeab2df6af6767f296b`
**Execution log SHA-256:** `066e9d0e4dd375079e9518dc90833cb9c63825b9c88b4d875793eaf645f1bc2a`

These commands were executed after the initial commit, with a clean worktree.
The exact reproduction commands and canonical environment setup appear above.

| Command or check | Observed result on the tested commit |
| --- | --- |
| `python -m unittest tests.test_policy_language_compatibility -v` | 9 tests, OK, 0.007 s |
| `PYTHONPATH=tests:. python -m unittest discover -s tests -q` | 964 tests, OK, one skip, 73.798 s |
| `cd policy_engine && python -m unittest discover -s tests -q` | 47 tests, OK, 1.241 s |
| `cd policy_engine && python -m genoma_policy ruleset-check` | PASS; canonical v3.4 identity and 263 sections |
| `python scripts/code_language_guard.py --check` | Exit 0 |
| `python scripts/validate_repo.py` | Exit 0 |
| `python scripts/verify_supply_chain_lock.py` | Exit 0 |
| `python -m compileall -q policy_engine/genoma_policy policy_engine/tests scripts evidence_adapters tests` | Exit 0 |
| `bash -n` on every `scripts/*.sh` | Exit 0 |
| pycodestyle 2.14.0, maximum line length 119, six changed Python files | Exit 0 |
| pydocstyle 6.3.0, pep257 convention, same six files | Exit 0 |
| Executable-equivalence procedure above | Five existing AST matches; 385 protected files byte-identical |
| Working-tree and base-to-HEAD `git diff --check` | Exit 0 |

The nine compatibility tests are included in the root suite, not added to 964.
The canonical test input was a disposable mode-444 materialization whose SHA-256
was `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.
The header read `VIGENTE`, `v3.4`, `17/08/2026`; all 263 sections were verified.
Only that temporary materialization was removed. No deployment status is granted.

Remote executions of the same initial implementation are independently linked:
[canonical policy workflow](repository_id=1212760346; run_id=34311670771)
and [scaffold workflow](repository_id=1212760346; run_id=34311670863).
Consult their actual job outcomes; scope-skipped jobs are not executions.

## Historical RED, mutation and diagnostic evidence

The merged-base root suite on `fe916c5f567380b5756dcdeab2df6af6767f296b`
ran 955 tests with one skip and no failures. The pre-implementation RED execution
used that base plus the newly written test overlay, not a committed test revision.
It produced 38 assertion/subtest failures for absent English access and old names;
three independent legacy-characterization tests already passed.

The mutation runs intentionally changed an uncommitted model copy: a wrong alias
target produced four assertion failures, and a translated verified wire value
produced 24. Original bytes were restored in `finally`, then the positive suite
was rerun. These are explicitly mutation-worktree runs, not clean-commit PASS
claims. The wire test checks exact value before value lookup so corruption is an
assertion failure rather than a secondary lookup exception.

| Historical artifact | SHA-256 |
| --- | --- |
| `red.log` | `bde556d5deecea5ba16d0f64ee41dde35c611e30d4976f8e4f1fd281ec85ab48` |
| `wrong-alias-target-final.log` | `59ac2c1ef6a9d2da59ce05ce09ed1720bf9d00c3cb8536d65eab043a87eebea7` |
| `translated-wire-value-final.log` | `013203ac42f9192878e44a58c5319e997b92b48587a1d67fd86a9eb05942c287` |

Mypy 1.18.2 on the three production files reproduced one existing `union-attr`
diagnostic in unchanged `evaluation_binding` on the merged base and the initial
implementation. Zero new diagnostics were observed; this is not a typing-clean
claim. No suppression or unrelated production fix was added.

## Review correction and delivered-HEAD evidence

CodeRabbit review `5149852490` requested an explicit inventory procedure link,
commit/tree-bound validation evidence, and strict pairing of fields with enum
cases. The inventory now names this plan and the exact unittest command. The
wire-rejection loop now uses `zip(..., strict=True)`; all original assertions
and normative input values remain intact. No production logic changes belong to
this correction.

A commit cannot embed its own final SHA without changing that SHA. Therefore
**correction validation remains PENDING in this static note** until the
[exact-HEAD evidence record](repository_id=1212760346; pr_number=60; comment_id=5596016415)
identifies the delivered commit and its Git tree, with commands, actual results
and artifact digests. This is a real existing evidence link, not a placeholder.
A reviewer must compare its tested SHA to the PR HEAD. Neither this historical
note nor a prior CI success certifies a different commit. External review and
manual merge remain independent requirements even after local validation.

Retained local evidence root:
`/home/operator/DeskRemoteWorkspace/codework-audit/policy-english-stage4/`.
Initial logs remain preserved. Correction logs use distinct filenames rather
than overwriting the initial exact-HEAD proof. Local paths are not public
artifact URLs; the committed procedures and linked evidence record provide the
review path. No automatic approval or post-deployment PASS is implied.
