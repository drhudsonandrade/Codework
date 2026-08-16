#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

REQUIRED_PUBLICATION = ("consent_verified", "qc_verified", "evidence_verified", "placeholders_resolved")
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")


def assemble_release(curated: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(curated)
    result["policy_evaluation"] = copy.deepcopy(policy)
    blockers: list[str] = []

    publication = result.get("publication_gate") if isinstance(result.get("publication_gate"), dict) else {}
    for key in REQUIRED_PUBLICATION:
        if publication.get(key) is not True:
            blockers.append(key)

    if policy.get("ready_for_requested_operation") is not True:
        blockers.append("policy_evaluation")

    planes = policy.get("planes") if isinstance(policy.get("planes"), dict) else {}
    for name in REQUIRED_PLANES:
        plane = planes.get(name) if isinstance(planes.get(name), dict) else {}
        if plane.get("state") != "PASS":
            blockers.append(f"plane:{name}")

    gates = policy.get("gates") if isinstance(policy.get("gates"), list) else []
    final_audit = next((g for g in gates if isinstance(g, dict) and g.get("gate") == "FINAL_AUDIT_GATE"), None)
    if not isinstance(final_audit, dict) or final_audit.get("state") != "PASS":
        blockers.append("FINAL_AUDIT_GATE")

    publication = dict(publication)
    publication["passed"] = not blockers
    result["publication_gate"] = publication
    result["report_release_status"] = "VERIFICADO" if not blockers else "NÃO DISPONÍVEL"
    result["report_release_blockers"] = blockers
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    curated = json.loads(Path(args.curated).read_text(encoding="utf-8"))
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    result = assemble_release(curated, policy)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "report_release_status": result["report_release_status"], "blockers": result["report_release_blockers"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
