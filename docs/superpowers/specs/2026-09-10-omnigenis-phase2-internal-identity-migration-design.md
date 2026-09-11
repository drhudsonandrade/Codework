# OmniGenis Phase 2 Internal Identity Migration Design

**Status:** Approved design. Phase 2A implementation exists and is under governed PR review; Phases 2B-2D have not started.

**Repository:** `drhudsonandrade/OmniGenis`

**Stable repository ID:** `1212760346`

**Baseline `main` SHA:** `939dfea5cc7cb2745638168d518d2005e941e9c6`

**Phase 1 merge:** PR #67, repository-address migration from `Codework` to `OmniGenis`

## 1. Objective

Phase 2 completes the internal technical identity migration from Codework-derived names to OmniGenis-derived names without changing genomic behavior, scientific semantics, normative identity, governance strength, or repository continuity.

The final active system must use OmniGenis terminology for runtime paths, runner labels and names, container/package identities, MCP identity, Conda environment identity, Nextflow manifest identity, Codex marketplace identity, tunnel profile, cache scope, environment variables, tests, and current operational documentation.

`Codework` may remain only when it is part of immutable historical evidence, provenance, a historical URL, or another explicitly reviewed historical record.

## 2. Non-goals

Phase 2 does not:

- change the GitHub repository object, visibility, default branch, or history;
- change canonical GENOMA v3.4 identity, normative bytes, version, formal date, SHA-256, or sealed transport;
- change variant interpretation, scientific thresholds, taxonomies, report semantics, evidence semantics, or genomic data processing behavior;
- delete or rewrite historical artifacts only because they contain the old identity;
- weaken branch rulesets, required checks, external security review, or manual merge policy;
- introduce personal genomic data, patient data, credentials, tokens, registration tokens, or secrets into Git or logs;
- perform an unverified destructive migration of GHCR packages or self-hosted runner containers.

## 3. Verified baseline

The Phase 1 post-merge baseline was verified before this design was written. Reproduced baseline commands, exit codes, environment metadata, output summaries, and digests are recorded in `docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json`; the original rename continuity source is `docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json`.

- repository full name: `drhudsonandrade/OmniGenis`;
- repository ID: `1212760346`;
- visibility: `public`;
- default branch: `main`;
- baseline `main`: `939dfea5cc7cb2745638168d518d2005e941e9c6`;
- the legacy `Codework` Git URL and the canonical `OmniGenis` Git URL resolve to the same current `main` history;
- ruleset `21303100` (`GENOMA protected main`) is active;
- ruleset `22347095` (`GENOMA approval gate`) is active;
- `scripts/validate_repo.py` passes at the baseline;
- the complete root suite passes 1,047 tests with zero failures, zero errors, and one expected skip in the pinned project environment.

The repository inventory found 182 active Codework-derived match lines across 32 files outside excluded historical/spec/evidence surfaces at the time of design exploration.

## 4. Verified live operational state

At design time the authorized Ubuntu host had no active `/opt/codework`, `/opt/omnigenis`, `/etc/codework`, or `/etc/omnigenis` deployment paths. No installed `genome-mcp`, tunnel client, or OmniGenis systemd unit was present. No active runtime container with an observable Codework deployment identity was established through the available user permissions.

Two repository self-hosted runners were verified online through the GitHub runner API:

- `drhudson-codework-01`, labels `self-hosted`, `Linux`, `X64`, `codework-isolated`, `codework-01`;
- `drhudson-codework-02`, labels `self-hosted`, `Linux`, `X64`, `codework-isolated`, `codework-02`.

The runner processes are hosted in rootless Docker containers under a different local user boundary. The current Remote Desktop Commander identity cannot inspect those containers through either the rootful or rootless Docker socket. Their exact image, mounts, registration command, token flow, and restart mechanism are therefore **NOT AVAILABLE** in this session and must be re-established through a Runtime/Resource Gate before runner re-registration.

The current shell environment exposes no observed `CODEWORK_*` environment variable. The `codex` CLI is not available on this host, so any externally registered `codework-codex` marketplace state is **NOT AVAILABLE** and must not be assumed.

The current GitHub CLI token can address runner metadata but lacks `read:packages`; querying `codework-genome` returned HTTP 403 and querying `omnigenis-genome` returned 404 under the same insufficient package-read context. Consequently, historical GHCR package existence/content is **NOT AVAILABLE** for this design and must not be deleted, rewritten, or claimed as migrated.

## 5. Canonical identity map

The target active identities are:

| Current identity | Canonical Phase 2 identity | Migration rule |
| --- | --- | --- |
| `Codework` | `OmniGenis` | Active identity only; preserve historical evidence |
| `/opt/codework` | `/opt/omnigenis` | Direct cutover; no permanent symlink on the currently observed host |
| `/etc/codework` | `/etc/omnigenis` | Direct cutover; no permanent symlink on the currently observed host |
| `codework-isolated` | `omnigenis-isolated` | Dual-label transition before workflow cutover |
| `codework-01` | `omnigenis-01` | Runner label migration |
| `codework-02` | `omnigenis-02` | Runner label migration |
| `drhudson-codework-01` | `drhudson-omnigenis-01` | Re-register one runner at a time after label cutover |
| `drhudson-codework-02` | `drhudson-omnigenis-02` | Re-register one runner at a time after runner 01 is healthy |
| `codework-genome` | `omnigenis-genome` | New builds publish under new identity; never delete old package as part of this phase |
| `codework-genome-scaffold-v1` | `omnigenis-genome-scaffold-v2` | New cache namespace to avoid semantic aliasing |
| `codework-genome-mcp` | `omnigenis-genome-mcp` | NPM package identity |
| `codework-private-genome` | `omnigenis-genome-mcp` | MCP server/product identity |
| `codework-ngs` | `omnigenis-ngs` | Conda environment identity |
| `codework/genome-runtime` | `omnigenis/genome-runtime` | Nextflow manifest identity |
| `codework-codex` | `omnigenis-codex` | Codex marketplace identity |
| `coderabbit@codework-codex` | `coderabbit@omnigenis-codex` | Plugin reference identity |
| `CODEWORK_CODERABBIT_BIN_DIR` | `OMNIGENIS_CODERABBIT_BIN_DIR` | Temporary fallback allowed only during 2B, removed in 2D |
| tunnel profile `codework-genome` | `omnigenis-genome` | Current operational profile identity |
| `PROJECT_ROOT=/opt/codework` | `PROJECT_ROOT=/opt/omnigenis` | Runtime root |
| `codework-synthetic-germline-v1` | `omnigenis-synthetic-germline-v2` for new canaries | Never rewrite historical evidence that truthfully used v1 |

Historical archive names such as `codework-genome-runtime-2026-08-15.zip` remain unchanged when cited as historical evidence. A current recovery bundle, if still required, must be generated under a new OmniGenis identity instead of silently renaming historical bytes.

## 6. Canonical identity contract

Phase 2A introduces a versioned repository contract, preferably `config/project_identity.json`, with the canonical active identities and an explicit migration schema/version.

The contract is not expected to dynamically parameterize every consumer. GitHub Actions `runs-on` labels, Dockerfile paths, package names, and other tools may require literals. Instead, repository validation tests treat the identity contract as the canonical source and assert that active literals match it.

The contract must include at least:

- repository product name;
- runtime root and configuration root;
- container/package identity;
- MCP package and server identity;
- Conda environment identity;
- Nextflow manifest identity;
- runner pool label and per-runner labels;
- planned runner names;
- Codex marketplace and CodeRabbit plugin identity;
- canonical environment variable name;
- tunnel profile;
- cache namespace;
- current synthetic canary fixture identity.

A temporary legacy identity ledger records each permitted active Codework-derived occurrence during migration. The ledger must be machine-readable, versioned, justified per occurrence/class, and monotonic: an implementation PR may remove legacy entries but may not introduce an unlisted legacy identity.

## 7. Migration architecture

The migration uses four governed subphases: 2A, 2B, 2C, and 2D. Each subphase is independently reviewable and mergeable. No later subphase begins implementation before the previous subphase has been merged and its post-merge continuity gate has passed.

The general transition rule is:

`expand -> verify -> switch -> verify -> contract`

Where an external state cannot be inspected or safely reconstructed, the system remains in the expanded compatibility state until the missing Runtime/Resource Gate is satisfied.

## 8. Phase 2A — Internal Identity Contract

### Purpose

Create the canonical OmniGenis identity contract and a fail-closed migration ledger without changing runtime behavior.

### Expected changes

- add `config/project_identity.json`;
- add a machine-readable legacy identity ledger;
- add repository identity validation tests;
- integrate the validation into `scripts/validate_repo.py`;
- document the migration contract in English;
- preserve all existing operational values until later phases.

### Core invariants

At 2A completion:

- all canonical OmniGenis target identities are declared exactly once in the identity contract;
- all still-active Codework-derived identities are explicitly classified in the legacy ledger;
- a new unclassified Codework-derived identity fails validation;
- the number of permitted legacy active identities can only stay equal or decrease;
- scientific and normative files remain byte-identical to the 2A baseline unless a separate approved scientific change exists, which is outside this phase.

### Rollback

Revert the 2A PR. No external resource is mutated by 2A.

## 9. Phase 2B — Runtime and Build Identity Cutover

### Purpose

Move repository-controlled runtime/build identities to OmniGenis while retaining only narrowly justified transition compatibility.

### Scope

2B covers Dockerfile paths, Docker tags, GHCR publication target, cache scope, Docker Compose environment, systemd templates, MCP package/server identity, Conda environment name, Nextflow manifest name, tunnel profile, project root, Codex marketplace metadata/scripts, relevant tests, current operational documentation, and new synthetic canary identity.

### Path cutover

The target deployment paths are `/opt/omnigenis` and `/etc/omnigenis`.

Because no active `/opt/codework` or `/etc/codework` deployment was observed on the authorized host, the default plan does not create permanent compatibility symlinks. If a later Runtime/Resource Gate finds another supported deployment host with live old paths, that host requires an explicit host-specific migration/rollback plan before cutover.

### CodeRabbit environment-variable compatibility

`OMNIGENIS_CODERABBIT_BIN_DIR` becomes canonical.

During 2B only, `CODEWORK_CODERABBIT_BIN_DIR` may be accepted as a deprecated fallback when the canonical variable is absent. If both are set with conflicting values, the script must fail closed rather than choose silently. Tests must prove precedence, conflict behavior, and deprecation. The old alias is removed in 2D.

### Container and GHCR behavior

New local and CI builds use `omnigenis-genome`.

New protected-main publication targets `ghcr.io/${{ github.repository_owner }}/omnigenis-genome`.

No `codework-genome` package or version is deleted, renamed, retagged, or used as proof of successful migration without package-read verification. If `read:packages` remains unavailable, the old package state remains explicitly unknown while new OmniGenis publication can be validated from the workflow output and digest evidence produced after the new publish path executes.

### Cache behavior

Use a new scope such as `omnigenis-genome-scaffold-v2`. Do not reuse the old cache scope under a new semantic name, preventing hidden coupling between old and new identity contracts.

### MCP identity behavior

The package becomes `omnigenis-genome-mcp`. The server/product identity becomes `omnigenis-genome-mcp`. Protocol behavior, tool set, authorization rules, request/response contracts, redaction behavior, and security boundaries remain unchanged.

### Synthetic canary behavior

Newly generated fixtures use `omnigenis-synthetic-germline-v2`. Historical outputs containing `codework-synthetic-germline-v1` are not rewritten. Tests must distinguish historical provenance from the active fixture identity.

### Rollback

Before merge, rollback is branch reversion. After merge, repository-controlled runtime identifiers can be reverted to the previous commit if the new identities fail before external consumers are contracted. Old GHCR artifacts are preserved. No filesystem alias is removed on an unverified external deployment host.

## 10. Phase 2C — Self-hosted Runner Identity Cutover

### Purpose

Migrate the protected-main private runner pool without ever leaving the repository with no known private executor.

### Stage C1 — Expand labels

Both currently online runners receive the new custom label `omnigenis-isolated` while retaining `codework-isolated`. The per-runner legacy labels may likewise coexist with `omnigenis-01` and `omnigenis-02` during transition.

Before any label mutation, capture runner IDs, names, status, busy state, and labels as non-secret evidence.

After adding labels, verify through the GitHub runner API that:

- runner 01 is online;
- runner 02 is online;
- neither required runner disappeared;
- both expose `omnigenis-isolated`;
- old labels remain available until workflow cutover succeeds.

### Stage C2 — Switch workflows

Change trusted protected-main workflow routing from `codework-isolated` to `omnigenis-isolated`.

Untrusted pull-request and fork execution must continue using GitHub-hosted runners. The existing trust expression and `github.ref_protected` boundary must not be weakened while changing only the private runner label identity.

### Stage C3 — Real protected-main canary

After human merge, a real protected-main job must be accepted and completed by the new `omnigenis-isolated` pool. Static YAML inspection is insufficient.

Capture the run ID, job ID, selected runner name/ID when available, commit SHA, conclusion, and relevant non-secret routing evidence.

If no new-label runner accepts the job, restore workflow routing to the previously verified `codework-isolated` path while both labels still coexist and investigate before proceeding.

### Stage C4 — Contract old pool label

Only after the protected-main canary succeeds may `codework-isolated`, `codework-01`, and `codework-02` be removed from runner metadata.

### Stage C5 — Re-register runner names one at a time

Runner name migration is intentionally later than label migration because GitHub does not expose a simple rename operation equivalent to changing a custom label; re-registration may be required.

Before re-registration, rerun the Runtime/Resource Gate and determine the actual container creation/restart mechanism, image/digest, mounts, registration workflow, and rollback procedure without exposing registration tokens or credentials.

Then:

1. leave runner 02 online and functional;
2. safely drain runner 01;
3. re-register it as `drhudson-omnigenis-01` with canonical labels;
4. verify runner 01 online and execute a controlled canary;
5. only then drain and re-register runner 02 as `drhudson-omnigenis-02`;
6. verify both online and execute a final pool canary.

If the Runtime/Resource Gate cannot prove a safe recreation procedure, runner-name migration remains blocked and no runner is removed merely to satisfy branding cleanliness.

### Rollback

During dual-label state, workflow routing can return to `codework-isolated` without runner recreation. During one-at-a-time re-registration, the untouched runner remains the continuity anchor. No operation may simultaneously unregister both runners.

## 11. Phase 2D — Legacy Elimination and Seal

### Purpose

Remove temporary compatibility and prove that all active operational identity is OmniGenis.

### Required removals

2D removes active uses of:

- `CODEWORK_CODERABBIT_BIN_DIR`;
- `codework-isolated`, `codework-01`, and `codework-02`;
- `codework-codex` and `coderabbit@codework-codex`;
- `/opt/codework` and `/etc/codework` in current deployment instructions/configuration;
- old active Docker/MCP/Conda/Nextflow/cache/tunnel names;
- old identity assertions in active tests;
- transition-only ledger allowances that no longer represent active compatibility needs.

### Historical allowlist

The final scanner may allow old terminology only in explicit historical classes, for example:

- immutable PR/run URLs whose original repository path was Codework;
- Phase 1/Phase 2 migration specifications and evidence that describe the old state truthfully;
- historical checkpoints and audit evidence;
- historical artifact filenames whose bytes or provenance must not be rewritten;
- historical canary outputs that used `codework-synthetic-germline-v1`.

The allowlist is exact and fail-closed. A broad directory exemption is not sufficient when active operational instructions can coexist with historical material. Each permitted class/path must be justified and tested.

### Final seal

The migration is sealed only when the active legacy scan returns zero unclassified operational Codework identities and every remaining old-identity occurrence is explicitly historical/provenance evidence.

## 12. English-first policy

All code, tests, comments, docstrings, technical messages, configuration descriptions, developer-facing documentation, migration specifications, plans, evidence metadata, and new identifiers created or modified by Phase 2 are written in English.

Existing Portuguese is preserved only where it remains an explicitly normative, localized, canonical, historical, or compatibility-preserved contract under the repository's current language policy.

The existing `code_language_guard` and residual-language audit remain mandatory. Phase 2 must not weaken their scope to make migration text pass.

## 13. Scientific and normative boundary

Phase 2 is an identity migration, not a genomic reanalysis or scientific-method change.

The following are protected from incidental change:

- canonical GENOMA v3.4 ruleset identity and sealed bytes;
- GRCh38/reference integrity contracts;
- evidence schemas and interpretation categories;
- clinical, reproductive, pharmacogenomic, ancestry, nutrigenetic, longevity, traits, and completeness semantics;
- scientific thresholds and QC thresholds;
- genomic calling behavior and supported/unsupported variant-class declarations;
- report taxonomy and clinical-status semantics.

Any diff touching those surfaces must be justified independently and is blocking for Phase 2 unless explicitly approved as a separate change.

## 14. Security and governance gates

Every implementation PR must satisfy all applicable gates before manual merge:

1. exact baseline/HEAD recorded;
2. clean isolated worktree;
3. TDD RED observed for each new enforcement behavior before implementation;
4. focused GREEN tests;
5. `scripts/validate_repo.py` PASS;
6. supply-chain lock verification PASS;
7. complete root regression PASS in the pinned project environment;
8. English-first guard PASS;
9. residual-language audit clean;
10. shell syntax/diff-integrity checks PASS;
11. secret-pattern scan of the diff PASS;
12. active legacy identity count does not increase;
13. scientific/normative boundary diff gate PASS;
14. required external reviewers/checks run on the exact final HEAD;
15. required review threads resolved;
16. rulesets remain semantically equivalent and active;
17. no automatic merge;
18. final merge performed only through explicit human action.

Draft-first/local-first development remains preferred to avoid unnecessary GitHub Actions consumption. A PR is marked ready only after its exact HEAD has passed the applicable local gates.

## 15. Evidence model

Each subphase records non-secret evidence sufficient to reproduce its claims. Evidence must identify:

- baseline and final SHA;
- exact changed paths;
- identity-contract version/hash;
- legacy ledger count before/after;
- validation commands and results;
- ruleset definitions or normalized semantic digests before/after when governance is involved;
- external check outcomes on the exact HEAD;
- runner IDs/names/labels/status when runner state is involved;
- protected-main canary run/job IDs for 2C;
- GHCR publication digest for the new package when available;
- unavailable capabilities explicitly labeled rather than inferred.

Evidence must never contain credentials, GitHub registration tokens, package tokens, genomic/patient data, cookies, or secret environment values.

## 16. Failure handling

Phase 2 is fail-closed.

Examples:

- If the canonical identity contract and an active consumer disagree, validation fails.
- If a new unclassified `codework-*` occurrence appears, validation fails.
- If the legacy count increases, validation fails.
- If both old and new CodeRabbit bin-dir variables are set to conflicting values during 2B, the setup script fails.
- If a new runner label cannot execute the protected-main canary, the old label remains and workflow routing is rolled back.
- If runner recreation cannot be proven, runner names are not changed.
- If GHCR history cannot be read, the old package is not modified or deleted.
- If a ruleset changes semantically, the migration stops.
- If a scientific/normative surface changes incidentally, the migration stops.
- If an external required check is unavailable, pending, or failing, readiness is not declared.

No migration stage may convert missing evidence into an assumed PASS.

## 17. Post-merge verification per subphase

After each human merge:

- fetch `origin/main` and record the merge SHA;
- rerun the identity/legacy gate from clean `main`;
- re-read both active GitHub rulesets and compare their normalized semantics with the pre-merge evidence;
- verify repository ID `1212760346`, full name `drhudsonandrade/OmniGenis`, visibility `public`, and default branch `main`;
- verify any external resource changed by that subphase from the authoritative external API;
- record a post-merge checkpoint before starting the next subphase.

## 18. Definition of Done

Phase 2 is complete only when all of the following are true:

1. the repository remains `drhudsonandrade/OmniGenis` with ID `1212760346`;
2. the protected-main and approval rulesets remain active and semantically unchanged unless separately approved;
3. the canonical internal identity contract is active and enforced;
4. current runtime/build/MCP/Conda/Nextflow/Codex/tunnel/cache identities use OmniGenis;
5. current deployment paths use `/opt/omnigenis` and `/etc/omnigenis`;
6. new container publication uses `omnigenis-genome` and produces digest-verifiable evidence;
7. historical `codework-genome` artifacts, if they exist, were not destroyed as part of the migration;
8. protected-main work has completed successfully on `omnigenis-isolated`;
9. both final runner identities are online as `drhudson-omnigenis-01` and `drhudson-omnigenis-02`, unless runner-name re-registration is explicitly blocked by a failed Runtime/Resource Gate—in which case Phase 2 cannot be sealed complete;
10. no temporary legacy runner labels remain;
11. `OMNIGENIS_CODERABBIT_BIN_DIR` is canonical and the old alias is removed;
12. new canary generation uses `omnigenis-synthetic-germline-v2`;
13. active operational scanning finds zero unclassified Codework-derived identities;
14. every remaining Codework-derived occurrence is exact historical/provenance evidence with a reviewed allowlist entry;
15. full regression, language, supply-chain, security, and governance gates pass on the final exact HEAD;
16. all implementation PRs were manually merged under the existing governance policy;
17. a final post-merge seal/checkpoint records the completed migration and remaining historical references.

## 19. Planned implementation sequence

The implementation plan produced after written-spec approval must preserve this sequence:

1. **2A — Internal Identity Contract**: identity registry, legacy ledger, fail-closed validators, no runtime behavior change.
2. **2B — Runtime and Build Identity Cutover**: repository-controlled runtime identities, compatibility fallback only where explicitly justified.
3. **2C — Runner Identity Cutover**: dual labels, workflow switch, real protected-main canary, one-at-a-time runner re-registration.
4. **2D — Legacy Elimination and Seal**: remove temporary compatibility, exact historical allowlist, zero active legacy identities, final seal.

Each subphase should normally be its own PR. If implementation exploration reveals a subphase is too large for one reviewable PR, it must be decomposed without changing the required order or weakening intermediate gates.

## 20. Final design decision

The approved direction is a complete OmniGenis technical identity, not a permanent dual-brand system. Compatibility exists only as a temporary migration mechanism where real external consumers require it. Historical truth is preserved rather than cosmetically rewritten.

This design favors continuity, evidence, rollback, and testability over a one-shot textual replacement.
