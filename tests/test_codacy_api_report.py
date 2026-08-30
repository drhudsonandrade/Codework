import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.StringIO(json.dumps(self.payload))

    def __exit__(self, exc_type, exc, tb):
        return False


class CodacyApiReportTest(unittest.TestCase):
    def test_project_token_is_preferred_but_account_token_is_retained_as_fallback(self):
        from scripts.codacy_api_report import credential_candidates

        self.assertEqual(
            credential_candidates("project", "account"),
            [("project-token", "project"), ("api-token", "account")],
        )
        self.assertEqual(credential_candidates("", ""), [])

    def test_auth_rejection_retries_once_with_account_token(self):
        from scripts.codacy_api_report import fetch_issues

        seen = []

        def opener(request, timeout=30):
            seen.append(dict(request.header_items()))
            if request.get_header("Project-token"):
                raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, io.BytesIO(b"bad token"))
            return _Response({"data": [{"id": "issue-1"}], "pagination": {}})

        issues = fetch_issues("gh", "org", "repo", "project", "account", opener=opener)
        self.assertEqual(issues, [{"id": "issue-1"}])
        self.assertEqual(len(seen), 2)
        self.assertTrue(any(k.lower() == "project-token" for k in seen[0]))
        self.assertTrue(any(k.lower() == "api-token" for k in seen[1]))

    def test_non_auth_http_error_does_not_fall_back(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        calls = 0

        def opener(request, timeout=30):
            nonlocal calls
            calls += 1
            raise urllib.error.HTTPError(request.full_url, 500, "server error", {}, io.BytesIO(b"boom"))

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "account", opener=opener)
        self.assertEqual(calls, 1)
        self.assertIn("HTTP 500", str(caught.exception))

    def test_cursor_pagination_accumulates_all_issues(self):
        from scripts.codacy_api_report import fetch_issues

        urls = []

        def opener(request, timeout=30):
            urls.append(request.full_url)
            if len(urls) == 1:
                return _Response({"data": [{"id": 1}], "pagination": {"cursor": "next page"}})
            return _Response({"data": [{"id": 2}], "pagination": {}})

        issues = fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertEqual([item["id"] for item in issues], [1, 2])
        self.assertEqual(len(urls), 2)
        self.assertIn("cursor=next+page", urls[1])

    def test_markdown_cells_cannot_break_out_of_the_table(self):
        from scripts.codacy_api_report import build_report

        report = build_report(
            "org",
            "repo",
            [{
                "filePath": "src/a`b.py\n| injected | row |",
                "patternInfo": {"id": "P|1`x", "level": "High\nInjected", "category": "Sec|urity"},
            }],
        )
        issue_row = next(line for line in report.splitlines() if line.startswith("| High"))
        self.assertIn(r"Sec\|urity", issue_row)
        self.assertIn(r"src/a\`b.py \\| injected \\| row \\|", issue_row)
        self.assertIn(r"P\|1\`x", issue_row)
        self.assertNotIn("\n", issue_row)

    def test_artifact_is_documented_by_its_actual_consolidated_shape(self):
        from scripts.codacy_api_report import write_artifacts

        with tempfile.TemporaryDirectory() as td:
            with patch("scripts.codacy_api_report.Path", wraps=Path):
                report_path, issues_path = write_artifacts(
                    "org", "repo", [{"id": 1}], directory=Path(td)
                )
            payload = json.loads(issues_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, {"data": [{"id": 1}]})
            self.assertTrue(report_path.read_text(encoding="utf-8").startswith("# Codacy API report"))


if __name__ == "__main__":
    unittest.main()
