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

The versioned definition is `.github/governance/main-ruleset.json`. Required check names in that file are limited to checks observed in this repository; do not invent a context that has never reported.

## `audit-evidence`

Target branch: `audit-evidence`.

This branch is an append-only publication surface for production witnesses, not a normal development branch. The versioned definition is `.github/governance/audit-evidence-ruleset.json`.

Required policy:

- block branch deletion;
- block non-fast-forward updates/force pushes;
- apply the `update` rule so ordinary writers cannot update the branch;
- configure exactly one dedicated **write-enabled deploy key** for the production-witness publisher and grant the DeployKey bypass required by the ruleset;
- store the matching private key only as the Actions secret `GENOMA_AUDIT_DEPLOY_KEY`;
- do not grant `GITHUB_TOKEN` `contents: write` in the publisher job;
- refuse to modify any existing `witnesses/<sha>/...` path;
- require `latest.json` to be byte-identical to the newly published `witnesses/<git_sha>/witness.json`;
- keep the exact-SHA idempotency guard: a previously published SHA can only be re-observed if both witness and `SHA256SUMS` are byte-identical.

The reviewed workflow implements the repository-side path/digest guards. The deploy key, Actions secret and live GitHub ruleset are **administrative prerequisites** and are not considered installed until the GitHub settings are applied and read back.

If the repository plan/settings cannot support the DeployKey bypass/update-rule combination, `audit-evidence` remains **GOVERNANCE PENDING**. Do not weaken the rule to make publication succeed.

## Verification record

After applying the GitHub settings, record all of the following in the closure report:

- repository: `drhudsonandrade/Codework`;
- branch names: `main`, `audit-evidence`;
- observed protected/ruleset state for each branch;
- required status checks actually configured on `main`;
- `update`, non-fast-forward and deletion rules on `audit-evidence`;
- the presence of the dedicated deploy-key bypass without exposing private key material;
- verification timestamp and GitHub settings/ruleset locator.

The repository must remain **GOVERNANCE PENDING** until the live GitHub settings are read back and match this contract.

## GitHub documentation

- Rulesets: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- Creating rulesets and bypass actors: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- REST rules API (`update` rule and DeployKey bypass): https://docs.github.com/en/rest/repos/rules
- Protected branches: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches
