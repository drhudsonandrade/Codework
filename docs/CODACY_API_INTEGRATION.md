# Codacy API integration

## Goal

Publish a reviewable Codacy report without confusing the repository backlog with a branch
delta and without exposing a credential to pull-request code.

## Trust boundary

The integration is deliberately split into two workflows.

| Workflow | Event | Code executed | Secrets | GitHub permissions |
|---|---|---|---|---|
| `codacy-api-report-tests.yml` | `pull_request` | pull-request revision | none | `contents: read` |
| `codacy-api-report.yml` | requested/in-progress/completed `workflow_run` of the unprivileged tests | trusted default-branch `github.sha` | `codacy-report` publisher only | resolver: `actions: read`, `contents: read`, `pull-requests: read`; publisher: `actions: read`, `contents: read`, `pull-requests: write` |

The test workflow exercises the Python reporter, the workflow trust-boundary regression and
the JavaScript comment behavior. Its checkout sets `persist-credentials: false`; it cannot
read a Codacy secret or write a pull-request comment.

The consumer is loaded from the trusted default branch when the unprivileged pull-request
workflow is requested, starts or completes. A resolver job with no secrets checks out only
the default-branch `github.sha`, verifies the upstream workflow path and resolves one live,
open PR against the default branch. It re-reads the run through the Actions API and binds the
PR to the live run ID, run number, attempt, workflow path and `workflow_run.head_sha`. An
event from an older rerun attempt is stale. Activity events for the same producer `workflow_run.id` and `run_attempt` use
`cancel-in-progress: true`, so a later lifecycle event supersedes work still running for that
exact producer attempt. Different producer run IDs or rerun attempts never share a concurrency
group and therefore cannot cancel one another. GitHub does not guarantee dispatch
order, so cancellation is not treated as freshness evidence: the resolver paginates every producer run returned for the
same SHA and accepts only the unique newest `(run_number, run_attempt)` for the resolved head
repository, branch and PR association. A truncated, changing or over-limit run listing fails
closed. The validated coordinates are carried into the publisher and re-read before each
artifact or comment path, so a delayed run or older attempt cannot overwrite a newer one. An
empty PR association (as can occur for a fork) is resolved through a unique live head
repository and branch match. Ambiguous identities fail closed.

Only the validated pull-request identity fields — PR number, head SHA, current base SHA, run
ID, run number and run attempt — reach the publishing job from the resolver. The publisher also receives
the fixed provider, organization and repository context from the trusted workflow. That job
checks out the same trusted default-branch code. It re-fetches the PR and producer attempt
after the Codacy query and again immediately before commenting, and refuses an artifact or
comment if that identity changed. A requested, in-progress, cancelled, failed or successfully completed current run replaces
any older owned report with the corresponding explicit `NÃO DISPONÍVEL` pending, cancelled,
failed or processing state, or with the verified final report, so an old clean-looking result
is not left current. Superseded activity for the same producer run and attempt may be cancelled to avoid
redundant publication work; the resolver always re-reads the live terminal state. If a later publisher step fails after the trusted checkout succeeded, an
`always()` terminal step attempts to revalidate the PR/run tuple and replace the pending
state with an explicit publisher-failure state. A cancelled consumer does not attempt cleanup:
every successor for that exact producer attempt starts from trusted code, revalidates the live
tuple and repairs or invalidates the owned comment before querying Codacy or publishing a final
report. If another lifecycle event cancels that successor, the newest successor repeats the same
repair; the completed event therefore owns the terminal state. Checkout, resolver or GitHub API
failures remain visible as failed checks; the workflow does not claim that a comment update
succeeded when it could not perform one.
The pull request's files and artifacts are never executed by the privileged job. Top-level
permissions are empty, and write access exists only on the publishing job.

Because a `workflow_run` consumer must already exist on the default branch, the publisher
introduced by a pull request cannot perform a live privileged run on that same pull request.
That is an intentional security property. Pre-merge validation consists of the unprivileged
tests and static workflow checks; the first live publisher run occurs from trusted `main` on a
subsequent pull request.

Third-party actions are pinned to immutable commits recorded in `locks/actions-lock.json`.
The workflows select Ubuntu 24.04, Python 3.12 and Node 22.

## Authentication

Preferred environment secret: `CODACY_REPORT_PROJECT_TOKEN` (repository-scoped Codacy API
token). The workflow maps it to the reporter's `CODACY_PROJECT_TOKEN` process variable.

Optional environment fallback: `CODACY_REPORT_API_TOKEN` (Codacy account API token). The
workflow maps it to `CODACY_API_TOKEN` only inside the trusted publisher.

When both exist, the project token is attempted first. A `401` or `403` retries the request
from page one with the account token. Other HTTP failures are reported directly. Every
successful response is rejected if any key or value reproduces either configured credential,
including a project token rejected before an account-token fallback succeeds. Credential
headers are added as unredirected `urllib` headers, so a Codacy redirect cannot forward them
to another origin.

Neither token may be committed, placed in workflow inputs, or stored as a repository/organization
secret available to pull-request workflows. Both names must exist only as secrets of the
`codacy-report` environment. That environment must restrict deployments to the protected
default branch (`main`). Repository-level duplicates must be deleted, and any organization
secret with repository access must be removed from this repository. These settings are part
of the trust boundary, not optional defense in depth. Tokens used by the earlier privileged
pull-request design must be rotated before activating this publisher.

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
query, changes the effective result to `repository` scope and adds a prominent
`NÃO DISPONÍVEL` note saying that the count is backlog, not branch delta. The JSON keeps the
failed requested delta as separate structured provenance (`requestedScope`, requested PR,
source/target commits, endpoint, status and typed failure metadata); it never presents those
requested fields as the effective repository count. Network failures, malformed payloads
and non-auth HTTP errors fail the run instead of degrading.

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
- a `status=new` delta element lacks an object `commitIssue` or has any `deltaType` other
  than the schema value `Added`.

For a delta, `analyzed: false` produces `NÃO DISPONÍVEL` and no numeric count. Codacy
documents the empty list in that state, so treating it as zero would be a green verdict on a
commit that was not analyzed.

## Output handling

The publisher writes `codacy-report.md` and `codacy-issues.json`, appends the Markdown report
to the job summary, uploads both files for 30 days, and creates or updates a single
`github-actions[bot]`-owned PR comment marked with `<!-- codacy-api-report -->`. A different
bot cannot claim the marker and have its comment overwritten. If historical retries left more
than one owned marker comment, the publisher updates the canonical one and removes only its
own duplicates.

Codacy strings are untrusted output. Newlines are collapsed, HTML is entity-escaped, Markdown
table/link delimiters are escaped and `@` mentions are neutralized. HTTP error bodies are read
with a bound and scrubbed of both the literal and JSON-escaped forms of configured credentials
before truncation. Network-error details are likewise redacted, flattened to one line and
bounded. These untrusted diagnostics are never copied raw into the comment. The reporter also
prevents credentials from following redirects. A successful JSON response that reproduces
either configured credential — literal or already JSON-escaped — in any key or string value
is rejected before it can become report evidence or an artifact; it is not silently redacted
because that would alter the evidence being audited.

The comment behavior tests use Node's built-in test runner and a literal import of
`scripts/codacy_pr_comment.js`. They do not create a program dynamically, load a caller-
supplied module path, or invoke a subprocess from Python.

## Manual setup

1. Create the `codacy-report` GitHub environment and restrict its deployment branches to the
   protected default branch `main`.
2. Add `CODACY_REPORT_PROJECT_TOKEN` only to that environment. Add
   `CODACY_REPORT_API_TOKEN` there only when an account token is intentionally approved.
3. Delete/rotate the old `CODACY_PROJECT_TOKEN` and `CODACY_API_TOKEN` repository secrets,
   delete any repository-level duplicates of the new names, and revoke this repository's
   access to equivalent organization secrets. Do not activate the publisher until these
   settings have been verified in GitHub.
4. Merge the trusted publisher through normal review. Validate its first live run on the next
   pull request; do not add a privileged `workflow_dispatch` path merely to test it early.

If no environment token is configured, the publisher replaces its owned PR comment with
`NÃO DISPONÍVEL` and does not claim that Codacy was queried.

## External documentation

- Codacy API: https://docs.codacy.com/codacy-api/using-the-codacy-api/
- Codacy API tokens: https://docs.codacy.com/codacy-api/api-tokens/
- GitHub secure use reference: https://docs.github.com/en/actions/reference/security/secure-use
- GitHub workflow events: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- Python `urllib.request.Request`: https://docs.python.org/3/library/urllib.request.html#urllib.request.Request
