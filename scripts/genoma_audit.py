#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULESET_SHA = "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    return p.returncode, p.stdout[-12000:]


def check(name: str, ok: bool, evidence: str, *, blocking: bool = True, status_if_ok: str = "VERIFICADO") -> dict:
    return {
        "id": name,
        "operational_status": status_if_ok if ok else "NÃO DISPONÍVEL",
        "state": "PASS" if ok else "BLOCKED",
        "blocking": blocking,
        "evidence": evidence,
    }


def audit(*, allow_template_sealed_only: bool = False) -> dict:
    checks: list[dict] = []

    rc, out = run(["python3", "scripts/validate_repo.py"])
    checks.append(check("REPOSITORY_CONTRACT", rc == 0, out))

    rc, out = run(["python3", "scripts/verify_supply_chain_lock.py"])
    checks.append(check("SUPPLY_CHAIN_LOCK", rc == 0, out))

    cmd = ["python3", "scripts/verify_template_store.py"]
    if allow_template_sealed_only:
        cmd.append("--allow-sealed-only")
    rc, out = run(cmd)
    template_binary_verified = rc == 0 and '"binary_materialization": "VERIFICADO"' in out
    manifest_verified = rc == 0 and '"manifest_identity": "VERIFICADO"' in out
    checks.append(check("TEMPLATE_IDENTITY_CONTRACT", manifest_verified, out))
    checks.append(check("TEMPLATE_BINARY_SOURCE_STORE", template_binary_verified, out, blocking=not allow_template_sealed_only))

    required_array = [
        ROOT / "workflows/array.nf",
        ROOT / "array_pipeline/qc.py",
        ROOT / "array_pipeline/annotation.py",
        ROOT / "array_pipeline/targets.py",
        ROOT / "config/partial_genome_annotation_targets.json",
        ROOT / ".github/workflows/genoma-snp-array.yml",
    ]
    checks.append(check("SCIENTIFIC_DATA_PLANE_ARRAY", all(p.is_file() for p in required_array), ", ".join(str(p.relative_to(ROOT)) for p in required_array)))

    adapters = (ROOT / "evidence_adapters/__init__.py").read_text(encoding="utf-8")
    evidence_sources = ["clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"]
    checks.append(check("EVIDENCE_ANNOTATION_PLANE", all(f'"{x}"' in adapters for x in evidence_sources), "official/primary adapter registry: " + ", ".join(evidence_sources)))

    prebuilt = ROOT / "scripts/verify_prebuilt_bwa_mem2_bundle.py"
    strategy = ROOT / "docs/GRCH38_COMPUTE_STRATEGY.md"
    checks.append(check("GRCH38_NO_PERMANENT_HIGHMEM_STRATEGY", prebuilt.is_file() and strategy.is_file(), "prebuilt checksum-locked index verifier + explicit ephemeral/self-hosted fallback", blocking=False))

    personal_patterns = ("dados dna", "dna_harmonizado", "myheritage_raw", "genera_raw")
    tracked_like = []
    for p in ROOT.rglob("*"):
        if p.is_file():
            low = str(p.relative_to(ROOT)).lower().replace("_", " ").replace("-", " ")
            if any(x in low for x in personal_patterns):
                tracked_like.append(str(p.relative_to(ROOT)))
    checks.append(check("NO_PERSONAL_GENOTYPE_FIXTURES", not tracked_like, json.dumps(tracked_like)))

    planes = {
        "policy_control": "PASS" if all(c["state"] == "PASS" for c in checks if c["id"] in {"REPOSITORY_CONTRACT", "SUPPLY_CHAIN_LOCK"}) else "BLOCKED",
        "scientific_data": "PASS" if next(c for c in checks if c["id"] == "SCIENTIFIC_DATA_PLANE_ARRAY")["state"] == "PASS" else "BLOCKED",
        "evidence": "PASS" if next(c for c in checks if c["id"] == "EVIDENCE_ANNOTATION_PLANE")["state"] == "PASS" else "BLOCKED",
        "audit": "PASS" if all(c["state"] == "PASS" for c in checks if c["blocking"]) else "BLOCKED",
    }
    blocking_failures = [c["id"] for c in checks if c["blocking"] and c["state"] != "PASS"]
    return {
        "schema": "genoma-v0.8-four-plane-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ruleset": {"status": "VIGENTE", "version": "v3.3", "effective_date": "14/08/2026", "sha256": RULESET_SHA},
        "operational_status": "VERIFICADO" if not blocking_failures else "NÃO DISPONÍVEL",
        "four_planes": planes,
        "checks": checks,
        "blocking_failures": blocking_failures,
        "post_deployment_status": "PENDENTE",
        "post_deployment_note": "This audit never grants POST-DEPLOYMENT PASS. Only the independent live Production Witness on the exact merged main SHA may do so.",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="audit.json")
    p.add_argument("--allow-template-sealed-only", action="store_true")
    args = p.parse_args()
    payload = audit(allow_template_sealed_only=args.allow_template_sealed_only)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["operational_status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
