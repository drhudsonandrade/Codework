'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  MARKER,
  buildCodacyStatusReport,
  codacyStatusForRunState,
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
        deleteComment: async (args) => calls.push(['delete', args]),
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

test('updates one owned report comment and removes owned duplicates', async () => {
  const previous = [
    { id: 8, user: { type: 'Bot', login: 'foreign-bot[bot]' }, body: `${MARKER}\nforeign` },
    { id: 7, user: { type: 'Bot', login: 'github-actions[bot]' }, body: `${MARKER}\nold` },
    { id: 10, user: { type: 'Bot', login: 'github-actions[bot]' }, body: `${MARKER}\nduplicate` },
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
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], 'update');
  assert.equal(calls[0][1].comment_id, 7);
  assert.equal(calls[0][1].body, `${MARKER}\n# current`);
  assert.equal(calls[1][0], 'delete');
  assert.equal(calls[1][1].owner, 'o');
  assert.equal(calls[1][1].repo, 'r');
  assert.equal(calls[1][1].comment_id, 10);
});

test('renders explicit unavailable states bound to a commit', () => {
  const head = 'a'.repeat(40);
  for (const state of [
    'pending',
    'processing',
    'cancelled',
    'failed',
    'missing-token',
    'publisher-failed',
  ]) {
    const report = buildCodacyStatusReport(head, state);
    assert.match(report, /NÃO DISPONÍVEL/);
    assert.ok(report.includes(head));
  }
  assert.throws(() => buildCodacyStatusReport('not-a-sha', 'pending'), TypeError);
  assert.throws(() => buildCodacyStatusReport(head, 'unknown'), TypeError);
  assert.equal(codacyStatusForRunState('pending'), 'pending');
  assert.equal(codacyStatusForRunState('publish'), 'processing');
  assert.equal(codacyStatusForRunState('interrupted'), 'cancelled');
  assert.equal(codacyStatusForRunState('failed'), 'failed');
  assert.throws(() => codacyStatusForRunState('stale'), TypeError);
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

  for (const override of [
    { head: 'c'.repeat(40) },
    { base: 'd'.repeat(40) },
    { defaultBranch: 'release' },
  ]) {
    const request = {
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base,
      defaultBranch: 'main',
      ...override,
    };
    assert.equal(await isCurrentCodacyPullRequest(request), false);
  }
});

test('refuses publication from an older attempt before it can touch the PR', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github, calls } = makeResolverGithub(pullRequest, {
    id: 123,
    run_number: 7,
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
      run_number: 7,
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
  liveRun = {},
  liveHead = pullRequest.head.sha,
  liveIdentity = {},
  workflowRuns = null,
) {
  const calls = [];
  const currentRun = {
    id: 123,
    run_number: 7,
    run_attempt: 1,
    status: 'completed',
    conclusion: 'success',
    ...liveRun,
    path: '.github/workflows/codacy-api-report-tests.yml',
    head_sha: liveHead,
    head_branch: 'feature',
    head_repository: { full_name: 'contributor/Codework' },
    event: 'pull_request',
    ...liveIdentity,
  };
  return {
    calls,
    github: {
      rest: {
        actions: {
          getWorkflowRun: async (args) => {
            calls.push(['run', args]);
            return { data: currentRun };
          },
          listWorkflowRuns: async (args) => {
            calls.push(['runs', args]);
            const allRuns = workflowRuns ?? [currentRun];
            const page = args.page ?? 1;
            const start = (page - 1) * 100;
            return {
              data: {
                total_count: allRuns.length,
                workflow_runs: allRuns.slice(start, start + 100),
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
    run_number: 7,
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

function makeProducerRun(head, id = 123, runNumber = 7) {
  return {
    id,
    run_number: runNumber,
    run_attempt: 1,
    status: 'completed',
    conclusion: 'success',
    path: '.github/workflows/codacy-api-report-tests.yml',
    head_sha: head,
    head_branch: 'feature',
    head_repository: { full_name: 'contributor/Codework' },
    event: 'pull_request',
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
    run_number: 7,
    run_attempt: 1,
    state: 'publish',
  });
  assert.deepEqual(calls.map(([operation]) => operation), ['run', 'get', 'runs']);
  assert.deepEqual(calls[2][1], {
    owner: 'owner',
    repo: 'repo',
    workflow_id: 'codacy-api-report-tests.yml',
    event: 'pull_request',
    branch: 'feature',
    head_sha: head,
    per_page: 100,
    page: 1,
  });
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

test('only the newest producer run may publish for the same commit', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const older = makeProducerRun(head);
  const newer = makeProducerRun(head, 124, 8);
  const runs = [newer, older];
  const oldGithub = makeResolverGithub(pullRequest, older, head, {}, runs).github;
  const newGithub = makeResolverGithub(pullRequest, newer, head, {}, runs).github;
  const deletedFork = { ...pullRequest, head: { ...pullRequest.head, repo: null } };
  const deletedForkGithub = makeResolverGithub(deletedFork, newer, head, {}, runs).github;
  const missingHeadRepository = { ...newer, head_repository: undefined };
  const missingEveryHeadRepository = makeResolverGithub(
    deletedFork,
    newer,
    head,
    { head_repository: undefined },
    [missingHeadRepository],
  ).github;
  const missingHeadBranchPr = {
    ...pullRequest,
    head: { ...pullRequest.head, ref: '' },
  };
  const missingHeadBranch = { ...newer, head_branch: '' };
  const missingEveryHeadBranch = makeResolverGithub(
    missingHeadBranchPr,
    newer,
    head,
    { head_branch: '' },
    [missingHeadBranch],
  ).github;

  assert.equal(
    await isCurrentCodacyPublication({
      github: oldGithub,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 123,
      run_number: 7,
      run_attempt: 1,
    }),
    false,
  );
  assert.equal(
    await isCurrentCodacyPublication({
      github: newGithub,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 124,
      run_number: 8,
      run_attempt: 1,
    }),
    true,
  );
  assert.equal(
    await isCurrentCodacyPublication({
      github: deletedForkGithub,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 124,
      run_number: 8,
      run_attempt: 1,
    }),
    false,
  );
  for (const github of [missingEveryHeadRepository, missingEveryHeadBranch]) {
    assert.equal(
      await isCurrentCodacyPublication({
        github,
        owner: 'owner',
        repo: 'repo',
        issue_number: 32,
        head,
        base: 'b'.repeat(40),
        defaultBranch: 'main',
        run_id: 124,
        run_number: 8,
        run_attempt: 1,
      }),
      false,
    );
  }

  const stale = await resolveCodacyPullRequest({
    github: oldGithub,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
    defaultBranch: 'main',
  });
  assert.equal(stale.state, 'stale');
});

test('reads every producer-run page before deciding which run is newest', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const older = makeProducerRun(head, 200, 100);
  const lower = Array.from(
    { length: 99 },
    (_, index) => makeProducerRun(head, 100 + index, index + 1),
  );
  const newer = makeProducerRun(head, 201, 101);
  const { github, calls } = makeResolverGithub(
    pullRequest,
    older,
    head,
    {},
    [older, ...lower, newer],
  );

  assert.equal(
    await isCurrentCodacyPublication({
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 200,
      run_number: 100,
      run_attempt: 1,
    }),
    false,
  );
  assert.equal(calls.filter(([operation]) => operation === 'runs').length, 2);
});

test('refuses a truncated producer-run listing instead of returning partial evidence', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const firstPage = Array.from(
    { length: 100 },
    (_, index) => makeProducerRun(head, 1000 + index, index + 1),
  );
  const { github, calls } = makeResolverGithub(pullRequest);
  github.rest.actions.listWorkflowRuns = async (args) => {
    calls.push(['runs', args]);
    return {
      data: {
        total_count: 101,
        workflow_runs: args.page === 1 ? firstPage : [],
      },
    };
  };

  await assert.rejects(
    isCurrentCodacyPublication({
      github,
      owner: 'owner',
      repo: 'repo',
      issue_number: 32,
      head,
      base: 'b'.repeat(40),
      defaultBranch: 'main',
      run_id: 123,
      run_number: 7,
      run_attempt: 1,
    }),
    /ended before every result was read/,
  );
  assert.equal(calls.filter(([operation]) => operation === 'runs').length, 2);
});

test('does not label a cancelled producer as a failed test run', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  const { github } = makeResolverGithub(pullRequest, {
    id: 123,
    run_attempt: 1,
    status: 'completed',
    conclusion: 'cancelled',
  });
  const resolved = await resolveCodacyPullRequest({
    github,
    owner: 'owner',
    repo: 'repo',
    workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
    defaultBranch: 'main',
  });

  assert.equal(resolved.state, 'interrupted');
});

test('rejects every live workflow identity mismatch', async () => {
  const head = 'a'.repeat(40);
  const pullRequest = makePullRequest(head);
  for (const liveIdentity of [
    { path: '.github/workflows/other.yml' },
    { head_sha: 'c'.repeat(40) },
    { event: 'push' },
  ]) {
    const { github } = makeResolverGithub(
      pullRequest,
      undefined,
      head,
      liveIdentity,
    );
    await assert.rejects(
      resolveCodacyPullRequest({
        github,
        owner: 'owner',
        repo: 'repo',
        workflowRun: makeWorkflowRun(head, [{ number: 32 }]),
        defaultBranch: 'main',
      }),
      /live workflow run does not match/,
    );
  }
});

async function assertPullIdentityRejected(pullRequest, signedHead) {
  const { github } = makeResolverGithub(pullRequest, undefined, signedHead);
  await assert.rejects(
    resolveCodacyPullRequest({
      github,
      owner: 'owner',
      repo: 'repo',
      workflowRun: makeWorkflowRun(signedHead, [{ number: 32 }]),
      defaultBranch: 'main',
    }),
    /outside the trusted workflow identity/,
  );
}

test('rejects every untrusted pull-request identity field', async () => {
  const signedHead = 'a'.repeat(40);
  const current = makePullRequest(signedHead);
  const invalidPullRequests = [
    { ...current, base: { ...current.base, repo: { full_name: 'other/repo' } } },
    { ...current, base: { ...current.base, ref: 'release' } },
    { ...current, base: { ...current.base, sha: 'not-a-sha' } },
    { ...current, head: { ...current.head, repo: { full_name: 'other/Codework' } } },
    { ...current, head: { ...current.head, ref: 'other-feature' } },
    { ...current, head: { ...current.head, sha: 'not-a-sha' } },
  ];

  for (const pullRequest of invalidPullRequests) {
    await assertPullIdentityRejected(pullRequest, signedHead);
  }
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
