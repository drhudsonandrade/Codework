# GENOMA v3.4 production ceremony

This ceremony converts an inactive, content-addressed normative transport into a real runtime instance without committing a second active plaintext `VIGENTE` source.

## 1. Normative activation

The authoritative repository evidence for the active identity is `manifests/RULESET_V3.4.sha256` plus `normative/sealed/MANIFEST.json`. Both must agree on `VIGENTE / v3.4 / 17/08/2026`, canonical filename `REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt`, raw SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`, and the sealed 13-part transport before activation.

`scripts/materialize_ruleset.py` decodes the sealed transport entirely under a controlled runtime path, verifies the transport SHA-256, gzip SHA-256, raw canonical SHA-256 `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`, exact normative identity and sequential sections 0–262. It atomically writes exactly `REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt` as mode `0444`.

The repository continues to contain zero active plaintext rulesets. `scripts/validate_repo.py` decodes the transport **in memory** during CI and verifies that it is byte-exact before any activation.

## 2. Real instance

`.github/workflows/genoma-production-ceremony.yml` builds the policy OCI image from the exact Git commit and starts a real hardened Linux container with:

- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges`;
- canonical TXT mounted `:ro`;
- external SHA manifest mounted `:ro`;
- HTTP bound only to `127.0.0.1`.

The workflow captures `docker inspect`, image ID, mount mode, health response and live ruleset identity.

## 3. Section-260 live smoke

`scripts/run_live_post_deployment_smoke.py` sends all 15 canonical scenarios through the **running HTTP service**, not through an in-process unit fixture. Each case records the canonical natural-language prompt, expected behavior, expected blocking gate, observed gate and SHA-256 of the full HTTP response.

The suite can report PASS only with `total=15`, `passed=15`, `critical_failures=0`, a verified ruleset-bootstrap attestation tied to the exact deployment Git SHA, authenticated evidence that the persistent Project Instructions are installed, `POST_DEPLOYMENT_GATE=PASS`, and `post_deployment_status=PASS`. The repository-local owner-export snapshot is deliberately insufficient for the installation condition.

At present the implementation has no authenticated machine-readable read of the authoritative persistent Project Instructions surface. Therefore `PROJECT_BOOTSTRAP_INSTALLED` remains false and the production ceremony remains fail-closed for POST-DEPLOYMENT until such evidence is available and bound to the deployment.

The independent `genoma-policy smoke` suite remains separate and can never grant post-deployment status.

## 4. Two independent bootstrap controls

### 4.1 RULESET_BOOTSTRAP_CLAUSE_PRESENT

`deploy/attestations/bootstrap-project-v3.4.json` is the versioned repository example of the normative bootstrap attestation. It is generated only through `scripts/bootstrap_attestation.py`; it must never be edited by hand. Regenerate a versioned copy with `python3 -m scripts.bootstrap_attestation --write --verified-at <ISO8601>`.

Every ruleset-bootstrap check is re-derived from the sealed canonical ruleset. This proves that the canonical ruleset contains the required bootstrap clauses. It **does not prove that Project Instructions were actually installed**.

For production witnessing, the workflow generates a fresh bootstrap attestation at runtime from the exact checked-out `main` commit. `scripts/run_live_post_deployment_smoke.py` verifies `source_commit_sha` against `GITHUB_SHA`; the committed historical attestation is never reused as proof for a later main SHA.

### 4.2 PROJECT_BOOTSTRAP_INSTALLED

`scripts/project_instructions_attestation.py` is a separate verifier for an owner-exported UTF-8 snapshot of the Project Instructions. It verifies the exact high-signal clauses of the canonical v3.4 BOOTSTRAP CURTO, records the source SHA-256/size, clause digests/lines, a locator describing the claimed settings surface, and a strict RFC 3339 verification timestamp.

The production paths are:

- `deploy/attestations/project-instructions-v3.4.txt` — owner-exported Project Instructions snapshot;
- `deploy/attestations/project-instructions-v3.4.json` — attestation generated from that exact snapshot.

Generate the snapshot attestation only after exporting the settings:

```bash
python3 -m scripts.project_instructions_attestation \
  --source deploy/attestations/project-instructions-v3.4.txt \
  --source-locator 'chatgpt-project://GENOMA/instructions' \
  --verified-at '<RFC3339>' \
  --output deploy/attestations/project-instructions-v3.4.json \
  --write
```

The live smoke re-reads the source snapshot and recomputes the attestation, but this evidence remains snapshot-only and **MUST NOT** set `post_deployment.bootstrap_installed=true`. The boolean remains false until an authenticated read from the authoritative persistent Project Instructions surface is available and bound to the deployment. The sealed ruleset likewise can never satisfy this installation boolean by itself.

If the platform does not expose a machine-readable Project Instructions API, the owner-exported snapshot is the explicit evidence boundary for snapshot verification only. Installation status remains `NÃO DISPONÍVEL`, and POST-DEPLOYMENT remains fail-closed; the snapshot must not be described as direct platform verification.

## 5. Evidence package

The ceremony uploads a 365-day artifact named `genoma-post-deployment-evidence-<commit>` containing the materialization record, runtime-generated ruleset bootstrap attestation, container metadata, live ruleset response, the Project Instructions snapshot verification recorded in the live summary, all 15 case results, container log, and a sorted SHA-256 manifest.

A post-deployment execution record is therefore tied to a precise Git commit, container image, canonical ruleset hash, Project Instructions snapshot digest and execution run. This does not elevate the snapshot to installation proof. A later model/UI/provider cannot retroactively alter the captured execution evidence.

## 6. Branch governance

The live repository settings are a separate control. Apply and then read back the policy in `docs/BRANCH_GOVERNANCE.md`. Until `main` and `audit-evidence` match that policy, report repository governance as **PENDING** rather than implying enforcement from documentation alone.

## 7. Regression rule

Any relevant change to policy logic, ruleset, deployment architecture, Project Instructions, or safety gates triggers the production ceremony again on `main`. A failed ceremony remains a failed audit; it must never be bypassed to obtain green status.
