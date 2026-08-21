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
        reasons.extend(self._blanket_not_applicable_reasons(by_section))
        return _gate("RULE_COVERAGE_GATE", not reasons, reasons)

    #: The rule that governs every relevant genetic analysis by its own text. Section 0 is the
    #: execution bootstrap — "antes de qualquer análise genética relevante" — so an operation
    #: that declares itself analysis-relevant cannot also declare this rule inapplicable. The
    #: number is not a judgement call by this engine; it is where the ruleset puts its own
    #: precondition, and the ruleset is pinned by SHA-256.
    BOOTSTRAP_SECTION = 0

    def _blanket_not_applicable_reasons(self, by_section: dict[int, dict[str, Any]]) -> list[str]:
        """Refuse the blanket declaration that no rule applies to a genetic analysis.

        An external audit reached ready_for_requested_operation=true by attesting all 263
        rules NOT_APPLICABLE with one boilerplate justification, no sources and no claims.
        Every individual attestation was well-formed; nothing looked at them as a set. These
        three checks look at the set, and each one alone breaks that manifest.
        """
        reasons: list[str] = []
        if not by_section:
            return reasons

        bootstrap = by_section.get(self.BOOTSTRAP_SECTION)
        if bootstrap is not None and bootstrap.get("applicability") == "NOT_APPLICABLE":
            reasons.append(
                f"section {self.BOOTSTRAP_SECTION} is the execution bootstrap and applies to "
                "every analysis-relevant operation by its own text; it cannot be attested "
                "NOT_APPLICABLE"
            )

        applicable = [i for i in by_section.values() if i.get("applicability") == "APPLICABLE"]
        if not applicable:
            reasons.append(
                f"no rule of {len(by_section)} was attested APPLICABLE to an analysis-relevant "
                "operation; a genetic analysis to which the entire ruleset is inapplicable is "
                "a contradiction, not a triage result"
            )

        # Grouping several rules under one honest reason is normal — "this operation performs
        # no reproductive analysis" answers the reproductive rules together. One string
        # answering *every* rule answers none of them; it is a placeholder in the shape of a
        # justification.
        not_applicable = [i for i in by_section.values() if i.get("applicability") == "NOT_APPLICABLE"]
        justifications = {str(i.get("justification") or "").strip() for i in not_applicable}
        if len(not_applicable) > 1 and len(justifications) == 1:
            reasons.append(
                f"all {len(not_applicable)} NOT_APPLICABLE attestations share a single "
                "justification; one text cannot be the reason each distinct rule does not apply"
            )
        return reasons

    def _plane_summary(self, gates: list[GateResult]) -> dict[str, Any]:
        by_name = {gate.gate: gate for gate in gates}
        groups = {
            "policy_control": ("RULESET_GATE", "TAXONOMY_GATE", "RULE_COVERAGE_GATE"),
            "scientific_data": ("DATA_PROVENANCE_GATE", "CONSENT_GATE", "QC_GATE", "RUNTIME_RESOURCE_GATE"),
            "evidence": (
                "EVIDENCE_RECENCY_GATE", "CAPABILITY_HONESTY_GATE", "CLINICAL_CONFIRMATION_GATE",
                "NEGATIVE_EVIDENCE_SCOPE_GATE", "BUILD_HARMONIZATION_GATE", "CLINVAR_CONFLICT_GATE",
                "ANCESTRY_AWARE_GATE", "REPRODUCTIVE_GATE", "PGX_COMPLEX_LOCUS_GATE",
                "TRAIT_NONDETERMINISM_GATE", "SCREENING_DIAGNOSIS_GATE",
            ),
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
        reasons.extend(self._final_audit_substance_reasons(manifest, audit))
        return _gate("FINAL_AUDIT_GATE", not reasons, reasons)

    def _final_audit_substance_reasons(self, manifest: dict[str, Any], audit: dict[str, Any]) -> list[str]:
        """Check the criteria the engine can see, instead of taking the manifest's word.

        Every criterion above was a boolean the manifest set about itself, so a final audited
        report could be declared complete over zero sources and zero findings. Only some of
        the fifteen are mechanically checkable from the manifest; those are checked here, and
        a criterion asserted while its own evidence is absent is a false declaration rather
        than an unverifiable one.
        """
        reasons: list[str] = []
        sources = _get_list(manifest, "sources")
        claims = _get_list(manifest, "claims")
        sections = _get_list(manifest, "sections")

        # A final audited report over nothing is the shape the bypass took.
        if not sources:
            reasons.append("FINAL_AUDITED_REPORT declares no source; a final report cites what it read")
        if not claims:
            reasons.append("FINAL_AUDITED_REPORT declares no claim; there is nothing for the audit to be about")

        if audit.get("no_accidental_empty_sections") is True and not sections:
            reasons.append("no_accidental_empty_sections asserted while the manifest declares no section at all")
        if audit.get("critical_sources_versioned") is True:
            unversioned = [
                s.get("id") for s in sources
                if isinstance(s, dict) and _as_bool(s.get("mutable")) and not s.get("version")
            ]
            if unversioned:
                reasons.append(f"critical_sources_versioned asserted while mutable sources carry no version: {unversioned[:5]}")
        if audit.get("qc_documented") is True:
            qc = manifest.get("qc", {}) if isinstance(manifest.get("qc"), dict) else {}
            if not qc.get("evidence_refs"):
                reasons.append("qc_documented asserted while QC carries no evidence_refs")
        if audit.get("domains_separated") is True:
            undomained = [
                idx for idx, c in enumerate(claims)
                if not isinstance(c, dict) or not c.get("domain")
            ]
            if undomained:
                reasons.append(f"domains_separated asserted while claims carry no domain: {undomained[:5]}")
        if audit.get("numbering_integrity") is True:
            considered = {
                item.get("section") for item in _get_list(manifest, "section_attestations")
                if isinstance(item, dict)
            }
            if len(considered) != len(self.ruleset.sections):
                reasons.append(
                    f"numbering_integrity asserted while {len(considered)} of "
                    f"{len(self.ruleset.sections)} rules were considered"
                )
        if audit.get("remaining_gaps_listed") is True and not manifest.get("remaining_gaps"):
            reasons.append("remaining_gaps_listed asserted while the manifest lists no gap")
        if audit.get("master_database_query_manifest") is True and not manifest.get("database_query_manifest"):
            reasons.append("master_database_query_manifest asserted while no query manifest is present")
        return reasons

    def _post_deployment_gate(self, manifest: dict[str, Any]):
        pd = manifest.get("post_deployment", {}) if isinstance(manifest.get("post_deployment"), dict) else {}
        criteria = {
            "single_active_ruleset": pd.get("single_active_ruleset") is True,
            "bootstrap_installed": pd.get("bootstrap_installed") is True,
            "live_smoke_15_of_15": pd.get("live_smoke_passed") is True and pd.get("live_smoke_count") == 15,
            "no_critical_failure": pd.get("critical_failures") == 0,
            "identity_recovered": pd.get("identity_recovered") == "v3.4/VIGENTE/17/08/2026",
        }
        if all(criteria.values()): return _gate("POST_DEPLOYMENT_GATE", True, blocking=False)
        missing = [name for name, ok in criteria.items() if not ok]
        return _gate("POST_DEPLOYMENT_GATE", False, ["POST-DEPLOYMENT PENDENTE; unmet external project criteria: " + ", ".join(missing)], blocking=False, pending=True)
