# GENOMA branch governance

This document defines the repository-side governance required before the control plane is considered closed. It does not claim that GitHub settings are active; the live settings must be verified through the GitHub repository administration surface after they are applied.

## `main`

Target branch: `main`.

Required policy:

- require a pull request before changes reach `main`;
- require at least one approving review;
- dismiss stale approvals after new code-modifying commits;
- require approval of the most recent reviewable push when GitHub makes that control available;
- require status checks to pass before merge;
- require the branch to be up to date before merge;
- block force pushes;
- block branch deletion;
- do not use an unrestricted administrator bypass to turn a failing gate into a merge;
- keep auto-merge disabled unless every required gate and the human merge decision are still enforced.

The required checks must be selected from checks that have actually reported on the repository recently. Do not invent check names. For the current architecture, the selected set must cover the repository/scaffold contract, policy contract, MCP contract, supply-chain/security checks and CodeRabbit review policy used by the active PR process.

The versioned definition is `.github/governance/main-ruleset.json`. It is a desired-state artifact, not evidence that GitHub has applied the ruleset.

## `audit-evidence`

Target branch: `audit-evidence`.

This branch is an append-only publication surface for production witnesses, not a normal development branch. The production witness workflow already refuses to overwrite a witness for an existing exact Git SHA unless the content is byte-identical.

Required policy:

- block force pushes;
- block branch deletion;
- restrict updates to the trusted deploy-key publisher through the versioned `update` rule;
- preserve direct publication by the reviewed `GENOMA Production Witness` publisher;
- do not require a normal pull-request merge path that would prevent the reviewed witness publisher from appending evidence;
- periodically verify that every `latest.json` target also exists under `witnesses/<git_sha>/witness.json` with matching `SHA256SUMS`.

The versioned definition is `.github/governance/audit-evidence-ruleset.json`. It is a desired-state artifact, not evidence that GitHub has applied the ruleset or installed the corresponding deploy key.

If the repository plan/settings cannot express the documented restriction, record the limitation explicitly and keep governance status `PENDING`; do not represent the desired-state JSON as enforced.

## Verification record

After applying the GitHub settings, record all of the following in the closure report:

- repository: `drhudsonandrade/Codework`;
- branch names: `main`, `audit-evidence`;
- observed protected/ruleset state for each branch;
- required status checks actually configured on `main`;
- force-push and deletion policy for both branches;
- bypass actors, if any;
- verification timestamp and GitHub settings/ruleset locator.

The repository must remain **GOVERNANCE PENDING** until the live GitHub settings are read back and match this contract.

## GitHub documentation

- Rulesets: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- Available rules, including required status checks and force-push controls: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
