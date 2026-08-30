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

1. calls Codacy API v3 `searchRepositoryIssues` for the current GitHub repository;
2. follows cursor pagination and consolidates the returned issue objects;
3. stores the consolidated issue list as `{ "data": [...] }` in `codacy-issues.json`; pagination metadata and other per-page top-level fields are not preserved;
4. creates `codacy-report.md` with totals by severity/category and a Markdown-safe issue table;
5. adds the report to the GitHub Actions job summary;
6. uploads both files as the `codacy-api-report` artifact for 30 days;
7. on pull requests, creates or updates one bot comment containing the report.

If no token is configured the workflow reports `NÃO DISPONÍVEL` and does not pretend that Codacy was queried. `NÃO DISPONÍVEL` is the repository's operational status vocabulary; it is intentionally retained even though the surrounding documentation is English.

Before contacting Codacy, the workflow runs the reporter regression tests. They cover credential preference and account-token fallback, missing-credential candidate selection, cursor pagination, Markdown cell normalization, artifact shape, and create/update behavior for the pull-request comment with mocked APIs.

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

### Account token fallback

If the repository token is rejected by a Codacy v3 endpoint with `401` or `403`, create an account API token in Codacy under `My Account` → `Access Management` → `API Tokens`, then store it in GitHub as `CODACY_API_TOKEN`.

The workflow prefers `CODACY_PROJECT_TOKEN` when both secrets are configured, but it no longer discards the configured account-token recovery path after an authentication or authorization rejection.

## Security notes

- Tokens are read only from GitHub Actions secrets and are scoped only to the steps that need them.
- Tokens are never written to artifacts, comments, repository files, or workflow outputs.
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
