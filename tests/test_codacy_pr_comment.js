'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  MARKER,
  buildCodacyStatusReport,
  isCurrentCodacyPublication,
  isCurrentCodacyPullRequest,
  resolveCodacyPullRequest,
  upsertCodacyReportComment,
} = require('../scripts/codacy_pr_comment.js');

function makeGithub(previous) {
  const calls = [];
  const paginationCalls = [];
  const github = {
    paginate: async (...args) => {
      paginationCalls.push(args);
      return previous;
    },
    rest: {
      issues: {
        listComments: async () => {},
        updateComment: async (args) => calls.push(['update', args]),
        createComment: async (args) => calls.push(['create', args]),
      },
    },
  };
  return { github, calls, paginationCalls };
}

test('creates one report comment when none exists', async () => {
  const { github, calls, paginationCalls } = makeGithub([]);
  const result = await upsertCodacyReportComment({
    github,
    owner: 'o',
    repo: 'r',
    issue_number: 32,
    report: '# report',
  });

  assert.equal(result, 'created');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'create');
  assert.equal(calls[0][1].owner, 'o');
  assert.equal(calls[0][1].repo, 'r');
  assert.equal(calls[0][1].issue_number, 32);
  assert.equal(calls[0][1].body, `${MARKER}\n# report`);
  assert.equal(paginationCalls.length, 1);
  assert.equal(paginationCalls[0][0], github.rest.issues.listComments);
  assert.deepEqual(paginationCalls[0][1], {
    owner: 'o',
    repo: 'r',
    issue_number: 32,
    per_page: 100,
  });
});

test('updates only the existing GitHub Actions report comment', async () => {
  const previous = [
    { id: 8, user: { type: 'Bot', login: 'foreign-bot[bot]' }, body: `${MARKER}\nforeign` },
    { id: 7, user: { type: 'Bot', login: 'github-actions[bot]' }, body: `${MARKER}\nold` },
    { id: 9, user: { type: 'User' }, body: `${MARKER}\nnot owned by the bot` },
  ];
  const { github, calls } = makeGithub(previous);
  const result = await upsertCodacyReportComment({
    github,
    owner: 'o',
    repo: 'r',
    issue_number: 32,
    report: '# current',
  });

  assert.equal(result, 'updated');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], 'update');
  assert.equal(calls[0][1].comment_id, 7);
  assert.equal(calls[0][1].body, `${MARKER}\n# current`);
});

test('renders explicit unavailable states bound to a commit', () => {
  const head = 'a'.repeat(40);
  for (const state of ['pending', 'failed', 'missing-token', 'publisher-failed']) {
    const report = buildCodacyStatusReport(head, state);
    assert.match(report, /NÃO DISPONÍVEL/);
    assert.match(report, new RegExp(head));
  }
  assert.throws(() => buildCodacyStatusReport('not-a-sha', 'pending'), TypeError);
  assert.throws(() => buildCodacyStatusReport(head, 'unknown'), TypeError);
});

test('accepts only the same open PR head and base on the default branch', async () => {
  const head = 'a'.repeat(40);
  const base = 'b'.repeat(40);
  const github = {
    rest: {
      pulls: {
        get: async () => ({
          data: {
            state: 'open',
            head: { sha: head },
            base: {
              sha: base,
              ref: 'main',
              repo: { full_name: 'owner/repo' },
            },
          },
        }),
      },
    },
  };

  assert.equal(
    await isCurrentCodacyPullRequest({
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base,
      defaultBranch: 'main',
    }),
    true,
  );

  for (const [field, value] of [
    ['head', 'c'.repeat(40)],
    ['base', 'd'.repeat(40)],
    ['defaultBranch', 'release'],
  ]) {
    const request = {
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base,
      defaultBranch: 'main',
    };
    request[field] = value;
    assert.equal(await isCurrentCodacyPullRequest(request), false);
  }
});

test('refuses publication from an older attempt before it can touch the PR', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github, calls } = makeResolverGithub(pullRequest, {
    id: 123,
    run_attempt: 2,
    status: 'in_progress',
    conclusion: null,
  });

  assert.equal(
    await isCurrentCodacyPublication({
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 123,
      run_attempt: 1,
    }),
    false,
  );
  assert.deepEqual(calls.map(([operation]) => operation), ['run']);
});

function makePullRequest(head, base = 'b'.repeat(40)) {
  return {
    number: 32,
    state: 'open',
    head: {
      sha: head,
      ref: 'feature',
      repo: { full_name: 'contributor/Codework' },
    },
    base: {
      sha: base,
      ref: 'main',
      repo: { full_name: 'owner/repo' },
    },
  };
}

function makeResolverGithub(
  pullRequest,
  liveRun = { id: 123, run_attempt: 1, status: 'completed', conclusion: 'success' },
  liveHead = pullRequest.head.sha,
) {
  const calls = [];
  return {
    calls,
    github: {
      rest: {
        actions: {
          getWorkflowRun: async (args) => {
            calls.push(['run', args]);
            return {
              data: {
                ...liveRun,
                path: '.github/workflows/codacy-api-report-tests.yml',
                head_sha: liveHead,
                event: 'pull_request',
              },
            };
          },
        },
        pulls: {
          get: async (args) => {
            calls.push(['get', args]);
            return { data: pullRequest };
          },
          list: async (args) => {
            calls.push(['list', args]);
            return { data: [pullRequest] };
          },
        },
      },
    },
  };
}

function makeWorkflowRun(head, pullRequests) {
  return {
    id: 123,
    run_attempt: 1,
    path: '.github/workflows/codacy-api-report-tests.yml',
    event: 'pull_request',
    head_sha: head,
    head_branch: 'feature',
    head_repository: {
      full_name: 'contributor/Codework',
      owner: { login: 'contributor' },
    },
    pull_requests: pullRequests,
    conclusion: 'success',
  };
}

test('resolves one associated PR and binds it to the workflow-run SHA', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github, calls } = makeResolverGithub(pullRequest);
  const resolved = await resolveCodacyPullRequest({
    github,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
    defaultBranch: 'main',
  });

  assert.deepEqual(resolved, {
    number: 32,
    head,
    base: 'b'.repeat(40),
    run_id: 123,
    run_attempt: 1,
    state: 'publish',
  });
  assert.deepEqual(calls.map(([operation]) => operation), ['run', 'get']);
});

test('resolves an empty association only through one matching live fork PR', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github, calls } = makeResolverGithub(pullRequest, {
    id: 123,
    run_attempt: 1,
    status: 'in_progress',
    conclusion: null,
  });
  const resolved = await resolveCodacyPullRequest({
    github,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, []),
    defaultBranch: 'main',
  });

  assert.equal(resolved.state, 'pending');
  assert.equal(calls[1][0], 'list');
  assert.deepEqual(calls[1][1], {
    owner: 'owner',
    repo: 'repo',
    state: 'open',
    base: 'main',
    head: 'contributor:feature',
    per_page: 100,
  });
});

test('ignores an event from an older workflow attempt', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github } = makeResolverGithub(pullRequest, {
    id: 123,
    run_attempt: 2,
    status: 'in_progress',
    conclusion: null,
  });
  const resolved = await resolveCodacyPullRequest({
    github,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
    defaultBranch: 'main',
  });

  assert.equal(resolved.state, 'stale');
});

test('rejects ambiguous associations and marks an old run stale', async () => {
  const head = 'a'.repeat(40);
  const current = makePullRequest('c'.repeat(40));
  const { github } = makeResolverGithub(
    current,
    { id: 123, run_attempt: 1, status: 'completed', conclusion: 'success' },
    head,
  );

  await assert.rejects(
    resolveCodacyPullRequest({
      github,
      owner: 'owner',
      repo: 'repo',
      workflowRun: makeWorkflowRun(head, [{ number: 31 }, { number: 32 }]),
      defaultBranch: 'main',
    }),
    /at most one associated pull request/,
  );

  const stale = await resolveCodacyPullRequest({
    github,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
    defaultBranch: 'main',
  });
  assert.equal(stale.state, 'stale');
});
