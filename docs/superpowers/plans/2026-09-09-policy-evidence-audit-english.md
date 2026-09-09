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
- Prior executor workspace was inaccessible to the `hudson` account. Work uses a
  separate full-history GitHub clone and worktree; old evidence is not overwritten.

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
- [ ] Bind final validation to committed SHA/tree and retain logs outside Git.
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

## Local validation notes

The initial merged-base root suite passed 955 tests with one intentional skip.
The new suite initially failed 38 assertion/subtests for absent English access
and old private names; three characterization tests already passed. All nine
passed after implementation. A wrong alias target was rejected with four
assertion failures; translating the verified wire value was rejected with 24.
Original model bytes were restored in `finally` before successful revalidation.
The final wire mutation checks the exact value before attempting value lookup,
so corruption is reported as an assertion failure rather than a secondary
lookup exception. No assertion or accepted payload was removed.

Canonical policy validation ran 47 tests successfully using mode-444 materialized
ruleset bytes; ruleset-check verified v3.4/VIGENTE/17-08-2026, the canonical SHA
and all 263 sections. These synthetic executions do not claim deployment.

Local mypy 1.18.2 on the three production files reproduced one pre-existing
`union-attr` diagnostic in `evaluation_binding` on both the merged base and the
refactor. That expression is unchanged. Zero new diagnostics were observed; this
is not a whole-repository typing-clean claim. No type suppression was added.

Retained local evidence root:
`/home/hudson/DeskRemoteWorkspace/codework-audit/policy-english-stage4/`.
Files include `baseline-root.log`, `red.log`, `green-after-hygiene.log`,
`wrong-alias-target-final.log`, `translated-wire-value-final.log`,
`policy-suite.log`, `ruleset-check.json`, `compatibility.json`,
`mypy-baseline.log`, `mypy.log`, `environment.txt`, and dependency setup logs.
These are local locators, not public download links. Final committed-SHA results
and log digests are recorded in the PR to avoid self-referential commit evidence.
Earlier local attempts remain retained; only final named results support release.
