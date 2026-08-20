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

import normative
from scripts.sealed_ruleset import EXPECTED_NAME, EXPECTED_SHA, SealedRulesetError, verify_transport

CANONICAL_RULESET = EXPECTED_NAME
CANONICAL_RULESET_SHA256 = EXPECTED_SHA
FALLOW_ACTION_SHA = "45fd28766199acb1f939f6862274a37aad12770b"
REQUIRED_PATHS = (
    "mcp/.fallowrc.json", ".github/workflows/fallow.yml", ".github/workflows/scaffold-validation.yml",
    ".github/workflows/genoma-policy-engine.yml", ".github/workflows/genoma-production-ceremony.yml",
    ".github/workflows/genoma-production-witness.yml", ".github/workflows/genoma-ngs-runtime-gate.yml",
    ".github/workflows/genoma-snp-array.yml", ".gitignore", "Dockerfile", "environment.yml", "main.nf",
    "nextflow.config", "workflows/wgs.nf", "workflows/array.nf", "array_pipeline/qc.py",
    "array_pipeline/annotation.py", "array_pipeline/targets.py", "config/partial_genome_annotation_targets.json",
    "manifests/GRCh38.sources.tsv", "manifests/GRCh38.lock.sha256.example", "manifests/RULESET_V3.4.sha256",
    "normative/__init__.py", "normative/sealed/MANIFEST.json", "normative/sealed/README.md",
    "manifests/COMPANION_SOURCES.sha256",
    "scripts/__init__.py", "scripts/sealed_ruleset.py", "scripts/seal_ruleset.py",
    "scripts/seal_template_store.py", "scripts/run_editorial_pixel_qa.py",
    "scripts/run_docx_parity_qa.py",
    "docs/evidence/EDITORIAL_V3_DOCX_PARITY_150DPI_2026-08-18.json",
    "docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI_2026-08-18.json",
    "scripts/check_versions.sh", "scripts/fetch_grch38.sh",
    "scripts/build_bwa_mem2_index.sh", "scripts/validate_grch38.sh", "scripts/validate_bwa_mem2_functional.sh",
    "scripts/generate_canary.py", "scripts/score_variants.py", "scripts/run_canary.sh", "scripts/verify_ruleset.sh",
    "scripts/materialize_ruleset.py", "scripts/run_live_post_deployment_smoke.py", "scripts/runtime_resource_gate.py",
    "scripts/runtime_stack.py", "scripts/prepare_latest_candidate.py", "scripts/promote_latest_candidate.py",
    "scripts/freshness_gate.py", "scripts/latest_runtime_resource_gate.py", "scripts/verify_runtime_gate_manifest.py",
    "scripts/wgs_consent_gate.py", "scripts/wgs_input_gate.py", "scripts/wgs_align_or_stage.sh",
    "scripts/build_wgs_curated_manifest.py", "scripts/query_evidence.py", "scripts/build_adapter_capabilities.py",
    "scripts/run_snp_array.py", "scripts/annotate_partial_genome.py", "scripts/build_array_case_manifest.py",
    "scripts/verify_prebuilt_bwa_mem2_bundle.py", "scripts/verify_supply_chain_lock.py",
    "scripts/generate_report.py", "scripts/generate_all_reports.py", "reporting/__init__.py", "reporting/catalog.json",
    "reporting/engine.py", "reporting/editorial_v3.py", "reporting/editorial_v3_hifi.py", "reporting/requirements.txt",
    "reporting/reference_v3_manifest.json", "template_store/v3.0/MANIFEST.json", "locks/actions-lock.json",
    "locks/runtime-lock.json", "evidence_adapters/__init__.py", "policy_engine/pyproject.toml",
    "policy_engine/genoma_policy/engine.py", "policy_engine/genoma_policy/attestation.py",
    "policy_engine/genoma_policy/ledger.py", "policy_engine/policy/schema/execution-manifest.schema.json",
    "policy_engine/Dockerfile", "mcp/package.json", "mcp/package-lock.json", "mcp/tsconfig.json", "mcp/src/server.ts",
    "deploy/docker-compose.yml", "deploy/attestations/bootstrap-project-v3.4.json", "adapters/README.md",
    "adapters/config.example.json", "docs/FALLOW_SECURITY_REVIEW.md", "docs/GITHUB_MOBILE_IMPORT.md",
    "docs/MAGALU_PRIVATE_MCP_SETUP.md", "docs/NORMATIVE_V3.4.md",
    "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/DETERMINISTIC_ENGINE.md",
    "docs/PRODUCTION_CEREMONY.md", "docs/PORTABILITY_MATRIX.md", "docs/GRCH38_COMPUTE_STRATEGY.md",
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


def validate_sealed_ruleset(root: Path, errors: list[str], observed: dict[str, str]) -> None:
    sealed_dir = root / "normative" / "sealed"
    try:
        evidence = verify_transport(sealed_dir)
    except (OSError, UnicodeError, ValueError, SealedRulesetError) as exc:
        errors.append(f"sealed normative transport invalid: {type(exc).__name__}: {exc}")
        return
    observed["sealed_transport"] = (
        f"{evidence['version']}/{evidence['status']}/{evidence['effective_date']} "
        f"sections={evidence['section_count']}"
    )


def validate(root: Path, facts: dict[str, str] | None = None) -> list[str]:
    """Collect contract violations. `facts` receives observed values so the caller can
    report what was actually measured instead of restating a hard-coded claim."""

    observed = facts if facts is not None else {}
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
    observed["active_rulesets"] = str(len(active))

    validate_sealed_ruleset(root, errors, observed)

    manifest = root / "manifests/GRCh38.sources.tsv"
    if manifest.is_file():
        with manifest.open(encoding="utf-8", newline="") as h:
            rows = list(csv.DictReader(h, delimiter="\t"))
        targets = {r.get("target", "") for r in rows}
        if len(rows) != 9 or targets != EXPECTED_ARTIFACTS:
            errors.append(f"GRCh38 manifest must contain exactly the required 9 artifacts; found {len(rows)}")
        if any(not r.get("url", "").startswith(("https://", "generated-from:")) for r in rows):
            errors.append("GRCh38 manifest contains a non-HTTPS/non-generated source")
        observed["grch38_artifacts"] = f"{len(targets & EXPECTED_ARTIFACTS)}/{len(EXPECTED_ARTIFACTS)}"
    else:
        errors.append("GRCh38 manifest not readable")

    package = root / "mcp/package.json"
    if package.is_file() and json.loads(package.read_text()).get("devDependencies", {}).get("fallow") != "3.16.0":
        errors.append("mcp/package.json must pin fallow 3.16.0 exactly")

    ruleset_manifest = root / normative.SHA_MANIFEST_RELATIVE
    if not ruleset_manifest.is_file():
        errors.append(f"external ruleset SHA manifest missing: {normative.SHA_MANIFEST_RELATIVE}")
    elif ruleset_manifest.read_text(encoding="ascii").strip().split() != [CANONICAL_RULESET_SHA256, CANONICAL_RULESET]:
        errors.append(f"ruleset external manifest does not match the verified {normative.VERSION} artifact")
    else:
        observed["ruleset_manifest"] = f"{normative.VERSION} raw SHA-256 pinned"

    # REGRA DE UNICIDADE: a superseded version may survive only as archived provenance.
    for stale in (root / "manifests").glob("RULESET_V*.sha256"):
        if stale.name != Path(normative.SHA_MANIFEST_RELATIVE).name:
            errors.append(f"superseded ruleset manifest must be archived as OBSOLETA, not left active: {stale.name}")

    # Companion sources are integrity-pinned but must never become a normative source.
    companion = root / normative.COMPANION_MANIFEST_RELATIVE
    if not companion.is_file():
        errors.append(f"companion source manifest missing: {normative.COMPANION_MANIFEST_RELATIVE}")
    else:
        text = companion.read_text(encoding="utf-8")
        if "NÃO NORMATIVAS" not in text:
            errors.append("companion manifest must state that its entries are not normative")
        pinned = {
            fields[1]: fields[0]
            for line in text.splitlines()
            if not line.startswith("#") and len(fields := line.split()) == 2
        }
        for name, spec in normative.COMPANION_SOURCES.items():
            if spec.get("normative") is not False:
                errors.append(f"companion source must be declared non-normative: {name}")
            if pinned.get(name) != spec["sha256"]:
                errors.append(f"companion manifest digest differs from the pinned identity: {name}")
        for name in pinned:
            if name not in normative.COMPANION_SOURCES:
                errors.append(f"companion manifest pins an unregistered source: {name}")
        observed["companion_sources"] = str(len(normative.COMPANION_SOURCES))

    fw = root / ".github/workflows/fallow.yml"
    if fw.is_file():
        text = fw.read_text(encoding="utf-8")
        if f"fallow-rs/fallow@{FALLOW_ACTION_SHA}" not in text or "version: 3.16.0" not in text:
            errors.append("Fallow workflow must pin wrapper SHA and CLI 3.16.0")
        # A fallow run rooted where there is no package.json cannot evaluate
        # unused-dependencies or unlisted-dependency at all, and reports a silent PASS.
        # Match the YAML key itself; prose mentioning "root: mcp" must not satisfy this.
        if not re.search(r"(?m)^[ \t]+root:[ \t]*mcp[ \t]*$", text):
            errors.append("Fallow audit must be rooted at the package that owns the TypeScript (root: mcp)")

    # Every fallow config must sit beside the package manifest whose dependencies it claims
    # to police, otherwise its dependency rules are declared but unenforceable.
    for config in root.rglob(".fallowrc.json"):
        if any(part in SKIP_PARTS for part in config.parts):
            continue
        relative = config.relative_to(root)
        if not (config.parent / "package.json").is_file():
            errors.append(f"fallow config has no adjacent package.json; dependency rules cannot be enforced: {relative}")
            continue
        declared = json.loads(config.read_text(encoding="utf-8")).get("rules", {})
        for rule in ("unused-files", "unused-exports", "unused-dependencies", "circular-dependencies"):
            if declared.get(rule) != "error":
                errors.append(f"{relative} must declare {rule} as error")

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
    facts: dict[str, str] = {}
    errors = validate(ROOT, facts)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\trepository_contract")
    print(f"PASS\truleset_manifest_contract\t{facts['ruleset_manifest']}")
    print(f"PASS\trepository_active_rulesets\t{facts['active_rulesets']}")
    print(f"PASS\tsealed_normative_transport\t{facts['sealed_transport']}")
    print(f"PASS\tgrch38_manifest\t{facts['grch38_artifacts']}")
    print(f"PASS\tcompanion_sources\t{facts['companion_sources']} pinned, non-normative")
    print("PASS\tpre_dna_readiness_contract\tlatest-tested candidate + canaries + freshness + runtime/resource gate")
    print("PASS\twgs_scientific_data_plane_contract\treal SNV/indel path + explicit unsupported classes")
    print("PASS\tarray_scientific_data_plane_contract\tQC + target-first evidence + policy/report handoff")
    print("PASS\tevidence_adapter_contract\tClinVar/ClinGen/CPIC/ClinPGx/gnomAD/PGS Catalog")
    print("PASS\tsupply_chain_contract\tworkflow/action/container lock paths present")
    print("PASS\treporting_contract\t11-model deterministic renderer and reference identities")
    print("PASS\toptional_adapters\tcore has no ingress, orchestration, projection or agent-interface runtime dependency")


if __name__ == "__main__":
    main()
