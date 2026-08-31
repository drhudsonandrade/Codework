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

    def test_auth_rejection_retries_once_with_account_token_for_401_and_403(self):
        from scripts.codacy_api_report import fetch_issues

        # Built by a factory, not defined inside the loop. A closure written in the loop
        # body reads the loop variable when it is *called*, which gives the right status
        # today only because the call happens in the same iteration; if it ever outlived
        # the iteration, the 403 case would silently re-test 401 and report both as
        # covered. The factory gives each opener its own scope, so the binding is a
        # property of the structure rather than of the call timing — and, unlike keyword
        # defaults, it does so without putting a mutable list in a signature.
        def make_opener(status, seen):
            """An opener that records each request and rejects the project token."""

            def opener(request, timeout=30):
                seen.append(dict(request.header_items()))
                if request.get_header("Project-token"):
                    raise urllib.error.HTTPError(
                        request.full_url,
                        status,
                        "auth rejected",
                        {},
                        io.BytesIO(b"bad token"),
                    )
                return _Response({"data": [{"id": "issue-1"}], "pagination": {}})

            return opener

        for status in (401, 403):
            with self.subTest(status=status):
                seen = []
                opener = make_opener(status, seen)

                issues = fetch_issues(
                    "gh", "org", "repo", "project", "account", opener=opener
                )
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

    def test_non_object_pagination_is_rejected(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        def opener(request, timeout=30):
            return _Response({"data": [{"id": 1}], "pagination": ["unexpected"]})

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("pagination", str(caught.exception).lower())

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
        self.assertIn(r"src/a\`b.py \| injected \| row \|", issue_row)
        self.assertIn(r"P\|1\`x", issue_row)
        self.assertNotIn("\n", issue_row)

    def test_the_token_is_scrubbed_from_an_error_body_before_it_reaches_a_log(self):
        """A job log is an output, and this PR promises the token never reaches one.

        `_read_http_error` returns the response body verbatim and `fetch_issues` embeds it in
        the `CodacyAPIError` message, which `main` prints to stderr — the job log, which is
        world-readable on a public repository and kept in the run history. An API that echoes
        the authenticated request in its error body therefore publishes the credential.

        Both `docs/CODACY_API_INTEGRATION.md` ("Tokens are never written to artifacts,
        comments, repository files, or workflow outputs") and this pull request's own
        description make that promise, so the body is scrubbed rather than trusted. Reproduced
        against the pre-fix code with a body echoing `project-token`.
        """
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        # Deliberately low-entropy placeholders. An earlier revision used random-looking
        # strings here and GitGuardian raised two "Generic High Entropy Secret" incidents
        # against this file: a fixture that looks like a credential costs a security review
        # and teaches the scanner nothing. These exercise the same code path.
        project, account = "PLACEHOLDER-PROJECT-TOKEN", "PLACEHOLDER-ACCOUNT-TOKEN"
        body = (
            b'{"error":"invalid token","request":{"headers":'
            b'{"project-token":"PLACEHOLDER-PROJECT-TOKEN",'
            b'"api-token":"PLACEHOLDER-ACCOUNT-TOKEN"}}}'
        )

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url, 500, "server error", {}, io.BytesIO(body)
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, account, opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        self.assertNotIn(account, message)
        # The diagnosis must survive the redaction, or the scrub trades one problem for another.
        self.assertIn("HTTP 500", message)
        self.assertIn("invalid token", message)

    def test_a_credential_starting_near_the_truncation_point_is_not_cut_in_half(self):
        """Truncating before redacting leaves the tail of the secret in the message.

        `_read_http_error` reported at most 1000 characters. A credential beginning at, say,
        character 990 was therefore sliced by the truncation, and `_redact` — which matches
        the whole string — no longer found it, so the surviving fragment went into the
        `CodacyAPIError` and from there to stderr. The read window is now the reported limit
        plus the longest secret, and the truncation happens after the scrub.
        """
        from scripts.codacy_api_report import (
            MAX_ERROR_BODY_CHARS,
            CodacyAPIError,
            fetch_issues,
        )

        project = "PLACEHOLDER-PROJECT-TOKEN"
        body = b"x" * (MAX_ERROR_BODY_CHARS - 10) + project.encode() + b"tail"

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url, 500, "server error", {}, io.BytesIO(body)
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, "", opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        # Not merely absent as a whole string: no fragment of it survives either.
        for cut in range(6, len(project)):
            self.assertNotIn(project[:cut], message, f"prefix of length {cut} survived")

    def test_a_credential_that_is_a_prefix_of_another_does_not_expose_its_suffix(self):
        """Replacing the shorter secret first turns `abcd` into `***d`.

        Two configured credentials can share a prefix, and `_redact` used to substitute them
        in the order the caller passed them. The order is now longest-first, so the outcome
        no longer depends on the argument order.
        """
        from scripts.codacy_api_report import _redact

        short, long = "PLACEHOLDER-TOKEN", "PLACEHOLDER-TOKEN-EXTENDED"
        for order in ((short, long), (long, short)):
            with self.subTest(order=order):
                redacted = _redact(f"header={long}", *order)
                self.assertEqual(redacted, "header=***")

    def test_a_credential_that_is_empty_is_not_scrubbed_into_every_message(self):
        """An unset secret is the empty string, and replacing "" would redact everything."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url, 500, "server error", {}, io.BytesIO(b"plain detail")
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "tok", "", opener=opener)
        self.assertIn("plain detail", str(caught.exception))

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
