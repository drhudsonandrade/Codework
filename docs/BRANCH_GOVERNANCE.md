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

The required checks must be selected from checks that have actually reported on the repository recently. Do not invent check names. For the current architecture, the selected set must cover the repository/scaffold contract, policy contract, MCP contract, supply-chain/security checks and CodeRabbit review policy used by the active PR process. Any check configured as required must have an unconditional pull-request provider; a path-filtered workflow must not be made globally required because unrelated PRs would wait forever for a check that never starts.

The versioned definition is `.github/governance/main-ruleset.json`. It is a desired-state artifact, not evidence that GitHub has applied the ruleset.

## `audit-evidence`

Target branch: `audit-evidence`.

This branch is an append-only publication surface for production witnesses, not a normal development branch. The production witness workflow already refuses to overwrite a witness for an existing exact Git SHA unless the content is byte-identical.

Required policy:

- block force pushes for every actor, including the publisher;
- block branch deletion for every actor, including the publisher;
- restrict ordinary updates to the trusted deploy-key publisher;
- preserve direct append publication by the reviewed `GENOMA Production Witness` publisher;
- do not grant the publisher a bypass over history-mutation protections;
- do not require a normal pull-request merge path that would prevent the reviewed witness publisher from appending evidence;
- periodically verify that every `latest.json` target also exists under `witnesses/<git_sha>/witness.json` with matching `SHA256SUMS`.

The desired state is deliberately split into two layered GitHub rulesets:

- `.github/governance/audit-evidence-integrity-ruleset.json` — `deletion` + `non_fast_forward`, with **no bypass actors**;
- `.github/governance/audit-evidence-publisher-ruleset.json` — `update` only, with the GitHub `DeployKey` actor class as the bypass actor.

For GitHub rulesets, a `DeployKey` bypass is represented with `actor_id: null`; this field therefore does not identify one numeric deploy-key ID. The desired-state JSON limits that bypass to the update-only layer, so it does not share a ruleset with deletion or non-fast-forward protections. Before governance can be marked verified, the live repository settings must also be read back to confirm that only the intended publisher deploy key is write-enabled for this publication path. If additional write-enabled deploy keys exist or the live rulesets differ from this design, keep governance status `PENDING`.

These JSON files are desired-state artifacts, not evidence that GitHub has applied the rulesets or installed the corresponding deploy key.

If the repository plan/settings cannot express the documented layered restriction, record the limitation explicitly and keep governance status `PENDING`; do not represent the desired-state JSON as enforced.

## Verification record

After applying the GitHub settings, record all of the following in the closure report:

- repository: `drhudsonandrade/Codework`;
- branch names: `main`, `audit-evidence`;
- observed protected/ruleset state for each branch;
- required status checks actually configured on `main`;
- force-push and deletion policy for both branches;
- update-restriction bypass actor class on `audit-evidence`;
- write-enabled deploy keys observed for the repository and which one is the intended publisher;
- verification timestamp and GitHub settings/ruleset locator.

The repository must remain **GOVERNANCE PENDING** until the live GitHub settings are read back and match this contract.

## GitHub documentation

- Rulesets: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- Available rules, including required status checks and force-push controls: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
