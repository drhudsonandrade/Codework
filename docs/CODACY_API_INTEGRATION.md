# Codacy API integration

## Goal

Publish a reviewable Codacy report without confusing the repository backlog with a branch
delta and without exposing a credential to pull-request code.

## Trust boundary

The integration is deliberately split into two workflows.

| Workflow | Event | Code executed | Secrets | GitHub permissions |
|---|---|---|---|---|
| `codacy-api-report-tests.yml` | `pull_request` | pull-request revision | none | `contents: read` |
| `codacy-api-report.yml` | `pull_request_target` against `main` | explicit `base.sha` checkout | trusted-base job only | job-only `contents: read`, `pull-requests: write` |

The test workflow exercises the Python reporter, the workflow trust-boundary regression and
the JavaScript comment behavior. Its checkout sets `persist-credentials: false`; it cannot
read a Codacy secret or write a pull-request comment.

The publisher is loaded from the trusted base branch and checks out that same base commit.
The pull request number, head SHA and base SHA are data passed to the trusted reporter; the
pull request's files are never executed by the privileged job. Top-level permissions are
empty, and write access exists only on the publishing job.

Because a new `pull_request_target` workflow is read from the base branch, the publisher
introduced by a pull request cannot perform a live privileged run on that same pull request.
That is an intentional security property. Pre-merge validation consists of the unprivileged
tests and static workflow checks; the first live publisher run occurs from trusted `main` on a
subsequent pull request.

Third-party actions are pinned to immutable commits recorded in `locks/actions-lock.json`.
The workflows select Ubuntu 24.04, Python 3.12 and Node 22.

## Authentication

Preferred secret: `CODACY_PROJECT_TOKEN` (repository-scoped Codacy API token).

Optional fallback: `CODACY_API_TOKEN` (Codacy account API token).

When both exist, the project token is attempted first. A `401` or `403` retries the request
from page one with the account token. Other HTTP failures are reported directly. Credential
headers are added as unredirected `urllib` headers, so a Codacy redirect cannot forward them
to another origin.

Neither token may be committed or placed in workflow inputs. The publisher declares the
`codacy-report` environment as a deployment-approval hook, but its primary security boundary
does not depend on unverified environment settings: only the trusted base revision executes.
An environment-scoped secret is recommended defense in depth; an existing repository secret
remains compatible with this base-only design.

## Scope and provenance

The repository backlog and a commit delta answer different questions. Their counts must never
be substituted for one another.

| Scope | Endpoint | Meaning |
|---|---|---|
| `repository` | `searchRepositoryIssues` | every open issue Codacy currently reports for the repository |
| `pull-request` | `listCommitDeltaIssues`, `status=new` | new issues between the PR head SHA and base SHA; the PR number is a GitHub label |
| `commit-delta` | `listCommitDeltaIssues`, `status=new` | new issues for an explicit source/target commit range without a PR label |

`targetCommitUuid` is required for pull requests. Without it, Codacy compares the source
commit with its parent, which measures only the most recent push instead of the whole branch
against its merge base.

The Markdown report names the effective scope and endpoint. For a delta it also records the
source commit, target commit and `status=new`. The JSON artifact preserves the raw issue shape
and the same provenance, for example:

```json
{
  "scope": "pull-request",
  "endpoint": "listCommitDeltaIssues",
  "pullRequest": 32,
  "sourceCommit": "<head-sha>",
  "targetCommit": "<base-sha>",
  "targetStrategy": "explicit",
  "status": "new",
  "analyzed": true,
  "data": []
}
```

A repository artifact records `scope: repository`, `endpoint: searchRepositoryIssues` and its
`data`. A manual delta without a PR number remains `commit-delta`; it is never relabelled as a
repository report.

## Measured credential behavior and degradation

This repository's project token has been measured as accepted by
`searchRepositoryIssues` and refused with `ProjectTokenNotAllowed` by both delta endpoints.
The immutable evidence is:

| Endpoint | Measured result | Workflow evidence |
|---|---|---|
| `searchRepositoryIssues` | repository backlog returned | [run 33461733645](https://github.com/drhudsonandrade/Codework/actions/runs/33461733645) |
| `listPullRequestIssues` | `ProjectTokenNotAllowed` | [run 33434452877](https://github.com/drhudsonandrade/Codework/actions/runs/33434452877) |
| `listCommitDeltaIssues` | `ProjectTokenNotAllowed` | [run 33461624729](https://github.com/drhudsonandrade/Codework/actions/runs/33461624729) |

The reporter still uses the commit-delta endpoint because it expresses the required
source/target query and can work with an account token or a future compatible token.

Only a typed authentication refusal may degrade. The reporter then performs a repository
query, changes both artifacts to `repository` scope and adds a prominent `NÃO DISPONÍVEL`
note saying that the count is backlog, not branch delta. It never leaves a PR label on a
repository-wide count. Network failures, malformed payloads and non-auth HTTP errors fail the
run instead of degrading.

The Codacy GitHub App's own PR publication remains the authoritative per-PR summary whenever
the API delta is unavailable.

## Fail-closed response handling

The reporter refuses an API response rather than publishing a partial or false-clean result
when any of these conditions occurs:

- the response is invalid UTF-8, invalid JSON, or not a JSON object;
- `data` is absent, is not a list, or contains a non-object element;
- `pagination` is present but not an object;
- a present cursor is not a non-empty string, or a cursor repeats;
- a delta omits the boolean `analyzed` field;
- a delta element lacks an object `commitIssue` or a non-empty string `deltaType`.

For a delta, `analyzed: false` produces `NÃO DISPONÍVEL` and no numeric count. Codacy
documents the empty list in that state, so treating it as zero would be a green verdict on a
commit that was not analyzed.

## Output handling

The publisher writes `codacy-report.md` and `codacy-issues.json`, appends the Markdown report
to the job summary, uploads both files for 30 days, and creates or updates a single
`github-actions[bot]`-owned PR comment marked with `<!-- codacy-api-report -->`. A different
bot cannot claim the marker and have its comment overwritten.

Codacy strings are untrusted output. Newlines are collapsed, HTML is entity-escaped, Markdown
table/link delimiters are escaped and `@` mentions are neutralized. HTTP error bodies are read
with a bound, scrubbed of both configured credentials before truncation, and never copied raw
into the comment. The reporter also prevents credentials from following redirects.

The comment behavior tests use Node's built-in test runner and a literal import of
`scripts/codacy_pr_comment.js`. They do not create a program dynamically, load a caller-
supplied module path, or invoke a subprocess from Python.

## Manual setup

1. Configure `CODACY_PROJECT_TOKEN` as a GitHub Actions secret. Add `CODACY_API_TOKEN` only
   when an account token is intentionally approved.
2. For additional deployment control, create or restrict the `codacy-report` environment to
   `main`, copy the approved secrets into it, and then remove the same-named repository-level
   secrets. This hardening is optional because the workflow already executes only trusted base
   code; it must not be claimed as active until repository settings confirm it.
3. Merge the trusted publisher through normal review. Validate its first live run on the next
   pull request; do not add a privileged `workflow_dispatch` path merely to test it early.

If no Actions token is configured, the publisher records `NÃO DISPONÍVEL` in its job summary
and does not claim that Codacy was queried.

## External documentation

- Codacy API: https://docs.codacy.com/codacy-api/using-the-codacy-api/
- Codacy API tokens: https://docs.codacy.com/codacy-api/api-tokens/
- GitHub secure use reference: https://docs.github.com/en/actions/reference/security/secure-use
- GitHub workflow events: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Python `urllib.request.Request`: https://docs.python.org/3/library/urllib.request.html#urllib.request.Request
