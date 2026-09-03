import importlib.util
import shutil
import subprocess
import tempfile
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

    def test_classifier_executes_git_diff_and_propagates_failures(self):
        classifier = _load_classifier()
        git = shutil.which("git")
        if git is None:
            self.skipTest("git executable is required for classifier integration coverage")

        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.check_call([git, "init", "-q"], cwd=repo)
            subprocess.check_call([git, "config", "user.email", "ci@example.invalid"], cwd=repo)
            subprocess.check_call([git, "config", "user.name", "CI Contract"], cwd=repo)
            (repo / "policy_engine").mkdir()
            (repo / "docs").mkdir()
            (repo / "policy_engine/policy.rego").write_text("package fixture\n", encoding="utf-8")
            (repo / "docs/required.md").write_text("# required\n", encoding="utf-8")
            subprocess.check_call([git, "add", "."], cwd=repo)
            subprocess.check_call([git, "commit", "-q", "-m", "base"], cwd=repo)
            base = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            null_base = "0" * 40
            self.assertTrue(classifier.classify_git_diff("policy", null_base, base, repo))
            self.assertTrue(classifier.classify_git_diff("markdown", null_base, base, repo))

            subprocess.check_call([git, "mv", "policy_engine/policy.rego", "notes.md"], cwd=repo)
            (repo / "docs/required.md").unlink()
            subprocess.check_call([git, "add", "-A"], cwd=repo)
            subprocess.check_call([git, "commit", "-q", "-m", "rename and delete"], cwd=repo)
            changed = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            self.assertTrue(classifier.classify_git_diff("policy", base, changed, repo))
            self.assertTrue(classifier.classify_git_diff("markdown", base, changed, repo))

            (repo / "notes.md").write_text("package fixture\n# docs only\n", encoding="utf-8")
            subprocess.check_call([git, "add", "notes.md"], cwd=repo)
            subprocess.check_call([git, "commit", "-q", "-m", "docs only"], cwd=repo)
            docs_only = subprocess.check_output([git, "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            self.assertFalse(classifier.classify_git_diff("policy", changed, docs_only, repo))
            self.assertFalse(classifier.classify_git_diff("markdown", changed, docs_only, repo))

            with self.assertRaises(subprocess.CalledProcessError):
                classifier.classify_git_diff("policy", "not-a-valid-sha", docs_only, repo)

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
        self.assertIn("scripts/ci_change_classifier.py markdown", changes)
        self.assertIn('--base "$BASE_SHA" --head "$HEAD_SHA"', changes)
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
        self.assertIn("scripts/ci_change_classifier.py policy", changes)
        self.assertIn('--base "$BASE_SHA" --head "$HEAD_SHA"', changes)
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

    def test_required_check_classifiers_delegate_git_diff_to_shared_classifier(self):
        for workflow_name in ("genoma-policy-engine.yml", "scaffold-validation.yml"):
            with self.subTest(workflow=workflow_name):
                changes = _job_block(_read(workflow_name), "changes")
                self.assertNotIn("git diff", changes)
                self.assertIn("scripts/ci_change_classifier.py", changes)
                self.assertIn('--base "$BASE_SHA" --head "$HEAD_SHA"', changes)

    def test_scaffold_required_checks_use_job_level_markdown_gate(self):
        workflow = _read("scaffold-validation.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("validation_required:", changes)
        self.assertIn("scripts/ci_change_classifier.py markdown", changes)
        self.assertIn('--base "$BASE_SHA" --head "$HEAD_SHA"', changes)

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
