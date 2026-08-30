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
from typing import Callable, Iterable

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


def _issue_url(provider: str, org: str, repo: str) -> str:
    quote = lambda value: urllib.parse.quote(value, safe="")
    return f"{API_ROOT}/{quote(provider)}/{quote(org)}/repositories/{quote(repo)}/issues/search"


def _read_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:1000]
    except Exception:
        return ""


def _fetch_pages(
    base: str,
    token_header: str,
    token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> list[dict]:
    issues: list[dict] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        url = base
        if cursor:
            url += "?" + urllib.parse.urlencode({"cursor": cursor})
        request = urllib.request.Request(
            url,
            data=b"{}",
            method="POST",
            headers={
                token_header: token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Codework-Codacy-API-Report/1.1",
            },
        )
        with opener(request, timeout=30) as response:
            payload = json.load(response)
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise CodacyAPIError("Codacy API returned a non-list data field")
        issues.extend(item for item in data if isinstance(item, dict))

        pagination = payload.get("pagination") or {}
        next_cursor = pagination.get("cursor") if isinstance(pagination, dict) else None
        if not next_cursor:
            return issues
        next_cursor = str(next_cursor)
        if next_cursor in seen_cursors:
            raise CodacyAPIError("Codacy API repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def fetch_issues(
    provider: str,
    org: str,
    repo: str,
    project_token: str,
    account_token: str,
    *,
    opener: Callable = urllib.request.urlopen,
) -> list[dict]:
    """Fetch all issue pages, retrying only auth failures with the account token."""
    candidates = credential_candidates(project_token, account_token)
    if not candidates:
        raise CodacyAPIError("No Codacy credential available")

    base = _issue_url(provider, org, repo)
    for index, (token_header, token) in enumerate(candidates):
        try:
            return _fetch_pages(base, token_header, token, opener=opener)
        except urllib.error.HTTPError as exc:
            has_fallback = index + 1 < len(candidates)
            if exc.code in AUTH_FAILURE_CODES and has_fallback:
                continue
            details = _read_http_error(exc)
            suffix = f": {details}" if details else ""
            raise CodacyAPIError(f"Codacy API HTTP {exc.code}{suffix}") from exc
        except urllib.error.URLError as exc:
            raise CodacyAPIError(f"Codacy API network error: {exc.reason}") from exc
    raise CodacyAPIError("Codacy authentication failed for all configured credentials")


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


def build_report(org: str, repo: str, issues: Iterable[dict]) -> str:
    """Build the human-readable report from a consolidated list of issues."""
    issue_list = list(issues)
    levels = Counter(str(pick(item, "patternInfo.level", "level", default="Unknown")) for item in issue_list)
    categories = Counter(str(pick(item, "patternInfo.category", "category", default="Unknown")) for item in issue_list)

    lines = [
        "# Codacy API report",
        "",
        f"Repository: `{markdown_cell(org)}/{markdown_cell(repo)}`",
        f"Issues returned by API: **{len(issue_list)}**",
        "",
        "## Severity",
        "",
    ]
    for name, count in sorted(levels.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {markdown_cell(name)}: {count}")
    lines += ["", "## Categories", ""]
    for name, count in sorted(categories.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {markdown_cell(name)}: {count}")

    lines += ["", "## Issues", "", "| Severity | Category | File | Pattern |", "|---|---|---|---|"]
    for issue in issue_list[:200]:
        severity = markdown_cell(pick(issue, "patternInfo.level", "level", default="Unknown"))
        category = markdown_cell(pick(issue, "patternInfo.category", "category", default="Unknown"))
        file_path = markdown_cell(pick(issue, "filePath", default=""))
        pattern = markdown_cell(pick(issue, "patternInfo.id", "patternId", default=""))
        lines.append(f"| {severity} | {category} | {file_path} | {pattern} |")
    if len(issue_list) > 200:
        lines += ["", f"Report truncated to the first 200 issues. Full JSON contains {len(issue_list)} issues."]
    return "\n".join(lines) + "\n"


def write_artifacts(org: str, repo: str, issues: list[dict], *, directory: Path = Path(".")) -> tuple[Path, Path]:
    """Write the consolidated JSON issue list and the Markdown report."""
    report_path = directory / "codacy-report.md"
    issues_path = directory / "codacy-issues.json"
    issues_path.write_text(json.dumps({"data": issues}, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(build_report(org, repo, issues), encoding="utf-8")
    return report_path, issues_path


def main() -> int:
    """Fetch Codacy data using environment configuration and publish local artifacts."""
    provider = os.environ.get("CODACY_PROVIDER", "gh")
    org = os.environ["CODACY_ORG"]
    repo = os.environ["CODACY_REPO"]
    issues = fetch_issues(
        provider,
        org,
        repo,
        os.environ.get("CODACY_PROJECT_TOKEN", ""),
        os.environ.get("CODACY_API_TOKEN", ""),
    )
    report_path, _ = write_artifacts(org, repo, issues)
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
