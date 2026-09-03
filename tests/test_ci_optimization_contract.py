import importlib.util
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
CLASSIFIER = ROOT / "scripts" / "ci_change_classifier.py"


def _load_classifier() -> ModuleType:
    if not CLASSIFIER.is_file():
        raise AssertionError("CI change classifier is missing")
    spec = importlib.util.spec_from_file_location("ci_change_classifier", CLASSIFIER)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load CI change classifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

CONCURRENCY_WORKFLOWS = (
    "fallow.yml",
    "genoma-audit.yml",
    "genoma-ngs-runtime-gate.yml",
    "genoma-policy-engine.yml",
    "genoma-snp-array.yml",
    "genoma-visual-qa-candidates.yml",
    "pr30-regressions.yml",
    "scaffold-validation.yml",
)

CONCURRENCY_BLOCK = """concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
"""


def _read(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    if marker not in workflow:
        raise AssertionError(f"job {job_name!r} is missing")
    tail = workflow.split(marker, 1)[1]
    lines: list[str] = []
    for line in tail.splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            break
        lines.append(line)
    return "".join(lines)


class CIOptimizationContractTest(unittest.TestCase):
    def test_validation_workflows_cancel_superseded_pr_runs(self):
        for name in CONCURRENCY_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIn(CONCURRENCY_BLOCK, _read(name))

    def test_policy_classifier_behavior_on_real_path_lists(self):
        classifier = _load_classifier()
        self.assertTrue(classifier.policy_relevant(["policy_engine/policy/rego/main.rego"]))
        self.assertTrue(classifier.policy_relevant(["scripts/sealed_ruleset.py"]))
        self.assertTrue(classifier.policy_relevant([".github/governance/main-ruleset.json"]))
        self.assertTrue(
            classifier.policy_relevant(["notes.md", "policy_engine/policy/rego/main.rego"])
        )
        self.assertFalse(classifier.policy_relevant(["docs/architecture.md"]))

    def test_markdown_classifier_behavior_on_modifications_deletions_and_renames(self):
        classifier = _load_classifier()
        self.assertFalse(classifier.validation_required(["docs/architecture.md"], []))
        self.assertTrue(
            classifier.validation_required(["docs/architecture.md"], ["docs/required-contract.md"])
        )
        self.assertTrue(classifier.validation_required(["notes.md", "src/code.py"], []))
        self.assertTrue(classifier.validation_required(["src/code.py", "notes.md"], ["src/code.py"]))

    def test_classifier_is_process_free_and_path_list_driven(self):
        source = CLASSIFIER.read_text(encoding="utf-8")
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("subprocess.", source)
        self.assertIn('parser.add_argument("--changed"', source)
        self.assertIn('parser.add_argument("--deleted"', source)

    def test_fallow_runs_only_for_javascript_typescript_surfaces(self):
        workflow = _read("fallow.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("paths:\n", pull_request)
        expected_paths = (
            "'mcp/**/*.ts'",
            "'mcp/**/*.js'",
            "'mcp/package.json'",
            "'mcp/package-lock.json'",
            "'mcp/tsconfig.json'",
            "'mcp/.fallowrc.json'",
            "'scripts/codacy_pr_comment.js'",
            "'tests/test_codacy_pr_comment.js'",
            "'.fallowrc.json'",
            "'.github/workflows/fallow.yml'",
        )
        for expected in expected_paths:
            self.assertIn(expected, pull_request)
        self.assertNotIn("'mcp/**'", pull_request)

    def test_four_plane_audit_skips_only_safe_markdown_modifications(self):
        workflow = _read("genoma-audit.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertNotIn("paths-ignore:", pull_request)
        self.assertNotIn("paths-ignore:", push)
        changes = _job_block(workflow, "changes")
        self.assertIn("audit_required:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/audit-changed-paths.zlist"', changes)
        self.assertIn('deleted_paths="$RUNNER_TEMP/audit-deleted-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$deleted_paths"', changes)
        self.assertIn('git ls-tree -r --name-only -z "$HEAD_SHA" -- > "$changed_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py|.github/workflows/genoma-audit.yml', changes)
        audit = _job_block(workflow, "audit")
        self.assertIn("needs: changes", audit)
        self.assertIn("needs.changes.result != 'success'", audit)
        self.assertIn("needs.changes.outputs.audit_required == 'true'", audit)
        self.assertIn("Require successful scope classification", audit)

    def test_policy_required_checks_use_job_level_scope_gates(self):
        workflow = _read("genoma-policy-engine.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("policy_relevant:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/policy-changed-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py policy --changed "$changed_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py|.github/workflows/genoma-policy-engine.yml', changes)
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("'scripts/sealed_ruleset.py'", push)
        self.assertIn("'scripts/ci_change_classifier.py'", push)
        self.assertIn("'.github/governance/**'", push)

        for job_name in ("policy", "rego", "container"):
            job = _job_block(workflow, job_name)
            self.assertIn("needs: changes", job)
            self.assertIn("always() &&", job)
            self.assertIn("needs.changes.result != 'success'", job)
            self.assertIn("needs.changes.outputs.policy_relevant == 'true'", job)
            self.assertIn("Require successful scope classification", job)

        secrets = _job_block(workflow, "secrets")
        self.assertNotIn("needs: changes", secrets)
        self.assertNotIn("policy_relevant", secrets)
        for required_name in (
            "Canonical policy + 263-rule contract",
            "OPA/Rego parity",
            "Gitleaks secret scan",
            "Real Docker + canonical read-only mount",
        ):
            self.assertIn(f"name: {required_name}", workflow)

    def test_required_check_classifiers_use_checked_diffs_without_process_substitution(self):
        for workflow_name in ("genoma-policy-engine.yml", "scaffold-validation.yml"):
            with self.subTest(workflow=workflow_name):
                changes = _job_block(_read(workflow_name), "changes")
                self.assertIn("set -euo pipefail", changes)
                self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
                self.assertNotIn("done < <(git diff", changes)
                self.assertIn("scripts/ci_change_classifier.py", changes)

    def test_scaffold_required_checks_use_job_level_markdown_gate(self):
        workflow = _read("scaffold-validation.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("validation_required:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/scaffold-changed-paths.zlist"', changes)
        self.assertIn('deleted_paths="$RUNNER_TEMP/scaffold-deleted-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py|.github/workflows/scaffold-validation.yml', changes)

        for job_name in ("static", "container-canary"):
            job = _job_block(workflow, job_name)
            self.assertIn("needs: changes", job)
            self.assertIn("always() &&", job)
            self.assertIn("needs.changes.result != 'success'", job)
            self.assertIn("needs.changes.outputs.validation_required == 'true'", job)
            self.assertIn("Require successful scope classification", job)

        self.assertIn("  static:\n", workflow)
        self.assertIn("  container-canary:\n", workflow)
        publish = _job_block(workflow, "publish-ghcr")
        self.assertIn("needs: [static, container-canary]", publish)


if __name__ == "__main__":
    unittest.main()
