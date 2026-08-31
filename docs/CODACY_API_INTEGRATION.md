# Codacy API integration

## Goal

Expose Codacy findings through GitHub Actions so reviewers and connected GitHub clients can read the report without opening the Codacy web application.

## Authentication

Preferred secret: `CODACY_PROJECT_TOKEN` (repository-scoped Codacy API token).

Fallback secret: `CODACY_API_TOKEN` (Codacy account API token).

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

## Scope: repository backlog vs. pull-request delta

These are different questions with different answers, and confusing them attributes to a
branch every finding that was already on the default branch. The scope is chosen by the
`CODACY_PULL_REQUEST` environment variable, which the workflow sets from
`github.event.pull_request.number` on pull-request events, falling back to the
`inputs.pull_request` dispatch input on a manual run.

| Run | `CODACY_PULL_REQUEST` | Endpoint | The count means |
|---|---|---|---|
| `pull_request` | the PR number | `listPullRequestIssues` with `status=new` | issues this pull request introduces |
| `workflow_dispatch` with the `pull_request` input | that number | `listPullRequestIssues` with `status=new` | issues that pull request introduces |
| `workflow_dispatch` with the input empty | empty | `searchRepositoryIssues` | every open issue in the repository |

An unset or empty variable selects the repository scope. Any other non-numeric or non-positive
value is refused rather than silently falling back to it, so a misconfigured workflow cannot
publish a repository-wide backlog total under a pull request's name.

The manual dispatch input exists so the delta for any open pull request can be obtained on
demand, without waiting for a new push to that branch.

### The pull-request endpoint requires an *account* token

VERIFICADO by live run `33434452877`. Codacy refuses `listPullRequestIssues` when it is
presented with a repository token:

```text
HTTP 401 {"message":"Account authentication required","error":"Unauthorized","code":"ProjectTokenNotAllowed"}
```

So `CODACY_PROJECT_TOKEN` reaches every repository-scoped endpoint and no pull-request one.
`CODACY_API_TOKEN` is therefore not merely a fallback for this feature — it is the only
credential that can answer "what did this pull request introduce?".

When Codacy rejects the pull-request endpoint **and no account token is configured at all**,
the run degrades to the repository scope rather than failing every pull request over a secret
the repository has never held. The degradation is explicit and cannot be mistaken for a delta:
the report and the artifact both drop to `scope: repository`, and both carry a `NÃO DISPONÍVEL`
note stating that the counts are the backlog and naming the missing secret. The pull-request
label is never kept over a repository-wide count.

When an account token **is** configured and Codacy still rejects the request, that is a real
authentication failure and the run fails.

`codacy-issues.json` records which scope produced it: `{"scope": "repository", "data": [...]}`
or `{"scope": "pull-request", "pullRequest": N, "analyzed": bool, "data": [...]}`. The report's
header states the same thing in words.

### The `analyzed` flag is load-bearing

`PullRequestIssuesResponse` carries a required `analyzed` boolean — "True if Codacy already
analyzed the latest commit" — and documents `data` as an "empty list if Codacy didn't analyze
the latest commit yet". An unanalysed pull request and a clean one therefore return the same
empty list.

The reporter carries the flag out of the fetch and refuses to print a count when it is false,
emitting `NÃO DISPONÍVEL` instead. A response that omits the field, or sends a non-boolean, is
an error rather than an assumed `true`. Reporting an unanalysed head as zero new issues would
be a green verdict on work Codacy has not read; that is the failure this reporter exists to
prevent, and it is pinned by
`tests/test_codacy_api_report.py::CodacyPullRequestScopeTest`.

### Shape of the pull-request data

The pull-request endpoint returns `CommitDeltaIssue` objects — `{"commitIssue": {...},
"deltaType": "..."}` — where the repository search returns the issue directly. The artifact
keeps whichever shape Codacy sent, because it is the evidence; the report unwraps `commitIssue`
when rendering rows.

### Endpoint reference

Verified against Codacy's published OpenAPI document (`https://api.codacy.com/api/api-docs/swagger.yaml`):

- operationId `listPullRequestIssues`, summary "List issues found in a pull request";
- path `/analysis/organizations/{provider}/{remoteOrganizationName}/repositories/{repositoryName}/pull-requests/{pullRequestNumber}/issues`;
- `status` accepts `all`, `new`, `fixed`; `cursor` and `limit` paginate;
- auth headers `project-token` (`ProjectTokenAuth`) and `api-token` (`ApiKeyAuth`), which are the two this reporter already sends.

The spec lists `https://api.codacy.com/api/v3` as its server while this reporter calls
`https://app.codacy.com/api/v3`, the host Codacy's own guides use and the one under which the
existing repository-scoped reports were produced. The base URL is left as it is; both hosts
serve API v3 and only the working one has local evidence behind it.

If no token is configured the workflow reports `NÃO DISPONÍVEL` and does not pretend that Codacy was queried. `NÃO DISPONÍVEL` is the repository's operational status vocabulary; it is intentionally retained even though the surrounding documentation is English.

Before contacting Codacy, the workflow runs the reporter regression tests. They cover credential preference and account-token fallback on both scopes, missing-credential candidate selection, cursor pagination, refusal of a response body that is not a JSON object, the pull-request endpoint's path and `status=new` filter, the `analyzed` fail-closed rule, delta unwrapping, pull-request number validation, Markdown cell normalization, artifact shape, refusal of a body that is not valid JSON, and create/update behavior for the pull-request comment with mocked APIs.

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

### Account token — required for pull-request scope

Create an account API token in Codacy under `My Account` → `Access Management` → `API Tokens`,
then store it in GitHub as the repository secret `CODACY_API_TOKEN` (`Settings` → `Secrets and
variables` → `Actions` → `New repository secret`). Paste it only into that field; it must never
be sent anywhere else.

This is not optional for the pull-request delta. As recorded above, Codacy answers
`listPullRequestIssues` only to an account token; without this secret the reporter can produce
the repository backlog and nothing else.

The workflow prefers `CODACY_PROJECT_TOKEN` when both secrets are configured, and does not discard the configured account-token recovery path after an authentication or authorization rejection.

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
