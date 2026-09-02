#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.policy_control import (
    PolicyEvaluationVerificationError,
    verify_policy_evaluation,
)

REQUIRED_PUBLICATION = (
    "consent_verified",
    "consent_scope_verified",
    "qc_verified",
    "evidence_verified",
    "placeholders_resolved",
)
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")


def _curated_input_sha256(curated: dict[str, Any]) -> str:
    """The primary subject input the curated manifest says its findings came from."""
    direct = str(curated.get("input_sha256") or "").strip()
    if direct:
        return direct
    array_artifacts = curated.get("array_artifacts") if isinstance(curated.get("array_artifacts"), dict) else {}
    value = str(array_artifacts.get("input_sha256") or "").strip()
    if value:
        return value
    wgs_artifacts = curated.get("wgs_artifacts") if isinstance(curated.get("wgs_artifacts"), dict) else {}
    return str(wgs_artifacts.get("sha256") or "").strip()


def _blocked_policy(reason: str) -> dict[str, Any]:
    """Fail-closed policy shape consumed by the renderer when verification cannot run."""
    return {
        "ready_for_requested_operation": False,
        "planes": {name: {"state": "BLOCKED"} for name in REQUIRED_PLANES},
        "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "BLOCKED", "blocking": True}],
        "source": {"status": "NÃO DISPONÍVEL", "reason": reason},
    }


def assemble_release(curated: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Assemble a release only from a Policy Control verdict re-executed for this case."""
    result = copy.deepcopy(curated)
    blockers: list[str] = []

    raw_case_id = curated.get("case_id")
    case_id = raw_case_id.strip() if isinstance(raw_case_id, str) else ""
    input_sha256 = _curated_input_sha256(curated)
    try:
        if not case_id:
            raise PolicyEvaluationVerificationError("curated manifest case_id is missing")
        if not input_sha256:
            raise PolicyEvaluationVerificationError("curated manifest primary input SHA-256 is missing")
        verified_policy = verify_policy_evaluation(
            policy,
            case_id=case_id,
            input_sha256=input_sha256,
            required_output="FINAL_AUDITED_REPORT",
        )
        result["policy_evaluation"] = copy.deepcopy(verified_policy)
        result["policy_evaluation_verification"] = {
            "status": "VERIFICADO",
            "method": "policy-control-reexecution",
            "manifest_sha256": verified_policy["manifest_sha256"],
        }
    except PolicyEvaluationVerificationError as exc:
        reason = str(exc)
        verified_policy = _blocked_policy(reason)
        result["policy_evaluation"] = verified_policy
        result["policy_evaluation_verification"] = {
            "status": "NÃO DISPONÍVEL",
            "method": "policy-control-reexecution",
            "reason": reason,
        }
        blockers.append("policy_evaluation_binding")

    publication = result.get("publication_gate") if isinstance(result.get("publication_gate"), dict) else {}
    for key in REQUIRED_PUBLICATION:
        if publication.get(key) is not True:
            blockers.append(key)

    if verified_policy.get("ready_for_requested_operation") is not True:
        blockers.append("policy_evaluation")

    planes = verified_policy.get("planes") if isinstance(verified_policy.get("planes"), dict) else {}
    for name in REQUIRED_PLANES:
        plane = planes.get(name) if isinstance(planes.get(name), dict) else {}
        if plane.get("state") != "PASS":
            blockers.append(f"plane:{name}")

    gates = verified_policy.get("gates") if isinstance(verified_policy.get("gates"), list) else []
    final_audit = next((g for g in gates if isinstance(g, dict) and g.get("gate") == "FINAL_AUDIT_GATE"), None)
    if not isinstance(final_audit, dict) or final_audit.get("state") != "PASS":
        blockers.append("FINAL_AUDIT_GATE")

    blockers = list(dict.fromkeys(blockers))
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
