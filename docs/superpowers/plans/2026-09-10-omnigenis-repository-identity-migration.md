# OmniGenis Repository Identity Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the existing GitHub repository from `repository_id=1212760346; historical_repository_name=Codework` to `repository_id=1212760346; repository_name=OmniGenis` while preserving repository identity, governance, CI, scientific contracts, and intentionally deferred internal `codework-*` compatibility surfaces.

**Architecture:** Execute the repository mutation as a controlled identity migration, capture pre/post evidence around the stable GitHub repository object, then update only active repository-address references through a governed post-rename pull request. Internal runtime names remain unchanged until a separately approved Phase 2.

**Tech Stack:** GitHub REST API via authenticated `gh` CLI, Git, Python 3.12, `unittest`, GitHub Actions, existing repository validation/language guards, CodeRabbit, GitGuardian, DeepSource, Snyk, and Semgrep.

**Spec:** `docs/superpowers/specs/2026-09-10-omnigenis-repository-identity-migration-design.md`

## Global Constraints

- The repository must remain the same GitHub object with repository ID `1212760346`; do not create a replacement repository.
- The repository name changes only from `Codework` to `OmniGenis` in Phase 1.
- Repository visibility remains `public`.
- Preserve `main` history and the exact pre-rename SHA observed immediately before the mutation.
- Preserve the canonical GENOMA v3.4 filename, version, date, SHA-256, sealed transport, evidence schemas, taxonomies, and scientific semantics.
- Preserve `/opt/codework`, `/etc/codework`, `codework-genome`, `codework-isolated`, `codework-genome-mcp`, `codework-private-genome`, `codework-codex`, `CODEWORK_CODERABBIT_BIN_DIR`, and `codework/genome-runtime` in Phase 1.
- Do not rewrite historical PR/run URLs or immutable evidence solely because the repository is renamed.
- Do not weaken required status checks, branch rulesets, security review, or fail-closed behavior.
- Do not add personal genomic data, patient data, credentials, tokens, or secrets.
- All new or modified technical code, tests, comments, docstrings, internal messages, and developer-facing documentation must be written in English, except existing explicit normative/localized/canonical/historical/compatibility-preserved surfaces.
- Auto-merge remains disabled; final merge requires explicit human action.

---

### Task 1: Capture the pre-rename repository and governance state

**Files:**
- Create outside Git: `/tmp/omnigenis-rename-pre/repository.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/main.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/rulesets.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/ruleset-22347095.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/ruleset-21303100.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/open-pulls.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/branches.json`
- Create outside Git: `/tmp/omnigenis-rename-pre/manifest.sha256`

**Interfaces:**
- Consumes: authenticated `gh`, repository `repository_id=1212760346; historical_repository_name=Codework`, current `origin/main`.
- Produces: immutable pre-mutation evidence used by Tasks 2 and 3.

- [ ] **Step 1: Refresh the remote and assert the approved baseline has not moved**

```bash
cd /srv/remote-desktop-commander-workspace/codework-audit/Codework/.worktrees/omnigenis-repository-rename-design
git fetch origin --prune
test "$(git rev-parse origin/main)" = "ae3cd2166d1f6ed5875fdb8be7d82543c962ee54"
```

Expected: exit `0`. If `origin/main` differs, stop and revalidate the plan against the new HEAD before any mutation.- [ ] **Step 2: Capture the raw GitHub state without mutating it**

```bash
rm -rf /tmp/omnigenis-rename-pre
mkdir -p /tmp/omnigenis-rename-pre
gh api repos/$repo > /tmp/omnigenis-rename-pre/repository.json
gh api repos/$repo/commits/main > /tmp/omnigenis-rename-pre/main.json
gh api repos/$repo/rulesets > /tmp/omnigenis-rename-pre/rulesets.json
gh api repos/$repo/rulesets/22347095 > /tmp/omnigenis-rename-pre/ruleset-22347095.json
gh api repos/$repo/rulesets/21303100 > /tmp/omnigenis-rename-pre/ruleset-21303100.json
gh api 'repos/$repo/pulls?state=open&per_page=100' > /tmp/omnigenis-rename-pre/open-pulls.json
gh api --paginate --slurp 'repos/$repo/branches?per_page=100' > /tmp/omnigenis-rename-pre/branches.json
(cd /tmp/omnigenis-rename-pre && sha256sum *.json | sort > manifest.sha256)
```

Expected: all files exist and no command prints credentials.

- [ ] **Step 3: Assert the pre-rename invariants from captured evidence**

```bash
python3 - <<'PY'
import json
from pathlib import Path
root = Path('/tmp/omnigenis-rename-pre')
repo = json.loads((root / 'repository.json').read_text())
main = json.loads((root / 'main.json').read_text())
pulls = json.loads((root / 'open-pulls.json').read_text())
rulesets = json.loads((root / 'rulesets.json').read_text())
assert repo['id'] == 1212760346
assert repo['name'] == 'Codework'
assert repo['visibility'] == 'public'
assert repo['default_branch'] == 'main'
assert main['sha'] == 'ae3cd2166d1f6ed5875fdb8be7d82543c962ee54'
assert pulls == []
assert {r['id'] for r in rulesets} == {22347095, 21303100}
print('PRE_RENAME_GATE=PASS')
PY
```

Expected: `PRE_RENAME_GATE=PASS`.

### Task 2: Rename the existing GitHub repository object

**Files:**
- Create outside Git: `/tmp/omnigenis-rename-post/repository.json`
- Create outside Git: `/tmp/omnigenis-rename-post/main.json`
- Create outside Git: `/tmp/omnigenis-rename-post/rulesets.json`
- Create outside Git: `/tmp/omnigenis-rename-post/ruleset-22347095.json`
- Create outside Git: `/tmp/omnigenis-rename-post/ruleset-21303100.json`
- Create outside Git: `/tmp/omnigenis-rename-post/manifest.sha256`

**Interfaces:**
- Consumes: Task 1 evidence and authenticated repository-admin capability through `gh api`.
- Produces: canonical repository name `repository_id=1212760346; repository_name=OmniGenis` on the same repository ID.

- [ ] **Step 1: Recheck the mutation preconditions immediately before PATCH**

```bash
test "$(gh api repos/$repo --jq .id)" = "1212760346"
test "$(gh api repos/$repo/commits/main --jq .sha)" = "ae3cd2166d1f6ed5875fdb8be7d82543c962ee54"
test "$(gh api 'repos/$repo/pulls?state=open&per_page=100' --jq 'length')" = "0"
```

Expected: exit `0`; otherwise stop.

- [ ] **Step 2: Perform the repository rename using the existing GitHub object**

```bash
gh api --method PATCH repos/$repo -f name=OmniGenis
```

Expected: response field `name` is `OmniGenis` and `id` remains `1212760346`.- [ ] **Step 3: Capture post-rename state and verify identity continuity**

```bash
rm -rf /tmp/omnigenis-rename-post
mkdir -p /tmp/omnigenis-rename-post
gh api repos/$repo > /tmp/omnigenis-rename-post/repository.json
gh api repos/$repo/commits/main > /tmp/omnigenis-rename-post/main.json
gh api repos/$repo/rulesets > /tmp/omnigenis-rename-post/rulesets.json
gh api repos/$repo/rulesets/22347095 > /tmp/omnigenis-rename-post/ruleset-22347095.json
gh api repos/$repo/rulesets/21303100 > /tmp/omnigenis-rename-post/ruleset-21303100.json
(cd /tmp/omnigenis-rename-post && sha256sum *.json | sort > manifest.sha256)
python3 - <<'PY'
import json
from pathlib import Path

pre_root = Path('/tmp/omnigenis-rename-pre')
post_root = Path('/tmp/omnigenis-rename-post')
expected_ids = {21303100, 22347095}


def normalize_ruleset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding='utf-8'))
    required_status_contexts = []
    for rule in data.get('rules', []):
        if rule.get('type') == 'required_status_checks':
            required_status_contexts = [
                item['context']
                for item in rule.get('parameters', {}).get('required_status_checks', [])
            ]
    return {
        'id': data['id'],
        'name': data['name'],
        'enforcement': data['enforcement'],
        'conditions': data.get('conditions'),
        'rules': data.get('rules'),
        'bypass_actors': data.get('bypass_actors', []),
        'required_status_contexts': required_status_contexts,
    }

repo = json.loads((post_root / 'repository.json').read_text(encoding='utf-8'))
main = json.loads((post_root / 'main.json').read_text(encoding='utf-8'))
rulesets = json.loads((post_root / 'rulesets.json').read_text(encoding='utf-8'))
ruleset_semantics_pre = {
    str(rid): normalize_ruleset(pre_root / f'ruleset-{rid}.json') for rid in expected_ids
}
ruleset_semantics_post = {
    str(rid): normalize_ruleset(post_root / f'ruleset-{rid}.json') for rid in expected_ids
}

assert repo['id'] == 1212760346
assert repo['name'] == 'OmniGenis'
assert repo['full_name'] == 'repository_id=1212760346; repository_name=OmniGenis'
assert repo['visibility'] == 'public'
assert repo['default_branch'] == 'main'
assert main['sha'] == 'ae3cd2166d1f6ed5875fdb8be7d82543c962ee54'
assert {r['id'] for r in rulesets} == expected_ids
assert {int(key) for key in ruleset_semantics_pre} == expected_ids
assert ruleset_semantics_pre == ruleset_semantics_post
print('POST_RENAME_GATE=PASS')
print('RULESET_SEMANTICS_CONTINUITY=PASS')
PY
```

Expected: `POST_RENAME_GATE=PASS`.- [ ] **Step 4: Verify old and new Git endpoints resolve to the same `main` SHA**

```bash
old_sha="$(git ls-remote https://github.com/repository_id=1212760346; historical_repository_name=Codework.git refs/heads/main | cut -f1)"
new_sha="$(git ls-remote https://github.com/repository_id=1212760346; repository_name=OmniGenis.git refs/heads/main | cut -f1)"
test "$old_sha" = "$new_sha"
test "$new_sha" = "ae3cd2166d1f6ed5875fdb8be7d82543c962ee54"
printf 'OLD_URL_MAIN=%s\nNEW_URL_MAIN=%s\n' "$old_sha" "$new_sha"
```

Expected: both endpoints resolve to the same pre-rename commit.

- [ ] **Step 5: Roll back only if the repository-object invariants fail**

If Task 2 Step 3 shows a changed repository ID, lost rulesets, wrong visibility, or wrong default branch, stop all further work. If the new repository endpoint is functional, restore the same object name with:

```bash
gh api --method PATCH repos/$repo -f name=Codework
```

Then verify repository ID `1212760346` and the pre-rename `main` SHA before reporting the failure. Do not create another repository and do not bypass governance.

### Task 3: Move the authorized Ubuntu checkout to the new remote identity

**Files:**
- Modify Git metadata only: repository `origin` URL.
- Create isolated worktree: `.worktrees/omnigenis-repository-identity`.

**Interfaces:**
- Consumes: renamed GitHub repository from Task 2.
- Produces: a post-rename implementation branch based on the unchanged `main` commit.

- [ ] **Step 1: Update the shared Git remote URL and fetch from `OmniGenis`**

```bash
cd /srv/remote-desktop-commander-workspace/codework-audit/Codework
git remote set-url origin https://github.com/repository_id=1212760346; repository_name=OmniGenis.git
git fetch origin --prune
test "$(git remote get-url origin)" = "https://github.com/repository_id=1212760346; repository_name=OmniGenis.git"
test "$(git rev-parse origin/main)" = "ae3cd2166d1f6ed5875fdb8be7d82543c962ee54"
```

Expected: fetch succeeds and history is unchanged.

- [ ] **Step 2: Create the post-rename implementation worktree from `origin/main`**

```bash
cd /srv/remote-desktop-commander-workspace/codework-audit/Codework
git check-ignore -q .worktrees
git worktree add .worktrees/omnigenis-repository-identity -b chore/omnigenis-repository-identity origin/main
cd .worktrees/omnigenis-repository-identity
git status -sb
```

Expected: clean branch `chore/omnigenis-repository-identity` at the unchanged `main` SHA.- [ ] **Step 3: Bring the approved design and implementation plan into the post-rename branch**

```bash
cd /srv/remote-desktop-commander-workspace/codework-audit/Codework/.worktrees/omnigenis-repository-identity
git fetch origin docs/omnigenis-repository-rename-design
git cherry-pick $(git rev-list --reverse origin/main..origin/docs/omnigenis-repository-rename-design)
```

Expected: the design and plan commits are present without modifying runtime code.

- [ ] **Step 4: Persist a concise pre/post rename evidence record**

Create `docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json` containing only non-secret fields: repository ID, old/new full names, pre/post `main` SHA, visibility, default branch, normalized pre/post ruleset semantics, required status contexts, old/new Git endpoint verification, UTC timestamps, and SHA-256 values of the raw `/tmp/omnigenis-rename-*/*.json` captures.

The committed evidence must also contain an immutable raw-capture attestation for both the pre-rename and post-rename capture directories. Record the ephemeral location, SHA-256 of `manifest.sha256`, every per-file digest already captured, the exact byte-verification command `sha256sum -c manifest.sha256`, and the observed verification result. This makes the Git record self-describing even after `/tmp` is reclaimed.

Record an authenticated recovery-reference verification: enumerate the GitHub App installation and selected repositories to prove access to repository ID `1212760346`, and query PR `#2` to record its observed state instead of asserting that state in recovery prose. Store only normalized non-secret output in the evidence artifact.

Use Python standard-library JSON serialization with `sort_keys=True` and `indent=2`. Do not embed authentication headers, tokens, cookies, or environment secrets.

- [ ] **Step 5: Commit the evidence-only checkpoint**

The design and plan arrive as already committed cherry-picks. Stage only the newly generated evidence record:

```bash
git add docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json
git diff --cached --check
git commit -m "docs: record OmniGenis repository identity migration evidence"
```

Expected: the new commit contains only the non-secret migration evidence record.

### Task 4: Add a fail-closed repository identity characterization test

**Files:**
- Create: `tests/test_repository_identity_migration.py`

**Interfaces:**
- Consumes: active documentation and preserved internal technical contracts.
- Produces: an executable boundary between Phase 1 repository identity changes and deferred Phase 2 internal renaming.

- [ ] **Step 1: Write the failing characterization tests before editing active references**

```python
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class RepositoryIdentityMigrationTest(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_active_repository_identity_uses_omnigenis(self):
        active = [
            "AGENTS.md",
            "docs/BRANCH_GOVERNANCE.md",
            "docs/GITHUB_MOBILE_IMPORT.md",
            "docs/MAGALU_PRIVATE_MCP_SETUP.md",
            "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md",
        ]
        for path in active:
            text = self.read(path)
            self.assertNotIn("repository_id=1212760346; historical_repository_name=Codework", text, path)
        self.assertIn("GENOMA OmniGenis", self.read("AGENTS.md"))
    def test_public_repository_state_is_documented(self):
        self.assertIn("Public, reproducible genomics execution repository", self.read("README.md"))
        self.assertIn("public, reproducible genomics runtime", self.read("AGENTS.md"))

    def test_historical_repository_urls_are_preserved(self):
        self.assertIn(
            "repository_id=1212760346; pr_number=60",
            self.read("docs/POLICY_CODE_LANGUAGE_INVENTORY.md"),
        )
        self.assertIn(
            "repository_id=1212760346; pr_number=61",
            self.read("docs/REPORTING_CODE_LANGUAGE_INVENTORY.md"),
        )

    def test_phase_two_internal_contracts_are_unchanged(self):
        self.assertIn("WORKDIR /opt/codework", self.read("Dockerfile"))
        self.assertIn("codework-isolated", self.read(".github/workflows/scaffold-validation.yml"))
        self.assertIn('"name": "codework-genome-mcp"', self.read("mcp/package.json"))
        self.assertIn("name: codework-ngs", self.read("environment.yml"))
        self.assertIn("name = 'codework/genome-runtime'", self.read("nextflow.config"))
        self.assertIn("CODEWORK_CODERABBIT_BIN_DIR", self.read("scripts/codex/setup-coderabbit.sh"))

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```bash
python3 -m unittest tests.test_repository_identity_migration -v
```

Expected before Task 5: failures on current `Codework`/private repository identity text, while the Phase 2 preservation assertions already pass.

### Task 5: Update only active repository identity and visibility documentation

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/BRANCH_GOVERNANCE.md`
- Modify: `docs/GITHUB_MOBILE_IMPORT.md`
- Modify: `docs/MAGALU_PRIVATE_MCP_SETUP.md`
- Modify: `docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md`
- Test: `tests/test_repository_identity_migration.py`

**Interfaces:**
- Consumes: failing characterization test from Task 4.
- Produces: current documentation that names `OmniGenis`, accurately states public repository visibility, and preserves private runtime/data boundaries.

- [ ] **Step 1: Update the repository-level current-state identity**

Make these exact semantic changes:

```text
README.md:
"Private, reproducible genomics execution repository..."
→ "Public, reproducible genomics execution repository..."

AGENTS.md:
"# AGENTS.md — GENOMA Codework"
→ "# AGENTS.md — GENOMA OmniGenis"
"This repository is a private, reproducible genomics runtime."
→ "This repository is a public, reproducible genomics runtime."
```

Do not change the canonical GENOMA v3.4 identity or code-language policy.- [ ] **Step 2: Update active GitHub repository references**

Apply only current-state repository identity changes:

```text
docs/BRANCH_GOVERNANCE.md:
`repository_id=1212760346; historical_repository_name=Codework` → `repository_id=1212760346; repository_name=OmniGenis`

docs/GITHUB_MOBILE_IMPORT.md:
current repository name `Codework` → `OmniGenis`
current repository visibility wording → public repository wording
keep `codework-genome-runtime-2026-08-15.zip` unchanged

docs/MAGALU_PRIVATE_MCP_SETUP.md:
repository selection `Codework` → `OmniGenis`
clone URL `${GITHUB_REPOSITORY_OWNER}/Codework.git` → `${GITHUB_REPOSITORY_OWNER}/OmniGenis.git`
keep `/opt/codework`, `/etc/codework`, `codework-genome`, `codework-isolated`, tunnel profile names, and private MCP wording unchanged

docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md:
source repository visibility → public repository with no personal genomic data
clone URL `${GITHUB_REPOSITORY_OWNER}/Codework.git` → `${GITHUB_REPOSITORY_OWNER}/OmniGenis.git`
`cd Codework` → `cd OmniGenis`
keep GHCR image names and `/opt/codework` runtime paths unchanged
```

- [ ] **Step 3: Correct public-repository/self-hosted-runner safety wording without changing workflow behavior**

In `docs/MAGALU_PRIVATE_MCP_SETUP.md`, replace the obsolete instruction to make the repository private before attaching a runner with English guidance stating that the repository is public, untrusted pull-request code must stay on GitHub-hosted runners, and the private `codework-isolated` runner is reserved for trusted protected-`main` execution. Do not modify workflow YAML in Phase 1.- [ ] **Step 4: Re-run the repository identity characterization tests and verify GREEN**

Run:

```bash
python3 -m unittest tests.test_repository_identity_migration -v
```

Expected: all repository identity, historical-preservation, public-state, and Phase 2 boundary tests pass.

- [ ] **Step 5: Prove no unintended active hard-coded old repository address remains**

Run:

```bash
python3 - <<'PY'
import subprocess
from pathlib import Path

needle = 'repository_id=1212760346; historical_repository_name=Codework'
allowed_historical_old_references = {
    'docs/POLICY_CODE_LANGUAGE_INVENTORY.md',
    'docs/REPORTING_CODE_LANGUAGE_INVENTORY.md',
    'docs/superpowers/checkpoints/2026-09-03-local-first-ci-session.md',
    'docs/superpowers/plans/2026-09-05-four-plane-audit-static-dependency.md',
    'docs/superpowers/plans/2026-09-08-scientific-internals-english.md',
    'docs/superpowers/plans/2026-09-09-policy-evidence-audit-english.md',
    'docs/superpowers/plans/2026-09-09-reporting-english-locale.md',
    'docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md',
    'docs/superpowers/specs/2026-09-03-local-first-ci-architecture-design.md',
    'docs/superpowers/specs/2026-09-05-draft-first-final-ci-design.md',
    'docs/superpowers/specs/2026-09-05-four-plane-audit-static-dependency-design.md',
}
migration_identity_records = {
    'docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json',
    'docs/superpowers/plans/2026-09-10-omnigenis-repository-identity-migration.md',
    'docs/superpowers/specs/2026-09-10-omnigenis-repository-identity-migration-design.md',
    'tests/test_repository_identity_migration.py',
}

result = subprocess.run(
    ['git', 'grep', '-n', needle, '--'],
    text=True,
    capture_output=True,
    check=False,
)
if result.returncode not in (0, 1):
    raise SystemExit(result.stderr or f'git grep failed with {result.returncode}')

unexpected_old_references = []
for line in result.stdout.splitlines():
    file_path = line.split(':', 1)[0]
    if file_path.startswith('docs/history/') or file_path in migration_identity_records:
        continue
    if file_path in allowed_historical_old_references:
        baseline = subprocess.run(
            ['git', 'show', f'origin/main:{file_path}'],
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        current = Path(file_path).read_text(encoding='utf-8')
        if current == baseline:
            continue
    unexpected_old_references.append(line)

if unexpected_old_references:
    raise SystemExit(
        'Unexpected old repository references:
' + '
'.join(unexpected_old_references)
    )
print('OLD_REPOSITORY_REFERENCE_GATE=PASS')
PY
```

Expected: the only old repository references outside immutable `docs/history/**` and the migration record itself are the explicitly listed historical files, and each listed file must remain byte-identical to `origin/main`. Any current operational reference or modified historical allowance is blocking.

- [ ] **Step 6: Review the Phase 1 preservation boundary**

Run:

```bash
python3 - <<'PY'
import subprocess

phase2_changed_paths = subprocess.run(
    [
        'git', 'diff', '--name-only', 'origin/main', '--',
        'Dockerfile', 'environment.yml', 'nextflow.config',
        '.github/workflows', 'mcp', 'scripts/codex/setup-coderabbit.sh',
    ],
    text=True,
    capture_output=True,
    check=True,
).stdout.splitlines()
if phase2_changed_paths:
    raise SystemExit(
        'Phase 2 contract files changed during Phase 1:
'
        + '
'.join(phase2_changed_paths)
    )
print('PHASE2_PRESERVATION_GATE=PASS')
PY
```

Expected: `phase2_changed_paths` is empty. Any changed Phase 2 contract path is blocking.

### Task 6: Run full local validation at the exact implementation HEAD

**Files:**
- No new implementation files beyond Tasks 3–5.

**Interfaces:**
- Consumes: completed Phase 1 documentation/test changes.
- Produces: exact-HEAD local evidence suitable for the pull request body.

- [ ] **Step 1: Run the repository validator and supply-chain verification**

```bash
python3 scripts/validate_repo.py
python3 scripts/verify_supply_chain_lock.py
```

Expected: both commands exit `0`.

- [ ] **Step 2: Run the complete root regression suite**

```bash
python3 -m unittest discover -s tests -v
```

Expected: `OK` with zero failures and zero errors.

- [ ] **Step 3: Re-run the English-first and residual-language gates**

```bash
python3 scripts/code_language_guard.py --check
python3 scripts/residual_language_audit.py --check
python3 -m unittest tests.test_developer_documentation_language -v
```

Expected: all gates pass; no new Portuguese technical implementation or developer-facing prose is introduced.- [ ] **Step 4: Run shell syntax and diff-integrity checks**

```bash
bash -n scripts/*.sh
git diff --check
git status -sb
```

Expected: shell syntax passes, no whitespace errors, and only intended Phase 1 files are modified.

- [ ] **Step 5: Inspect the final diff against renamed `origin/main`**

```bash
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
git diff origin/main...HEAD -- README.md AGENTS.md docs/BRANCH_GOVERNANCE.md docs/GITHUB_MOBILE_IMPORT.md docs/MAGALU_PRIVATE_MCP_SETUP.md docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md tests/test_repository_identity_migration.py
```

Expected: no scientific code, normative bytes, workflow behavior, dependency pins, evidence semantics, or internal `codework-*` contracts are changed.

- [ ] **Step 6: Commit the coherent validated implementation block**

```bash
git add README.md AGENTS.md docs/BRANCH_GOVERNANCE.md docs/GITHUB_MOBILE_IMPORT.md \
        docs/MAGALU_PRIVATE_MCP_SETUP.md docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md \
        tests/test_repository_identity_migration.py
git diff --cached --check
git commit -m "chore: migrate repository identity to OmniGenis"
```

Expected: one focused implementation commit after fresh local validation.

### Task 7: Open the governed OmniGenis pull request and verify external integrations

**Files:**
- No additional tracked implementation files required.
- Create outside Git: `/tmp/omnigenis-pr-body.md`.

**Interfaces:**
- Consumes: exact validated implementation HEAD from Task 6.
- Produces: a draft/ready PR whose checks prove that protected-main integrations still operate under `repository_id=1212760346; repository_name=OmniGenis`.

- [ ] **Step 1: Run the optional local CodeRabbit review only if actually available and authenticated**

```bash
if command -v coderabbit >/dev/null 2>&1; then
  coderabbit review --agent --base main -c AGENTS.md
else
  printf '%s\n' 'CodeRabbit CLI unavailable; no local CodeRabbit review claimed.'
fi
```

Expected: either an actual review result or an explicit unavailable status; never fabricate a review.

- [ ] **Step 2: Push the coherent implementation branch to the renamed repository**

```bash
git push -u origin chore/omnigenis-repository-identity
```

Expected: push target is `https://github.com/repository_id=1212760346; repository_name=OmniGenis.git`.

- [ ] **Step 3: Create the pull request as draft**

```bash
HEAD_SHA="$(git rev-parse HEAD)"
cat > /tmp/omnigenis-pr-body.md <<EOF
## Scope
Migrate the current GitHub repository identity from Codework to OmniGenis without changing the repository object, scientific behavior, canonical GENOMA v3.4 identity, or deferred internal codework-* compatibility contracts.

## Evidence
- Repository ID preserved: 1212760346
- Pre/post main continuity: ae3cd2166d1f6ed5875fdb8be7d82543c962ee54
- Implementation HEAD: ${HEAD_SHA}
- Visibility: public, unchanged
- Active rulesets preserved: 22347095 and 21303100
- Migration evidence: docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json
EOF
gh pr create --draft --base main --head chore/omnigenis-repository-identity \
  --title "chore: migrate repository identity to OmniGenis" \
  --body-file /tmp/omnigenis-pr-body.md
```

Expected: a draft PR in `repository_id=1212760346; repository_name=OmniGenis`.- [ ] **Step 4: Mark the exact validated HEAD ready for external review**

```bash
PR_NUMBER="$(gh pr view --json number --jq .number)"
gh pr ready "$PR_NUMBER"
```

Expected: the PR leaves draft state only after the local validation evidence corresponds to its exact HEAD.

- [ ] **Step 5: Wait for and inspect required checks**

```bash
gh pr checks "$PR_NUMBER" --watch --interval 20
gh pr checks "$PR_NUMBER" --required
```

Required protected-main contexts must remain satisfiable, including `static`, `container-canary`, `Canonical policy + 263-rule contract`, `OPA/Rego parity`, `Real Docker + canonical read-only mount`, `CodeRabbit`, `GitGuardian Security Checks`, the five DeepSource contexts, `security/snyk (legacy-operatorandrade)`, and `semgrep-cloud-platform/scan`.

- [ ] **Step 6: Verify rulesets again under the new repository identity**

```bash
gh api repos/$repo/rulesets --jq '.[] | [.id,.name,.enforcement] | @tsv'
gh api repos/$repo/rulesets/21303100 --jq '.rules'
gh api repos/$repo/rulesets/22347095 --jq '.rules'
```

Expected: both rulesets remain active and protected-main checks are not weakened.- [ ] **Step 7: Treat integration identity failures as blocking**

If CodeRabbit, GitGuardian, DeepSource, Snyk, Semgrep, or a required GitHub Actions context is missing because the integration did not follow the rename, return the PR to draft before any corrective push:

```bash
gh pr ready --undo "$PR_NUMBER"
```

Repair or re-authorize only the affected integration against `OmniGenis`, then re-run the exact affected validation. Do not remove a required check, change a ruleset to bypass it, or merge while the context is absent.

### Task 8: Final readiness and human merge handoff

**Files:**
- No additional implementation files.

**Interfaces:**
- Consumes: reviewed PR with all required checks satisfied.
- Produces: an evidence-based `ready for manual merge` declaration; the assistant does not perform the final merge.

- [ ] **Step 1: Revalidate the PR head and review-thread state**

```bash
gh pr view "$PR_NUMBER" --json headRefOid,mergeStateStatus,reviewDecision,isDraft,url
gh pr checks "$PR_NUMBER" --required
```

Expected: PR is not draft, required checks pass, and no unresolved blocking review thread remains.- [ ] **Step 2: Declare readiness without merging**

Report the exact PR URL, head SHA, local validation commands/results, CodeRabbit status, GitHub Actions status, security-review status, ruleset continuity, and any remaining limitation. State `ready for manual merge` only if every blocking condition is satisfied.

Do not call `gh pr merge`, enable auto-merge, bypass a ruleset, or push directly to `main`.

- [ ] **Step 3: After the human merge, verify final Phase 1 continuity**

After the user confirms the manual merge:

```bash
cd /srv/remote-desktop-commander-workspace/codework-audit/Codework
git fetch origin --prune
git remote get-url origin
git log -1 --oneline origin/main
gh api repos/$repo --jq '[.id,.full_name,.visibility,.default_branch] | @tsv'
gh api repos/$repo/rulesets --jq '.[] | [.id,.name,.enforcement] | @tsv'
git ls-remote https://github.com/repository_id=1212760346; historical_repository_name=Codework.git refs/heads/main
git ls-remote https://github.com/repository_id=1212760346; repository_name=OmniGenis.git refs/heads/main
```

Expected: canonical repository identity is `repository_id=1212760346; repository_name=OmniGenis`, repository ID remains `1212760346`, visibility remains public, `origin` uses the new URL, rulesets remain active, and old/new Git endpoints resolve to the same current `main` history.

Phase 2 internal `codework-*` renaming remains explicitly deferred and requires a separate design, approval, implementation plan, compatibility analysis, and test cycle.
