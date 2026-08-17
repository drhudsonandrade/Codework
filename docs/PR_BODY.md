# Pull request checklist

## Scope

Describe exactly which GENOMA plane, workflow, report renderer or deployment contract changes.

## Safety evidence

- [ ] Canonical ruleset identity unchanged or explicitly reviewed.
- [ ] Repository contract passes.
- [ ] Unit/regression tests cover the change.
- [ ] No personal genotype data added to Git.
- [ ] Supply-chain/action/container references remain pinned.
- [ ] Real-analysis paths remain fail closed.
- [ ] Consent/provenance/QC/evidence status cannot be silently promoted.
- [ ] No provider-specific dependency is required by the core.
- [ ] Final reports remain blocked unless all required policy/audit gates pass.

## Deployment consequence

Any merge that changes relevant policy, deployment or safety behavior invalidates the previous exact-SHA production witness for the new revision. Run the live 15/15 section-260 ceremony on the merged `main` SHA before declaring post-deployment PASS for that revision.
