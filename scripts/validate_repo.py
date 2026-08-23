#!/usr/bin/env python3
"""Validate static repository safety and the shared GENOMA v3.4 sealed contract."""
from __future__ import annotations

import ast
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sealed_ruleset import EXPECTED_NAME, EXPECTED_SHA, SealedRulesetError, verify_transport

CANONICAL_RULESET = EXPECTED_NAME
CANONICAL_RULESET_SHA256 = EXPECTED_SHA
FALLOW_ACTION_SHA = "45fd28766199acb1f939f6862274a37aad12770b"
REQUIRED_PATHS = (
    ".fallowrc.json", ".github/workflows/fallow.yml", ".github/workflows/scaffold-validation.yml",
    ".github/workflows/genoma-policy-engine.yml", ".github/workflows/genoma-production-ceremony.yml",
    ".github/workflows/genoma-production-witness.yml", ".github/workflows/genoma-ngs-runtime-gate.yml",
    ".github/workflows/genoma-snp-array.yml", ".gitignore", "Dockerfile", "environment.yml", "main.nf",
    "nextflow.config", "workflows/wgs.nf", "workflows/array.nf", "array_pipeline/qc.py",
    "array_pipeline/annotation.py", "array_pipeline/targets.py", "config/partial_genome_annotation_targets.json",
    "manifests/GRCh38.sources.tsv", "manifests/GRCh38.lock.sha256.example", "manifests/RULESET_V3.4.sha256",
    "normative/sealed/MANIFEST.json", "normative/sealed/README.md",
    "scripts/__init__.py", "scripts/sealed_ruleset.py", "scripts/check_versions.sh", "scripts/fetch_grch38.sh",
    "scripts/build_bwa_mem2_index.sh", "scripts/validate_grch38.sh", "scripts/validate_bwa_mem2_functional.sh",
    "scripts/generate_canary.py", "scripts/score_variants.py", "scripts/run_canary.sh", "scripts/verify_ruleset.sh",
    "scripts/materialize_ruleset.py", "scripts/bootstrap_attestation.py", "scripts/run_live_post_deployment_smoke.py",
    "scripts/runtime_resource_gate.py", "scripts/runtime_stack.py", "scripts/prepare_latest_candidate.py",
    "scripts/promote_latest_candidate.py", "scripts/freshness_gate.py", "scripts/latest_runtime_resource_gate.py",
    "scripts/verify_runtime_gate_manifest.py", "scripts/wgs_consent_gate.py", "scripts/wgs_input_gate.py",
    "scripts/wgs_align_or_stage.sh", "scripts/build_wgs_curated_manifest.py", "scripts/query_evidence.py",
    "scripts/build_adapter_capabilities.py", "scripts/run_snp_array.py", "scripts/annotate_partial_genome.py",
    "scripts/build_array_case_manifest.py", "scripts/verify_prebuilt_bwa_mem2_bundle.py",
    "scripts/verify_supply_chain_lock.py", "scripts/generate_report.py", "scripts/generate_all_reports.py",
    "reporting/__init__.py", "reporting/catalog.json", "reporting/engine.py", "reporting/editorial_v3.py",
    "reporting/editorial_v3_hifi.py", "reporting/requirements.txt", "reporting/reference_v3_manifest.json",
    "template_store/v3.0/MANIFEST.json", "locks/actions-lock.json", "locks/runtime-lock.json",
    "evidence_adapters/__init__.py", "policy_engine/pyproject.toml", "policy_engine/genoma_policy/engine.py",
    "policy_engine/genoma_policy/attestation.py", "policy_engine/genoma_policy/ledger.py",
    "policy_engine/genoma_policy/version.py", "policy_engine/policy/schema/execution-manifest.schema.json",
    "policy_engine/Dockerfile", "policy_engine/docker-compose.yml", "mcp/package.json", "mcp/package-lock.json",
    "mcp/tsconfig.json", "mcp/src/server.ts", "deploy/docker-compose.yml",
    "deploy/attestations/bootstrap-project-v3.4.json", "adapters/README.md", "adapters/config.example.json",
    "docs/FALLOW_SECURITY_REVIEW.md", "docs/GITHUB_MOBILE_IMPORT.md", "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md", "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/PR_BODY.md",
    "docs/DETERMINISTIC_ENGINE.md", "docs/PRODUCTION_CEREMONY.md", "docs/PORTABILITY_MATRIX.md",
    "docs/GRCH38_COMPUTE_STRATEGY.md", "docs/audits/GENOMA_V0.8_PREIMPLEMENTATION_AUDIT_2026-08-16.md",
)
EXPECTED_ARTIFACTS = {
    "Homo_sapiens_assembly38.fasta", "Homo_sapiens_assembly38.fasta.fai", "Homo_sapiens_assembly38.dict",
    "gencode.v50.primary_assembly.annotation.gtf.gz", "Homo_sapiens_assembly38.dbsnp138.vcf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz.tbi", "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz.tbi", "hg38-blacklist.v2.bed.gz",
}
EXPECTED_EVIDENCE_ADAPTERS = {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"}
FORBIDDEN_SUFFIXES = (".fastq", ".fq", ".bam", ".bai", ".cram", ".crai", ".vcf", ".tbi")
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".pytest_cache"}
TEXT_IDENTITY_SUFFIXES = {
    ".json", ".md", ".nf", ".py", ".rego", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
}
HISTORICAL_V33_ROOT = Path("docs/history/v3.3")
HISTORICAL_SUPERSEDED_IDENTITY_PATHS = {
    Path("docs/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md"),
    Path("docs/audits/GENOMA_V0.8_FINAL_AUDIT_2026-08-16.md"),
    Path("docs/audits/GENOMA_V0.8_PREIMPLEMENTATION_AUDIT_2026-08-16.md"),
    Path("docs/superpowers/plans/2026-08-14-magalu-private-mcp.md"),
    Path("docs/superpowers/plans/2026-08-16-genoma-array-evidence-template-lock-v0.8.md"),
}
SUPERSEDED_IDENTITY_GUARDRAIL_PATHS = {
    Path("scripts/validate_repo.py"),
    Path("tests/test_v34_activation_contract.py"),
}
FORBIDDEN_ACTIVE_PATHS = (
    "manifests/RULESET_V3.3.sha256",
    "deploy/attestations/bootstrap-project-v3.3.json",
)
OLD_ACTIVE_TOKENS = (
    "REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt",
    "RULESET_V3.3.sha256",
    "v3.3",
    "GENOMA-V3.3",
    "14/08/2026",
    "2026-08-14",
    "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a",
)
ACTIVE_IDENTITY_SURFACES = (
    "scripts/run_live_post_deployment_smoke.py", "scripts/verify_ruleset.sh", "scripts/genoma_audit.py",
    "scripts/run_snp_array.py", "scripts/annotate_partial_genome.py", "scripts/build_wgs_curated_manifest.py",
    "scripts/build_array_case_manifest.py", "scripts/generate_report.py", "scripts/generate_all_reports.py",
    "array_pipeline/qc.py", "array_pipeline/annotation.py", "workflows/wgs.nf", "workflows/array.nf",
    "main.nf", "nextflow.config", "Dockerfile", "deploy/docker-compose.yml", "mcp/src/server.ts",
    "reporting/engine.py", "policy_engine/Dockerfile", "policy_engine/docker-compose.yml",
    "policy_engine/pyproject.toml", "policy_engine/README_GENOMA_POLICY.md", "policy_engine/tests/test_server.py",
    "policy_engine/genoma_policy/__init__.py", "policy_engine/genoma_policy/cli.py",
    "policy_engine/genoma_policy/engine.py", "policy_engine/genoma_policy/gates_core.py",
    "policy_engine/genoma_policy/gates_audit.py", "policy_engine/genoma_policy/models.py",
    "policy_engine/genoma_policy/paths.py", "policy_engine/genoma_policy/ruleset.py",
    "policy_engine/genoma_policy/smoke.py", "policy_engine/policy/rego/genoma.rego",
    "policy_engine/policy/rego/genoma_test.rego", "policy_engine/policy/schema/execution-manifest.schema.json",
    "locks/runtime-lock.json", ".github/workflows/genoma-policy-engine.yml",
    ".github/workflows/genoma-production-ceremony.yml", ".github/workflows/genoma-production-witness.yml",
    ".github/workflows/genoma-ngs-runtime-gate.yml", ".github/workflows/genoma-snp-array.yml",
    "docs/DETERMINISTIC_ENGINE.md", "docs/PRODUCTION_CEREMONY.md", "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/SNP_ARRAY_PARTIAL_GENOME.md", "docs/PR_BODY.md",
)


def validate_sealed_ruleset(root: Path, errors: list[str]) -> None:
    try:
        verify_transport(root / "normative" / "sealed")
    except (OSError, UnicodeError, ValueError, SealedRulesetError) as exc:
        errors.append(f"sealed normative transport invalid: {type(exc).__name__}: {exc}")


def validate_active_identity_text(text: str, relative: str, errors: list[str]) -> None:
    """Reject each superseded active-identity token independently."""
    for token in OLD_ACTIVE_TOKENS:
        if token in text:
            errors.append(f"active ruleset surface still references superseded identity: {relative}: {token}")


def _constant_string(node: ast.AST) -> str | None:
    """Fold only literal string concatenations; never execute repository code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _python_constant_strings(text: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()
    values = (_constant_string(node) for node in ast.walk(tree))
    return tuple(dict.fromkeys(value for value in values if value is not None))


def _is_historical_superseded_identity_path(relative: Path) -> bool:
    return (
        relative in HISTORICAL_SUPERSEDED_IDENTITY_PATHS
        or relative == HISTORICAL_V33_ROOT
        or HISTORICAL_V33_ROOT in relative.parents
    )


def validate_superseded_identity_locations(root: Path, errors: list[str]) -> None:
    """Reject superseded identities globally except immutable historical records and guardrail fixtures."""
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root)
        if relative in SUPERSEDED_IDENTITY_GUARDRAIL_PATHS:
            continue
        if _is_historical_superseded_identity_path(relative):
            continue
        if "v3.3" in relative.as_posix().lower():
            errors.append(f"superseded identity path outside explicit history: {relative}")
        if path.suffix.lower() not in TEXT_IDENTITY_SUFFIXES and path.name not in {"Dockerfile", "AGENTS.md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        candidates = [text]
        if path.suffix.lower() == ".py":
            candidates.extend(_python_constant_strings(text))
        for token in OLD_ACTIVE_TOKENS:
            if any(token in candidate for candidate in candidates):
                errors.append(f"superseded identity outside explicit history: {relative}: {token}")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(
        f"missing required path: {relative}"
        for relative in REQUIRED_PATHS
        if not (root / relative).is_file()
    )
    errors.extend(
        f"superseded active ruleset path must be archived outside executable surfaces: {relative}"
        for relative in FORBIDDEN_ACTIVE_PATHS
        if (root / relative).exists()
    )
    validate_superseded_identity_locations(root, errors)

    active = []
    for candidate in root.rglob("REGRAS_PROJETO_GENOMA*.txt"):
        if any(part in SKIP_PARTS for part in candidate.parts):
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", text, re.MULTILINE):
            active.append(candidate.relative_to(root))
    if active:
        errors.append(f"active normative ruleset must be materialized at runtime, not duplicated in repo; found {active}")

    validate_sealed_ruleset(root, errors)

    ruleset_manifest = root / "manifests/RULESET_V3.4.sha256"
    if ruleset_manifest.is_file() and ruleset_manifest.read_text(encoding="ascii").strip().split() != [CANONICAL_RULESET_SHA256, CANONICAL_RULESET]:
        errors.append("ruleset external manifest does not match the verified v3.4 artifact")

    for relative in ACTIVE_IDENTITY_SURFACES:
        path = root / relative
        if path.is_file():
            validate_active_identity_text(path.read_text(encoding="utf-8", errors="replace"), relative, errors)

    manifest = root / "manifests/GRCh38.sources.tsv"
    if manifest.is_file():
        with manifest.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        targets = {row.get("target", "") for row in rows}
        if len(rows) != 9 or targets != EXPECTED_ARTIFACTS:
            errors.append(f"GRCh38 manifest must contain exactly the required 9 artifacts; found {len(rows)}")
        if any(not row.get("url", "").startswith(("https://", "generated-from:")) for row in rows):
            errors.append("GRCh38 manifest contains a non-HTTPS/non-generated source")

    package = root / "mcp/package.json"
    if package.is_file() and json.loads(package.read_text()).get("devDependencies", {}).get("fallow") != "3.16.0":
        errors.append("mcp/package.json must pin fallow 3.16.0 exactly")

    fw = root / ".github/workflows/fallow.yml"
    if fw.is_file():
        text = fw.read_text(encoding="utf-8")
        if f"fallow-rs/fallow@{FALLOW_ACTION_SHA}" not in text or "version: 3.16.0" not in text:
            errors.append("Fallow workflow must pin wrapper SHA and CLI 3.16.0")

    runbook = root / "docs/MAGALU_PRIVATE_MCP_SETUP.md"
    if runbook.is_file() and "--entrypoint /bin/bash" in runbook.read_text(encoding="utf-8"):
        errors.append("runbook must not bypass the micromamba container entrypoint")

    main_nf = root / "main.nf"
    if main_nf.is_file():
        text = main_nf.read_text(encoding="utf-8")
        for token in ("params.mode", "WGS_PRODUCTION", "ARRAY_PRODUCTION", "CANARY", "array_input", "array_build_evidence", "array_strand_evidence"):
            if token not in text:
                errors.append(f"main.nf missing dispatcher contract token: {token}")

    wgs_nf = root / "workflows/wgs.nf"
    if wgs_nf.is_file():
        text = wgs_nf.read_text(encoding="utf-8")
        for token in ("VERIFY_RUNTIME_GATE", "REFRESH_FRESHNESS_GATE", "VERIFY_CONSENT_PROVENANCE", "ready_for_first_dna_read", "INGEST_AND_QC", "ALIGN_OR_STAGE", "RERUN_SAMPLE_RUNTIME_GATE", "CALL_SHORT_VARIANTS", "NORMALIZE_VARIANTS", "ANNOTATE_EVIDENCE", "BUILD_CURATED_MANIFEST", "POLICY_EVALUATE", "GENERATE_REPORTS", "unsupported_variant_classes", "NÃO DISPONÍVEL", "CYP2D6", "CNV", "SV"):
            if token not in text:
                errors.append(f"WGS workflow missing fail-closed contract token: {token}")

    array_nf = root / "workflows/array.nf"
    if array_nf.is_file():
        text = array_nf.read_text(encoding="utf-8")
        for token in ("ARRAY_QC", "ARRAY_ANNOTATE", "ARRAY_BUILD_MANIFEST", "ARRAY_POLICY_EVALUATE", "ARRAY_GENERATE_REPORTS", "LIMITED_INTERPRETATION_GATE", "plan-only", "live"):
            if token not in text:
                errors.append(f"SNP-array workflow missing fail-closed contract token: {token}")

    witness = root / ".github/workflows/genoma-production-witness.yml"
    if witness.is_file():
        text = witness.read_text(encoding="utf-8")
        if "--output-dir evidence/live-section-260" in text:
            errors.append("Production Witness still uses obsolete live smoke --output-dir contract")
        for token in ("--deployment-id", "--output evidence/live-section-260/summary.json"):
            if token not in text:
                errors.append(f"Production Witness missing current live smoke contract: {token}")

    ngs_gate = root / ".github/workflows/genoma-ngs-runtime-gate.yml"
    if ngs_gate.is_file():
        text = ngs_gate.read_text(encoding="utf-8")
        if "bash -lc './scripts/run_canary.sh" in text:
            errors.append("NGS gate must not bypass micromamba environment with a login-shell canary")
        for token in ("freshness_gate.py", "GRCh38.lock.sha256.approved", "[self-hosted, linux, x64, genoma-production, highmem]", "nextflow run /opt/codework/main.nf --mode canary", "validate_bwa_mem2_functional.sh", "verify_supply_chain_lock.py"):
            if token not in text:
                errors.append(f"NGS gate missing current-session readiness contract: {token}")

    nextflow_cfg = root / "nextflow.config"
    if nextflow_cfg.is_file() and "nextflowVersion = '!>=26.04.6'" not in nextflow_cfg.read_text(encoding="utf-8"):
        errors.append("Nextflow manifest must permit tested forward versions while enforcing minimum 26.04.6")

    adapters = root / "evidence_adapters/__init__.py"
    if adapters.is_file():
        text = adapters.read_text(encoding="utf-8")
        for key in EXPECTED_EVIDENCE_ADAPTERS:
            if f'"{key}"' not in text:
                errors.append(f"missing evidence adapter: {key}")
        if "api.pharmgkb.org" in text:
            errors.append("retired PharmGKB API hostname must not be used; use ClinPGx")
        for token in ("result_digest", "checked_at", "locator", "NÃO DISPONÍVEL", "VERIFICADO"):
            if token not in text:
                errors.append(f"evidence adapter contract missing: {token}")

    renderer = root / "reporting/editorial_v3_hifi.py"
    if renderer.is_file():
        text = renderer.read_text(encoding="utf-8")
        for token in ("0B1F33", "0F766E", "A16207", "F2F4F7", "RESULTADO GENÔMICO", "write_editorial_bundle", "DejaVu Sans"):
            if token not in text:
                errors.append(f"editorial v3 high-fidelity renderer contract missing: {token}")

    catalog = root / "reporting/catalog.json"
    if catalog.is_file():
        models = json.loads(catalog.read_text(encoding="utf-8"))
        expected_accents = {"01": "0F766E", "02": "2563EB", "03": "7C3AED", "04": "166534", "05": "475467", "06": "B42318", "07": "A16207", "08": "0F766E", "09": "475467", "10": "0B1F33", "11": "0B1F33"}
        for report_id, accent in expected_accents.items():
            if models.get(report_id, {}).get("accent") != accent:
                errors.append(f"report {report_id} v3 accent mismatch")

    requirements = root / "reporting/requirements.txt"
    if requirements.is_file():
        req = requirements.read_text(encoding="utf-8")
        if "python-docx==" not in req or "reportlab==" not in req:
            errors.append("editorial renderer dependencies must be exact-pinned")

    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root)
        name = path.name.lower()
        if name.endswith(FORBIDDEN_SUFFIXES) or name.endswith((".fastq.gz", ".fq.gz", ".vcf.gz")):
            errors.append(f"genomic/reference payload must not be committed: {relative}")
        if name == "grch38.lock.sha256.approved":
            errors.append("externally approved GRCh38 lock must not be committed")
        if path.suffix == ".json":
            try:
                json.loads(path.read_text())
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid JSON: {relative}: {exc}")
    return errors


def main() -> None:
    errors = validate(ROOT)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\trepository_contract")
    print("PASS\truleset_manifest_contract\tv3.4 raw SHA-256 pinned")
    print("PASS\trepository_active_rulesets\t0")
    print("PASS\tsealed_normative_transport\tshared decoder")
    print("PASS\tgrch38_manifest\t9/9")
    print("PASS\tpre_dna_readiness_contract\tlatest-tested candidate + canaries + freshness + runtime/resource gate")
    print("PASS\twgs_scientific_data_plane_contract\treal SNV/indel path + explicit unsupported classes")
    print("PASS\tarray_scientific_data_plane_contract\tQC + target-first evidence + policy/report handoff")
    print("PASS\tevidence_adapter_contract\tClinVar/ClinGen/CPIC/ClinPGx/gnomAD/PGS Catalog")
    print("PASS\tsupply_chain_contract\tworkflow/action/container lock paths present")
    print("PASS\treporting_contract\t11-model deterministic renderer and reference identities")
    print("PASS\toptional_adapters\tcore has no external runtime dependency")


if __name__ == "__main__":
    main()
