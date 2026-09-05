import ast
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

from tests.workflow_test_utils import job_block as _job_block


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


def _subprocess_references(source: str) -> list[str]:
    findings: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            findings.extend(alias.name for alias in node.names if alias.name == "subprocess" or alias.name.startswith("subprocess."))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "subprocess" or module.startswith("subprocess."):
                findings.append(module)
        elif isinstance(node, ast.Name) and node.id == "subprocess":
            findings.append(node.id)
    return findings


class CIOptimizationContractTest(unittest.TestCase):
    def _assert_job_gate(self, workflow: str, job_name: str, output_name: str) -> None:
        job = _job_block(workflow, job_name)
        self.assertIn("needs: changes", job)
        self.assertIn("always() &&", job)
        self.assertIn("needs.changes.result != 'success'", job)
        self.assertIn(f"needs.changes.outputs.{output_name} == 'true'", job)
        self.assertIn("Require successful scope classification", job)

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
        self.assertEqual([], _subprocess_references(source))
        self.assertNotEqual([], _subprocess_references("from subprocess import run\nrun([])\n"))
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
        self.assertIn('bash scripts/ci_changed_paths.sh "$BASE_SHA" "$HEAD_SHA" "$changed_paths" "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_changed_paths.sh|scripts/ci_change_classifier.py|.github/workflows/genoma-audit.yml', changes)
        self._assert_job_gate(workflow, "audit", "audit_required")

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
            self._assert_job_gate(workflow, job_name, "policy_relevant")

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

    def test_changed_path_shell_helper_is_wired_and_behaviorally_exercised(self):
        helper = ROOT / "scripts" / "ci_changed_paths.sh"
        regression = ROOT / "tests" / "test_ci_changed_paths.sh"
        self.assertTrue(helper.is_file())
        self.assertTrue(regression.is_file())
        helper_text = helper.read_text(encoding="utf-8")
        self.assertIn("0000000000000000000000000000000000000000", helper_text)
        self.assertIn('git ls-tree -r --name-only -z "$head_sha" --', helper_text)
        self.assertIn('git diff --no-renames --name-only -z "$base_sha" "$head_sha" --', helper_text)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$base_sha" "$head_sha" --', helper_text)
        static = _job_block(_read("scaffold-validation.yml"), "static")
        self.assertIn("bash tests/test_ci_changed_paths.sh", static)

    def test_scaffold_required_checks_use_job_level_markdown_gate(self):
        workflow = _read("scaffold-validation.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        self.assertNotIn("paths-ignore:", push)
        changes = _job_block(workflow, "changes")
        self.assertIn("validation_required:", changes)
        self.assertIn('changed_paths="$RUNNER_TEMP/scaffold-changed-paths.zlist"', changes)
        self.assertIn('deleted_paths="$RUNNER_TEMP/scaffold-deleted-paths.zlist"', changes)
        self.assertIn('git diff --no-renames --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$changed_paths"', changes)
        self.assertIn('git diff --no-renames --diff-filter=D --name-only -z "$BASE_SHA" "$HEAD_SHA" > "$deleted_paths"', changes)
        self.assertIn('scripts/ci_change_classifier.py markdown --changed "$changed_paths" --deleted "$deleted_paths"', changes)
        self.assertIn('scripts/ci_changed_paths.sh|scripts/ci_change_classifier.py|.github/workflows/scaffold-validation.yml', changes)
        self.assertIn('PUSH_BASE_SHA: ${{ github.event.before }}', changes)
        self.assertIn('CURRENT_SHA: ${{ github.sha }}', changes)
        self.assertIn('bash scripts/ci_changed_paths.sh "$BASE_SHA" "$HEAD_SHA" "$changed_paths" "$deleted_paths"', changes)

        for job_name in ("static", "container-canary"):
            self._assert_job_gate(workflow, job_name, "validation_required")

        self.assertIn("  static:\n", workflow)
        self.assertIn("  container-canary:\n", workflow)
        publish = _job_block(workflow, "publish-ghcr")
        self.assertIn("needs: [static, container-canary]", publish)


if __name__ == "__main__":
    unittest.main()
