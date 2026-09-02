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

    def test_privileged_publisher_runs_only_after_the_unprivileged_workflow(self):
        workflow = (ROOT / ".github/workflows/codacy-api-report.yml").read_text(encoding="utf-8")
        header = workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_run:\n", header)
        self.assertIn("workflows: [Codacy API Report Tests]", header)
        self.assertIn("types: [requested, in_progress, completed]", header)
        self.assertNotIn("pull_request_target:", header)
        self.assertNotIn("\n  pull_request:\n", header)
        self.assertNotIn("workflow_dispatch:", header)
        self.assertIn("permissions: {}", workflow)
        self.assertIn(
            "codacy-api-report-${{ github.event.workflow_run.head_repository.id }}-${{ "
            "github.event.workflow_run.head_branch }}",
            workflow,
        )
        self.assertIn("cancel-in-progress: false", workflow)

        resolve = _job_block(workflow, "resolve")
        self.assertNotIn("environment:", resolve)
        self.assertNotIn("secrets.", resolve)
        self.assertRegex(
            resolve,
            r"permissions:\n\s+actions: read[^\n]*\n\s+contents: read[^\n]*\n"
            r"\s+pull-requests: read",
        )
        self.assertIn("ref: ${{ github.sha }}", resolve)
        self.assertIn("persist-credentials: false", resolve)
        self.assertIn("resolveCodacyPullRequest", resolve)
        self.assertIn("workflowRun: context.payload.workflow_run", resolve)
        self.assertIn("head: ${{ steps.pr.outputs.head }}", resolve)
        self.assertIn("base: ${{ steps.pr.outputs.base }}", resolve)
        self.assertIn("run_id: ${{ steps.pr.outputs.run_id }}", resolve)
        self.assertIn("run_attempt: ${{ steps.pr.outputs.run_attempt }}", resolve)

        report = _job_block(workflow, "report")
        self.assertIn("needs: resolve", report)
        self.assertIn("environment: codacy-report", report)
        self.assertRegex(
            report,
            r"permissions:\n\s+actions: read[^\n]*\n\s+contents: read[^\n]*\n"
            r"\s+pull-requests: write",
        )
        self.assertIn("ref: ${{ github.sha }}", report)
        self.assertIn("persist-credentials: false", report)
        self.assertNotIn("ref: ${{ github.event.workflow_run", report)
        self.assertIn(
            "CODACY_PROJECT_TOKEN: ${{ secrets.CODACY_REPORT_PROJECT_TOKEN }}", report
        )
        self.assertIn("CODACY_API_TOKEN: ${{ secrets.CODACY_REPORT_API_TOKEN }}", report)
        self.assertIn("CODACY_PULL_REQUEST: ${{ needs.resolve.outputs.number }}", report)
        self.assertIn("CODACY_COMMIT: ${{ needs.resolve.outputs.head }}", report)
        self.assertIn("CODACY_BASE_COMMIT: ${{ needs.resolve.outputs.base }}", report)
        self.assertIn("CODACY_WORKFLOW_RUN_ID: ${{ needs.resolve.outputs.run_id }}", report)
        self.assertIn(
            "CODACY_WORKFLOW_RUN_ATTEMPT: ${{ needs.resolve.outputs.run_attempt }}", report
        )
        self.assertIn("name: Verify source before publication", report)
        self.assertIn("isCurrentCodacyPublication", report)
        self.assertNotIn("isCurrentCodacyPullRequest", report)
        self.assertIn("head: process.env.EXPECTED_HEAD", report)
        self.assertIn("base: process.env.EXPECTED_BASE", report)
        self.assertIn("steps.current.outputs.current == 'true'", report)
        self.assertIn("steps.current.outputs.current != 'true'", report)
        self.assertIn("Invalidate prior report before processing", report)
        self.assertIn("needs.resolve.outputs.state == 'publish'", report)
        self.assertIn("Publish missing credential state", report)
        self.assertIn("Publish terminal publisher failure", report)
        self.assertIn("always()", report)
        self.assertIn("failure()", report)

        self.assertNotIn("workflow_run.pull_requests[0]", workflow)
        self.assertNotIn("secrets.CODACY_PROJECT_TOKEN", workflow)
        self.assertNotIn("secrets.CODACY_API_TOKEN", workflow)
        for line in workflow.splitlines():
            stripped = line.strip()
            if stripped.startswith(("run:", "uses:")):
                self.assertNotIn("github.event.workflow_run", stripped)

        checkout = report.index("uses: actions/checkout@")
        first_secret = report.index("secrets.CODACY_")
        self.assertLess(checkout, first_secret)


if __name__ == "__main__":
    unittest.main()
