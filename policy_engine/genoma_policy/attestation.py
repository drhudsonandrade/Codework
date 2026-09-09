"""Validate attributable section attestations against canonical rule identities."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .models import OperationalStatus, RulesetSection

ALLOWED_OPERATIONAL = {status.value for status in OperationalStatus}
ALLOWED_APPLICABILITY = {"APPLICABLE", "NOT_APPLICABLE", "UNRESOLVED"}
ALLOWED_DECISIONS = {"SATISFIED", "BLOCKED", "NOT_APPLICABLE", "UNRESOLVED"}
SATISFYING_STATUSES = {
    OperationalStatus.EXECUTED.value,
    OperationalStatus.VERIFIED.value,
    OperationalStatus.INFERRED.value,
}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _valid_timestamp(value: Any) -> bool:
    """Require a nonempty string accepted by the ISO timestamp parser."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _valid_hash_list(value: Any) -> bool:
    """Require a nonempty list containing only SHA-256 strings."""
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and SHA256_RE.fullmatch(item) for item in value
    )


def validate_section_attestation(
    attestation: dict[str, Any], section: RulesetSection, evidence_ids: set[str],
) -> list[str]:
    """Validate a portable non-binary attestation without replacing scientific judgement."""
    reasons: list[str] = []
    prefix = f"section {section.number}"
    if attestation.get("section") != section.number:
        reasons.append(f"{prefix} attestation section number mismatch")
    if attestation.get("rule_id") != section.rule_id:
        reasons.append(f"{prefix} rule_id does not match canonical compiled rule")
    if attestation.get("rule_sha256") != section.sha256:
        reasons.append(f"{prefix} rule_sha256 does not match canonical section hash")

    applicability = attestation.get("applicability")
    status = attestation.get("status")
    decision = attestation.get("decision")
    justification = attestation.get("justification")
    refs = attestation.get("evidence_refs")
    trace = attestation.get("trace")
    if applicability not in ALLOWED_APPLICABILITY:
        reasons.append(f"{prefix} applicability invalid or missing")
    if status not in ALLOWED_OPERATIONAL:
        reasons.append(f"{prefix} operational status invalid or missing")
    if decision not in ALLOWED_DECISIONS:
        reasons.append(f"{prefix} decision invalid or missing")
    if not isinstance(justification, str) or not justification.strip():
        reasons.append(f"{prefix} justification is required")
    if not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs):
        reasons.append(f"{prefix} evidence_refs must be a list of non-empty IDs")
        refs = []
    unknown_refs = sorted({ref for ref in refs if ref not in evidence_ids})
    if unknown_refs:
        reasons.append(f"{prefix} references unknown evidence IDs: {unknown_refs[:5]}")
    if applicability == "NOT_APPLICABLE" and decision != "NOT_APPLICABLE":
        reasons.append(f"{prefix} NOT_APPLICABLE applicability requires NOT_APPLICABLE decision")
    if applicability == "UNRESOLVED" and decision != "UNRESOLVED":
        reasons.append(f"{prefix} UNRESOLVED applicability requires UNRESOLVED decision")
    if applicability == "APPLICABLE" and decision == "NOT_APPLICABLE":
        reasons.append(f"{prefix} APPLICABLE rule cannot use NOT_APPLICABLE decision")
    if decision == "SATISFIED":
        if status not in SATISFYING_STATUSES:
            reasons.append(f"{prefix} status {status} cannot claim SATISFIED")
        if not refs:
            reasons.append(f"{prefix} SATISFIED decision requires explicit evidence")
    if (
        status in {OperationalStatus.EXECUTED.value, OperationalStatus.VERIFIED.value}
        and applicability == "APPLICABLE"
        and not refs
    ):
        reasons.append(f"{prefix} {status} applicable attestation requires evidence")
    if not isinstance(trace, dict):
        reasons.append(f"{prefix} trace object is required")
        return reasons
    for field in ("attestation_id", "actor_type", "actor_id", "method", "run_id"):
        if not isinstance(trace.get(field), str) or not trace.get(field, "").strip():
            reasons.append(f"{prefix} trace.{field} is required")
    if trace.get("actor_type") not in {"HUMAN", "SOFTWARE", "SERVICE"}:
        reasons.append(f"{prefix} trace.actor_type invalid")
    if not _valid_timestamp(trace.get("created_at")):
        reasons.append(f"{prefix} trace.created_at must be an ISO-8601 timestamp")
    tool_versions = trace.get("tool_versions")
    if not isinstance(tool_versions, dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in tool_versions.items()
    ):
        reasons.append(f"{prefix} trace.tool_versions must be a string map")
    if applicability == "APPLICABLE" and decision == "SATISFIED":
        if not _valid_hash_list(trace.get("input_sha256")):
            reasons.append(f"{prefix} SATISFIED trace.input_sha256 requires one or more SHA-256 hashes")
        if not _valid_hash_list(trace.get("output_sha256")):
            reasons.append(f"{prefix} SATISFIED trace.output_sha256 requires one or more SHA-256 hashes")
    else:
        for field in ("input_sha256", "output_sha256"):
            value = trace.get(field, [])
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not SHA256_RE.fullmatch(item)
                for item in value
            ):
                reasons.append(f"{prefix} trace.{field} must contain SHA-256 hashes when present")
    return reasons
