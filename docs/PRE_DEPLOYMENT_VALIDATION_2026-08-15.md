# Pre-deployment validation record

The dated validation originally stored at this path is a historical record and has been archived as [`docs/history/v3.3/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md`](history/v3.3/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md) so superseded normative identities cannot remain on an active documentation surface. The filename is retained only as a compatibility pointer; it is not evidence that v3.4 existed or was validated on 15/08/2026.

## Current contract

- Active ruleset: `VIGENTE / v3.4 / 17/08/2026`.
- Canonical SHA-256: `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.
- Normative evidence: `manifests/RULESET_V3.4.sha256` and `normative/sealed/MANIFEST.json`.
- Canonical ruleset is materialized only at runtime from the sealed 13-part transport.
- Current deployment state: `PRE-DEPLOYMENT VALIDATION / POST-DEPLOYMENT PENDENTE` until the live production witness on the exact merged `main` SHA proves `passed == 15`, `total == 15`, `critical_failures == 0` and `post_deployment_status == "PASS"`.
- Historical evidence cannot be promoted to current approval.

See `docs/PRODUCTION_CEREMONY.md` and `docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md` for the current activation procedure.
