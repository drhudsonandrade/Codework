import json
import shutil

# Imported to execute `scripts/codacy_pr_comment.js` under Node: the upsert logic runs inside
# a github-script step, and asserting on its source text is not the same as running it.
# Bandit's B404 is an advisory on the import alone; the single call site below states why its
# argv is trusted.
import subprocess  # nosec B404
import unittest
from pathlib import Path

#: Absolute path to the Node binary, resolved once. The class guard below performs the same
#: lookup, so pinning the result makes the binary that gated the test and the binary that runs
#: it the same one, instead of two independent PATH resolutions that a change to the
#: environment between them could separate.
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is required for github-script behavior tests")
class CodacyPrCommentTest(unittest.TestCase):
    """The one report comment is created once and updated thereafter."""

    def _run_case(self, existing):
        """Run the real upsert against a stub Octokit, with these comments already present.

        Bandit's B603 asks a human to confirm the argv is trusted before the call is made.
        This is that confirmation: `NODE` is resolved from PATH at import and `program` is
        built here from a repository path and the fixture this test passed in. Nothing in it
        comes from outside the process, and there is no shell — the list form goes straight
        to `execve`. The suppression names the single rule and covers the single line.
        """
        module = Path("scripts/codacy_pr_comment.js").resolve()
        program = f"""
const {{ upsertCodacyReportComment }} = require({json.dumps(str(module))});
const calls = [];
const previous = {json.dumps(existing)};
const github = {{
  paginate: async () => previous,
  rest: {{ issues: {{
    listComments: async () => {{}},
    updateComment: async (args) => calls.push(['update', args]),
    createComment: async (args) => calls.push(['create', args]),
  }} }}
}};
(async () => {{
  const result = await upsertCodacyReportComment({{
    github, owner: 'o', repo: 'r', issue_number: 32, report: '# report'
  }});
  process.stdout.write(JSON.stringify({{ result, calls }}));
}})().catch(err => {{ console.error(err); process.exit(1); }});
"""
        completed = subprocess.run(  # nosec B603
            [NODE, "-e", program], text=True, capture_output=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_creates_the_single_report_comment_when_none_exists(self):
        result = self._run_case([])
        self.assertEqual(result["result"], "created")
        self.assertEqual(result["calls"][0][0], "create")
        self.assertIn("<!-- codacy-api-report -->", result["calls"][0][1]["body"])

    def test_updates_the_existing_bot_report_comment(self):
        result = self._run_case([
            {"id": 7, "user": {"type": "Bot"}, "body": "<!-- codacy-api-report -->\nold"}
        ])
        self.assertEqual(result["result"], "updated")
        self.assertEqual(result["calls"][0][0], "update")
        self.assertEqual(result["calls"][0][1]["comment_id"], 7)


if __name__ == "__main__":
    unittest.main()
