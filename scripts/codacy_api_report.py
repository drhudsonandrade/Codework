#!/usr/bin/env python3
"""Fetch Codacy issues and render deterministic GitHub-facing report artifacts."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

AUTH_FAILURE_CODES = {401, 403}
API_ROOT = "https://app.codacy.com/api/v3/analysis/organizations"


class CodacyAPIError(RuntimeError):
    """A Codacy API request failed without a safe fallback path."""


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


def _pull_request_issue_url(provider: str, org: str, repo: str, pull_request: int) -> str:
    """`listPullRequestIssues` — the issues Codacy attributes to one pull request.

    Verified against Codacy's published OpenAPI document (`api.codacy.com/api/api-docs/
    swagger.yaml`, operationId `listPullRequestIssues`, summary "List issues found in a pull
    request"). This is the distinction the repository-scoped endpoint cannot make: a body of
    `{}` there returns the repository's whole backlog, and reporting that total as a pull
    request's own delta would attribute to a branch every finding that was already on main.
    """
    return f"{_repository_url(provider, org, repo)}/pull-requests/{pull_request}/issues"


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
    a JSON filter body, the pull-request listing a GET carrying query parameters. Holding that
    difference in one value keeps the pagination loop identical for both instead of growing a
    parameter for each way they diverge.
    """

    base: str
    method: str
    body: bytes | None = None
    params: dict[str, str] | None = None


#: Identifies this reporter in Codacy's request logs. Bumped when the request shape changes.
USER_AGENT = "Codework-Codacy-API-Report/1.2"


def _page_request(
    endpoint: _Endpoint, token_header: str, token: str, cursor: str | None
) -> urllib.request.Request:
    """Build the request for a single page of `endpoint`, positioned at `cursor`."""
    query = dict(endpoint.params or {})
    if cursor:
        query["cursor"] = cursor
    url = endpoint.base + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {
        token_header: token,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if endpoint.body is not None:
        headers["Content-Type"] = "application/json"
    return urllib.request.Request(url, data=endpoint.body, method=endpoint.method, headers=headers)


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
            payload = json.load(response)
        yield payload

        pagination = payload.get("pagination")
        if pagination is not None and not isinstance(pagination, dict):
            raise CodacyAPIError("Codacy API returned a non-object pagination field")
        next_cursor = pagination.get("cursor") if pagination else None
        if not next_cursor:
            return
        next_cursor = str(next_cursor)
        if next_cursor in seen_cursors:
            raise CodacyAPIError("Codacy API repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _page_issues(payload: dict) -> list[dict]:
    """The issue objects on one page, refusing a `data` field that is not a list."""
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise CodacyAPIError("Codacy API returned a non-list data field")
    return [item for item in data if isinstance(item, dict)]


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


def _fetch_pull_request_pages(
    base: str,
    token_header: str,
    token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> tuple[bool, list[dict]]:
    """The pull request's new issues, paired with whether Codacy has analysed its head.

    `analyzed` is not advisory. The published schema documents `data` as an "empty list if
    Codacy didn't analyze the latest commit yet", so an unanalysed pull request and a clean one
    are indistinguishable by the issue list alone. Reporting the first as the second would
    announce a green result for work Codacy has not looked at, which is the one claim this
    reporter exists to make impossible — so the flag is carried out of here and a missing or
    non-boolean flag is refused rather than assumed true.

    Pages are combined with `and`: if any page of a paginated answer reports an unanalysed
    head, the whole answer is unanalysed.
    """
    endpoint = _Endpoint(base=base, method="GET", params={"status": "new"})
    issues: list[dict] = []
    analyzed: bool | None = None
    for payload in _paged_payloads(endpoint, token_header, token, opener=opener):
        page_analyzed = payload.get("analyzed")
        if not isinstance(page_analyzed, bool):
            raise CodacyAPIError(
                "Codacy API omitted the required `analyzed` field for the pull request"
            )
        analyzed = page_analyzed if analyzed is None else (analyzed and page_analyzed)
        issues.extend(_page_issues(payload))
    if analyzed is None:
        raise CodacyAPIError("Codacy API returned no pages for the pull request")
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
            raise CodacyAPIError(f"Codacy API HTTP {exc.code}{suffix}") from exc
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


def fetch_pull_request_issues(
    provider: str,
    org: str,
    repo: str,
    pull_request: int,
    project_token: str,
    account_token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> tuple[bool, list[dict]]:
    """Fetch the issues Codacy attributes to one pull request, with its `analyzed` flag.

    The pull request number is validated here rather than interpolated on trust: it reaches
    this function from a workflow environment variable, and a value that is not a positive
    integer would otherwise be pasted into the request path and answered with a 404 whose real
    cause — a misconfigured workflow — would be invisible in the report.
    """
    if isinstance(pull_request, bool) or not isinstance(pull_request, int) or pull_request < 1:
        raise CodacyAPIError(f"invalid pull request number: {pull_request!r}")
    base = _pull_request_issue_url(provider, org, repo, pull_request)
    return _with_credentials(
        project_token,
        account_token,
        lambda header, token: _fetch_pull_request_pages(base, header, token, opener=opener),
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
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("`", "\\`")


#: How many issues the Markdown table carries. The full set is always in the JSON artifact;
#: this only bounds what is pasted into a job summary and a pull-request comment.
MAX_TABLE_ROWS = 200


def _issue_table(bodies: list[dict]) -> list[str]:
    """The Markdown issue table, truncated to a length a PR comment can hold."""
    lines = ["", "## Issues", "", "| Severity | Category | File | Pattern |", "|---|---|---|---|"]
    for issue in bodies[:MAX_TABLE_ROWS]:
        severity = markdown_cell(pick(issue, "patternInfo.level", "level", default="Unknown"))
        category = markdown_cell(pick(issue, "patternInfo.category", "category", default="Unknown"))
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

    The pull-request endpoint answers with `CommitDeltaIssue` — `{commitIssue, deltaType}` —
    while the repository search answers with the issue directly. The JSON artifact keeps
    whichever shape Codacy sent, because it is the evidence; the unwrapping happens here, where
    the report is rendered, rather than by rewriting what the API said.
    """
    inner = issue.get("commitIssue")
    return inner if isinstance(inner, dict) else issue


def build_report(
    org: str,
    repo: str,
    issues: Iterable[dict],
    *,
    pull_request: int | None = None,
    analyzed: bool = True,
) -> str:
    """Build the human-readable report, stating the scope the numbers actually belong to.

    A count is meaningless without its scope: the repository search returns every open finding
    in the default branch's backlog, and quoting that total next to a pull request would credit
    the branch with issues it never introduced. Each report therefore says which endpoint
    produced it and, for a pull request, that the filter was `status=new`.

    `analyzed=False` suppresses the count entirely. An unanalysed pull request returns an empty
    issue list, and printing "0" for it would be a green verdict on work Codacy has not read.
    """
    issue_list = list(issues)
    bodies = [_issue_body(item) for item in issue_list]
    levels = Counter(str(pick(item, "patternInfo.level", "level", default="Unknown")) for item in bodies)
    categories = Counter(str(pick(item, "patternInfo.category", "category", default="Unknown")) for item in bodies)

    lines = [
        "# Codacy API report",
        "",
        f"Repository: `{markdown_cell(org)}/{markdown_cell(repo)}`",
    ]
    if pull_request is None:
        lines += [
            "Scope: **repository** — every open issue Codacy currently reports for this "
            "repository, not the delta of any pull request.",
            f"Issues returned by API: **{len(issue_list)}**",
        ]
    else:
        lines.append(
            f"Scope: **pull request #{pull_request}** — issues Codacy attributes to this pull "
            "request (`listPullRequestIssues`, `status=new`)."
        )
        if analyzed:
            lines.append(f"New issues introduced by this pull request: **{len(issue_list)}**")
        else:
            lines += [
                "",
                "**NÃO DISPONÍVEL** — Codacy has not yet analysed the latest commit of this "
                "pull request (`analyzed: false`). The endpoint returns an empty issue list in "
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
    pull_request: int | None = None,
    analyzed: bool = True,
) -> tuple[Path, Path]:
    """Write the consolidated JSON issue list and the Markdown report.

    The JSON carries the scope alongside the data. A reader who finds `codacy-issues.json` in
    an artifact download has no other way to tell a repository backlog from a pull request's
    own delta, and the two have been confused before — the counts are of entirely different
    things.
    """
    report_path = directory / "codacy-report.md"
    issues_path = directory / "codacy-issues.json"
    payload: dict[str, object] = {
        "scope": "repository" if pull_request is None else "pull-request",
        "data": issues,
    }
    if pull_request is not None:
        payload["pullRequest"] = pull_request
        payload["analyzed"] = analyzed
    issues_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(
        build_report(org, repo, issues, pull_request=pull_request, analyzed=analyzed),
        encoding="utf-8",
    )
    return report_path, issues_path


def parse_pull_request(raw: str) -> int | None:
    """The configured pull request number, or `None` for a repository-scoped run.

    An unset or empty variable means "no pull request", which is how `workflow_dispatch` runs
    reach the repository scope. Anything else must be a positive integer: a workflow that
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


def main() -> int:
    """Fetch Codacy data using environment configuration and publish local artifacts."""
    provider = os.environ.get("CODACY_PROVIDER", "gh")
    org = os.environ["CODACY_ORG"]
    repo = os.environ["CODACY_REPO"]
    project_token = os.environ.get("CODACY_PROJECT_TOKEN", "")
    account_token = os.environ.get("CODACY_API_TOKEN", "")
    pull_request = parse_pull_request(os.environ.get("CODACY_PULL_REQUEST", ""))

    if pull_request is None:
        analyzed, issues = True, fetch_issues(provider, org, repo, project_token, account_token)
    else:
        analyzed, issues = fetch_pull_request_issues(
            provider, org, repo, pull_request, project_token, account_token
        )

    report_path, _ = write_artifacts(
        org, repo, issues, pull_request=pull_request, analyzed=analyzed
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
