# GENOMA recovery and activation runbook

This runbook restores the deterministic system after loss of a VM, runner, optional adapter or local installation.

## Immutable anchors

- canonical ruleset: `REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt`
- status/version/date: `VIGENTE / v3.3 / 14/08/2026`
- canonical SHA-256: `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`
- repository: `drhudsonandrade/Codework`

## Recovery order

1. Check out an explicitly selected Git SHA; never silently use an unreviewed moving branch.
2. Run `python3 scripts/validate_repo.py`.
3. Verify sealed ruleset transport and external manifest.
4. Verify supply-chain/action/runtime locks.
5. Rebuild or pull the digest-pinned runtime image.
6. Recreate the reference bundle from approved manifests or restore an exact checksum-verified bundle.
7. Run executable/version checks, reference checks and synthetic canary.
8. Re-run the current-session Runtime/Resource Gate before any real calling.
9. Verify consent scope, input provenance and input hashes for the case.
10. Only then permit the Scientific Data Plane to read real genomic data.

## Optional interfaces

MCP, private ingress, durable orchestration, SQL projections, hosting and serverless helpers may be recreated later. None is required to restore the policy or scientific core and none can grant scientific status.

## Failure policy

- Missing/corrupt resource: `NÃO DISPONÍVEL`.
- Planned but not executed work: `PROPOSTO`.
- Inference without direct confirmation: `INFERIDO`.
- Never mark a step completed merely to close an audit.
- Never inherit a Runtime/Resource Gate from a prior session.

## Post-deployment

After any relevant code/deployment change, run the live Production Witness on the exact merged SHA. Only 15/15 with zero critical failures can grant `POST-DEPLOYMENT PASS` for that exact revision.
