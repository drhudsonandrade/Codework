import re
import unittest
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]


def _fail(message: str) -> NoReturn:
    raise AssertionError(message)


def _job_block(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    if marker not in workflow:
        _fail(f"job {job_name!r} is missing")
    tail = workflow.split(marker, 1)[1]
    lines: list[str] = []
    for line in tail.splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            break
        lines.append(line)
    return "".join(lines)


def _permissions(block: str) -> dict[str, str]:
    """Parse the one simple GitHub Actions permissions map in a workflow or job block."""
    lines = block.splitlines()
    indexes = [index for index, line in enumerate(lines) if line.strip().startswith("permissions:")]
    if len(indexes) != 1:
        _fail(f"expected exactly one permissions map, got {len(indexes)}")
    marker = lines[indexes[0]]
    if marker.strip() == "permissions: {}":
        return {}
    if marker.strip() != "permissions:":
        _fail("permissions must be an explicit map")
    base_indent = len(marker) - len(marker.lstrip())
    result: dict[str, str] = {}
    for line in lines[indexes[0] + 1 :]:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped and indent <= base_indent:
            break
        if not stripped or stripped.startswith("#"):
            continue
        if indent != base_indent + 2 or ":" not in stripped:
            _fail("permissions entries must be one scalar mapping level")
        key, value = stripped.split(":", 1)
        result[key] = value.split("#", 1)[0].strip()
    return result


def _top_level_scalar_map(workflow: str, key: str) -> dict[str, str]:
    """Parse one top-level scalar map and reject duplicate or nested entries."""
    lines = workflow.splitlines()
    marker = f"{key}:"
    key_pattern = re.compile(rf"^{re.escape(key)}\s*:")
    indexes = [index for index, line in enumerate(lines) if key_pattern.match(line)]
    if len(indexes) != 1:
        _fail(f"expected exactly one top-level {key!r} map, got {len(indexes)}")
    if lines[indexes[0]] != marker:
        _fail(f"top-level {key!r} must use a block map")
    result: dict[str, str] = {}
    for line in lines[indexes[0] + 1 :]:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped and indent == 0:
            break
        if not stripped or stripped.startswith("#"):
            continue
        if indent != 2 or ":" not in stripped:
            _fail(f"{key} entries must be one scalar mapping level")
        entry, value = stripped.split(":", 1)
        if entry in result:
            _fail(f"duplicate {key} entry: {entry}")
        result[entry] = value.split("#", 1)[0].strip()
    return result

def _github_expressions(workflow: str) -> list[str]:
    """Normalize every GitHub-context expression, independent of its YAML location."""
    expressions = re.findall(r"\$\{\{(.*?)\}\}", workflow, flags=re.DOTALL)
    normalized: list[str] = []
    for expression in expressions:
        compact = re.sub(r"\s+", "", expression)
        compact = re.sub(r"\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]", r".\1", compact)
        if "github" in compact:
            normalized.append(compact)
    return normalized


def _job_entries(workflow: str) -> list[str]:
    """List every two-space YAML entry in jobs, including non-canonical key syntax."""
    jobs = workflow.split("\njobs:\n", 1)
    if len(jobs) != 2:
        _fail("workflow jobs map is missing")
    return [
        line.strip()
        for line in jobs[1].splitlines()
        if line.startswith("  ") and not line.startswith("   ") and line.strip()
    ]


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
        self.assertEqual(_permissions(workflow), {"contents": "read"})
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
        global_header = workflow.split("\njobs:", 1)[0]
        self.assertIn("workflow_run:\n", header)
        self.assertIn("workflows: [Codacy API Report Tests]", header)
        self.assertIn("types: [requested, in_progress, completed]", header)
        self.assertNotIn("pull_request_target:", header)
        self.assertNotIn("\n  pull_request:\n", header)
        self.assertNotIn("workflow_dispatch:", header)
        self.assertEqual(_permissions(global_header), {})
        self.assertEqual(
            _top_level_scalar_map(workflow, "concurrency"),
            {
                "group": (
                    "codacy-api-report-${{ github.event.workflow_run.head_repository.id }}-${{ "
                    "github.event.workflow_run.id }}-${{ github.event.workflow_run.run_attempt }}"
                ),
                "cancel-in-progress": "true",
            },
        )
        self.assertEqual(_job_entries(workflow), ["resolve:", "report:"])

        resolve = _job_block(workflow, "resolve")
        self.assertNotIn("environment:", resolve)
        self.assertNotIn("secrets.", resolve)
        self.assertEqual(
            _permissions(resolve),
            {"actions": "read", "contents": "read", "pull-requests": "read"},
        )
        self.assertIn("ref: ${{ github.sha }}", resolve)
        self.assertIn("persist-credentials: false", resolve)
        self.assertIn("resolveCodacyPullRequest", resolve)
        self.assertIn("workflowRun: context.payload.workflow_run", resolve)
        self.assertIn("head: ${{ steps.pr.outputs.head }}", resolve)
        self.assertIn("base: ${{ steps.pr.outputs.base }}", resolve)
        self.assertIn("run_id: ${{ steps.pr.outputs.run_id }}", resolve)
        self.assertIn("run_number: ${{ steps.pr.outputs.run_number }}", resolve)
        self.assertIn("run_attempt: ${{ steps.pr.outputs.run_attempt }}", resolve)

        report = _job_block(workflow, "report")
        self.assertIn("needs: resolve", report)
        self.assertIn("environment: codacy-report", report)
        self.assertEqual(
            _permissions(report),
            {"actions": "read", "contents": "read", "pull-requests": "write"},
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
            "CODACY_WORKFLOW_RUN_NUMBER: ${{ needs.resolve.outputs.run_number }}",
            report,
        )
        self.assertIn(
            "CODACY_WORKFLOW_RUN_ATTEMPT: ${{ needs.resolve.outputs.run_attempt }}", report
        )
        self.assertEqual(
            report.count("run_number: Number(process.env.CODACY_WORKFLOW_RUN_NUMBER)"),
            9,
        )
        self.assertIn("name: Verify source before publication", report)
        self.assertIn("isCurrentCodacyPublication", report)
        self.assertNotIn("isCurrentCodacyPullRequest", report)
        self.assertIn("head: process.env.EXPECTED_HEAD", report)
        self.assertIn("base: process.env.EXPECTED_BASE", report)
        self.assertIn("steps.current.outputs.current == 'true'", report)
        self.assertIn("steps.current.outputs.current != 'true'", report)
        trusted_checkout = report.index("Checkout trusted default-branch revision")
        repair = report.index("Repair or invalidate prior report before processing")
        query = report.index("Query Codacy API and build report")
        publish = report.index("Publish report on pull request")
        self.assertLess(trusted_checkout, repair)
        self.assertLess(repair, query)
        self.assertLess(query, publish)
        repair_block = report[repair:query]
        for state in ("pending", "interrupted", "failed", "publish"):
            self.assertIn(f"needs.resolve.outputs.state == '{state}'", repair_block)
        self.assertIn("isCurrentCodacyPublication", repair_block)
        self.assertIn("upsertCodacyReportComment", repair_block)
        self.assertIn("publication: {", repair_block)
        self.assertIn("rank: process.env.REPORT_STATE", repair_block)
        self.assertIn("codacyStatusForRunState", report)
        self.assertIn("Publish missing credential state", report)
        self.assertIn("Publish terminal publisher failure", report)
        self.assertIn("always()", report)
        self.assertIn("failure()", report)

        self.assertNotIn("workflow_run.pull_requests[0]", workflow)
        self.assertNotIn("secrets.CODACY_PROJECT_TOKEN", workflow)
        self.assertNotIn("secrets.CODACY_API_TOKEN", workflow)
        self.assertEqual(
            _github_expressions(workflow),
            [
                "github.event.workflow_run.head_repository.id",
                "github.event.workflow_run.id",
                "github.event.workflow_run.run_attempt",
                "github.sha",
                "github.repository_owner",
                "github.event.repository.name",
                "github.sha",
            ],
        )

        checkout = report.index("uses: actions/checkout@")
        first_secret = report.index("secrets.CODACY_")
        self.assertLess(checkout, first_secret)

    def test_concurrency_parser_does_not_accept_a_true_value_outside_the_map(self):
        workflow = """
concurrency:
  group: producer-attempt
  cancel-in-progress: false
jobs:
  check:
    run: echo 'cancel-in-progress: true'
"""
        self.assertEqual(
            _top_level_scalar_map(workflow, "concurrency"),
            {"group": "producer-attempt", "cancel-in-progress": "false"},
        )

    def test_concurrency_parser_rejects_a_duplicate_inline_map(self):
        workflow = """
concurrency:
  group: producer-attempt
  cancel-in-progress: true
jobs:
  check:
    runs-on: ubuntu-latest
concurrency: {group: bypass, cancel-in-progress: false}
"""
        with self.assertRaisesRegex(
            AssertionError, "expected exactly one top-level 'concurrency' map"
        ):
            _top_level_scalar_map(workflow, "concurrency")

    def test_every_yaml_form_of_an_untrusted_github_expression_reaches_the_gate(self):
        fixtures = (
            "run: |\n  echo '${{ github.event.workflow_run.head_branch }}'\n",
            "- run: echo '${{ github.event['workflow_run'].head_branch }}'\n",
            "with:\n  script: >-\n    core.info('${{ github[\"event\"][\"workflow_run\"].head_branch }}')\n",
        )
        for workflow in fixtures:
            with self.subTest(workflow=workflow):
                self.assertEqual(
                    _github_expressions(workflow),
                    ["github.event.workflow_run.head_branch"],
                )

    def test_permissions_parser_keeps_unexpected_privileges_visible(self):
        block = """
permissions:
  contents: read
  id-token: write
"""
        self.assertEqual(
            _permissions(block),
            {"contents": "read", "id-token": "write"},
        )

    def test_job_enumeration_keeps_every_yaml_key_form_visible(self):
        prefix = """
jobs:
  resolve:
    permissions: {}
  report:
    permissions: {}
"""
        suffixes = (
            "  exfiltrate:\n",
            '  "exfiltrate":\n',
            "  'exfiltrate':\n",
            "  exfiltrate: # comment\n",
            "  ? exfiltrate\n  :\n",
            "  exfiltrate: {environment: codacy-report}\n",
        )
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                self.assertNotEqual(
                    _job_entries(prefix + suffix),
                    ["resolve:", "report:"],
                )


if __name__ == "__main__":
    unittest.main()
