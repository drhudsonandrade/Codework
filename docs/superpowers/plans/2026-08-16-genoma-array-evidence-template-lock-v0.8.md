# GENOMA v0.8 Array/Evidence/Template Hardening — historical plan

## Goal

Integrate partial-genome SNP-array processing into the deterministic Scientific Data Plane, add a traceable Evidence Plane, store the exact 11 v3.0 report templates as immutable private content, harden supply-chain identities and finish a fresh exact-SHA production witness.

## Architecture

`Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane`

Optional edge, orchestration, database, hosting and interface services remain adapters only. None may be required for scientific execution or policy truth.

## Global constraints

- Normative identity remains `VIGENTE / v3.3 / 14/08/2026`.
- Canonical ruleset SHA-256 remains `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`.
- Use only `EXECUTADO`, `VERIFICADO`, `INFERIDO`, `PROPOSTO`, `NÃO DISPONÍVEL` for operational status.
- Never commit personal genotype bytes.
- SNP-array is never equivalent to WGS; unassayed loci are not negative evidence.
- POST-DEPLOYMENT PASS requires the exact merged `main` SHA, live 15/15 section-260 witness and zero critical failures.

## Workstreams

1. Audit baseline and explicit gap register.
2. First-class SNP-array Nextflow lane with QC and fail-closed parameter contracts.
3. Budgeted Evidence Plane for ClinVar, ClinGen, CPIC, ClinPGx, gnomAD and PGS Catalog.
4. Immutable v3.0 template store verified by SHA-256, size and page count.
5. Immutable GitHub Actions/runtime dependency locks.
6. Two legal GRCh38/BWA-MEM2 strategies: high-memory build or independently verified prebuilt index.
7. Four-plane audit plus exact-SHA live Production Witness.

## Supersession

This plan is a historical implementation record. Current repository validators, safety gates and production-witness contracts supersede any incomplete checkbox or historical execution note.
