'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  MARKER,
  upsertCodacyReportComment,
} = require('../scripts/codacy_pr_comment.js');

function makeGithub(previous) {
  const calls = [];
  const github = {
    paginate: async () => previous,
    rest: {
      issues: {
        listComments: async () => {},
        updateComment: async (args) => calls.push(['update', args]),
        createComment: async (args) => calls.push(['create', args]),
      },
    },
  };
  return { github, calls };
}

test('creates one report comment when none exists', async () => {
  const { github, calls } = makeGithub([]);
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
