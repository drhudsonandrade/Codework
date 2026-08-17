#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sealed_ruleset import SealedRulesetError, verify_transport
from scripts.source_integrity_audit import audit as source_audit

SEALED_DIR = ROOT / "normative" / "sealed" / "v3.4"


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def evaluate(runtime: dict[str, Any], freshness: dict[str, Any], consent: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    evidence: dict[str, Any] = {}

    try:
        evidence["ruleset_transport"] = verify_transport(SEALED_DIR)
    except (OSError, ValueError, UnicodeError, SealedRulesetError) as exc:
        blockers.append(f"RULESET_TRANSPORT:{type(exc).__name__}:{exc}")

    source = source_audit(ROOT)
    evidence["source_integrity"] = {
        "operational_status": source.get("operational_status"),
        "blocking_failures": source.get("blocking_failures", []),
        "counts": source.get("counts", {}),
    }
    if source.get("operational_status") != "VERIFICADO":
        blockers.append("SOURCE_INTEGRITY_AUDIT")

    supply = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_supply_chain_lock.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    evidence["supply_chain"] = {
        "returncode": supply.returncode,
        "stdout": supply.stdout[-8000:],
        "stderr": supply.stderr[-8000:],
    }
    if supply.returncode != 0:
        blockers.append("SUPPLY_CHAIN_LOCK")

    if runtime.get("status") != "VERIFICADO" or runtime.get("ready_for_operation") is not True:
        blockers.append("RUNTIME_RESOURCE_GATE")
    if freshness.get("ready_for_dna") is not True:
        blockers.append("FRESHNESS_GATE")
    if consent.get("status") != "VERIFICADO" or consent.get("ready_for_first_dna_read") is not True:
        blockers.append("CONSENT_PROVENANCE_GATE")

    return {
        "schema": "genoma-pre-analysis-master-gate-v1",
        "gate": "PRE_ANALYSIS_MASTER_GATE",
        "status": "VERIFICADO" if not blockers else "NÃO DISPONÍVEL",
        "ready_for_first_dna_read": not blockers,
        "blockers": blockers,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-verified", required=True)
    parser.add_argument("--freshness", required=True)
    parser.add_argument("--consent", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = evaluate(_load(args.runtime_verified), _load(args.freshness), _load(args.consent))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready_for_first_dna_read"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
