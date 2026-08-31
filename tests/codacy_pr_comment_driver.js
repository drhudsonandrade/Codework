// Fixed driver for the `upsertCodacyReportComment` regression tests.
//
// The tests used to build a JavaScript program as a Python f-string and hand it to `node -e`.
// Raised in review, and fair: the argv was trusted because the fixtures happened to be local
// literals, which is a fact about today's callers rather than a property of the code. A
// program assembled at run time also cannot be linted, reviewed as a unit, or reasoned about
// without reconstructing the string.
//
// This file is that program, written once and committed. The test passes only *data*: the
// path of the module under test and the JSON fixture, both as argv elements that `node` never
// interprets as code. Bandit's B603 is then answered by a checked property rather than by an
// argument about intent — argv is a fixed interpreter, a fixed script in this repository, a
// repository path, and one JSON string.
//
// Usage: node codacy_pr_comment_driver.js <module-path> <existing-comments-json>
// Writes {result, calls} to stdout as JSON, or exits non-zero with the error on stderr.

const modulePath = process.argv[2];
const previous = JSON.parse(process.argv[3]);

const { upsertCodacyReportComment } = require(modulePath);

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

(async () => {
  const result = await upsertCodacyReportComment({
    github,
    owner: 'o',
    repo: 'r',
    issue_number: 32,
    report: '# report',
  });
  process.stdout.write(JSON.stringify({ result, calls }));
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
