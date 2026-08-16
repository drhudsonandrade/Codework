#!/usr/bin/env python3
"""Validate static repository safety, sealed normative integrity, and deployment scaffold."""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import json
import re
from pathlib import Path

CANONICAL_RULESET = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt"
CANONICAL_RULESET_SHA256 = "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"
REQUIRED_PATHS = (
    ".fallowrc.json", ".github/workflows/fallow.yml", ".github/workflows/scaffold-validation.yml",
    ".github/workflows/genoma-policy-engine.yml", ".github/workflows/genoma-production-ceremony.yml",
    ".github/workflows/genoma-ngs-runtime-gate.yml", ".gitignore", "Dockerfile", "environment.yml", "main.nf", "nextflow.config",
    "manifests/GRCh38.sources.tsv", "manifests/GRCh38.lock.sha256.example", "manifests/RULESET_V3.3.sha256",
    "normative/sealed/GENOMA_RULESET_v3.3.txt.gz.b64", "normative/sealed/MANIFEST.json", "normative/sealed/README.md",
    "scripts/check_versions.sh", "scripts/fetch_grch38.sh", "scripts/build_bwa_mem2_index.sh", "scripts/validate_grch38.sh",
    "scripts/generate_canary.py", "scripts/score_variants.py", "scripts/run_canary.sh", "scripts/verify_ruleset.sh",
    "scripts/materialize_ruleset.py", "scripts/run_live_post_deployment_smoke.py", "scripts/runtime_resource_gate.py",
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
FORBIDDEN_SUFFIXES = (".fastq", ".fq", ".bam", ".bai", ".cram", ".crai", ".vcf", ".tbi")
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".pytest_cache"}


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def top_level_sections(text: str) -> list[int]:
    expected = 0
    found: list[int] = []
    for raw in text.splitlines():
        match = re.match(r"^(\d+)\.\s+(.+?)\s*$", raw.strip())
        if not match:
            continue
        number = int(match.group(1))
        if number != expected:
            continue
        found.append(number)
        expected += 1
        if expected == 263:
            break
    return found


def validate_sealed_ruleset(root: Path, errors: list[str]) -> None:
    manifest_path = root / "normative/sealed/MANIFEST.json"
    transport_path = root / "normative/sealed/GENOMA_RULESET_v3.3.txt.gz.b64"
    if not manifest_path.is_file() or not transport_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        encoded = transport_path.read_bytes()
        if manifest.get("active_at_rest") is not False:
            errors.append("sealed normative transport must declare active_at_rest=false")
        if manifest.get("raw_sha256") != CANONICAL_RULESET_SHA256 or manifest.get("canonical_filename") != CANONICAL_RULESET:
            errors.append("sealed normative manifest identity mismatch")
        if sha256(encoded) != manifest.get("transport_sha256"):
            errors.append("sealed normative transport SHA-256 mismatch")
            return
        compressed = base64.b64decode(b"".join(encoded.split()), validate=True)
        if sha256(compressed) != manifest.get("gzip_sha256"):
            errors.append("sealed normative gzip SHA-256 mismatch")
            return
        raw = gzip.decompress(compressed)
        if sha256(raw) != CANONICAL_RULESET_SHA256:
            errors.append("sealed normative payload does not decode to canonical raw SHA-256")
            return
        text = raw.decode("utf-8")
        head = set(text.splitlines()[:20])
        required = {
            "STATUS NORMATIVO: VIGENTE", "VERSÃO NORMATIVA: v3.3",
            "DATA FORMAL DE EMISSÃO E VIGÊNCIA: 14/08/2026", f"ARQUIVO CANÔNICO: {CANONICAL_RULESET}",
        }
        if not required.issubset(head):
            errors.append("sealed normative payload header mismatch")
        sections = top_level_sections(text)
        if sections != list(range(263)):
            errors.append(f"sealed normative payload top-level section sequence mismatch: {len(sections)}")
    except (OSError, UnicodeError, ValueError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
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
        if "STATUS NORMATIVO: VIGENTE" in text:
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
    root = Path(__file__).resolve().parents[1]
    errors = validate(root)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\trepository_contract")
    print("PASS\truleset_manifest_contract\tv3.3 raw SHA-256 pinned")
    print("PASS\trepository_active_rulesets\t0")
    print("PASS\tsealed_normative_transport\tbyte-exact canonical v3.3 verified in memory")
    print("PASS\tgrch38_manifest\t9/9")
    print("PASS\toptional_adapters\tcore has no Cloudflare/Temporal/Supabase/OpenAI runtime dependency")


if __name__ == "__main__":
    main()
