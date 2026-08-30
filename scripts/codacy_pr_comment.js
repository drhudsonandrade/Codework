'use strict';

const MARKER = '<!-- codacy-api-report -->';

async function upsertCodacyReportComment({ github, owner, repo, issue_number, report }) {
  const body = `${MARKER}\n${report}`;
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number,
    per_page: 100,
  });
  const previous = comments.find(
    (comment) => comment.user?.type === 'Bot' && comment.body?.includes(MARKER),
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

module.exports = { MARKER, upsertCodacyReportComment };
