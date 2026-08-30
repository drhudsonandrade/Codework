import json
import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "node is required for github-script behavior tests")
class CodacyPrCommentTest(unittest.TestCase):
    def _run_case(self, existing):
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
        completed = subprocess.run(
            ["node", "-e", program], text=True, capture_output=True, check=False
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
