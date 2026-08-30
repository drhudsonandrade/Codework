# Codacy API integration

## Goal

Expose Codacy findings through GitHub Actions so reviewers and connected GitHub clients can read the report without opening the Codacy web application.

## Authentication

Preferred secret: `CODACY_PROJECT_TOKEN` (repository-scoped Codacy API token).

Fallback secret: `CODACY_API_TOKEN` (Codacy account API token).

Never commit either token to the repository.

## Workflow

`.github/workflows/codacy-api-report.yml` runs on pull-request updates and by manual dispatch.

When a token is present it:

1. calls Codacy API v3 `searchRepositoryIssues` for `drhudsonandrade/Codework`;
2. follows cursor pagination;
3. stores the complete response in `codacy-issues.json`;
4. creates `codacy-report.md` with totals by severity/category and an issue table;
5. adds the report to the GitHub Actions job summary;
6. uploads both files as the `codacy-api-report` artifact for 30 days;
7. on pull requests, creates or updates one bot comment containing the report.

If no token is configured the workflow reports `NÃO DISPONÍVEL` and does not pretend that Codacy was queried.

## Manual setup

### Repository token (preferred)

1. Open Codacy and select `drhudsonandrade / Codework`.
2. Open `Settings` → `API tokens`.
3. Select `Create API token` and create a repository token.
4. Copy the token once.
5. In GitHub open `Codework` → `Settings` → `Secrets and variables` → `Actions`.
6. Select `New repository secret`.
7. Name: `CODACY_PROJECT_TOKEN`.
8. Value: paste the Codacy repository token.
9. Save.
10. Open GitHub `Actions` → `Codacy API Report` → `Run workflow` to validate the connection.

### Account token fallback

If the repository token is rejected by a Codacy v3 endpoint, create an account API token in Codacy under `My Account` → `Access Management` → `API Tokens`, then store it in GitHub as `CODACY_API_TOKEN`.

The workflow always prefers `CODACY_PROJECT_TOKEN` when both secrets are configured.

## Security notes

- Tokens are read only from GitHub Actions secrets.
- Tokens are never written to artifacts, comments, repository files, or workflow outputs.
- The workflow requests only `contents: read` and `pull-requests: write` from `GITHUB_TOKEN`.
- PR comments contain Codacy findings, not the authentication token.

## External documentation

- Codacy API overview: https://docs.codacy.com/codacy-api/using-the-codacy-api/
- Codacy API tokens: https://docs.codacy.com/codacy-api/api-tokens/
- Codacy issues API example: https://docs.codacy.com/codacy-api/examples/obtaining-current-issues-in-repositories/
- GitHub Actions secrets: https://docs.github.com/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
