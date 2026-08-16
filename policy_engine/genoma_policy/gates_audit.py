from __future__ import annotations

from typing import Any

from .attestation import validate_section_attestation
from .gates_common import CRITICAL_FINAL_AUDIT_KEYS, _as_bool, _gate, _get_list
from .models import GateResult, GateState

class AuditGates:
    def _section_coverage_summary(self, manifest: dict[str, Any]) -> dict[str, Any]:
        attestations = _get_list(manifest, "section_attestations")
        by_section = {item.get("section"): item for item in attestations if isinstance(item, dict) and isinstance(item.get("section"), int)}
        considered = len([n for n in range(len(self.ruleset.sections)) if n in by_section])
        applicable = sum(1 for item in by_section.values() if item.get("applicability") == "APPLICABLE")
        not_applicable = sum(1 for item in by_section.values() if item.get("applicability") == "NOT_APPLICABLE")
        unresolved = len(self.ruleset.sections) - considered + sum(1 for item in by_section.values() if item.get("applicability") == "UNRESOLVED")
        return {"total_rules": len(self.ruleset.sections), "considered": considered, "applicable": applicable, "not_applicable": not_applicable, "unresolved": unresolved}

    def _section_coverage_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if not _as_bool(operation.get("analysis_relevant")): return _gate("RULE_COVERAGE_GATE", True)
        reasons: list[str] = []; attestations = _get_list(manifest, "section_attestations"); by_section: dict[int, dict[str, Any]] = {}
        for idx, item in enumerate(attestations):
            if not isinstance(item, dict) or not isinstance(item.get("section"), int): reasons.append(f"section_attestations[{idx}] malformed"); continue
            number = item["section"]
            if number in by_section: reasons.append(f"duplicate section attestation for {number}")
            by_section[number] = item
        missing = [n for n in range(len(self.ruleset.sections)) if n not in by_section]
        if missing: reasons.append(f"{len(missing)} rules not considered; first missing: {missing[:10]}")
        evidence_ids = {source.get("id") for source in _get_list(manifest, "sources") if isinstance(source, dict) and isinstance(source.get("id"), str) and source.get("id")}
        for number, item in by_section.items():
            if number < 0 or number >= len(self.ruleset.sections): reasons.append(f"unknown section attestation {number}"); continue
            reasons.extend(validate_section_attestation(item, self.ruleset.sections[number], evidence_ids))
            if item.get("applicability") == "UNRESOLVED" or item.get("decision") in {"UNRESOLVED", "BLOCKED"}: reasons.append(f"section {number} is not resolved as satisfied/not-applicable")
        return _gate("RULE_COVERAGE_GATE", not reasons, reasons)

    def _plane_summary(self, gates: list[GateResult]) -> dict[str, Any]:
        by_name = {gate.gate: gate for gate in gates}
        groups = {
            "policy_control": ("RULESET_GATE", "TAXONOMY_GATE", "RULE_COVERAGE_GATE"),
            "scientific_data": ("DATA_PROVENANCE_GATE", "CONSENT_GATE", "QC_GATE", "RUNTIME_RESOURCE_GATE"),
            "evidence": ("EVIDENCE_RECENCY_GATE", "CAPABILITY_HONESTY_GATE", "CLINICAL_CONFIRMATION_GATE", "NEGATIVE_EVIDENCE_SCOPE_GATE", "ANCESTRY_AWARE_GATE", "REPRODUCTIVE_GATE", "PGX_COMPLEX_LOCUS_GATE", "TRAIT_NONDETERMINISM_GATE", "SCREENING_DIAGNOSIS_GATE"),
            "audit": ("FINAL_AUDIT_GATE",),
        }
        result: dict[str, Any] = {}
        for plane, names in groups.items():
            selected = [by_name[name] for name in names if name in by_name]
            if any(gate.state == GateState.FAIL and gate.blocking for gate in selected): state = "FAIL"
            elif any(gate.state == GateState.PENDING and gate.blocking for gate in selected): state = "PENDING"
            else: state = "PASS"
            result[plane] = {"state": state, "gates": [gate.gate for gate in selected]}
        post = by_name.get("POST_DEPLOYMENT_GATE")
        if post is not None: result["audit"]["post_deployment_state"] = post.state.value
        return result

    def _final_audit_gate(self, manifest: dict[str, Any]):
        operation = manifest.get("operation", {}) if isinstance(manifest.get("operation"), dict) else {}
        if operation.get("output") != "FINAL_AUDITED_REPORT": return _gate("FINAL_AUDIT_GATE", True)
        audit = manifest.get("final_audit", {}) if isinstance(manifest.get("final_audit"), dict) else {}
        reasons = [f"final audit criterion missing/false: {key}" for key in CRITICAL_FINAL_AUDIT_KEYS if audit.get(key) is not True]
        return _gate("FINAL_AUDIT_GATE", not reasons, reasons)

    def _post_deployment_gate(self, manifest: dict[str, Any]):
        pd = manifest.get("post_deployment", {}) if isinstance(manifest.get("post_deployment"), dict) else {}
        criteria = {
            "single_active_ruleset": pd.get("single_active_ruleset") is True,
            "bootstrap_installed": pd.get("bootstrap_installed") is True,
            "live_smoke_15_of_15": pd.get("live_smoke_passed") is True and pd.get("live_smoke_count") == 15,
            "no_critical_failure": pd.get("critical_failures") == 0,
            "identity_recovered": pd.get("identity_recovered") == "v3.3/VIGENTE/14/08/2026",
        }
        if all(criteria.values()): return _gate("POST_DEPLOYMENT_GATE", True, blocking=False)
        missing = [name for name, ok in criteria.items() if not ok]
        return _gate("POST_DEPLOYMENT_GATE", False, ["POST-DEPLOYMENT PENDENTE; unmet external project criteria: " + ", ".join(missing)], blocking=False, pending=True)
