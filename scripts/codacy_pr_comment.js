'use strict';

const MARKER = '<!-- codacy-api-report -->';
const SHA_PATTERN = /^[0-9a-f]{40}$/i;
const STATUS_MESSAGES = Object.freeze({
  pending: 'the required pull-request tests are still running for this commit.',
  failed: 'the required pull-request tests did not complete successfully for this commit.',
  'missing-token': 'the trusted publisher has no environment-scoped Codacy API credential.',
  'publisher-failed': 'the trusted publisher failed before it could produce a current report.',
});
const PENDING_RUN_STATUSES = new Set([
  'requested',
  'queued',
  'pending',
  'waiting',
  'in_progress',
]);

function requireValid(condition, message) {
  if (!condition) {
    throw new TypeError(message);
  }
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function arrayOrEmpty(value) {
  return Array.isArray(value) ? value : [];
}

function hasLiveRunIdentity(liveRun, { id, run_attempt, head }) {
  return [
    liveRun?.id === id,
    liveRun?.run_attempt === run_attempt,
    liveRun?.path === '.github/workflows/codacy-api-report-tests.yml',
    liveRun?.head_sha === head,
    liveRun?.event === 'pull_request',
  ].every(Boolean);
}

function buildCodacyStatusReport(head, state) {
  if (!SHA_PATTERN.test(head) || !Object.hasOwn(STATUS_MESSAGES, state)) {
    throw new TypeError('A valid commit SHA and known Codacy report state are required.');
  }
  return [
    '# Codacy API report',
    '',
    `**NÃO DISPONÍVEL** — ${STATUS_MESSAGES[state]}`,
    '',
    `Source commit: \`${head}\`.`,
  ].join('\n');
}

async function isCurrentCodacyPullRequest({
  github,
  owner,
  repo,
  issue_number,
  head,
  base,
  defaultBranch,
}) {
  requireValid(
    [
      isPositiveInteger(issue_number),
      SHA_PATTERN.test(head),
      SHA_PATTERN.test(base),
      typeof defaultBranch === 'string',
      Boolean(defaultBranch),
    ].every(Boolean),
    'A validated pull-request identity is required.',
  );
  const { data: pr } = await github.rest.pulls.get({
    owner,
    repo,
    pull_number: issue_number,
  });
  return [
    pr.state === 'open',
    pr.head?.sha === head,
    pr.base?.sha === base,
    pr.base?.ref === defaultBranch,
    pr.base?.repo?.full_name?.toLowerCase() === `${owner}/${repo}`.toLowerCase(),
  ].every(Boolean);
}

async function isCurrentCodacyPublication({
  github,
  owner,
  repo,
  issue_number,
  head,
  base,
  defaultBranch,
  run_id,
  run_attempt,
}) {
  requireValid(
    [
      isPositiveInteger(run_id),
      isPositiveInteger(run_attempt),
      SHA_PATTERN.test(head),
      SHA_PATTERN.test(base),
    ].every(Boolean),
    'A validated publication identity is required.',
  );
  const { data: liveRun } = await github.rest.actions.getWorkflowRun({
    owner,
    repo,
    run_id,
  });
  if (!hasLiveRunIdentity(liveRun, { id: run_id, run_attempt, head })) {
    return false;
  }
  return isCurrentCodacyPullRequest({
    github,
    owner,
    repo,
    issue_number,
    head,
    base,
    defaultBranch,
  });
}

function validateWorkflowRun(workflowRun) {
  requireValid(
    [isPositiveInteger(workflowRun?.id), isPositiveInteger(workflowRun?.run_attempt)].every(
      Boolean,
    ),
    'The workflow run did not supply a valid run identity.',
  );
  requireValid(
    workflowRun.path === '.github/workflows/codacy-api-report-tests.yml',
    'The workflow run did not originate from the trusted test workflow.',
  );
  requireValid(
    workflowRun.event === 'pull_request',
    'The workflow run did not originate from a pull request.',
  );
  requireValid(
    SHA_PATTERN.test(workflowRun.head_sha),
    'The workflow run did not supply a valid source SHA.',
  );
  const headRepository = workflowRun.head_repository?.full_name;
  const headOwner = workflowRun.head_repository?.owner?.login;
  requireValid(
    [headRepository, headOwner, workflowRun.head_branch].every(Boolean),
    'The workflow run did not supply a complete head identity.',
  );
  const associated = arrayOrEmpty(workflowRun.pull_requests);
  requireValid(
    associated.length <= 1,
    'Expected at most one associated pull request.',
  );
  return associated;
}

async function loadLiveWorkflowRun({ github, owner, repo, workflowRun }) {
  const { data: liveRun } = await github.rest.actions.getWorkflowRun({
    owner,
    repo,
    run_id: workflowRun.id,
  });
  requireValid(
    hasLiveRunIdentity(liveRun, {
      id: workflowRun.id,
      run_attempt: liveRun?.run_attempt,
      head: workflowRun.head_sha,
    }),
    'The live workflow run does not match the signed event identity.',
  );
  requireValid(
    isPositiveInteger(liveRun.run_attempt),
    'The live workflow run does not have a valid attempt.',
  );
  return liveRun;
}

async function pullRequestCandidates({
  github,
  owner,
  repo,
  workflowRun,
  defaultBranch,
  associated,
}) {
  if (associated.length === 1) {
    const pullNumber = associated[0].number;
    if (!Number.isSafeInteger(pullNumber) || pullNumber <= 0) {
      throw new TypeError('The workflow run did not supply a valid pull-request number.');
    }
    const { data: pr } = await github.rest.pulls.get({
      owner,
      repo,
      pull_number: pullNumber,
    });
    return [pr];
  }
  const { data: pulls } = await github.rest.pulls.list({
    owner,
    repo,
    state: 'open',
    base: defaultBranch,
    head: `${workflowRun.head_repository.owner.login}:${workflowRun.head_branch}`,
    per_page: 100,
  });
  return pulls.filter((pr) => pr.head.sha === workflowRun.head_sha);
}

function validateResolvedPullRequest({ pr, owner, repo, workflowRun, defaultBranch }) {
  const expectedBase = `${owner}/${repo}`.toLowerCase();
  const expectedHead = workflowRun.head_repository.full_name.toLowerCase();
  requireValid(
    [
      pr?.state === 'open',
      pr?.base?.repo?.full_name?.toLowerCase() === expectedBase,
      pr?.base?.ref === defaultBranch,
      pr?.head?.repo?.full_name?.toLowerCase() === expectedHead,
      pr?.head?.ref === workflowRun.head_branch,
      SHA_PATTERN.test(pr?.head?.sha),
      SHA_PATTERN.test(pr?.base?.sha),
    ].every(Boolean),
    'The resolved pull request is outside the trusted workflow identity.',
  );
}

function workflowRunState({ workflowRun, liveRun, current }) {
  if (![current, liveRun.run_attempt === workflowRun.run_attempt].every(Boolean)) {
    return 'stale';
  }
  if (PENDING_RUN_STATUSES.has(liveRun.status)) {
    return 'pending';
  }
  requireValid(
    liveRun.status === 'completed',
    `Unexpected workflow run status: ${liveRun.status}`,
  );
  return liveRun.conclusion === 'success' ? 'publish' : 'failed';
}

async function resolveCodacyPullRequest({
  github,
  owner,
  repo,
  workflowRun,
  defaultBranch,
}) {
  requireValid(
    [owner, repo, defaultBranch].every(Boolean),
    'The trusted repository identity is required.',
  );
  const associated = validateWorkflowRun(workflowRun);
  const liveRun = await loadLiveWorkflowRun({ github, owner, repo, workflowRun });
  const candidates = await pullRequestCandidates({
    github,
    owner,
    repo,
    workflowRun,
    defaultBranch,
    associated,
  });
  requireValid(
    candidates.length === 1,
    `Expected exactly one live pull request; got ${candidates.length}.`,
  );
  const [pr] = candidates;
  validateResolvedPullRequest({ pr, owner, repo, workflowRun, defaultBranch });
  return {
    number: pr.number,
    head: workflowRun.head_sha,
    base: pr.base.sha,
    run_id: workflowRun.id,
    run_attempt: workflowRun.run_attempt,
    state: workflowRunState({
      workflowRun,
      liveRun,
      current: pr.head.sha === workflowRun.head_sha,
    }),
  };
}

async function upsertCodacyReportComment({ github, owner, repo, issue_number, report }) {
  const body = `${MARKER}\n${report}`;
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number,
    per_page: 100,
  });
  const previous = comments.find(
    (comment) =>
      [
        comment.user?.type === 'Bot',
        comment.user?.login === 'github-actions[bot]',
        comment.body?.includes(MARKER),
      ].every(Boolean),
  );
  if (previous) {
    await github.rest.issues.updateComment({
      owner,
      repo,
      comment_id: previous.id,
      body,
    });
    return 'updated';
  }
  await github.rest.issues.createComment({ owner, repo, issue_number, body });
  return 'created';
}

module.exports = {
  MARKER,
  buildCodacyStatusReport,
  isCurrentCodacyPublication,
  isCurrentCodacyPullRequest,
  resolveCodacyPullRequest,
  upsertCodacyReportComment,
};
