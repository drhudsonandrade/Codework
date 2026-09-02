'use strict';

const MARKER = '<!-- codacy-api-report -->';
const SHA_PATTERN = /^[0-9a-f]{40}$/i;
const STATUS_MESSAGES = Object.freeze({
  pending: 'the required pull-request tests are still running for this commit.',
  failed: 'the required pull-request tests did not complete successfully for this commit.',
  'missing-token': 'the trusted publisher has no environment-scoped Codacy API credential.',
  'publisher-failed': 'the trusted publisher failed before it could produce a current report.',
});

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
  if (
    !Number.isSafeInteger(issue_number) ||
    issue_number <= 0 ||
    !SHA_PATTERN.test(head) ||
    !SHA_PATTERN.test(base) ||
    typeof defaultBranch !== 'string' ||
    defaultBranch.length === 0
  ) {
    throw new TypeError('A validated pull-request identity is required.');
  }
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
  if (
    !Number.isSafeInteger(run_id) ||
    run_id <= 0 ||
    !Number.isSafeInteger(run_attempt) ||
    run_attempt <= 0 ||
    !SHA_PATTERN.test(head) ||
    !SHA_PATTERN.test(base)
  ) {
    throw new TypeError('A validated publication identity is required.');
  }
  const { data: liveRun } = await github.rest.actions.getWorkflowRun({
    owner,
    repo,
    run_id,
  });
  if (
    liveRun?.id !== run_id ||
    liveRun.run_attempt !== run_attempt ||
    liveRun.path !== '.github/workflows/codacy-api-report-tests.yml' ||
    liveRun.head_sha !== head ||
    liveRun.event !== 'pull_request'
  ) {
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
  if (
    !Number.isSafeInteger(workflowRun?.id) ||
    workflowRun.id <= 0 ||
    !Number.isSafeInteger(workflowRun.run_attempt) ||
    workflowRun.run_attempt <= 0
  ) {
    throw new TypeError('The workflow run did not supply a valid run identity.');
  }
  if (workflowRun?.path !== '.github/workflows/codacy-api-report-tests.yml') {
    throw new TypeError('The workflow run did not originate from the trusted test workflow.');
  }
  if (workflowRun.event !== 'pull_request') {
    throw new TypeError('The workflow run did not originate from a pull request.');
  }
  if (!SHA_PATTERN.test(workflowRun.head_sha)) {
    throw new TypeError('The workflow run did not supply a valid source SHA.');
  }
  const headRepository = workflowRun.head_repository?.full_name;
  const headOwner = workflowRun.head_repository?.owner?.login;
  if (!headRepository || !headOwner || !workflowRun.head_branch) {
    throw new TypeError('The workflow run did not supply a complete head identity.');
  }
  const associated = Array.isArray(workflowRun.pull_requests)
    ? workflowRun.pull_requests
    : [];
  if (associated.length > 1) {
    throw new TypeError('Expected at most one associated pull request.');
  }
  return associated;
}

async function loadLiveWorkflowRun({ github, owner, repo, workflowRun }) {
  const { data: liveRun } = await github.rest.actions.getWorkflowRun({
    owner,
    repo,
    run_id: workflowRun.id,
  });
  if (
    liveRun?.id !== workflowRun.id ||
    !Number.isSafeInteger(liveRun.run_attempt) ||
    liveRun.run_attempt <= 0 ||
    liveRun.path !== workflowRun.path ||
    liveRun.head_sha !== workflowRun.head_sha ||
    liveRun.event !== 'pull_request'
  ) {
    throw new TypeError('The live workflow run does not match the signed event identity.');
  }
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
  if (
    pr?.state !== 'open' ||
    pr.base?.repo?.full_name?.toLowerCase() !== expectedBase ||
    pr.base?.ref !== defaultBranch ||
    pr.head?.repo?.full_name?.toLowerCase() !== expectedHead ||
    pr.head?.ref !== workflowRun.head_branch ||
    !SHA_PATTERN.test(pr.head?.sha) ||
    !SHA_PATTERN.test(pr.base?.sha)
  ) {
    throw new TypeError('The resolved pull request is outside the trusted workflow identity.');
  }
}

function workflowRunState({ workflowRun, liveRun, current }) {
  if (!current || liveRun.run_attempt !== workflowRun.run_attempt) {
    return 'stale';
  }
  if (['requested', 'queued', 'pending', 'waiting', 'in_progress'].includes(liveRun.status)) {
    return 'pending';
  }
  if (liveRun.status !== 'completed') {
    throw new TypeError(`Unexpected workflow run status: ${liveRun.status}`);
  }
  return liveRun.conclusion === 'success' ? 'publish' : 'failed';
}

async function resolveCodacyPullRequest({
  github,
  owner,
  repo,
  workflowRun,
  defaultBranch,
}) {
  if (!owner || !repo || !defaultBranch) {
    throw new TypeError('The trusted repository identity is required.');
  }
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
  if (candidates.length !== 1) {
    throw new TypeError(`Expected exactly one live pull request; got ${candidates.length}.`);
  }
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
