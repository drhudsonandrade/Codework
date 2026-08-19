#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from scripts.sealed_ruleset import SealedRulesetError, verify_transport


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


def verify_ruleset_identity() -> tuple[bool, dict, str]:
    """Prove the normative identity instead of asserting it.

    The audit used to emit a literal `status: VIGENTE` block, so it kept attesting to a
    superseded ruleset with nothing able to notice. Here the identity is decoded from the
    sealed transport and checked byte-for-byte against the declared canonical artifact; if
    that fails, the audit reports RULESET NÃO DISPONÍVEL/CONFLITANTE and blocks.
    """
    try:
        evidence = verify_transport(ROOT / "normative" / "sealed")
    except (OSError, UnicodeError, ValueError, SealedRulesetError) as exc:
        return False, {"status": "NÃO DISPONÍVEL", "reason": f"{type(exc).__name__}: {exc}"}, (
            f"RULESET NÃO DISPONÍVEL/CONFLITANTE: {type(exc).__name__}: {exc}"
        )

    expected = {
        "status": normative.STATUS,
        "version": normative.VERSION,
        "effective_date": normative.EFFECTIVE_DATE,
        "canonical_filename": normative.CANONICAL_FILENAME,
        "normative_identifier": normative.NORMATIVE_IDENTIFIER,
        "raw_sha256": normative.RAW_SHA256,
        "section_count": normative.SECTION_COUNT,
    }
    mismatches = {k: {"expected": v, "observed": evidence.get(k)} for k, v in expected.items() if evidence.get(k) != v}

    manifest_path = ROOT / normative.SHA_MANIFEST_RELATIVE
    if not manifest_path.is_file():
        mismatches["external_sha_manifest"] = {"expected": normative.SHA_MANIFEST_RELATIVE, "observed": None}
    elif manifest_path.read_text(encoding="ascii").split() != [normative.RAW_SHA256, normative.CANONICAL_FILENAME]:
        mismatches["external_sha_manifest"] = {"expected": "matching digest and filename", "observed": "mismatch"}

    # REGRA DE UNICIDADE: exactly one source may be marked VIGENTE.
    active = sorted(p.name for p in (ROOT / "manifests").glob("RULESET_V*.sha256"))
    if active != [manifest_path.name]:
        mismatches["unique_active_manifest"] = {"expected": [manifest_path.name], "observed": active}

    ok = not mismatches
    block = {
        "status": evidence["status"] if ok else "NÃO DISPONÍVEL",
        "version": evidence["version"],
        "effective_date": evidence["effective_date"],
        "normative_identifier": evidence["normative_identifier"],
        "canonical_filename": evidence["canonical_filename"],
        "sha256": evidence["raw_sha256"],
        "section_count": evidence["section_count"],
        "verification": "sealed transport decoded and hashed in this run",
    }
    detail = json.dumps(
        {"verified": ok, "identity": block, "mismatches": mismatches}, ensure_ascii=False, indent=2, sort_keys=True
    )
    return ok, block, detail


#: Which checks constitute each plane. Naming them here — rather than filtering the check
#: list inline — is what makes a missing check detectable. The previous form,
#: `all(c["state"] == "PASS" for c in checks if c["id"] in {...})`, is vacuously True when
#: the filter matches nothing, so renaming a check id turned its FAIL into a plane PASS,
#: and an empty blocking set made the whole audit pass. This is the top-level aggregator
#: that reports the project VERIFICADO, so it is the last place a fail-open belongs.
PLANE_CHECKS = {
    "policy_control": ("RULESET_GATE", "REPOSITORY_CONTRACT", "SUPPLY_CHAIN_LOCK"),
    "scientific_data": ("SCIENTIFIC_DATA_PLANE_ARRAY",),
    "evidence": ("EVIDENCE_ANNOTATION_PLANE",),
}

#: The audit plane covers every blocking check, so it is defined by the blocking flag
#: rather than a list — but it must still cover at least this many.
MIN_BLOCKING_CHECKS = 5


def _aggregate_planes(checks: list[dict]) -> dict[str, str]:
    """Reduce the check list to plane verdicts, failing closed on a missing check."""
    by_id = {c["id"]: c for c in checks}
    planes: dict[str, str] = {}
    for plane, required in PLANE_CHECKS.items():
        missing = [name for name in required if name not in by_id]
        if missing:
            planes[plane] = "BLOCKED"
            continue
        planes[plane] = "PASS" if all(by_id[name]["state"] == "PASS" for name in required) else "BLOCKED"

    blocking = [c for c in checks if c["blocking"]]
    if len(blocking) < MIN_BLOCKING_CHECKS:
        # An audit that ran almost nothing must not report the strongest verdict.
        planes["audit"] = "BLOCKED"
    else:
        planes["audit"] = "PASS" if all(c["state"] == "PASS" for c in blocking) else "BLOCKED"
    return planes


def audit(*, allow_template_sealed_only: bool = False) -> dict:
    checks: list[dict] = []

    ruleset_ok, ruleset_block, ruleset_evidence = verify_ruleset_identity()
    checks.append(check("RULESET_GATE", ruleset_ok, ruleset_evidence))

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
    # A passing manifest cross-check proves the two JSON manifests agree, not that any
    # template was read. Carry the count so the audit cannot be read as template assurance.
    templates_hashed = 0
    try:
        templates_hashed = int(json.loads(out).get("templates_hashed", 0))
    except (json.JSONDecodeError, TypeError, ValueError):
        templates_hashed = 0
    checks.append(
        check(
            "TEMPLATE_IDENTITY_CONTRACT",
            manifest_verified,
            out,
            status_if_ok="VERIFICADO" if templates_hashed else "INFERIDO",
        )
    )
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

    planes = _aggregate_planes(checks)
    blocking_failures = [c["id"] for c in checks if c["blocking"] and c["state"] != "PASS"]
    return {
        "schema": "genoma-v0.8-four-plane-audit-v1",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ruleset": ruleset_block,
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
