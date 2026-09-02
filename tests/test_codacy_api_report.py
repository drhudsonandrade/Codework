import io
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn
from unittest.mock import patch

#: Two commit SHAs standing in for a pull request's head and its base.
HEAD = "2957025d42e8daadf937d4044516f991d21deea4"
BASE = "eedcda6d2d6f7c009e40affa010161d3fd40ae94"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return io.StringIO(json.dumps(self.payload))

    def __exit__(self, exc_type, exc, tb):
        return False


def _payload_opener(payload) -> Callable[..., _Response]:
    """Return an opener that always serves one decoded JSON payload."""

    def opener(request, timeout=30) -> _Response:
        return _Response(payload)

    return opener


def _http_error_opener(
    status: int,
    body: bytes,
    *,
    reason: str = "server error",
    seen: list[str] | None = None,
) -> Callable:
    """Return an opener that records its URL, then raises one HTTP response."""

    def opener(request, timeout=30):
        if seen is not None:
            seen.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url, status, reason, {}, io.BytesIO(body)
        )

    return opener


def _credential_fallback_opener(
    status: int, seen: list[dict], payload: dict
) -> Callable[..., _Response]:
    """Reject the project token, record both attempts and accept the account token."""

    def opener(request, timeout=30) -> _Response:
        seen.append(dict(request.header_items()))
        if request.get_header("Project-token"):
            raise urllib.error.HTTPError(
                request.full_url,
                status,
                "auth rejected",
                {},
                io.BytesIO(b"bad token"),
            )
        return _Response(payload)

    return opener


def _url_recording_opener(urls: list[str], payload: dict) -> Callable[..., _Response]:
    """Record each requested URL while serving one decoded payload."""

    def opener(request, timeout=30) -> _Response:
        urls.append(request.full_url)
        return _Response(payload)

    return opener


class CodacyApiReportTest(unittest.TestCase):
    def test_project_token_is_preferred_but_account_token_is_retained_as_fallback(self):
        from scripts.codacy_api_report import credential_candidates

        self.assertEqual(
            credential_candidates("project", "account"),
            [("project-token", "project"), ("api-token", "account")],
        )
        self.assertEqual(credential_candidates("", ""), [])

    def test_a_malformed_credential_is_refused_before_any_request(self):
        from scripts.codacy_api_report import CodacyAPIError, credential_candidates

        with self.assertRaises(CodacyAPIError):
            credential_candidates("PLACEHOLDER\nINJECTED", "")

    def test_a_header_error_cannot_expose_a_valid_credential(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        prefix = "PLACEHOLDER"
        header_value = f"{prefix}-PROJECT-CREDENTIAL"

        def opener(request, timeout=30) -> NoReturn:
            del timeout
            value = request.get_header("Project-token")
            message = f"invalid header value {value!r} INJECTED"
            raise ValueError(message)

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", header_value, "", opener=opener)
        self.assertNotIn(header_value, str(caught.exception))
        self.assertNotIn("INJECTED", str(caught.exception))

    def test_auth_rejection_retries_once_with_account_token_for_401_and_403(self):
        from scripts.codacy_api_report import fetch_issues

        for status in (401, 403):
            with self.subTest(status=status):
                seen = []
                opener = _credential_fallback_opener(
                    status,
                    seen,
                    {"data": [{"id": "issue-1"}], "pagination": {}},
                )

                issues = fetch_issues(
                    "gh", "org", "repo", "project", "account", opener=opener
                )
                self.assertEqual(issues, [{"id": "issue-1"}])
                self.assertEqual(len(seen), 2)
                self.assertTrue(any(k.lower() == "project-token" for k in seen[0]))
                self.assertTrue(any(k.lower() == "api-token" for k in seen[1]))

    def test_fallback_payload_cannot_echo_the_rejected_project_credential(self):
        """Every configured credential stays secret, not only the successful fallback."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        prefix = "PLACEHOLDER"
        project = f"{prefix}-PROJECT-CREDENTIAL"
        account = f"{prefix}-ACCOUNT-CREDENTIAL"
        seen: list[dict] = []
        opener = _credential_fallback_opener(
            403,
            seen,
            {
                "data": [{"id": "issue-1", "diagnostic": project}],
                "pagination": {},
            },
        )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, account, opener=opener)
        self.assertEqual(len(seen), 2)
        self.assertIn("credential", str(caught.exception).lower())
        self.assertNotIn(project, str(caught.exception))

    def test_every_fallback_page_is_checked_against_both_credentials(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        prefix = "PLACEHOLDER"
        project = f"{prefix}-PROJECT-CREDENTIAL"
        account = f"{prefix}-ACCOUNT-CREDENTIAL"
        calls = 0

        def opener(request, timeout=30):
            nonlocal calls
            calls += 1
            if request.get_header("Project-token"):
                raise urllib.error.HTTPError(
                    request.full_url,
                    403,
                    "auth rejected",
                    {},
                    io.BytesIO(b"bad token"),
                )
            if calls == 2:
                return _Response({"data": [], "pagination": {"cursor": "next"}})
            return _Response(
                {"data": [{"id": "issue-1", "diagnostic": project}], "pagination": {}}
            )

        with self.assertRaises(CodacyAPIError):
            fetch_issues("gh", "org", "repo", project, account, opener=opener)
        self.assertEqual(calls, 3)

    def test_non_auth_http_error_does_not_fall_back(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        seen = []
        opener = _http_error_opener(500, b"boom", seen=seen)

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "account", opener=opener)
        self.assertEqual(len(seen), 1)
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

    def test_a_body_that_is_not_json_becomes_a_named_error(self):
        """A 200 carrying HTML is a proxy or a login page, not a Codacy response.

        `json.load` raised `JSONDecodeError`, which no handler here caught, so it reached
        `main` as a traceback that reads like a bug in this reporter. Raised by review.
        """
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        class _RawResponse:
            """A response whose body is not JSON at all."""

            def __enter__(self):
                return io.StringIO("<html><body>Sign in</body></html>")

            def __exit__(self, exc_type, exc, tb):
                return False

        def opener(request, timeout=30) -> _RawResponse:
            return _RawResponse()

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_non_standard_json_numbers_are_refused_on_input_and_output(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues, write_artifacts

        opener = _payload_opener(
            {"data": [{"metric": float("nan")}], "pagination": {}}
        )
        with self.assertRaises(CodacyAPIError):
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(CodacyAPIError):
                write_artifacts(
                    "org",
                    "repo",
                    [{"metric": float("inf")}],
                    directory=Path(td),
                )

    def test_invalid_utf8_becomes_a_named_error(self):
        """Invalid response bytes are an API failure, not an uncaught decoder traceback."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        class _RawResponse:
            def __enter__(self):
                return io.BytesIO(b'{"data":"\x80"}')

            def __exit__(self, exc_type, exc, tb):
                return False

        def opener(request, timeout=30) -> _RawResponse:
            return _RawResponse()

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_missing_data_is_refused_instead_of_becoming_a_clean_result(self):
        """A malformed 200 response must not be published as zero repository issues."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        opener = _payload_opener({"pagination": {}})

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("data", str(caught.exception))

    def test_a_successful_payload_that_echoes_the_active_credential_is_refused(self):
        """A credential in a 200 response must never reach the JSON artifact."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        prefix = "PLACEHOLDER-"
        header_value = f'{prefix}"PROJECT\\CREDENTIAL'
        opener = _payload_opener(
            {
                "data": [{"id": 1, "diagnostic": {"requestToken": header_value}}],
                "pagination": {},
            }
        )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", header_value, "", opener=opener)
        self.assertIn("credential", str(caught.exception).lower())
        self.assertNotIn(header_value, str(caught.exception))

    def test_a_preescaped_credential_variant_in_a_successful_payload_is_refused(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        prefix = "PLACEHOLDER-"
        credential = f'{prefix}"PROJECT\\CREDENTIAL'
        escaped = json.dumps(credential)[1:-1]
        opener = _payload_opener(
            {"data": [{"id": 1, "diagnostic": escaped}], "pagination": {}}
        )

        with self.assertRaises(CodacyAPIError):
            fetch_issues("gh", "org", "repo", credential, "", opener=opener)

    def test_delta_fallback_payload_is_checked_against_both_credentials(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_commit_delta_issues

        prefix = "PLACEHOLDER"
        project = f"{prefix}-PROJECT-CREDENTIAL"
        account = f"{prefix}-ACCOUNT-CREDENTIAL"
        seen: list[dict] = []
        opener = _credential_fallback_opener(
            401,
            seen,
            {
                "analyzed": True,
                "data": [
                    {
                        "deltaType": "Added",
                        "commitIssue": {"id": "issue-1", "diagnostic": project},
                    }
                ],
                "pagination": {},
            },
        )

        with self.assertRaises(CodacyAPIError):
            fetch_commit_delta_issues(
                "gh",
                "org",
                "repo",
                HEAD,
                project,
                account,
                target_commit=BASE,
                opener=opener,
            )
        self.assertEqual(len(seen), 2)

    def test_non_object_issue_is_refused_instead_of_being_dropped_from_the_count(self):
        """Every API element is evidence; silently discarding malformed elements undercounts."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        opener = _payload_opener(
            {"data": [{"id": 1}, "not-an-object"], "pagination": {}}
        )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("data", str(caught.exception))

    def test_credential_header_is_not_forwarded_by_urllib_redirects(self):
        """A cross-origin redirect must not inherit the Codacy credential header."""
        from scripts.codacy_api_report import _Endpoint, _page_request

        request = _page_request(
            _Endpoint(base="https://app.codacy.com/api/v3/issues", method="GET"),
            "project-token",
            "PLACEHOLDER-PROJECT-TOKEN",
            None,
        )
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://example.invalid/collect",
        )
        self.assertIsNotNone(redirected)
        self.assertEqual(request.get_header("Project-token"), "PLACEHOLDER-PROJECT-TOKEN")
        self.assertIsNone(redirected.get_header("Project-token"))

    def test_cursor_must_be_a_non_empty_string_when_present(self):
        """Malformed cursors cannot truncate pagination or be stringified into a new request."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        for cursor in (None, "", 0, False, [], {}, 3):
            with self.subTest(cursor=cursor):
                opener = _payload_opener(
                    {"data": [], "pagination": {"cursor": cursor}}
                )

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_issues("gh", "org", "repo", "project", "", opener=opener)
                self.assertIn("cursor must be a string", str(caught.exception))

    def test_repeated_cursor_is_refused_instead_of_looping_forever(self):
        """The second occurrence of one cursor terminates with a named error."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        def opener(request, timeout=30) -> _Response:
            return _Response({"data": [], "pagination": {"cursor": "same"}})

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("repeated", str(caught.exception))

    def test_a_payload_that_is_not_a_json_object_is_refused_before_it_is_read(self):
        """An array or scalar body must raise a named error, not `AttributeError`.

        `data`, `pagination` and `analyzed` are each validated, but every one of those checks
        reads a key off the payload. A JSON array or scalar — which an error page or an
        intercepting proxy can return with a 200 — reached `payload.get` first and raised
        `AttributeError: 'list' object has no attribute 'get'`, replacing the error that names
        the problem with a traceback that names the wrong one. Raised by review on this PR.
        """
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        for body in ([{"id": 1}], "unauthorized", 7, None):
            with self.subTest(body=body):
                opener = _payload_opener(body)

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_issues("gh", "org", "repo", "project", "", opener=opener)
                self.assertIn("JSON object", str(caught.exception))

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
                "patternInfo": {
                    "id": "P|1`x<details>[click](https://invalid)@spoof",
                    "level": "High\nInjected",
                    "category": "Sec|urity",
                },
            }],
        )
        issue_row = next(line for line in report.splitlines() if line.startswith("| High"))
        self.assertIn(r"Sec\|urity", issue_row)
        self.assertIn(r"src/a\`b.py \| injected \| row \|", issue_row)
        self.assertIn(r"P\|1\`x&lt;details&gt;\[click\]\(https://invalid\)&#64;spoof", issue_row)
        self.assertNotIn("<details>", issue_row)
        self.assertNotIn("[click](https://invalid)", issue_row)
        self.assertNotIn("@spoof", issue_row)
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

        opener = _http_error_opener(500, body)

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, account, opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        self.assertNotIn(account, message)
        # The diagnosis must survive the redaction, or the scrub trades one problem for another.
        self.assertIn("HTTP 500", message)
        self.assertIn("invalid token", message)

    def test_a_json_escaped_credential_is_also_scrubbed_from_an_error_body(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        for project in ('PLACEHOLDER-"-TOKEN', r"PLACEHOLDER-\-TOKEN"):
            with self.subTest(project=project):
                encoded = json.dumps({"echo": project}).encode("utf-8")
                opener = _http_error_opener(500, encoded)

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_issues("gh", "org", "repo", project, "", opener=opener)
                message = str(caught.exception)
                escaped = json.dumps(project)[1:-1]
                self.assertNotIn(project, message)
                self.assertNotIn(escaped, message)
                self.assertIn("HTTP 500", message)

    def test_an_unreadable_error_body_still_reports_the_http_status(self):
        """A broken error stream must not erase the actionable HTTP diagnosis."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        class _ExplodingBody:
            def read(self, *_args):
                raise OSError("connection reset")

            def close(self):
                pass

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url, 500, "server error", {}, _ExplodingBody()
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertIn("HTTP 500", str(caught.exception))

    def test_a_network_error_reason_cannot_expose_a_credential(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        project = "PLACEHOLDER-PROJECT-TOKEN"

        def opener(request, timeout=30):
            raise urllib.error.URLError(
                f"TLS helper echoed header: {project}\nsecond line"
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, "", opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        self.assertNotIn("\n", message)
        self.assertIn("network error", message)

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

        opener = _http_error_opener(500, body)

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, "", opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        # Not merely absent as a whole string: no fragment of it survives either.
        for cut in range(6, len(project)):
            self.assertNotIn(project[:cut], message, f"prefix of length {cut} survived")

    def test_a_multibyte_error_prefix_cannot_make_the_read_cut_through_a_credential(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_issues

        project = "A" * 40
        body = ("é" * 501).encode("utf-8") + project.encode("ascii") + b"tail"
        opener = _http_error_opener(500, body)

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", project, "", opener=opener)
        message = str(caught.exception)
        self.assertNotIn(project, message)
        self.assertNotIn("A" * 20, message)

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

        opener = _http_error_opener(500, b"plain detail")

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
            self.assertEqual(
                payload,
                {
                    "scope": "repository",
                    "endpoint": "searchRepositoryIssues",
                    "data": [{"id": 1}],
                },
            )
            self.assertTrue(
                report_path.read_text(encoding="utf-8").startswith("# Codacy API report")
            )


class CodacyPullRequestScopeTest(unittest.TestCase):
    """The endpoint that answers "what did *this pull request* introduce?".

    The repository search called with a body of `{}` returns the whole backlog. Quoting that
    total beside a pull request credits the branch with every finding already on the default
    branch — a mistake this project has actually made — so the delta has to come from the
    endpoint that computes it.

    That endpoint is `listCommitDeltaIssues`, not `listPullRequestIssues`. This repository's
    project token has been measured as refused by both; the commit endpoint still defines the
    correct source/target query and can succeed with an approved account token.
    """

    def test_the_commit_delta_endpoint_is_called_with_the_new_status_and_the_base_commit(self):
        """Path, filter and base are pinned, because a near-miss returns a plausible wrong number.

        Verified against Codacy's published OpenAPI document: operationId
        `listCommitDeltaIssues`, path `.../repositories/{repo}/commits/{sha}/deltaIssues`, with
        `status` taking `all | new | fixed` and an optional `targetCommitUuid`.

        Each part is load-bearing. Without `status=new` the answer includes issues the branch
        only inherited. Without `targetCommitUuid` Codacy compares against the source commit's
        *parent* — the delta of the last push, not of the branch against what it merges into.
        Either omission still returns a number that looks like a delta.

        The pull-request path must never appear: it refuses this credential outright.
        """
        from scripts.codacy_api_report import fetch_commit_delta_issues

        seen = []

        def opener(request, timeout=30):
            seen.append((request.get_method(), request.full_url, request.data))
            return _Response({"analyzed": True, "data": [], "pagination": {}})

        analyzed, issues = fetch_commit_delta_issues(
            "gh", "org", "repo", HEAD, "project", "", target_commit=BASE, opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(issues, [])
        method, url, body = seen[0]
        self.assertEqual(method, "GET")
        self.assertIsNone(body)
        self.assertIn(f"/repositories/repo/commits/{HEAD}/deltaIssues", url)
        self.assertIn("status=new", url)
        self.assertIn(f"targetCommitUuid={BASE}", url)
        self.assertNotIn("/pull-requests/", url)

    def test_an_unanalyzed_pull_request_is_never_reported_as_having_no_issues(self):
        """`analyzed: false` and "clean" are the same empty list, and must not read the same.

        The schema documents `data` as an "empty list if Codacy didn't analyze the latest
        commit yet". Treating that as zero findings publishes a green verdict on a commit
        Codacy has not read — the single failure this reporter exists to prevent — so the flag
        travels with the data and suppresses the count.
        """
        from scripts.codacy_api_report import build_report, fetch_commit_delta_issues

        opener = _payload_opener(
            {"analyzed": False, "data": [], "pagination": {}}
        )

        analyzed, issues = fetch_commit_delta_issues(
            "gh", "org", "repo", HEAD, "project", "", target_commit=BASE, opener=opener
        )
        self.assertFalse(analyzed)

        report = build_report(
            "org", "repo", issues, pull_request=32, source_commit=HEAD,
            target_commit=BASE, analyzed=analyzed,
        )
        self.assertIn("NÃO DISPONÍVEL", report)
        self.assertNotIn("**0**", report)

        # And the analysed case does state the count, or the guard above would be satisfied by
        # a report that never reports anything.
        clean = build_report(
            "org", "repo", [], pull_request=32, source_commit=HEAD,
            target_commit=BASE, analyzed=True,
        )
        self.assertIn("**0**", clean)
        self.assertNotIn("NÃO DISPONÍVEL", clean)

    def test_a_missing_analyzed_flag_is_refused_rather_than_assumed_true(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_commit_delta_issues

        for payload in ({"data": []}, {"analyzed": "true", "data": []}):
            with self.subTest(payload=payload):
                opener = _payload_opener(payload)

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_commit_delta_issues(
                        "gh", "org", "repo", HEAD, "project", "", opener=opener
                    )
                self.assertIn("analyzed", str(caught.exception))

    def test_one_unanalyzed_page_makes_the_whole_paginated_answer_unanalyzed(self):
        """Combining pages with `and`, not last-page-wins."""
        from scripts.codacy_api_report import fetch_commit_delta_issues

        pages = [
            {"analyzed": False, "data": [], "pagination": {"cursor": "p2"}},
            {"analyzed": True, "data": [], "pagination": {}},
        ]

        def opener(request, timeout=30):
            return _Response(pages.pop(0))

        analyzed, _ = fetch_commit_delta_issues(
            "gh", "org", "repo", HEAD, "project", "", target_commit=BASE, opener=opener
        )
        self.assertFalse(analyzed)

    def test_pull_request_pages_are_followed_and_delta_issues_are_unwrapped_for_the_report(self):
        """`data` here is `CommitDeltaIssue`, not the bare issue the repository search returns.

        The artifact keeps the wrapper — it is what Codacy said — so the report has to reach
        through `commitIssue` to find the severity and path. Without that, every row of a
        pull-request report renders as `Unknown`.
        """
        from scripts.codacy_api_report import build_report, fetch_commit_delta_issues

        pages = [
            {
                "analyzed": True,
                "data": [
                    {
                        "commitIssue": {
                            "filePath": "scripts/a.py",
                            "patternInfo": {
                                "id": "B101",
                                "level": "Warning",
                                "category": "Security",
                            },
                        },
                        "deltaType": "Added",
                    }
                ],
                "pagination": {"cursor": "page-2"},
            },
            {
                "analyzed": True,
                "data": [
                    {
                        "commitIssue": {
                            "filePath": "scripts/b.py",
                            "patternInfo": {
                                "id": "E731",
                                "level": "Info",
                                "category": "CodeStyle",
                            },
                        },
                        "deltaType": "Added",
                    }
                ],
                "pagination": {},
            },
        ]
        urls = []

        def opener(request, timeout=30):
            urls.append(request.full_url)
            return _Response(pages.pop(0))

        analyzed, issues = fetch_commit_delta_issues(
            "gh", "org", "repo", HEAD, "project", "", target_commit=BASE, opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(len(issues), 2)
        self.assertIn("cursor=page-2", urls[1])
        # The wrapper survives into the evidence rather than being flattened away.
        self.assertEqual(issues[0]["deltaType"], "Added")

        report = build_report(
            "org", "repo", issues, pull_request=32, source_commit=HEAD,
            target_commit=BASE, analyzed=True,
        )
        self.assertIn("| Warning | Security | scripts/a.py | B101 |", report)
        self.assertIn("| Info | CodeStyle | scripts/b.py | E731 |", report)
        self.assertNotIn("Unknown", report)

    def test_malformed_delta_wrapper_is_refused_instead_of_rendering_unknown(self):
        """A delta element must contain the issue object whose fields are reported."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_commit_delta_issues

        for item in (
            {"deltaType": "Added"},
            {"commitIssue": "not-an-object", "deltaType": "Added"},
            {"commitIssue": {"id": 1}},
            {"commitIssue": {"id": 1}, "deltaType": 1},
        ):
            with self.subTest(item=item):
                opener = _payload_opener(
                    {"analyzed": True, "data": [item], "pagination": {}}
                )

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_commit_delta_issues(
                        "gh", "org", "repo", HEAD, "project", "", opener=opener
                    )
                self.assertIn("commit delta issue", str(caught.exception))

    def test_the_report_states_which_scope_produced_its_count(self):
        from scripts.codacy_api_report import CodacyAPIError, build_report

        repository = build_report("org", "repo", [{"id": 1}])
        self.assertIn("Scope: **repository**", repository)
        self.assertIn("not the delta of any pull request", repository)

        pull = build_report(
            "org",
            "repo",
            [{"id": 1}],
            pull_request=30,
            source_commit=HEAD,
            target_commit=BASE,
            analyzed=True,
        )
        self.assertIn("Scope: **pull request #30**", pull)
        self.assertIn("listCommitDeltaIssues", pull)
        self.assertNotIn("listPullRequestIssues", pull)
        self.assertIn("status=new", pull)

        for source, target in (("", BASE), (HEAD, "")):
            with self.subTest(source=source, target=target):
                with self.assertRaises(CodacyAPIError):
                    build_report(
                        "org",
                        "repo",
                        [],
                        pull_request=30,
                        source_commit=source,
                        target_commit=target,
                    )
        with self.assertRaises(CodacyAPIError):
            build_report("org", "repo", [], scope="commit-delta")
        contradictory = (
            {"scope": "repository", "source_commit": HEAD},
            {"scope": "repository", "target_commit": BASE},
            {"scope": "commit-delta", "source_commit": HEAD, "status": "fixed"},
            {"scope": "commit-delta", "source_commit": "not-a-sha"},
            {
                "pull_request": 30,
                "source_commit": HEAD,
                "target_commit": "not-a-sha",
            },
            {"pull_request": 0, "source_commit": HEAD, "target_commit": BASE},
            {"pull_request": -1, "source_commit": HEAD, "target_commit": BASE},
            {"pull_request": True, "source_commit": HEAD, "target_commit": BASE},
            {"pull_request": "32", "source_commit": HEAD, "target_commit": BASE},
            {"scope": "commit-delta", "source_commit": HEAD, "analyzed": "false"},
            {"scope": "commit-delta", "source_commit": HEAD, "analyzed": 0},
            {"scope": "commit-delta", "source_commit": HEAD, "analyzed": 1},
            {"scope": "commit-delta", "source_commit": HEAD, "analyzed": None},
        )
        for provenance in contradictory:
            with self.subTest(provenance=provenance):
                with self.assertRaises(CodacyAPIError):
                    build_report("org", "repo", [], **provenance)

    def test_a_note_is_rendered_for_every_supported_scope(self):
        from scripts.codacy_api_report import build_report

        note = "diagnostic note"
        pull_request = build_report(
            "org",
            "repo",
            [],
            pull_request=32,
            source_commit=HEAD,
            target_commit=BASE,
            note=note,
        )
        commit_delta = build_report(
            "org",
            "repo",
            [],
            scope="commit-delta",
            source_commit=HEAD,
            target_commit=BASE,
            note=note,
        )

        self.assertIn(note, pull_request)
        self.assertIn(note, commit_delta)

    def test_commit_delta_without_a_pull_request_label_keeps_its_real_scope(self):
        """A manual commit delta is not the repository backlog merely because it lacks a PR."""
        from scripts.codacy_api_report import collect

        opener = _payload_opener({"analyzed": True, "data": [], "pagination": {}})

        collected = collect(
            "gh", "org", "repo", None, "project", "", src_commit=HEAD,
            target_commit=BASE, opener=opener,
        )
        self.assertEqual(getattr(collected, "scope", None), "commit-delta")
        self.assertEqual(getattr(collected, "endpoint", None), "listCommitDeltaIssues")
        self.assertEqual(getattr(collected, "source_commit", None), HEAD)
        self.assertEqual(getattr(collected, "target_commit", None), BASE)

    def test_a_pull_request_label_requires_both_head_and_base_commits(self):
        """A PR count cannot default to one push or silently become the repository backlog."""
        from scripts.codacy_api_report import CodacyAPIError, collect

        opener = _payload_opener(
            {"analyzed": True, "data": [], "pagination": {}}
        )
        for source, target, missing in (
            ("", BASE, "source"),
            (HEAD, "", "target"),
        ):
            with self.subTest(missing=missing):
                with self.assertRaises(CodacyAPIError) as caught:
                    collect(
                        "gh",
                        "org",
                        "repo",
                        32,
                        "project",
                        "",
                        src_commit=source,
                        target_commit=target,
                        opener=opener,
                    )
                self.assertIn(missing, str(caught.exception))

    def test_the_artifact_records_the_scope_it_was_produced_under(self):
        from scripts.codacy_api_report import write_artifacts

        with tempfile.TemporaryDirectory() as td:
            _, issues_path = write_artifacts(
                "org",
                "repo",
                [],
                directory=Path(td),
                pull_request=30,
                source_commit=HEAD,
                target_commit=BASE,
                analyzed=False,
            )
            payload = json.loads(issues_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "pull-request")
        self.assertEqual(payload["endpoint"], "listCommitDeltaIssues")
        self.assertEqual(payload["pullRequest"], 30)
        self.assertEqual(payload["sourceCommit"], HEAD)
        self.assertEqual(payload["targetCommit"], BASE)
        self.assertEqual(payload["targetStrategy"], "explicit")
        self.assertEqual(payload["status"], "new")
        self.assertIs(payload["analyzed"], False)

    def test_a_value_that_is_not_a_commit_sha_is_refused_before_any_request(self):
        """A bad SHA would be interpolated into the path and answered with a bare 404.

        Both SHAs arrive from workflow environment variables. A ref name, an empty expression
        substituted into a non-empty string, or a non-string from a programmatic caller must
        each produce an error naming the misconfiguration — not a 404, and not a `TypeError`
        from the regex, which is what a bare `re.match` gives for a non-string.
        """
        from scripts.codacy_api_report import CodacyAPIError, fetch_commit_delta_issues

        def opener(request, timeout=30):
            raise AssertionError(f"no request should be made: {request.full_url}")

        bad = (
            "",
            "refs/pull/30/merge",
            "abc",
            "zzzzzzz",
            HEAD + "0",
            HEAD + "\n",
            30,
            3.0,
            None,
            True,
        )
        for value in bad:
            with self.subTest(source=value):
                with self.assertRaises(CodacyAPIError):
                    fetch_commit_delta_issues(
                        "gh", "org", "repo", value, "project", "", opener=opener
                    )
        # The target SHA is validated on the same terms, not merely passed through.
        for value in bad[1:]:
            with self.subTest(target=value):
                with self.assertRaises(CodacyAPIError):
                    fetch_commit_delta_issues(
                        "gh", "org", "repo", HEAD, "project", "",
                        target_commit=value, opener=opener,
                    )

    def test_an_abbreviated_sha_is_accepted(self):
        """Codacy documents the path segment as a "UUID or SHA string"; short SHAs are valid."""
        from scripts.codacy_api_report import fetch_commit_delta_issues

        urls = []

        opener = _url_recording_opener(
            urls, {"analyzed": True, "data": [], "pagination": {}}
        )

        fetch_commit_delta_issues("gh", "org", "repo", HEAD[:7], "project", "", opener=opener)
        self.assertIn(f"/commits/{HEAD[:7]}/deltaIssues", urls[0])

    def test_the_configured_pull_request_variable_is_parsed_or_refused(self):
        """An unset variable is the repository scope; a malformed one is never silently that.

        A workflow that substitutes an empty GitHub expression into `pr-${{ ... }}`, or passes
        a ref name where a number belongs, must not quietly produce a repository-wide backlog
        total published under a pull request's name.
        """
        from scripts.codacy_api_report import CodacyAPIError, parse_pull_request

        self.assertIsNone(parse_pull_request(""))
        self.assertIsNone(parse_pull_request("   "))
        self.assertEqual(parse_pull_request("30"), 30)
        self.assertEqual(parse_pull_request(" 30 "), 30)
        for bad in ("0", "-1", "refs/pull/30/merge", "30x", "pr-"):
            with self.subTest(bad=bad):
                with self.assertRaises(CodacyAPIError):
                    parse_pull_request(bad)

    def test_the_account_token_fallback_covers_the_pull_request_endpoint_too(self):
        """The fallback is shared, so it must be shown to apply to both scopes."""
        from scripts.codacy_api_report import fetch_commit_delta_issues

        seen = []

        opener = _credential_fallback_opener(
            403,
            seen,
            {"analyzed": True, "data": [], "pagination": {}},
        )

        analyzed, _ = fetch_commit_delta_issues(
            "gh", "org", "repo", HEAD, "project", "account", opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(len(seen), 2)
        self.assertTrue(any(k.lower() == "api-token" for k in seen[1]))

    def test_status_new_refuses_a_delta_that_is_not_added(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_commit_delta_issues

        for delta_type in ("Removed", "Unexpected"):
            with self.subTest(delta_type=delta_type):
                opener = _payload_opener({
                    "analyzed": True,
                    "data": [{"commitIssue": {"id": 1}, "deltaType": delta_type}],
                    "pagination": {},
                })
                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_commit_delta_issues(
                        "gh", "org", "repo", HEAD, "project", "",
                        target_commit=BASE, opener=opener,
                    )
                self.assertIn("deltaType", str(caught.exception))


class CodacyScopeDegradationTest(unittest.TestCase):
    """What happens when the commit-delta endpoint refuses the configured credential.

    Observed live: this repository's project token receives
    `401 {"code":"ProjectTokenNotAllowed"}` from both delta endpoints. These cases prove that
    the commit-delta refusal is typed and that an explicit repository fallback cannot inherit
    the PR label.
    """

    @staticmethod
    def _opener(pull_request_status=401, repository_payload=None) -> Callable[..., _Response]:
        """An opener that rejects the delta endpoint and serves the repository search."""

        def opener(request, timeout=30) -> _Response:
            if "/deltaIssues" in request.full_url:
                raise urllib.error.HTTPError(
                    request.full_url,
                    pull_request_status,
                    "Unauthorized",
                    {},
                    io.BytesIO(b'{"code":"ProjectTokenNotAllowed"}'),
                )
            return _Response(repository_payload or {"data": [{"id": "backlog"}], "pagination": {}})

        return opener

    def test_a_rejected_delta_endpoint_raises_a_typed_auth_error(self):
        from scripts.codacy_api_report import CodacyAuthError, fetch_commit_delta_issues

        with self.assertRaises(CodacyAuthError):
            fetch_commit_delta_issues(
                "gh", "org", "repo", HEAD, "project", "", opener=self._opener()
            )

    def test_a_non_auth_failure_is_not_a_typed_auth_error(self):
        """The type must separate "needs a credential nobody has" from "something broke"."""
        from scripts.codacy_api_report import CodacyAPIError, CodacyAuthError, fetch_issues

        opener = _http_error_opener(500, b"boom")

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertNotIsInstance(caught.exception, CodacyAuthError)

    def test_a_refused_delta_degrades_to_the_backlog_and_says_so_loudly(self):
        """Degrading is allowed; relabelling a backlog as a branch's delta is not.

        The alternative to degrading is producing no report at all when Codacy refuses the
        delta endpoint. What it must never do is keep the pull-request label: the report and
        the artifact both drop to `repository` scope and carry a note saying, in words, that
        the counts are not the delta — and naming the refusal so it can be diagnosed.
        """
        from scripts.codacy_api_report import build_report, collect

        collected = collect(
            "gh", "org", "repo", 32, "project", "", src_commit=HEAD,
            target_commit=BASE, opener=self._opener()
        )
        self.assertIsNone(collected.pull_request)
        self.assertEqual(collected.issues, [{"id": "backlog"}])
        self.assertIn("NÃO DISPONÍVEL", collected.note)
        self.assertIn("not this branch's new issues", collected.note)
        # The refusal itself survives into the note, or the degradation is undiagnosable.
        self.assertIn("401", collected.note)

        report = build_report(
            "org", "repo", collected.issues, pull_request=collected.pull_request,
            analyzed=collected.analyzed, note=collected.note,
        )
        self.assertIn("Scope: **repository**", report)
        self.assertNotIn("Scope: **pull request", report)
        self.assertIn("NÃO DISPONÍVEL", report)

    def test_refusal_detail_cannot_inject_rendered_markdown_into_the_bot_comment(self):
        from scripts.codacy_api_report import _delta_refused_note

        note = _delta_refused_note(
            32,
            "HTTP 401 <details><summary>SPOOF</summary></details> [click](https://invalid) @spoof",
        )
        self.assertNotIn("<details>", note)
        self.assertNotIn("[click](https://invalid)", note)
        self.assertNotIn("@spoof", note)
        self.assertIn("&lt;details&gt;", note)

    def test_the_project_token_is_never_sent_to_the_pull_request_endpoint(self):
        """Codacy refuses a repository token there, so the reporter must not present it.

        The pull-request number is carried as a label for the report and nothing else. This
        asserts on the URLs actually requested, so a future change that reintroduced the
        account-token-only endpoint would be caught rather than merely discouraged in a
        comment.
        """
        from scripts.codacy_api_report import collect

        urls = []

        opener = _url_recording_opener(
            urls, {"analyzed": True, "data": [], "pagination": {}}
        )

        collect(
            "gh", "org", "repo", 30, "project", "", src_commit=HEAD,
            target_commit=BASE, opener=opener,
        )
        self.assertTrue(urls)
        for url in urls:
            self.assertNotIn("/pull-requests/", url)
        self.assertIn("/deltaIssues", urls[0])

    def test_the_degradation_is_recorded_in_the_artifact_not_only_in_the_prose(self):
        from scripts.codacy_api_report import collect, write_artifacts

        collected = collect(
            "gh", "org", "repo", 32, "project", "", src_commit=HEAD,
            target_commit=BASE, opener=self._opener()
        )
        with tempfile.TemporaryDirectory() as td:
            try:
                _, issues_path = write_artifacts(
                    "org", "repo", collected.issues, directory=Path(td),
                    pull_request=collected.pull_request, analyzed=collected.analyzed,
                    note=collected.note,
                    requested=collected.requested,
                    failure=collected.failure,
                )
            except (AttributeError, TypeError) as exc:
                self.fail(f"degraded provenance is not structurally supported: {exc}")
            payload = json.loads(issues_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "repository")
        self.assertNotIn("pullRequest", payload)
        self.assertIn("NÃO DISPONÍVEL", payload["note"])
        self.assertEqual(payload["requestedScope"], "pull-request")
        self.assertEqual(payload["requestedPullRequest"], 32)
        self.assertEqual(payload["requestedSourceCommit"], HEAD)
        self.assertEqual(payload["requestedTargetCommit"], BASE)
        self.assertEqual(payload["requestedEndpoint"], "listCommitDeltaIssues")
        self.assertEqual(payload["requestedStatus"], "new")
        self.assertEqual(payload["failure"]["type"], "authentication-refusal")
        self.assertIn("HTTP 401", payload["failure"]["detail"])

    def test_contradictory_or_incomplete_degradation_provenance_is_refused(self):
        from scripts.codacy_api_report import (
            AUTHENTICATION_REFUSAL,
            CodacyAPIError,
            CollectionFailure,
            RequestedQuery,
            write_artifacts,
        )

        repository_request = RequestedQuery(
            "repository", "searchRepositoryIssues", None, "", "", ""
        )
        delta_request = RequestedQuery(
            "pull-request", "listCommitDeltaIssues", 32, HEAD, BASE, "new"
        )
        valid_failure = CollectionFailure(AUTHENTICATION_REFUSAL, "HTTP 401")
        bad_detail = CollectionFailure(AUTHENTICATION_REFUSAL, 401)

        for requested, failure, note in (
            (repository_request, valid_failure, "NÃO DISPONÍVEL"),
            (delta_request, valid_failure, ""),
            (delta_request, bad_detail, "NÃO DISPONÍVEL"),
            (delta_request, None, "NÃO DISPONÍVEL"),
            (None, valid_failure, "NÃO DISPONÍVEL"),
        ):
            with self.subTest(requested=requested, failure=failure, note=note):
                with tempfile.TemporaryDirectory() as td:
                    with self.assertRaises(CodacyAPIError):
                        write_artifacts(
                            "org",
                            "repo",
                            [],
                            directory=Path(td),
                            scope="repository",
                            requested=requested,
                            failure=failure,
                            note=note,
                        )

    def test_a_repository_scoped_run_carries_no_note(self):
        """The note exists to mark a degraded run; an ordinary one must not look degraded."""
        from scripts.codacy_api_report import build_report, collect

        collected = collect("gh", "org", "repo", None, "project", "", opener=self._opener())
        self.assertEqual(collected.note, "")
        self.assertNotIn(
            "NÃO DISPONÍVEL", build_report("org", "repo", collected.issues, note=collected.note)
        )


if __name__ == "__main__":
    unittest.main()
