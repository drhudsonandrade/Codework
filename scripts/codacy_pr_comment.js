'use strict';

const MARKER = '<!-- codacy-api-report -->';
const SHA_PATTERN = /^[0-9a-f]{40}$/i;
const PRODUCER_WORKFLOW = 'codacy-api-report-tests.yml';
const PRODUCER_PATH = `.github/workflows/${PRODUCER_WORKFLOW}`;
const PRODUCER_PAGE_SIZE = 100;
const MAX_PRODUCER_RUNS = 1000;
const STATUS_MESSAGES = Object.freeze({
  pending: 'the required pull-request tests are still running for this commit.',
  processing: 'the required pull-request tests passed and the trusted publisher is processing this commit.',
  cancelled: 'the required pull-request tests were cancelled before completion for this commit.',
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
const COMPLETED_RUN_STATES = Object.freeze({
  success: 'publish',
  cancelled: 'interrupted',
});
const RUN_REPORT_STATES = Object.freeze({
  pending: 'pending',
  publish: 'processing',
  interrupted: 'cancelled',
  failed: 'failed',
});

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

function objectOrEmpty(value) {
  return typeof value === 'object' && value !== null ? value : {};
}

function isOwnedReportComment(comment) {
  return [
    comment.user?.type === 'Bot',
    comment.user?.login === 'github-actions[bot]',
    comment.body?.includes(MARKER),
  ].every(Boolean);
}

function hasRunCoordinates(liveRun, { id, run_number, run_attempt }) {
  return [
    liveRun?.id === id,
    liveRun?.run_number === run_number,
    liveRun?.run_attempt === run_attempt,
  ].every(Boolean);
}

function hasTrustedRunSource(liveRun, head) {
  const run = objectOrEmpty(liveRun);
  return [
    run.path === PRODUCER_PATH || String(run.path).startsWith(`${PRODUCER_PATH}@`),
    run.head_sha === head,
    run.event === 'pull_request',
  ].every(Boolean);
}

function hasProducerHeadIdentity(run, headRepository, headBranch) {
  const producer = objectOrEmpty(run);
  const repository = objectOrEmpty(producer.head_repository);
  return [
    String(repository.full_name).toLowerCase() === String(headRepository).toLowerCase(),
    producer.head_branch === headBranch,
  ].every(Boolean);
}

function hasLiveRunIdentity(liveRun, identity) {
  return [
    hasRunCoordinates(liveRun, identity),
    hasTrustedRunSource(liveRun, identity.head),
  ].every(Boolean);
}

function hasCurrentPullRequestIdentity(
  pr,
  { owner, repo, head, base, defaultBranch },
) {
  const current = objectOrEmpty(pr);
  const pullHead = objectOrEmpty(current.head);
  const pullBase = objectOrEmpty(current.base);
  const baseRepository = objectOrEmpty(pullBase.repo);
  return [
    current.state === 'open',
    pullHead.sha === head,
    pullBase.sha === base,
    pullBase.ref === defaultBranch,
    String(baseRepository.full_name).toLowerCase() === `${owner}/${repo}`.toLowerCase(),
  ].every(Boolean);
}

function hasMatchingProducerIdentity(run, pr, head) {
  const producer = objectOrEmpty(run);
  const associated = arrayOrEmpty(producer.pull_requests);
  return [
    producer.event === 'pull_request',
    producer.head_sha === head,
    hasProducerHeadIdentity(producer, pr.head.repo.full_name, pr.head.ref),
    associated.length === 0 || associated.some((item) => item?.number === pr.number),
  ].every(Boolean);
}

function compareRunOrder(left, right) {
  return left.run_number - right.run_number || left.run_attempt - right.run_attempt;
}

function validatedRunPage(data, expectedTotal) {
  const payload = objectOrEmpty(data);
  requireValid(
    Array.isArray(payload.workflow_runs),
    'The workflow-run listing did not return a run array.',
  );
  requireValid(
    [
      Number.isSafeInteger(payload.total_count),
      payload.total_count >= 0,
      payload.total_count <= MAX_PRODUCER_RUNS,
    ].every(Boolean),
    'The workflow-run listing has an unsupported result count.',
  );
  requireValid(
    [expectedTotal === null, expectedTotal === payload.total_count].some(Boolean),
    'The workflow-run listing changed while it was being read.',
  );
  return { runs: payload.workflow_runs, total: payload.total_count };
}

async function loadProducerRuns({ github, owner, repo, pr, head }) {
  const collected = [];
  let expectedTotal = null;
  for (let page = 1; page <= MAX_PRODUCER_RUNS / PRODUCER_PAGE_SIZE; page += 1) {
    const { data } = await github.rest.actions.listWorkflowRuns({
      owner,
      repo,
      workflow_id: PRODUCER_WORKFLOW,
      event: 'pull_request',
      branch: pr.head.ref,
      head_sha: head,
      per_page: PRODUCER_PAGE_SIZE,
      page,
    });
    const current = validatedRunPage(data, expectedTotal);
    expectedTotal = current.total;
    collected.push(...current.runs);
    requireValid(
      collected.length <= expectedTotal,
      'The workflow-run listing returned more results than declared.',
    );
    if (collected.length === expectedTotal) {
      const uniqueIds = new Set(collected.map((run) => run?.id));
      requireValid(
        uniqueIds.size === collected.length,
        'The workflow-run listing changed while it was being read.',
      );
      return collected;
    }
    requireValid(
      current.runs.length === PRODUCER_PAGE_SIZE,
      'The workflow-run listing ended before every result was read.',
    );
  }
  throw new TypeError('The workflow-run listing exceeded its documented search limit.');
}

async function isNewestProducerRun({ github, owner, repo, liveRun, pr, head }) {
  const producerRuns = await loadProducerRuns({ github, owner, repo, pr, head });
  const matching = producerRuns.filter((run) => (
    hasMatchingProducerIdentity(run, pr, head)
  ));
  if (
    matching.length === 0
    || matching.some((run) => ![
      isPositiveInteger(run.id),
      isPositiveInteger(run.run_number),
      isPositiveInteger(run.run_attempt),
    ].every(Boolean))
  ) {
    return false;
  }
  const newest = matching.reduce((current, run) => (
    compareRunOrder(run, current) > 0 ? run : current
  ));
  const sameOrder = matching.filter((run) => compareRunOrder(run, newest) === 0);
  return sameOrder.length === 1 && hasRunCoordinates(newest, liveRun);
}

function hasWorkflowHeadIdentity(workflowRun) {
  return [
    workflowRun.head_repository?.full_name,
    workflowRun.head_repository?.owner?.login,
    workflowRun.head_branch,
  ].every(Boolean);
}

function hasTrustedBaseIdentity(pr, owner, repo, defaultBranch) {
  return [
    pr?.base?.repo?.full_name?.toLowerCase() === `${owner}/${repo}`.toLowerCase(),
    pr?.base?.ref === defaultBranch,
  ].every(Boolean);
}

function hasTrustedHeadIdentity(pr, workflowRun) {
  return [
    pr?.head?.repo?.full_name?.toLowerCase()
      === workflowRun.head_repository.full_name.toLowerCase(),
    pr?.head?.ref === workflowRun.head_branch,
  ].every(Boolean);
}

function hasValidCommitPair(pr) {
  return [SHA_PATTERN.test(pr?.head?.sha), SHA_PATTERN.test(pr?.base?.sha)].every(Boolean);
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

function codacyStatusForRunState(state) {
  requireValid(
    Object.hasOwn(RUN_REPORT_STATES, state),
    'A known workflow-run state is required.',
  );
  return RUN_REPORT_STATES[state];
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
  return hasCurrentPullRequestIdentity(
    pr,
    { owner, repo, head, base, defaultBranch },
  );
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
  run_number,
  run_attempt,
}) {
  requireValid(
    [
      isPositiveInteger(run_id),
      isPositiveInteger(run_number),
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
  if (!hasLiveRunIdentity(liveRun, {
    id: run_id,
    run_number,
    run_attempt,
    head,
  })) {
    return false;
  }
  const { data: pr } = await github.rest.pulls.get({
    owner,
    repo,
    pull_number: issue_number,
  });
  if (
    !hasCurrentPullRequestIdentity(
      pr,
      { owner, repo, head, base, defaultBranch },
    )
    || !hasProducerHeadIdentity(liveRun, pr.head.repo.full_name, pr.head.ref)
  ) {
    return false;
  }
  return isNewestProducerRun({ github, owner, repo, liveRun, pr, head });
}

function validateWorkflowRun(workflowRun) {
  requireValid(
    isPositiveInteger(workflowRun?.id),
    'The workflow run did not supply a valid run identity.',
  );
  requireValid(
    isPositiveInteger(workflowRun?.run_attempt),
    'The workflow run did not supply a valid run identity.',
  );
  requireValid(
    isPositiveInteger(workflowRun?.run_number),
    'The workflow run did not supply a valid run identity.',
  );
  requireValid(
    workflowRun.path === PRODUCER_PATH,
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
  requireValid(
    hasWorkflowHeadIdentity(workflowRun),
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
      run_number: workflowRun.run_number,
      run_attempt: liveRun?.run_attempt,
      head: workflowRun.head_sha,
    }),
    'The live workflow run does not match the signed event identity.',
  );
  requireValid(
    isPositiveInteger(liveRun.run_attempt),
    'The live workflow run does not have a valid attempt.',
  );
  requireValid(
    hasProducerHeadIdentity(
      liveRun,
      workflowRun.head_repository.full_name,
      workflowRun.head_branch,
    ),
    'The live workflow run does not match the signed head identity.',
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
  const message = 'The resolved pull request is outside the trusted workflow identity.';
  requireValid(
    pr?.state === 'open',
    message,
  );
  requireValid(hasTrustedBaseIdentity(pr, owner, repo, defaultBranch), message);
  requireValid(hasTrustedHeadIdentity(pr, workflowRun), message);
  requireValid(hasValidCommitPair(pr), message);
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
  return COMPLETED_RUN_STATES[liveRun.conclusion] ?? 'failed';
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
  let current = [
    pr.head.sha === workflowRun.head_sha,
    liveRun.run_attempt === workflowRun.run_attempt,
  ].every(Boolean);
  if (current) {
    current = await isNewestProducerRun({
      github,
      owner,
      repo,
      liveRun,
      pr,
      head: pr.head.sha,
    });
  }
  return {
    number: pr.number,
    head: workflowRun.head_sha,
    base: pr.base.sha,
    run_id: workflowRun.id,
    run_number: workflowRun.run_number,
    run_attempt: workflowRun.run_attempt,
    state: workflowRunState({
      workflowRun,
      liveRun,
      current,
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
  const owned = comments.filter(isOwnedReportComment);
  if (owned.length > 0) {
    const [canonical, ...duplicates] = owned;
    await github.rest.issues.updateComment({
      owner,
      repo,
      comment_id: canonical.id,
      body,
    });
    for (const duplicate of duplicates) {
      await github.rest.issues.deleteComment({
        owner,
        repo,
        comment_id: duplicate.id,
      });
    }
    return 'updated';
  }
  await github.rest.issues.createComment({ owner, repo, issue_number, body });
  return 'created';
}

module.exports = {
  MARKER,
  buildCodacyStatusReport,
  codacyStatusForRunState,
  isCurrentCodacyPublication,
  isCurrentCodacyPullRequest,
  resolveCodacyPullRequest,
  upsertCodacyReportComment,
};
