#!/usr/bin/env python3
"""Validate the repository's static safety and deployment scaffold contract."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


REQUIRED_PATHS = (
    ".fallowrc.json",
    ".github/workflows/fallow.yml",
    ".github/workflows/scaffold-validation.yml",
    ".gitignore",
    "Dockerfile",
    "environment.yml",
    "main.nf",
    "nextflow.config",
    "manifests/GRCh38.sources.tsv",
    "manifests/GRCh38.lock.sha256.example",
    "manifests/RULESET_V3.3.sha256",
    "scripts/check_versions.sh",
    "scripts/fetch_grch38.sh",
    "scripts/build_bwa_mem2_index.sh",
    "scripts/validate_grch38.sh",
    "scripts/generate_canary.py",
    "scripts/score_variants.py",
    "scripts/run_canary.sh",
    "scripts/verify_ruleset.sh",
    "mcp/package.json",
    "mcp/package-lock.json",
    "mcp/tsconfig.json",
    "mcp/src/server.ts",
    "deploy/docker-compose.yml",
    "docs/FALLOW_SECURITY_REVIEW.md",
    "docs/GITHUB_MOBILE_IMPORT.md",
    "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md",
    "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md",
    "docs/PR_BODY.md",
)

EXPECTED_ARTIFACTS = {
    "Homo_sapiens_assembly38.fasta",
    "Homo_sapiens_assembly38.fasta.fai",
    "Homo_sapiens_assembly38.dict",
    "gencode.v50.primary_assembly.annotation.gtf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz.tbi",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz.tbi",
    "hg38-blacklist.v2.bed.gz",
}

FORBIDDEN_SUFFIXES = (".fastq", ".fq", ".bam", ".bai", ".cram", ".crai", ".vcf", ".tbi")
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__"}


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            errors.append(f"missing required path: {relative}")

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
    if package.is_file():
        parsed = json.loads(package.read_text(encoding="utf-8"))
        if parsed.get("devDependencies", {}).get("fallow") != "3.16.0":
            errors.append("mcp/package.json must pin fallow 3.16.0 exactly")

    ruleset_manifest = root / "manifests/RULESET_V3.3.sha256"
    if ruleset_manifest.is_file():
        fields = ruleset_manifest.read_text(encoding="ascii").strip().split()
        if fields != [
            "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a",
            "REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt",
        ]:
            errors.append("ruleset external manifest does not match the verified v3.3 artifact")

    fallow_workflow = root / ".github/workflows/fallow.yml"
    if fallow_workflow.is_file():
        text = fallow_workflow.read_text(encoding="utf-8")
        if "fallow-rs/fallow@v3.16.0" not in text or "version: 3.16.0" not in text:
            errors.append("Fallow workflow must pin wrapper and CLI to 3.16.0")

    runbook = root / "docs/MAGALU_PRIVATE_MCP_SETUP.md"
    if runbook.is_file():
        runbook_text = runbook.read_text(encoding="utf-8")
        if "PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE" not in runbook_text:
            errors.append("runbook must preserve the pending post-deployment status")
        if "--entrypoint /bin/bash" in runbook_text:
            errors.append("runbook must not bypass the micromamba container entrypoint")

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
                json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                errors.append(f"invalid JSON: {relative}: {error}")

    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\trepository_contract")
    print("PASS\tgrch38_manifest\t9/9")
    print("PASS\tstatus\tPRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE")


if __name__ == "__main__":
    main()
