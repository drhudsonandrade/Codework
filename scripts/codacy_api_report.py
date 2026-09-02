#!/usr/bin/env python3
"""Fetch Codacy issues and render deterministic GitHub-facing report artifacts."""

from __future__ import annotations

import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import NamedTuple

AUTH_FAILURE_CODES = {401, 403}
API_ROOT = "https://app.codacy.com/api/v3/analysis/organizations"
REPOSITORY_SCOPE = "repository"
PULL_REQUEST_SCOPE = "pull-request"
COMMIT_DELTA_SCOPE = "commit-delta"
REPOSITORY_ENDPOINT = "searchRepositoryIssues"
COMMIT_DELTA_ENDPOINT = "listCommitDeltaIssues"
COMMIT_DELTA_STATUS = "new"


class CodacyAPIError(RuntimeError):
    """A Codacy API request failed without a safe fallback path."""


class CodacyAuthError(CodacyAPIError):
    """Codacy rejected every configured credential for this endpoint.

    Distinguished from other failures because it is the one that can mean "this endpoint is
    outside the credential's scope" rather than "something is broken". Codacy answers
    `listPullRequestIssues` only to an account token, refusing a repository token with
    `401 ProjectTokenNotAllowed` — observed live in run 33434452877. The reporter therefore
    uses `listCommitDeltaIssues`, whose response can answer the same branch-delta question,
    but this repository's project token has also been measured as refused there. This class
    lets that scope refusal be distinguished from a broken credential and reported rather
    than converted into a false clean result.
    """


def credential_candidates(project_token: str, account_token: str) -> list[tuple[str, str]]:
    """Return credentials in preferred order without discarding the configured fallback."""
    candidates: list[tuple[str, str]] = []
    if project_token:
        candidates.append(("project-token", project_token))
    if account_token:
        candidates.append(("api-token", account_token))
    return candidates


def _quote(value: str) -> str:
    """Escape one path segment, `/` included, so a value can never add a path of its own."""
    return urllib.parse.quote(value, safe="")


def _repository_url(provider: str, org: str, repo: str) -> str:
    """Base path shared by every repository-scoped endpoint."""
    return f"{API_ROOT}/{_quote(provider)}/{_quote(org)}/repositories/{_quote(repo)}"


def _issue_url(provider: str, org: str, repo: str) -> str:
    """`searchRepositoryIssues` — every open issue in the repository, not in a pull request."""
    return f"{_repository_url(provider, org, repo)}/issues/search"


def _commit_delta_url(provider: str, org: str, repo: str, src_commit: str) -> str:
    """`listCommitDeltaIssues` — the issues one commit introduced or fixed.

    Chosen over Codacy's other delta endpoint, `listPullRequestIssues`, which is documented as
    account-only and refuses a repository token outright (`401 ProjectTokenNotAllowed`,
    observed in run 33434452877). This one sits in the repository analysis tree, and its
    published contract answers the same question: "List the issues introduced or fixed by a
    commit …
    Codacy will calculate the issues by creating a delta between the source commit and its
    parent commit. As an alternative, you can also provide a destination commit."

    The distinction from `searchRepositoryIssues` is the whole point: a body of `{}` there
    returns the repository's entire backlog, and quoting that total beside a branch would
    credit it with every finding that was already on the default branch.

    Verified against Codacy's published OpenAPI document (`api.codacy.com/api/api-docs/
    swagger.yaml`, operationId `listCommitDeltaIssues`). Its `CommitDeltaIssuesResponse` has
    the same shape as the pull-request one — required `analyzed`, `data` of `CommitDeltaIssue`,
    optional `pagination` — so every fail-closed rule below applies unchanged.

    MEASURED, and it did not go as expected: this repository's token is refused here too
    (run 33461624729, same `ProjectTokenNotAllowed`). The specification does not distinguish
    the two endpoints by credential class, so reachability was an assumption until a run
    tested it. The call is kept because it is the one that can succeed if the token's scope is
    widened, and because it never presents the project token to an endpoint documented as
    account-only; the degradation below is what actually runs today.
    """
    return f"{_repository_url(provider, org, repo)}/commits/{_quote(src_commit)}/deltaIssues"


def _redact(text: str, *secrets: str) -> str:
    """Remove every configured credential from text that is about to be logged.

    An `HTTPError` body is not this repository's to trust: an API that echoes the
    authenticated request in its error payload puts the credential in whatever reads that
    body. Here that is the `CodacyAPIError` message, which `main` prints to stderr — the job
    log, which is world-readable on a public repository and kept in the run history.

    The empty string is skipped: an unconfigured secret is `""`, and `str.replace("", ...)`
    would splice the placeholder between every character of the message.

    Longest first. Two configured credentials can share a prefix — the account token issued
    from the same project is the obvious case — and replacing the shorter one first turns
    `abcd` into `***d`, publishing the suffix of the longer secret. Ordering by length makes
    the outcome independent of the order the caller happened to pass them in.
    """
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "***")
    return text


#: How much of an error body reaches the message. Enough to diagnose, short enough not to
#: paste an entire API response into a job log.
MAX_ERROR_BODY_CHARS = 1000


def _read_http_error(exc: urllib.error.HTTPError, *secrets: str) -> str:
    """The error body, with any credential removed before it can be printed.

    Read bounded, redact, *then* truncate — in that order. Truncating first would cut a
    credential that begins just before the limit in half and leave the surviving fragment in
    the message, which is exactly what this function exists to prevent; so the read window is
    the reported limit plus the longest secret, which guarantees that any secret starting
    inside the reported window is present whole when `_redact` runs.

    The read is bounded rather than `exc.read()`: an error body is under the remote server's
    control, and this one is about to be held in memory and printed.
    """
    window = MAX_ERROR_BODY_CHARS + max((len(secret) for secret in secrets), default=0)
    try:
        body = exc.read(window).decode("utf-8", "replace")
    except Exception:
        return ""
    return _redact(body, *secrets)[:MAX_ERROR_BODY_CHARS]


class _Endpoint(NamedTuple):
    """One Codacy endpoint and how it is called, apart from the credential and the cursor.

    The two scopes differ in shape, not just in path: the repository search is a POST carrying
    a JSON filter body, the commit-delta listing a GET carrying query parameters. Holding that
    difference in one value keeps the pagination loop identical for both instead of growing a
    parameter for each way they diverge.
    """

    base: str
    method: str
    body: bytes | None = None
    params: dict[str, str] | None = None


#: Identifies this reporter in Codacy's request logs. Bumped when the request shape changes.
USER_AGENT = "Codework-Codacy-API-Report/1.3"


def _page_request(
    endpoint: _Endpoint, token_header: str, token: str, cursor: str | None
) -> urllib.request.Request:
    """Build the request for a single page of `endpoint`, positioned at `cursor`."""
    query = dict(endpoint.params or {})
    if cursor:
        query["cursor"] = cursor
    url = endpoint.base + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if endpoint.body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=endpoint.body, method=endpoint.method, headers=headers
    )
    # `urllib` copies ordinary headers when it follows a redirect. Credentials are deliberately
    # unredirected so a Codacy response cannot forward them to another origin.
    request.add_unredirected_header(token_header, token)
    return request


def _paged_payloads(endpoint: _Endpoint, token_header: str, token: str, *, opener: Callable):
    """Yield each page's decoded payload, following Codacy's cursor pagination to the end.

    Shared by both scopes so that pagination is implemented once: whatever the method and
    filter, both answer with the same `pagination.cursor` and both must be read to exhaustion.
    A partial read is the failure mode this repository cannot tolerate quietly — it looks
    exactly like a smaller set of findings.
    """
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        request = _page_request(endpoint, token_header, token, cursor)
        with opener(request, timeout=30) as response:
            try:
                payload = json.load(response)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                # A 200 carrying something that is not JSON is an answer from a proxy, a login
                # page or an error template, not from Codacy. `JSONDecodeError` escaped every
                # handler here and reached `main` as a traceback, which reads like a bug in
                # this reporter rather than a response it should not have been given.
                raise CodacyAPIError(
                    f"Codacy API returned a body that is not valid JSON: {exc}"
                ) from exc
        # Checked before anything reads a key off it. `data`, `pagination` and `analyzed` are
        # each validated below, but only once `payload` is known to be a mapping: a JSON array
        # or scalar — which an error page or an intercepting proxy can return with a 200 —
        # would otherwise reach `payload.get` and raise `AttributeError`, replacing a
        # `CodacyAPIError` naming the problem with a traceback that names the wrong one.
        if not isinstance(payload, dict):
            raise CodacyAPIError(
                f"Codacy API returned a {type(payload).__name__} where a JSON object was expected"
            )
        yield payload

        if "pagination" not in payload:
            return
        pagination = payload["pagination"]
        if not isinstance(pagination, dict):
            raise CodacyAPIError("Codacy API returned a non-object pagination field")
        if "cursor" not in pagination:
            return
        next_cursor = pagination["cursor"]
        if not isinstance(next_cursor, str) or not next_cursor:
            raise CodacyAPIError(
                "Codacy API pagination cursor must be a string when present"
            )
        if next_cursor in seen_cursors:
            raise CodacyAPIError("Codacy API repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _page_issues(payload: dict) -> list[dict]:
    """The issue objects on one page, refusing a `data` field that is not a list."""
    if "data" not in payload:
        raise CodacyAPIError("Codacy API omitted the required data field")
    data = payload["data"]
    if not isinstance(data, list):
        raise CodacyAPIError("Codacy API returned a non-list data field")
    if any(not isinstance(item, dict) for item in data):
        raise CodacyAPIError("Codacy API data field contains a non-object issue")
    return data


def _fetch_pages(
    base: str,
    token_header: str,
    token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> list[dict]:
    """Every issue the repository-scoped search returns, across all pages."""
    endpoint = _Endpoint(base=base, method="POST", body=b"{}")
    issues: list[dict] = []
    for payload in _paged_payloads(endpoint, token_header, token, opener=opener):
        issues.extend(_page_issues(payload))
    return issues


def _fetch_delta_pages(
    base: str,
    token_header: str,
    token: str,
    *,
    params: dict[str, str],
    opener: Callable = urllib.request.urlopen,
) -> tuple[bool, list[dict]]:
    """A delta endpoint's new issues, paired with whether Codacy has analysed the commit.

    `analyzed` is not advisory. The published schema documents `data` as an "empty list if
    Codacy didn't analyze the commit yet", so an unanalysed commit and a clean one are
    indistinguishable by the issue list alone. Reporting the first as the second would announce
    a green result for work Codacy has not looked at, which is the one claim this reporter
    exists to make impossible — so the flag is carried out of here and a missing or non-boolean
    flag is refused rather than assumed true.

    Pages are combined with `and`: if any page of a paginated answer reports an unanalysed
    commit, the whole answer is unanalysed.
    """
    endpoint = _Endpoint(base=base, method="GET", params=params)
    issues: list[dict] = []
    analyzed: bool | None = None
    for payload in _paged_payloads(endpoint, token_header, token, opener=opener):
        page_analyzed = payload.get("analyzed")
        if not isinstance(page_analyzed, bool):
            raise CodacyAPIError(
                "Codacy API omitted the required `analyzed` field for the commit delta"
            )
        analyzed = page_analyzed if analyzed is None else (analyzed and page_analyzed)
        page_issues = _page_issues(payload)
        for item in page_issues:
            if not isinstance(item.get("commitIssue"), dict) or not isinstance(
                item.get("deltaType"), str
            ) or not item["deltaType"]:
                raise CodacyAPIError(
                    "Codacy API returned a malformed commit delta issue"
                )
        issues.extend(page_issues)
    if analyzed is None:
        raise CodacyAPIError("Codacy API returned no pages for the commit delta")
    return analyzed, issues


def _with_credentials(
    project_token: str,
    account_token: str,
    attempt: Callable[[str, str], object],
) -> object:
    """Run `attempt` with the preferred credential, retrying only auth failures with the next.

    Shared by both scopes so the fallback rule is stated once: `401`/`403` means this
    credential cannot see the resource and the next configured one is worth trying; any other
    status is a real answer from Codacy and retrying it with a second token would only obscure
    it behind a second identical failure.
    """
    candidates = credential_candidates(project_token, account_token)
    if not candidates:
        raise CodacyAPIError("No Codacy credential available")

    for index, (token_header, token) in enumerate(candidates):
        try:
            return attempt(token_header, token)
        except urllib.error.HTTPError as exc:
            has_fallback = index + 1 < len(candidates)
            if exc.code in AUTH_FAILURE_CODES and has_fallback:
                continue
            details = _read_http_error(exc, project_token, account_token)
            suffix = f": {details}" if details else ""
            failure = CodacyAuthError if exc.code in AUTH_FAILURE_CODES else CodacyAPIError
            raise failure(f"Codacy API HTTP {exc.code}{suffix}") from exc
        except urllib.error.URLError as exc:
            raise CodacyAPIError(f"Codacy API network error: {exc.reason}") from exc
    raise CodacyAPIError("Codacy authentication failed for all configured credentials")


def fetch_issues(
    provider: str,
    org: str,
    repo: str,
    project_token: str,
    account_token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> list[dict]:
    """Fetch all repository issue pages, retrying only auth failures with the account token."""
    base = _issue_url(provider, org, repo)
    return _with_credentials(
        project_token,
        account_token,
        lambda header, token: _fetch_pages(base, header, token, opener=opener),
    )


#: A commit SHA as Codacy accepts it in a path segment: hexadecimal, full or abbreviated.
_COMMIT_SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _validate_commit_sha(label: str, value: object) -> None:
    """Refuse a non-empty value that is not a Codacy-compatible commit SHA."""
    if not isinstance(value, str):
        raise CodacyAPIError(f"invalid {label} commit SHA: {value!r}")
    if value and not _COMMIT_SHA.fullmatch(value):
        raise CodacyAPIError(f"invalid {label} commit SHA: {value!r}")


def fetch_commit_delta_issues(
    provider: str,
    org: str,
    repo: str,
    src_commit: str,
    project_token: str,
    account_token: str,
    *,
    target_commit: str = "",
    opener: Callable = urllib.request.urlopen,
) -> tuple[bool, list[dict]]:
    """The issues a commit introduced, with the flag saying whether Codacy analysed it.

    `target_commit` is the base the delta is taken against. Left empty, Codacy compares against
    the source commit's parent, which on a pull-request branch is the previous commit *on that
    branch* — the delta of one push, not of the whole branch. Passing the pull request's base
    SHA makes the answer the delta of the branch against what it will merge into, which is the
    question a reviewer is actually asking.

    Both SHAs are validated rather than interpolated on trust: they reach this function from
    workflow environment variables, and a value that is not a commit SHA would be pasted into
    the request path and answered with a 404 whose real cause — a misconfigured workflow —
    would be invisible in the report.
    """
    for label, value in (("source", src_commit), ("target", target_commit)):
        _validate_commit_sha(label, value)
    if not src_commit:
        raise CodacyAPIError("no source commit configured for the delta query")

    base = _commit_delta_url(provider, org, repo, src_commit)
    params = {"status": COMMIT_DELTA_STATUS}
    if target_commit:
        params["targetCommitUuid"] = target_commit
    return _with_credentials(
        project_token,
        account_token,
        lambda header, token: _fetch_delta_pages(
            base, header, token, params=params, opener=opener
        ),
    )


def pick(mapping: dict, *paths: str, default: object = "") -> object:
    """Return the first non-empty nested value from a Codacy issue object."""
    for path in paths:
        current: object = mapping
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                break
            current = current[part]
        else:
            if current not in (None, ""):
                return current
    return default


def markdown_cell(value: object) -> str:
    """Normalize untrusted API text into one Markdown-table-safe line."""
    text = re.sub(r"[\r\n\t]+", " ", str(value))
    text = re.sub(r" {2,}", " ", text).strip()
    text = html.escape(text, quote=False)
    text = text.translate(
        str.maketrans(
            {
                "\\": "\\\\",
                "|": "\\|",
                "`": "\\`",
                "[": "\\[",
                "]": "\\]",
                "(": "\\(",
                ")": "\\)",
            }
        )
    )
    return text.replace("@", "&#64;")


#: How many issues the Markdown table carries. The full set is always in the JSON artifact;
#: this only bounds what is pasted into a job summary and a pull-request comment.
MAX_TABLE_ROWS = 200


def _issue_table(bodies: list[dict]) -> list[str]:
    """The Markdown issue table, truncated to a length a PR comment can hold."""
    lines = ["", "## Issues", "", "| Severity | Category | File | Pattern |", "|---|---|---|---|"]
    for issue in bodies[:MAX_TABLE_ROWS]:
        severity = markdown_cell(pick(issue, "patternInfo.level", "level", default="Unknown"))
        category = markdown_cell(
            pick(issue, "patternInfo.category", "category", default="Unknown")
        )
        file_path = markdown_cell(pick(issue, "filePath", default=""))
        pattern = markdown_cell(pick(issue, "patternInfo.id", "patternId", default=""))
        lines.append(f"| {severity} | {category} | {file_path} | {pattern} |")
    if len(bodies) > MAX_TABLE_ROWS:
        lines += [
            "",
            f"Report truncated to the first {MAX_TABLE_ROWS} issues. "
            f"Full JSON contains {len(bodies)} issues.",
        ]
    return lines


def _issue_body(issue: dict) -> dict:
    """The issue itself, whether it arrived bare or wrapped in a pull-request delta.

    The commit-delta endpoint answers with `CommitDeltaIssue` — `{commitIssue, deltaType}` —
    while the repository search answers with the issue directly. The JSON artifact keeps
    whichever shape Codacy sent, because it is the evidence; the unwrapping happens here, where
    the report is rendered, rather than by rewriting what the API said.
    """
    inner = issue.get("commitIssue")
    return inner if isinstance(inner, dict) else issue


class _ReportContext(NamedTuple):
    """Normalized provenance shared by the Markdown and JSON renderers."""

    scope: str
    endpoint: str
    status: str
    is_delta: bool


def _report_context(
    scope: str | None,
    endpoint: str,
    pull_request: int | None,
    source_commit: str,
    target_commit: str,
    status: str,
    analyzed: object,
) -> _ReportContext:
    """Resolve defaults once and refuse contradictory scope/provenance labels."""
    if scope is None:
        if pull_request is not None:
            scope = PULL_REQUEST_SCOPE
        elif source_commit:
            scope = COMMIT_DELTA_SCOPE
        else:
            scope = REPOSITORY_SCOPE
    if scope not in {REPOSITORY_SCOPE, PULL_REQUEST_SCOPE, COMMIT_DELTA_SCOPE}:
        raise CodacyAPIError(f"unsupported Codacy report scope: {scope!r}")
    if pull_request is not None and (
        not isinstance(pull_request, int)
        or isinstance(pull_request, bool)
        or pull_request < 1
    ):
        raise CodacyAPIError(f"invalid pull request number: {pull_request!r}")
    if scope == PULL_REQUEST_SCOPE and pull_request is None:
        raise CodacyAPIError("pull-request scope requires a pull request number")
    if scope != PULL_REQUEST_SCOPE and pull_request is not None:
        raise CodacyAPIError(f"{scope} scope cannot carry a pull request label")
    if scope == REPOSITORY_SCOPE and (source_commit or target_commit):
        raise CodacyAPIError("repository scope cannot carry commit provenance")
    is_delta = scope in {PULL_REQUEST_SCOPE, COMMIT_DELTA_SCOPE}
    if is_delta and not source_commit:
        raise CodacyAPIError(f"{scope} scope requires a source commit SHA")
    if scope == PULL_REQUEST_SCOPE and not target_commit:
        raise CodacyAPIError("pull-request scope requires a target commit SHA")
    if is_delta:
        if not isinstance(analyzed, bool):
            raise CodacyAPIError("commit-delta analyzed field must be a boolean")
        _validate_commit_sha("source", source_commit)
        _validate_commit_sha("target", target_commit)
    expected_endpoint = COMMIT_DELTA_ENDPOINT if is_delta else REPOSITORY_ENDPOINT
    if endpoint and endpoint != expected_endpoint:
        raise CodacyAPIError(
            f"{scope} scope cannot claim the {endpoint!r} Codacy endpoint"
        )
    endpoint = endpoint or expected_endpoint
    if is_delta:
        if status and status != COMMIT_DELTA_STATUS:
            raise CodacyAPIError(
                f"commit-delta reports require status={COMMIT_DELTA_STATUS!r}"
            )
        status = COMMIT_DELTA_STATUS
    elif status:
        raise CodacyAPIError("repository scope cannot carry a commit-delta status")
    return _ReportContext(scope, endpoint, status, is_delta)


def build_report(
    org: str,
    repo: str,
    issues: Iterable[dict],
    *,
    scope: str | None = None,
    endpoint: str = "",
    pull_request: int | None = None,
    source_commit: str = "",
    target_commit: str = "",
    status: str = "",
    analyzed: bool = True,
    note: str = "",
) -> str:
    """Build the human-readable report, stating the scope the numbers actually belong to.

    A count is meaningless without its scope: the repository search returns every open finding
    in the default branch's backlog, and quoting that total next to a pull request would credit
    the branch with issues it never introduced. Each report therefore says which endpoint
    produced it and, for a pull request, that the filter was `status=new`.

    `analyzed=False` suppresses the count entirely. An unanalysed pull request returns an empty
    issue list, and printing "0" for it would be a green verdict on work Codacy has not read.
    """
    context = _report_context(
        scope,
        endpoint,
        pull_request,
        source_commit,
        target_commit,
        status,
        analyzed,
    )
    scope, endpoint, status = context.scope, context.endpoint, context.status

    issue_list = list(issues)
    bodies = [_issue_body(item) for item in issue_list]
    levels = Counter(
        str(pick(item, "patternInfo.level", "level", default="Unknown"))
        for item in bodies
    )
    categories = Counter(
        str(pick(item, "patternInfo.category", "category", default="Unknown"))
        for item in bodies
    )

    lines = [
        "# Codacy API report",
        "",
        f"Repository: `{markdown_cell(org)}/{markdown_cell(repo)}`",
    ]
    if scope == REPOSITORY_SCOPE:
        lines += [
            "Scope: **repository** — every open issue Codacy currently reports for this "
            "repository, not the delta of any pull request.",
            f"Endpoint: `{endpoint}`.",
            f"Issues returned by API: **{len(issue_list)}**",
        ]
        if note:
            lines += ["", note]
    else:
        if scope == PULL_REQUEST_SCOPE:
            lines.append(
                f"Scope: **pull request #{pull_request}** — commit delta returned by "
                f"`{endpoint}` (`status={status}`)."
            )
        else:
            lines.append(
                f"Scope: **commit delta** — result returned by `{endpoint}` "
                f"(`status={status}`)."
            )
        if source_commit:
            lines.append(f"Source commit: `{markdown_cell(source_commit)}`.")
        if target_commit:
            lines.append(f"Target commit: `{markdown_cell(target_commit)}`.")
        elif source_commit:
            lines.append("Target: source commit parent (Codacy default).")
        if pull_request is not None:
            lines.append(
                "The pull-request number labels the GitHub report; the source and target "
                "commits above define the API query."
            )
        if analyzed:
            subject = "this pull request" if pull_request is not None else "this commit delta"
            lines.append(f"New issues introduced by {subject}: **{len(issue_list)}**")
        else:
            subject = (
                "this pull request" if pull_request is not None else "the source commit"
            )
            lines += [
                "",
                f"**NÃO DISPONÍVEL** — Codacy has not yet analysed {subject} "
                "(`analyzed: false`). The endpoint returns an empty issue list in "
                "that state, so no count is reported here: an empty answer is not evidence of a "
                "clean result. Rerun this workflow once Codacy finishes analysing the head "
                "commit.",
            ]
            return "\n".join(lines) + "\n"

    lines += [
        "",
        "## Severity",
        "",
    ]
    for name, count in sorted(levels.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {markdown_cell(name)}: {count}")
    lines += ["", "## Categories", ""]
    for name, count in sorted(categories.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {markdown_cell(name)}: {count}")

    lines += _issue_table(bodies)
    return "\n".join(lines) + "\n"


def write_artifacts(
    org: str,
    repo: str,
    issues: list[dict],
    *,
    directory: Path = Path("."),
    scope: str | None = None,
    endpoint: str = "",
    pull_request: int | None = None,
    source_commit: str = "",
    target_commit: str = "",
    status: str = "",
    analyzed: bool = True,
    note: str = "",
) -> tuple[Path, Path]:
    """Write the consolidated JSON issue list and the Markdown report.

    The JSON carries the scope alongside the data. A reader who finds `codacy-issues.json` in
    an artifact download has no other way to tell a repository backlog from a pull request's
    own delta, and the two have been confused before — the counts are of entirely different
    things.
    """
    report_path = directory / "codacy-report.md"
    issues_path = directory / "codacy-issues.json"
    context = _report_context(
        scope,
        endpoint,
        pull_request,
        source_commit,
        target_commit,
        status,
        analyzed,
    )
    scope, endpoint, status, is_delta = context

    payload: dict[str, object] = {"scope": scope, "endpoint": endpoint, "data": issues}
    if is_delta:
        payload["sourceCommit"] = source_commit or None
        payload["targetCommit"] = target_commit or None
        payload["targetStrategy"] = "explicit" if target_commit else "source-parent"
        payload["status"] = status
        payload["analyzed"] = analyzed
    if pull_request is not None:
        payload["pullRequest"] = pull_request
    if note:
        payload["note"] = note
    issues_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(
        build_report(
            org,
            repo,
            issues,
            scope=scope,
            endpoint=endpoint,
            pull_request=pull_request,
            source_commit=source_commit,
            target_commit=target_commit,
            status=status,
            analyzed=analyzed,
            note=note,
        ),
        encoding="utf-8",
    )
    return report_path, issues_path


def parse_pull_request(raw: str) -> int | None:
    """The configured pull request number, or `None` for a repository-scoped run.

    An unset or empty variable means "no pull request" and therefore no PR label. Anything
    else must be a positive integer: a workflow that
    substitutes an empty expression into a non-empty string, or passes a ref name where a
    number belongs, is a configuration fault and is refused here rather than silently falling
    back to the repository scope and publishing a backlog total under a pull request's name.
    """
    text = raw.strip()
    if not text:
        return None
    if not text.isdigit() or int(text) < 1:
        raise CodacyAPIError(f"invalid CODACY_PULL_REQUEST value: {text!r}")
    return int(text)


def _delta_refused_note(pull_request: int | None, detail: str) -> str:
    """Why a delta run is reporting the repository backlog instead of the branch's own issues."""
    subject = f"pull request #{pull_request}" if pull_request else "commit"
    return (
        f"**NÃO DISPONÍVEL — {subject} delta.** Codacy refused `listCommitDeltaIssues` for the "
        f"configured credential ({markdown_cell(detail)}). **The counts above are the "
        "repository backlog, not "
        "this branch's new issues** — do not quote them as the delta. The delta published by "
        "the Codacy GitHub App on the pull request itself remains the authoritative summary."
    )


class Collected(NamedTuple):
    """What was actually fetched, and under which scope it may be quoted."""

    scope: str
    endpoint: str
    pull_request: int | None
    source_commit: str
    target_commit: str
    status: str
    analyzed: bool
    issues: list[dict]
    note: str


def collect(
    provider: str,
    org: str,
    repo: str,
    pull_request: int | None,
    project_token: str,
    account_token: str,
    *,
    src_commit: str = "",
    target_commit: str = "",
    opener: Callable = urllib.request.urlopen,
) -> Collected:
    """Fetch the branch delta when a commit is configured, else the repository backlog.

    The delta comes from `listCommitDeltaIssues`. The pull-request number is carried only as a
    *label* for the report — it is never sent to `listPullRequestIssues`, the endpoint that
    refuses a repository token outright. This repository's project token has also been
    measured as refused by the commit-delta endpoint, so a typed refusal degrades explicitly
    to repository scope instead of being mistaken for a clean delta.

    Degradation is narrow on purpose: only an authentication refusal falls back, and only to
    the repository backlog with the scope relabelled and a note saying so. It never keeps the
    pull-request label over a repository-wide count — that substitution, quoting the backlog as
    a branch's delta, is the specific error this whole change exists to make impossible.
    """
    if pull_request is not None and not src_commit:
        raise CodacyAPIError("pull request scope requires a source commit SHA")
    if pull_request is not None and not target_commit:
        raise CodacyAPIError("pull request scope requires a target commit SHA")
    if target_commit and not src_commit:
        raise CodacyAPIError("a target commit requires a source commit SHA")
    if not src_commit:
        return Collected(
            REPOSITORY_SCOPE,
            REPOSITORY_ENDPOINT,
            None,
            "",
            "",
            "",
            True,
            fetch_issues(
                provider, org, repo, project_token, account_token, opener=opener
            ),
            "",
        )
    try:
        analyzed, issues = fetch_commit_delta_issues(
            provider,
            org,
            repo,
            src_commit,
            project_token,
            account_token,
            target_commit=target_commit,
            opener=opener,
        )
        scope = PULL_REQUEST_SCOPE if pull_request is not None else COMMIT_DELTA_SCOPE
        return Collected(
            scope,
            COMMIT_DELTA_ENDPOINT,
            pull_request,
            src_commit,
            target_commit,
            COMMIT_DELTA_STATUS,
            analyzed,
            issues,
            "",
        )
    except CodacyAuthError as exc:
        return Collected(
            REPOSITORY_SCOPE,
            REPOSITORY_ENDPOINT,
            None,
            "",
            "",
            "",
            True,
            fetch_issues(provider, org, repo, project_token, account_token, opener=opener),
            _delta_refused_note(pull_request, str(exc)),
        )


def main() -> int:
    """Fetch Codacy data using environment configuration and publish local artifacts."""
    provider = os.environ.get("CODACY_PROVIDER", "gh")
    org = os.environ["CODACY_ORG"]
    repo = os.environ["CODACY_REPO"]
    collected = collect(
        provider,
        org,
        repo,
        parse_pull_request(os.environ.get("CODACY_PULL_REQUEST", "")),
        os.environ.get("CODACY_PROJECT_TOKEN", ""),
        os.environ.get("CODACY_API_TOKEN", ""),
        src_commit=os.environ.get("CODACY_COMMIT", "").strip(),
        target_commit=os.environ.get("CODACY_BASE_COMMIT", "").strip(),
    )

    report_path, _ = write_artifacts(
        org,
        repo,
        collected.issues,
        scope=collected.scope,
        endpoint=collected.endpoint,
        pull_request=collected.pull_request,
        source_commit=collected.source_commit,
        target_commit=collected.target_commit,
        status=collected.status,
        analyzed=collected.analyzed,
        note=collected.note,
    )
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(report_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CodacyAPIError as exc:
        raise SystemExit(str(exc)) from exc
