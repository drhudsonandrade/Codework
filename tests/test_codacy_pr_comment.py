import json
import shutil

# Imported to execute `tests/codacy_pr_comment_driver.js` under Node: the upsert logic runs
# inside a github-script step, and asserting on its source text is not the same as running it.
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

#: The committed driver. Every element of the argv below is a fixed path or a JSON string —
#: nothing is a program assembled at run time. See the comment at the top of that file.
DRIVER = Path(__file__).resolve().parent / "codacy_pr_comment_driver.js"

#: The module under test, resolved from this file rather than from the working directory, so
#: the argv does not depend on where the suite was started.
MODULE = Path(__file__).resolve().parent.parent / "scripts" / "codacy_pr_comment.js"


@unittest.skipUnless(NODE, "node is required for github-script behavior tests")
class CodacyPrCommentTest(unittest.TestCase):
    """The one report comment is created once and updated thereafter."""

    def test_the_driver_and_the_module_under_test_are_both_committed_files(self):
        """The argv is trusted because these resolve to files here, not because of intent.

        This is what lets the suppression below name a checked property instead of an
        argument: if either path stopped resolving to a file in this repository, the argv
        would no longer be what the comment claims, and this test would say so.
        """
        self.assertTrue(DRIVER.is_file(), DRIVER)
        self.assertTrue(MODULE.is_file(), MODULE)

    def _run_case(self, existing) -> dict:
        """Run the real upsert against a stub Octokit, with these comments already present.

        Bandit's B603 asks a human to confirm the argv is trusted before the call is made.
        This is that confirmation, and it is now structural rather than a claim about the
        fixtures: the argv is `NODE` (resolved from PATH at import), the committed driver
        script, the committed module under test, and one JSON string. Node never interprets
        an argv element as code — the previous form passed a whole program to `-e`, which it
        did — and there is no shell, because the list form goes straight to `execve`.
        """
        completed = subprocess.run(  # nosec B603  # nosemgrep
            [NODE, str(DRIVER), str(MODULE), json.dumps(existing)],
            text=True,
            capture_output=True,
            check=False,
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
