import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


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


class CodacyWorkflowTrustBoundaryTest(unittest.TestCase):
    def test_comment_regression_also_runs_in_the_existing_static_job(self):
        workflow = (ROOT / ".github/workflows/scaffold-validation.yml").read_text(
            encoding="utf-8"
        )
        static = _job_block(workflow, "static")
        self.assertIn("node --test tests/test_codacy_pr_comment.js", static)

    def test_pull_request_workflow_is_unprivileged_and_executes_only_tests(self):
        path = ROOT / ".github/workflows/codacy-api-report-tests.yml"
        self.assertTrue(path.is_file(), "the unprivileged PR test workflow is missing")
        workflow = path.read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("pull_request:\n", header)
        self.assertNotIn("pull_request_target:", header)
        self.assertNotIn("workflow_dispatch:", header)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("actions/github-script@", workflow)
        self.assertNotIn("actions/upload-artifact@", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("python3 -m unittest tests.test_codacy_api_report", workflow)
        self.assertIn("node --test tests/test_codacy_pr_comment.js", workflow)

    def test_privileged_publisher_runs_only_the_trusted_base_revision(self):
        workflow = (ROOT / ".github/workflows/codacy-api-report.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("pull_request_target:\n", header)
        self.assertIn("branches: [main]", header)
        self.assertNotIn("\n  pull_request:\n", header)
        self.assertNotIn("workflow_dispatch:", header)
        self.assertIn("permissions: {}", workflow)

        report = _job_block(workflow, "report")
        self.assertIn("environment: codacy-report", report)
        self.assertIn("permissions:\n      contents: read\n      pull-requests: write", report)
        self.assertIn("ref: ${{ github.event.pull_request.base.sha }}", report)
        self.assertIn("persist-credentials: false", report)
        self.assertNotIn("ref: ${{ github.event.pull_request.head", report)
        self.assertIn("CODACY_PROJECT_TOKEN: ${{ secrets.CODACY_PROJECT_TOKEN }}", report)
        self.assertIn("CODACY_API_TOKEN: ${{ secrets.CODACY_API_TOKEN }}", report)

        allowed_pull_request_expressions = {
            "group: codacy-api-report-${{ github.event.pull_request.number }}",
            "CODACY_PULL_REQUEST: ${{ github.event.pull_request.number }}",
            "CODACY_COMMIT: ${{ github.event.pull_request.head.sha }}",
            "CODACY_BASE_COMMIT: ${{ github.event.pull_request.base.sha }}",
            "ref: ${{ github.event.pull_request.base.sha }}",
        }
        observed = {
            line.strip()
            for line in report.splitlines()
            if "${{ github.event.pull_request" in line
        }
        self.assertEqual(observed, allowed_pull_request_expressions)
        for line in report.splitlines():
            stripped = line.strip()
            if stripped.startswith(("run:", "uses:")):
                self.assertNotIn("github.event.pull_request", stripped)

        checkout = report.index("uses: actions/checkout@")
        first_secret = report.index("secrets.CODACY_")
        self.assertLess(checkout, first_secret)


if __name__ == "__main__":
    unittest.main()
