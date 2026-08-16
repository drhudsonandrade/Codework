# GENOMA v0.8 Array/Evidence/Template Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate partial-genome SNP-array processing into the deterministic Scientific Data Plane, add a broad traceable Evidence/Annotation Plane, make the 11 v3.0 report templates content-addressed/private/immutable inside the private repository, harden GitHub Actions/dependency identities, and finish a fresh post-deployment witness on `main`.

**Architecture:** Preserve the existing `Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`. Add `array` as a first-class Nextflow mode; keep interpretation limited to interrogated loci; use evidence adapters through a budgeted query planner that records every retrieval and limitation; store the exact v3.0 PDFs under content-addressed paths with a signed-style manifest contract; pin workflow actions by immutable commit SHA and generate a machine-readable dependency lock. Cloudflare, Temporal, Supabase and ChatGPT remain optional adapters only.

**Tech Stack:** Python 3.11/3.12, Nextflow DSL2 26.04.6, Docker/OCI, GitHub Actions, PyMuPDF 1.26.7, existing policy engine, existing evidence adapters, SHA-256 content addressing.

## Global Constraints

- Normative identity must remain `STATUS NORMATIVO: VIGENTE`, `VERSÃO NORMATIVA: v3.3`, `DATA FORMAL DE EMISSÃO E VIGÊNCIA: 14/08/2026`.
- Canonical ruleset SHA-256 must remain `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`.
- Use only operational labels `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, `NÃO DISPONÍVEL`.
- No personal genotype bytes may be committed to GitHub or uploaded to CI artifacts.
- SNP-array must never be treated as WGS; absent/non-interrogated loci are not negative evidence.
- POST-DEPLOYMENT PASS may be stated only after the merged final `main` commit runs the live 15/15 section-260 witness with zero critical failures.
- `full-grch38` remains independent of partial-genome readiness; alternative reference strategies may reduce the need to build BWA-MEM2 indexes locally, but must not bypass checksum/reference/runtime gates.

---

### Task 1: Audit baseline and PR #12 landing

**Files:**
- Create: `docs/audits/GENOMA_V0.8_PREIMPLEMENTATION_AUDIT_2026-08-16.md`

**Interfaces:**
- Consumes: merged `main` after PR #12.
- Produces: explicit gap register and acceptance criteria used by later tasks.

- [ ] Record ruleset identity, current `main` SHA, merged PR #12, current workflows, partial-array lane, WGS lane, report-template state, and external-infrastructure limitations.
- [ ] Record every state as EXECUTADO/VERIFICADO/INFERIDO/PROPOSTO/NÃO DISPONÍVEL.
- [ ] Add acceptance criteria for array integration, evidence traceability, template immutability, supply-chain lock, and final witness.

### Task 2: First-class SNP-array Scientific Data Plane

**Files:**
- Create: `workflows/array.nf`
- Create: `scripts/build_array_case_manifest.py`
- Modify: `main.nf`
- Modify: `.github/workflows/genoma-snp-array.yml`
- Test: `tests/test_array_scientific_data_plane.py`

**Interfaces:**
- Consumes: array input path, case ID, build/strand evidence, QC output.
- Produces: `array-qc.json`, `array-observations.tsv`, `array-case-manifest.json`, annotation plan/result, policy/report handoff.

- [ ] Write tests requiring `--mode array` and fail-closed required parameters.
- [ ] Implement `workflows/array.nf` stages: QC → case manifest → evidence annotation → publication manifest.
- [ ] Ensure all intermediate artifacts are content-addressed and no raw personal genotype is copied outside the designated case workspace.
- [ ] Extend synthetic CI to run the full array workflow without personal data.

### Task 3: Broad Evidence/Annotation Plane for partial genomes

**Files:**
- Create: `array_pipeline/annotation.py`
- Create: `array_pipeline/targets.py`
- Create: `scripts/annotate_partial_genome.py`
- Create: `config/partial_genome_annotation_targets.json`
- Test: `tests/test_partial_genome_annotation.py`

**Interfaces:**
- Consumes: QC JSON + observation TSV + target manifest.
- Produces: deterministic query plan, evidence snapshots, normalized annotation records, source status table, limitations.

- [ ] Implement a query-budget planner so 700k SNPs never trigger uncontrolled API fan-out.
- [ ] Support ClinVar, ClinGen, CPIC, ClinPGx, gnomAD and PGS Catalog adapters through the existing adapter interface.
- [ ] Require locator/query/checked_at/result_digest for every VERIFICADO source result.
- [ ] Keep ClinVar/ClinGen/CPIC/ClinPGx/gnomAD/PGS interpretations separate and classify clinical/predisposition/research/curiosity scope explicitly.
- [ ] Produce explicit `NÃO DISPONÍVEL` for structural/CNV/SV/repeat/HLA/CYP2D6-complex claims not supported by SNP-array.

### Task 4: Immutable private v3.0 template store

**Files:**
- Create binary PDFs under: `template_store/v3.0/sha256/<sha>/<filename>.pdf`
- Create: `template_store/v3.0/MANIFEST.json`
- Create: `template_store/v3.0/README.md`
- Create: `scripts/verify_template_store.py`
- Modify: `reporting/reference_v3_manifest.json`
- Test: `tests/test_template_store.py`

**Interfaces:**
- Consumes: exact 11 attached v3.0 PDFs.
- Produces: content-addressed immutable source pack verified by SHA-256/page count/size and used by renderer.

- [ ] Upload the exact attached PDFs; verify the known SHA-256 identities before commit.
- [ ] Enforce one-way immutability: known template IDs may not change hash/path without a manifest version bump.
- [ ] Make renderer resolve templates from content-addressed paths, not mutable filenames or external conversation attachments.
- [ ] Keep the repository private; never embed case/patient data in the template store.

### Task 5: Supply-chain lock and immutable GitHub Actions

**Files:**
- Create: `locks/runtime-lock.json`
- Create: `locks/actions-lock.json`
- Create: `scripts/verify_supply_chain_lock.py`
- Modify: `.github/workflows/*.yml`
- Modify: `scripts/validate_repo.py`
- Test: `tests/test_supply_chain_lock.py`

**Interfaces:**
- Consumes: environment.yml, action identities, container/base-image identities where available.
- Produces: reproducible lock with version + immutable identity + verification timestamp/source.

- [ ] Pin critical GitHub Actions to immutable commit SHAs with comments preserving human-readable major versions.
- [ ] Snapshot runtime package pins and hash `environment.yml`, Dockerfile, policy engine source and template manifest.
- [ ] Fail CI if a critical action returns to mutable tag-only syntax or a locked file digest drifts without lock update.

### Task 6: High-memory/GRCh38 alternative architecture

**Files:**
- Create: `docs/GRCH38_COMPUTE_STRATEGY.md`
- Create: `scripts/verify_prebuilt_bwa_mem2_bundle.py`
- Modify: `.github/workflows/genoma-ngs-runtime-gate.yml`
- Test: `tests/test_grch38_compute_strategy.py`

**Interfaces:**
- Consumes: approved GRCh38 bundle, optional prebuilt BWA-MEM2 indexes, approved SHA lock.
- Produces: two legal paths: `self-hosted-build` or `prebuilt-verified`, both ending in functional index canary + Runtime/Resource Gate.

- [ ] Keep self-hosted high-memory build path.
- [ ] Add a no-highmem steady-state path that accepts prebuilt BWA-MEM2 indexes only when all five index files are checksum-locked to the exact approved FASTA and pass functional validation.
- [ ] Document that BWA-MEM2 index construction itself needs high memory and cannot be made equivalent by simply combining ordinary GitHub runners; use one-time ephemeral high-memory or externally prebuilt content-addressed index instead.
- [ ] Never claim the prebuilt path is VERIFIED until an actual approved bundle/index is supplied and validated.

### Task 7: Audit workflow and final deployment witness

**Files:**
- Create: `.github/workflows/genoma-audit.yml`
- Create: `scripts/genoma_audit.py`
- Create: `docs/audits/GENOMA_V0.8_FINAL_AUDIT_2026-08-16.md`
- Test: `tests/test_genoma_audit.py`

**Interfaces:**
- Consumes: repository contracts, supply-chain lock, template store, synthetic array workflow evidence, policy-engine state.
- Produces: machine-readable `audit.json` + human-readable audit report; never grants section-260 POST-DEPLOYMENT by itself.

- [ ] Audit all four planes and optional-adapter boundaries.
- [ ] Require no personal-genotype fixtures in repository.
- [ ] Require template-store and supply-chain verification PASS.
- [ ] Require synthetic array integration PASS.
- [ ] Merge only after all PR checks pass.
- [ ] After merge, wait for `GENOMA Production Witness` on the exact final `main` SHA; only if 15/15 and zero critical failures record POST-DEPLOYMENT PASS.
