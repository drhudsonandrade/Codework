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
            self.assertEqual(payload, {"scope": "repository", "data": [{"id": 1}]})
            self.assertTrue(report_path.read_text(encoding="utf-8").startswith("# Codacy API report"))


class CodacyPullRequestScopeTest(unittest.TestCase):
    """The endpoint that answers "what did *this pull request* introduce?".

    The repository search called with a body of `{}` returns the whole backlog. Quoting that
    total beside a pull request credits the branch with every finding already on the default
    branch — a mistake this project has actually made — so the pull-request delta has to come
    from the endpoint that computes it.
    """

    def test_the_official_pull_request_endpoint_is_called_with_the_new_status_filter(self):
        """Path and filter are pinned, because a near-miss returns a plausible wrong number.

        Verified against Codacy's published OpenAPI document: operationId
        `listPullRequestIssues`, path `.../repositories/{repo}/pull-requests/{n}/issues`, with
        `status` taking `all | new | fixed`. A URL that omitted `status=new` would return the
        pull request's issues *including* pre-existing ones and still look like a delta.
        """
        from scripts.codacy_api_report import fetch_pull_request_issues

        seen = []

        def opener(request, timeout=30):
            seen.append((request.get_method(), request.full_url, request.data))
            return _Response({"analyzed": True, "data": [], "pagination": {}})

        analyzed, issues = fetch_pull_request_issues(
            "gh", "org", "repo", 32, "project", "", opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(issues, [])
        method, url, body = seen[0]
        self.assertEqual(method, "GET")
        self.assertIsNone(body)
        self.assertIn("/repositories/repo/pull-requests/32/issues", url)
        self.assertIn("status=new", url)

    def test_an_unanalyzed_pull_request_is_never_reported_as_having_no_issues(self):
        """`analyzed: false` and "clean" are the same empty list, and must not read the same.

        The schema documents `data` as an "empty list if Codacy didn't analyze the latest
        commit yet". Treating that as zero findings publishes a green verdict on a commit
        Codacy has not read — the single failure this reporter exists to prevent — so the flag
        travels with the data and suppresses the count.
        """
        from scripts.codacy_api_report import build_report, fetch_pull_request_issues

        def opener(request, timeout=30):
            return _Response({"analyzed": False, "data": [], "pagination": {}})

        analyzed, issues = fetch_pull_request_issues(
            "gh", "org", "repo", 32, "project", "", opener=opener
        )
        self.assertFalse(analyzed)

        report = build_report("org", "repo", issues, pull_request=32, analyzed=analyzed)
        self.assertIn("NÃO DISPONÍVEL", report)
        self.assertNotIn("**0**", report)

        # And the analysed case does state the count, or the guard above would be satisfied by
        # a report that never reports anything.
        clean = build_report("org", "repo", [], pull_request=32, analyzed=True)
        self.assertIn("**0**", clean)
        self.assertNotIn("NÃO DISPONÍVEL", clean)

    def test_a_missing_analyzed_flag_is_refused_rather_than_assumed_true(self):
        from scripts.codacy_api_report import CodacyAPIError, fetch_pull_request_issues

        for payload in ({"data": []}, {"analyzed": "true", "data": []}):
            with self.subTest(payload=payload):

                def opener(request, timeout=30, payload=payload):
                    return _Response(payload)

                with self.assertRaises(CodacyAPIError) as caught:
                    fetch_pull_request_issues(
                        "gh", "org", "repo", 32, "project", "", opener=opener
                    )
                self.assertIn("analyzed", str(caught.exception))

    def test_one_unanalyzed_page_makes_the_whole_paginated_answer_unanalyzed(self):
        """Combining pages with `and`, not last-page-wins."""
        from scripts.codacy_api_report import fetch_pull_request_issues

        pages = [
            {"analyzed": False, "data": [], "pagination": {"cursor": "p2"}},
            {"analyzed": True, "data": [], "pagination": {}},
        ]

        def opener(request, timeout=30):
            return _Response(pages.pop(0))

        analyzed, _ = fetch_pull_request_issues(
            "gh", "org", "repo", 32, "project", "", opener=opener
        )
        self.assertFalse(analyzed)

    def test_pull_request_pages_are_followed_and_delta_issues_are_unwrapped_for_the_report(self):
        """`data` here is `CommitDeltaIssue`, not the bare issue the repository search returns.

        The artifact keeps the wrapper — it is what Codacy said — so the report has to reach
        through `commitIssue` to find the severity and path. Without that, every row of a
        pull-request report renders as `Unknown`.
        """
        from scripts.codacy_api_report import build_report, fetch_pull_request_issues

        pages = [
            {
                "analyzed": True,
                "data": [
                    {
                        "commitIssue": {
                            "filePath": "scripts/a.py",
                            "patternInfo": {"id": "B101", "level": "Warning", "category": "Security"},
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
                            "patternInfo": {"id": "E731", "level": "Info", "category": "CodeStyle"},
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

        analyzed, issues = fetch_pull_request_issues(
            "gh", "org", "repo", 32, "project", "", opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(len(issues), 2)
        self.assertIn("cursor=page-2", urls[1])
        # The wrapper survives into the evidence rather than being flattened away.
        self.assertEqual(issues[0]["deltaType"], "Added")

        report = build_report("org", "repo", issues, pull_request=32, analyzed=True)
        self.assertIn("| Warning | Security | scripts/a.py | B101 |", report)
        self.assertIn("| Info | CodeStyle | scripts/b.py | E731 |", report)
        self.assertNotIn("Unknown", report)

    def test_the_report_states_which_scope_produced_its_count(self):
        from scripts.codacy_api_report import build_report

        repository = build_report("org", "repo", [{"id": 1}])
        self.assertIn("Scope: **repository**", repository)
        self.assertIn("not the delta of any pull request", repository)

        pull = build_report("org", "repo", [{"id": 1}], pull_request=30, analyzed=True)
        self.assertIn("Scope: **pull request #30**", pull)
        self.assertIn("status=new", pull)

    def test_the_artifact_records_the_scope_it_was_produced_under(self):
        from scripts.codacy_api_report import write_artifacts

        with tempfile.TemporaryDirectory() as td:
            _, issues_path = write_artifacts(
                "org", "repo", [], directory=Path(td), pull_request=30, analyzed=False
            )
            payload = json.loads(issues_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "pull-request")
        self.assertEqual(payload["pullRequest"], 30)
        self.assertIs(payload["analyzed"], False)

    def test_a_pull_request_number_that_is_not_a_positive_integer_is_refused(self):
        """A bad number would be interpolated into the path and answered with a bare 404."""
        from scripts.codacy_api_report import CodacyAPIError, fetch_pull_request_issues

        def opener(request, timeout=30):
            raise AssertionError(f"no request should be made: {request.full_url}")

        for value in (0, -1, "32", 3.0, None, True):
            with self.subTest(value=value):
                with self.assertRaises(CodacyAPIError):
                    fetch_pull_request_issues(
                        "gh", "org", "repo", value, "project", "", opener=opener
                    )

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
        from scripts.codacy_api_report import fetch_pull_request_issues

        seen = []

        def opener(request, timeout=30):
            seen.append(dict(request.header_items()))
            if request.get_header("Project-token"):
                raise urllib.error.HTTPError(
                    request.full_url, 403, "auth rejected", {}, io.BytesIO(b"bad token")
                )
            return _Response({"analyzed": True, "data": [], "pagination": {}})

        analyzed, _ = fetch_pull_request_issues(
            "gh", "org", "repo", 32, "project", "account", opener=opener
        )
        self.assertTrue(analyzed)
        self.assertEqual(len(seen), 2)
        self.assertTrue(any(k.lower() == "api-token" for k in seen[1]))


class CodacyScopeDegradationTest(unittest.TestCase):
    """What happens when the pull-request endpoint refuses the only configured credential.

    Observed live: Codacy answers `listPullRequestIssues` with
    `401 {"code":"ProjectTokenNotAllowed"}` for a repository token. The endpoint is answered
    only to an account token. A deployment holding just `CODACY_PROJECT_TOKEN` can therefore
    reach every repository-scoped endpoint and no pull-request one.
    """

    @staticmethod
    def _opener(pull_request_status=401, repository_payload=None):
        """An opener that rejects the pull-request endpoint and serves the repository one."""

        def opener(request, timeout=30):
            if "/pull-requests/" in request.full_url:
                raise urllib.error.HTTPError(
                    request.full_url,
                    pull_request_status,
                    "Unauthorized",
                    {},
                    io.BytesIO(b'{"code":"ProjectTokenNotAllowed"}'),
                )
            return _Response(repository_payload or {"data": [{"id": "backlog"}], "pagination": {}})

        return opener

    def test_a_rejected_pull_request_endpoint_raises_a_typed_auth_error(self):
        from scripts.codacy_api_report import CodacyAuthError, fetch_pull_request_issues

        with self.assertRaises(CodacyAuthError):
            fetch_pull_request_issues(
                "gh", "org", "repo", 32, "project", "", opener=self._opener()
            )

    def test_a_non_auth_failure_is_not_a_typed_auth_error(self):
        """The type must separate "needs a credential nobody has" from "something broke"."""
        from scripts.codacy_api_report import CodacyAPIError, CodacyAuthError, fetch_issues

        def opener(request, timeout=30):
            raise urllib.error.HTTPError(
                request.full_url, 500, "server error", {}, io.BytesIO(b"boom")
            )

        with self.assertRaises(CodacyAPIError) as caught:
            fetch_issues("gh", "org", "repo", "project", "", opener=opener)
        self.assertNotIsInstance(caught.exception, CodacyAuthError)

    def test_without_an_account_token_the_run_degrades_and_says_so_loudly(self):
        """Degrading is allowed; relabelling a backlog as a pull request's delta is not.

        The alternative to degrading would be failing every pull-request run over a secret the
        repository has never had. What it must never do is keep the pull-request label: the
        report and the artifact both drop to `repository` scope and carry a note saying the
        counts are not the delta.
        """
        from scripts.codacy_api_report import build_report, collect

        collected = collect("gh", "org", "repo", 32, "project", "", opener=self._opener())
        self.assertIsNone(collected.pull_request)
        self.assertEqual(collected.issues, [{"id": "backlog"}])
        self.assertIn("NÃO DISPONÍVEL", collected.note)
        self.assertIn("CODACY_API_TOKEN", collected.note)
        self.assertIn("not this pull request's new issues", collected.note)

        report = build_report(
            "org", "repo", collected.issues, pull_request=collected.pull_request,
            analyzed=collected.analyzed, note=collected.note,
        )
        self.assertIn("Scope: **repository**", report)
        self.assertNotIn("Scope: **pull request", report)
        self.assertIn("NÃO DISPONÍVEL", report)

    def test_with_an_account_token_configured_a_rejection_is_a_real_failure(self):
        """Both credentials rejected means broken auth, not an unconfigured capability."""
        from scripts.codacy_api_report import CodacyAuthError, collect

        with self.assertRaises(CodacyAuthError):
            collect("gh", "org", "repo", 32, "project", "account", opener=self._opener())

    def test_the_degradation_is_recorded_in_the_artifact_not_only_in_the_prose(self):
        from scripts.codacy_api_report import collect, write_artifacts

        collected = collect("gh", "org", "repo", 32, "project", "", opener=self._opener())
        with tempfile.TemporaryDirectory() as td:
            _, issues_path = write_artifacts(
                "org", "repo", collected.issues, directory=Path(td),
                pull_request=collected.pull_request, analyzed=collected.analyzed,
                note=collected.note,
            )
            payload = json.loads(issues_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["scope"], "repository")
        self.assertNotIn("pullRequest", payload)
        self.assertIn("NÃO DISPONÍVEL", payload["note"])

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
