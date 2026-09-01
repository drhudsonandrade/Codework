# Codacy API integration

## Goal

Expose Codacy findings through GitHub Actions so reviewers and connected GitHub clients can read the report without opening the Codacy web application.

## Authentication

Preferred secret: `CODACY_PROJECT_TOKEN` (repository-scoped Codacy API token).

Optional fallback secret: `CODACY_API_TOKEN` (Codacy account API token). Not required — see below.

Never commit either token to the repository.

When both secrets are configured, the project token is attempted first. If Codacy rejects it with an authentication or authorization response (`401` or `403`), the reporter retries from the first page with the account token. Other HTTP failures are reported directly and are not retried with a different credential.

## Workflow

`.github/workflows/codacy-api-report.yml` runs on pull-request updates and by manual dispatch. Repository owner and name are taken from the GitHub event context rather than hardcoded.

For pull requests, workflow runs are serialized by pull-request identity and a newer run cancels an older in-progress run. This prevents concurrent runs from creating duplicate report comments or allowing an older report to overwrite a newer one.

When a token is present it:

1. calls Codacy API v3 for the current GitHub repository, choosing the endpoint by scope (below);
2. follows cursor pagination and consolidates the returned issue objects;
3. stores the consolidated issue list with its scope in `codacy-issues.json`; pagination metadata and other per-page top-level fields are not preserved;
4. creates `codacy-report.md` with totals by severity/category and a Markdown-safe issue table;
5. adds the report to the GitHub Actions job summary;
6. uploads both files as the `codacy-api-report` artifact for 30 days;
7. on pull requests, creates or updates one bot comment containing the report.

## Scope: repository backlog vs. branch delta

These are different questions with different answers, and confusing them attributes to a
branch every finding that was already on the default branch.

| Run | Endpoint attempted | The count means |
|---|---|---|
| `pull_request` | `listCommitDeltaIssues` on the head SHA, `status=new`, `targetCommitUuid` = base SHA | issues this branch introduces against its base |
| `workflow_dispatch` with `commit` | the same, on the SHA given | issues that commit introduces |
| `workflow_dispatch` with `commit` empty | `searchRepositoryIssues` | every open issue in the repository |

**As configured today the first two are refused** (see the credentials section below) and the
run degrades to the repository backlog with the scope relabelled and a `NÃO DISPONÍVEL` note.
The authoritative per-PR delta is the summary the Codacy GitHub App publishes on the pull
request.

The workflow sets `CODACY_COMMIT` from `github.event.pull_request.head.sha` (or the `commit`
dispatch input) and `CODACY_BASE_COMMIT` from `github.event.pull_request.base.sha` (or
`base_commit`). `CODACY_PULL_REQUEST` is only a **label** for the report.

`codacy-issues.json` records which scope produced it: `{"scope": "repository", "data": [...]}`
or `{"scope": "pull-request", "pullRequest": N, "analyzed": bool, "data": [...]}`. The report's
header states the same thing in words.

Both SHAs are validated as hexadecimal commit strings before use, and a value that is not one
is refused rather than interpolated into the request path and answered with a bare 404.

### Why the base SHA matters

Left to its default, Codacy takes the delta between the source commit and **its parent** — on
a pull-request branch, the previous commit *on that branch*. That is the delta of one push, not
of the branch against what it will merge into. Passing the base SHA as `targetCommitUuid` makes
the answer the one a reviewer is actually asking for.

### Credentials: what the repository token actually reaches — MEASURED

Two delta endpoints exist. **This repository's `CODACY_PROJECT_TOKEN` is refused by both**,
with the same answer:

```text
HTTP 401 {"message":"Account authentication required","error":"Unauthorized","code":"ProjectTokenNotAllowed"}
```

| Endpoint | Scope | Repository token | Evidence |
|---|---|---|---|
| `searchRepositoryIssues` | repository backlog | **accepted** | every run of this workflow |
| `listPullRequestIssues` | PR delta | refused | run `33434452877` |
| `listCommitDeltaIssues` | commit delta | refused | run `33461624729` |

The commit-delta endpoint was adopted precisely because it sits in the repository analysis
tree and was expected to be within the token's scope. It is not, for this token. That is a
measurement, not a conclusion from the specification — the OpenAPI document does not
distinguish the two, and the earlier revision of this file asserted a reachability it had not
tested.

`ProjectTokenNotAllowed` is a credential-*scope* answer, not an invalid token. The repository
token continues to serve the repository backlog exactly as before.

The reporter still calls `listCommitDeltaIssues` rather than `listPullRequestIssues`: both are
refused today, but only the former can succeed if the token's scope is ever widened, and it
keeps the project token away from an endpoint documented as account-only. A regression test
asserts no request is ever made to a `/pull-requests/` path.

### Where a pull request's official delta comes from

The Codacy GitHub App already publishes a summary comment and a check run on every pull
request, carrying the total of new issues with their categories and severities. **That
publication is the authoritative per-PR delta** and needs no API call at all — read the pull
request's comments and locate the `codacy-production` comment.

Use this vocabulary when reporting, and do not blur it:

- **CONFIRMADO PELO CODACY NA PR** — from the Codacy publication on that pull request.
- **CONFIRMADO VIA CODACY API** — from a query actually executed with `CODACY_PROJECT_TOKEN`.
- **INFERIDO** — repository issues cross-referenced against the branch's files or commits.

An inference is never reported as "new issues da PR".

If the GitHub publication gives only the aggregate and the exact, individual list of that pull
request's new issues is indispensable and the commit delta cannot supply it, declare:

> NÃO DISPONÍVEL COM REPOSITORY API TOKEN NA API v3.

Only in that case is it worth explaining that `listPullRequestIssues` requires an Account API
Token. Do not request a new credential while the published summary or the commit delta answers
the question.

### Degradation

When Codacy refuses the delta endpoint, the run does not fail and does not silently substitute
one number for another: it falls back to the repository backlog, **relabels the scope to
`repository`** in both the report and the artifact, and carries a `NÃO DISPONÍVEL` note that
states the counts are not the delta and quotes the refusal so it can be diagnosed. The
pull-request label is never kept over a repository-wide count.

### The `analyzed` flag is load-bearing

`CommitDeltaIssuesResponse` carries a required `analyzed` boolean — "True if Codacy already
analyzed the commit" — and documents `data` as an "empty list if Codacy didn't analyze the
commit yet". An unanalysed commit and a clean one therefore return the same empty list.

The reporter carries the flag out of the fetch and refuses to print a count when it is false,
emitting `NÃO DISPONÍVEL` instead. A response that omits the field, or sends a non-boolean, is
an error rather than an assumed `true`. Reporting an unanalysed head as zero new issues would
be a green verdict on work Codacy has not read; that is the failure this reporter exists to
prevent, and it is pinned by
`tests/test_codacy_api_report.py::CodacyPullRequestScopeTest`.

### Shape of the delta data

The commit-delta endpoint returns `CommitDeltaIssue` objects — `{"commitIssue": {...},
"deltaType": "..."}` — where the repository search returns the issue directly. The artifact
keeps whichever shape Codacy sent, because it is the evidence; the report unwraps `commitIssue`
when rendering rows.

### Endpoint reference

Verified against Codacy's published OpenAPI document (`https://api.codacy.com/api/api-docs/swagger.yaml`):

- operationId `listCommitDeltaIssues`, summary "List the issues introduced or fixed by a commit";
- path `/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/commits/{srcCommitUuid}/deltaIssues`;
- `status` accepts `all`, `new`, `fixed`; `targetCommitUuid` selects the destination commit; `cursor` and `limit` paginate;
- response `CommitDeltaIssuesResponse`: required `analyzed` and `data` (of `CommitDeltaIssue` = `{commitIssue, deltaType}`), optional `pagination`;
- auth headers `project-token` (`ProjectTokenAuth`) and `api-token` (`ApiKeyAuth`), which are the two this reporter already sends.

The spec lists `https://api.codacy.com/api/v3` as its server while this reporter calls
`https://app.codacy.com/api/v3`, the host Codacy's own guides use and the one under which the
existing repository-scoped reports were produced. The base URL is left as it is; both hosts
serve API v3 and only the working one has local evidence behind it.

If no token is configured the workflow reports `NÃO DISPONÍVEL` and does not pretend that Codacy was queried. `NÃO DISPONÍVEL` is the repository's operational status vocabulary; it is intentionally retained even though the surrounding documentation is English.

Before contacting Codacy, the workflow runs the reporter regression tests. They cover credential preference and account-token fallback on both scopes, missing-credential candidate selection, cursor pagination, refusal of a response body that is not a JSON object, the commit-delta endpoint's path with its `status=new` filter and `targetCommitUuid`, the refusal of anything that is not a commit SHA, the guarantee that no request reaches a `/pull-requests/` path, the `analyzed` fail-closed rule, delta unwrapping, pull-request number validation, Markdown cell normalization, artifact shape, refusal of a body that is not valid JSON, and create/update behavior for the pull-request comment with mocked APIs.

The comment tests run the real `scripts/codacy_pr_comment.js` under Node through the committed
driver `tests/codacy_pr_comment_driver.js`, which takes the module path and the fixture as
argv *data*. Nothing is assembled into a program at run time, so the Bandit suppression at
that call site rests on a checked property — both paths are asserted to resolve to committed
files — rather than on a statement of intent. The workflow verifies `node --version` before
running the suite: the class is guarded by `skipUnless(node)`, and without that check a runner
image without Node would skip it and still report a green regression job.

## Manual setup

### Repository token (preferred)

1. Open Codacy and select the repository.
2. Open `Settings` → `API tokens`.
3. Select `Create API token` and create a repository token.
4. Copy the token once.
5. In GitHub open the repository → `Settings` → `Secrets and variables` → `Actions`.
6. Select `New repository secret`.
7. Name: `CODACY_PROJECT_TOKEN`.
8. Value: paste the Codacy repository token.
9. Save.
10. Open GitHub `Actions` → `Codacy API Report` → `Run workflow` to validate the connection.

### Account token — optional, and not needed for the delta

`CODACY_API_TOKEN` (a Codacy **Account** API Token) is optional and is not configured here.

Do not add it merely to read a pull request's delta: the Codacy GitHub App already publishes
that delta on the pull request itself, with totals, categories and severities, and that
publication is the authoritative source. Adding an account token would additionally let the
API return the individual issue list — which is a convenience, not a requirement, and a second
long-lived credential is not worth introducing for it.

The workflow prefers `CODACY_PROJECT_TOKEN` when both secrets are configured, and does not
discard a configured account-token recovery path after an authentication rejection.

## Security notes

- Tokens are read only from GitHub Actions secrets and are scoped only to the steps that need them.
- Tokens are never written to artifacts, comments, repository files, or workflow outputs.
- A job log is one of those outputs. An `HTTPError` body from Codacy is scrubbed of both
  configured tokens before it reaches the `CodacyAPIError` message that `main` prints to
  stderr, because an API that echoes the authenticated request in its error payload would
  otherwise publish the credential into a run history that is world-readable on a public
  repository. Covered by
  `tests/test_codacy_api_report.py::test_the_token_is_scrubbed_from_an_error_body_before_it_reaches_a_log`.
- The scrub runs before the body is shortened, not after. The reported body is capped at
  `MAX_ERROR_BODY_CHARS` (1000), but the read window is that cap plus the longest configured
  secret, so a credential starting just inside the cap is present whole when it is replaced
  rather than being sliced in half and leaving its tail in the message. Secrets are replaced
  longest first, so an account token that begins with the project token cannot be reduced to
  its suffix. Both are covered by regression tests in the same module.
- Third-party GitHub Actions are pinned to immutable commit SHAs recorded in `locks/actions-lock.json`.
- The workflow requests only `contents: read` and `pull-requests: write` from `GITHUB_TOKEN`.
- PR comments contain Codacy findings, not the authentication token.
- Dynamic Codacy values are normalized to a single line and escaped before insertion into Markdown tables.

## External documentation

- Codacy API overview: https://docs.codacy.com/codacy-api/using-the-codacy-api/
- Codacy API tokens: https://docs.codacy.com/codacy-api/api-tokens/
- Codacy issues API example: https://docs.codacy.com/codacy-api/examples/obtaining-current-issues-in-repositories/
- GitHub Actions secrets: https://docs.github.com/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- GitHub Actions concurrency: https://docs.github.com/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
