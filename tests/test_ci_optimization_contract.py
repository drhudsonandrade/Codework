import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"

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
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
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

    def test_fallow_runs_only_for_javascript_typescript_surfaces(self):
        workflow = _read("fallow.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("paths:\n", pull_request)
        for expected in (
            "'mcp/**'",
            "'scripts/codacy_pr_comment.js'",
            "'tests/test_codacy_pr_comment.js'",
            "'.fallowrc.json'",
            "'.github/workflows/fallow.yml'",
        ):
            self.assertIn(expected, pull_request)

    def test_four_plane_audit_ignores_only_markdown_only_changes(self):
        workflow = _read("genoma-audit.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        push = header.split("  push:\n", 1)[1].split("  workflow_dispatch:\n", 1)[0]
        self.assertIn("paths-ignore:\n", pull_request)
        self.assertIn("'**/*.md'", pull_request)
        self.assertIn("paths-ignore:\n", push)
        self.assertIn("'**/*.md'", push)

    def test_policy_required_checks_use_job_level_scope_gates(self):
        workflow = _read("genoma-policy-engine.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("policy_relevant:", changes)
        self.assertIn("git diff --name-only", changes)

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

    def test_scaffold_required_checks_use_job_level_markdown_gate(self):
        workflow = _read("scaffold-validation.yml")
        header = workflow.split("permissions:", 1)[0]
        pull_request = header.split("  pull_request:\n", 1)[1].split("  push:\n", 1)[0]
        self.assertNotIn("paths:", pull_request)
        changes = _job_block(workflow, "changes")
        self.assertIn("validation_required:", changes)
        self.assertIn("git diff --name-only", changes)
        self.assertIn("*.md", changes)

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
