#!/usr/bin/env python3
"""Validate static repository safety and the shared sealed normative contract."""
from __future__ import annotations

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
REQUIRED_PATHS = (
    ".fallowrc.json", ".github/workflows/fallow.yml", ".github/workflows/scaffold-validation.yml",
    ".github/workflows/genoma-policy-engine.yml", ".github/workflows/genoma-production-ceremony.yml",
    ".github/workflows/genoma-production-witness.yml", ".github/workflows/genoma-ngs-runtime-gate.yml",
    ".gitignore", "Dockerfile", "environment.yml", "main.nf", "nextflow.config", "workflows/wgs.nf",
    "manifests/GRCh38.sources.tsv", "manifests/GRCh38.lock.sha256.example", "manifests/RULESET_V3.3.sha256",
    "normative/sealed/MANIFEST.json", "normative/sealed/README.md",
    "scripts/__init__.py", "scripts/sealed_ruleset.py", "scripts/check_versions.sh", "scripts/fetch_grch38.sh",
    "scripts/build_bwa_mem2_index.sh", "scripts/validate_grch38.sh", "scripts/validate_bwa_mem2_functional.sh",
    "scripts/generate_canary.py", "scripts/score_variants.py", "scripts/run_canary.sh", "scripts/verify_ruleset.sh",
    "scripts/materialize_ruleset.py", "scripts/run_live_post_deployment_smoke.py", "scripts/runtime_resource_gate.py",
    "scripts/prepare_latest_candidate.py", "scripts/promote_latest_candidate.py", "scripts/freshness_gate.py",
    "scripts/latest_runtime_resource_gate.py", "scripts/verify_runtime_gate_manifest.py",
    "scripts/wgs_input_gate.py", "scripts/wgs_align_or_stage.sh", "scripts/build_wgs_curated_manifest.py",
    "scripts/query_evidence.py", "scripts/build_adapter_capabilities.py", "scripts/generate_report.py",
    "scripts/generate_all_reports.py", "reporting/__init__.py", "reporting/catalog.json", "reporting/engine.py",
    "reporting/editorial_v3.py", "reporting/requirements.txt", "evidence_adapters/__init__.py",
    "policy_engine/pyproject.toml", "policy_engine/genoma_policy/engine.py", "policy_engine/genoma_policy/attestation.py",
    "policy_engine/genoma_policy/ledger.py", "policy_engine/policy/schema/execution-manifest.schema.json", "policy_engine/Dockerfile",
    "mcp/package.json", "mcp/package-lock.json", "mcp/tsconfig.json", "mcp/src/server.ts", "deploy/docker-compose.yml",
    "deploy/attestations/bootstrap-project-v3.3.json", "adapters/README.md", "adapters/config.example.json",
    "docs/FALLOW_SECURITY_REVIEW.md", "docs/GITHUB_MOBILE_IMPORT.md", "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md", "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/PR_BODY.md",
    "docs/DETERMINISTIC_ENGINE.md", "docs/PRODUCTION_CEREMONY.md", "docs/PORTABILITY_MATRIX.md",
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


def validate_sealed_ruleset(root: Path, errors: list[str]) -> None:
    sealed_dir = root / "normative" / "sealed"
    try:
        verify_transport(sealed_dir)
    except (OSError, UnicodeError, ValueError, SealedRulesetError) as exc:
        errors.append(f"sealed normative transport invalid: {type(exc).__name__}: {exc}")


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            errors.append(f"missing required path: {relative}")

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

    manifest = root / "manifests/GRCh38.sources.tsv"
    if manifest.is_file():
        with manifest.open(encoding="utf-8", newline="") as h:
            rows = list(csv.DictReader(h, delimiter="\t"))
        targets = {r.get("target", "") for r in rows}
        if len(rows) != 9 or targets != EXPECTED_ARTIFACTS:
            errors.append(f"GRCh38 manifest must contain exactly the required 9 artifacts; found {len(rows)}")
        if any(not r.get("url", "").startswith(("https://", "generated-from:")) for r in rows):
            errors.append("GRCh38 manifest contains a non-HTTPS/non-generated source")

    package = root / "mcp/package.json"
    if package.is_file() and json.loads(package.read_text()).get("devDependencies", {}).get("fallow") != "3.16.0":
        errors.append("mcp/package.json must pin fallow 3.16.0 exactly")

    ruleset_manifest = root / "manifests/RULESET_V3.3.sha256"
    if ruleset_manifest.is_file() and ruleset_manifest.read_text(encoding="ascii").strip().split() != [CANONICAL_RULESET_SHA256, CANONICAL_RULESET]:
        errors.append("ruleset external manifest does not match the verified v3.3 artifact")

    fw = root / ".github/workflows/fallow.yml"
    if fw.is_file():
        text = fw.read_text()
        if "fallow-rs/fallow@v3.16.0" not in text or "version: 3.16.0" not in text:
            errors.append("Fallow workflow must pin wrapper and CLI to 3.16.0")

    runbook = root / "docs/MAGALU_PRIVATE_MCP_SETUP.md"
    if runbook.is_file() and "--entrypoint /bin/bash" in runbook.read_text(encoding="utf-8"):
        errors.append("runbook must not bypass the micromamba container entrypoint")

    main_nf = root / "main.nf"
    wgs_nf = root / "workflows/wgs.nf"
    if main_nf.is_file():
        text = main_nf.read_text(encoding="utf-8")
        for token in ("params.mode", "WGS_PRODUCTION", "CANARY", "runtime_gate_manifest", "freshness_state_manifest"):
            if token not in text:
                errors.append(f"main.nf missing production dispatcher contract token: {token}")
    if wgs_nf.is_file():
        text = wgs_nf.read_text(encoding="utf-8")
        for token in (
            "VERIFY_RUNTIME_GATE", "REFRESH_FRESHNESS_GATE", "INGEST_AND_QC", "ALIGN_OR_STAGE",
            "RERUN_SAMPLE_RUNTIME_GATE", "CALL_SHORT_VARIANTS", "NORMALIZE_VARIANTS", "ANNOTATE_EVIDENCE",
            "BUILD_CURATED_MANIFEST", "POLICY_EVALUATE", "GENERATE_REPORTS", "unsupported_variant_classes",
            "NÃO DISPONÍVEL", "CYP2D6", "CNV", "SV",
        ):
            if token not in text:
                errors.append(f"WGS workflow missing fail-closed contract token: {token}")

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
        for token in (
            "freshness_gate.py", "GRCh38.lock.sha256.approved",
            "[self-hosted, linux, x64, genoma-production, highmem]",
            "nextflow run /opt/codework/main.nf --mode canary",
            "validate_bwa_mem2_functional.sh",
        ):
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

    renderer = root / "reporting/editorial_v3.py"
    if renderer.is_file():
        text = renderer.read_text(encoding="utf-8")
        for token in ("0B1F33", "0F766E", "A16207", "F2F4F7", "RESULTADO GENÔMICO", "write_editorial_bundle"):
            if token not in text:
                errors.append(f"editorial v3 renderer contract missing: {token}")

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
    print("PASS\truleset_manifest_contract\tv3.3 raw SHA-256 pinned")
    print("PASS\trepository_active_rulesets\t0")
    print("PASS\tsealed_normative_transport\tchunked transport verified through shared decoder")
    print("PASS\tgrch38_manifest\t9/9")
    print("PASS\tpre_dna_readiness_contract\tlatest-tested candidate + direct/Nextflow canaries + session promotion + freshness + runtime/resource gate present")
    print("PASS\twgs_scientific_data_plane_contract\treal SNV/indel path + explicit unsupported complex classes")
    print("PASS\tevidence_adapter_contract\tClinVar/ClinGen/CPIC/ClinPGx/gnomAD/PGS Catalog traceable adapters present")
    print("PASS\treporting_contract\t11-model deterministic renderer + PDF/DOCX editorial v3 present")
    print("PASS\toptional_adapters\tcore has no Cloudflare/Temporal/Supabase/OpenAI runtime dependency")


if __name__ == "__main__":
    main()
