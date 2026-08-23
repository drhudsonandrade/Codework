from __future__ import annotations

from typing import Any

from .attestation import validate_section_attestation
from .gates_common import CRITICAL_FINAL_AUDIT_KEYS, _as_bool, _gate, _get_list
from .gates_evidence import _parse_iso_date
from .models import GateResult, GateState

#: The classes section 117 requires a negative conclusion to account for. `variant_class_
#: coverage_explicit` claims each of them has a declared status; this is that list.
VARIANT_CLASSES = (
    "SNV", "indel", "CNV", "SV", "repeat_expansion", "mtDNA", "HLA", "KIR",
    "noncoding", "mosaicism",
)

#: Loci sections 174 and 238 name as unresolvable by a generic callset. `complex_regions_
#: flagged` claims they are flagged; flagged means present in the capability matrix.
COMPLEX_LOCI = ("CYP2D6", "SMN1_SMN2", "PMS2", "GBA1", "HLA")

#: Fields whose presence on a claim means it is asserting a magnitude of risk.
RISK_MAGNITUDE_FIELDS = ("odds_ratio", "hazard_ratio", "relative_risk", "absolute_risk",
                         "lifetime_risk", "penetrance", "prs_percentile", "effect_size")

#: Section 233's vocabulary. A magnitude must say which of these it is.
RISK_TYPES = ("OR", "HR", "RR", "ABSOLUTE", "LIFETIME", "PENETRANCE", "PERCENTILE",
              "EFFECT_SIZE")


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
        queries = _get_list(manifest, "database_query_manifest")
        if audit.get("master_database_query_manifest") is True and not queries:
            reasons.append("master_database_query_manifest asserted while no query manifest is present")

        capability = manifest.get("capability_matrix")
        capability = capability if isinstance(capability, dict) else {}

        if audit.get("critical_databases_current") is True:
            # Section 202's freshness status, checked against the same field and window
            # EVIDENCE_RECENCY_GATE uses, so the two cannot disagree about one source.
            stale = [
                s.get("id") for s in sources
                if isinstance(s, dict) and _as_bool(s.get("mutable"))
                and not _parse_iso_date(str(s.get("checked_at", "")))
            ]
            if stale:
                reasons.append(
                    "critical_databases_current asserted while mutable sources carry no "
                    f"readable checked_at: {stale[:5]}"
                )

        if audit.get("variant_class_coverage_explicit") is True:
            # Section 117 names the classes a negative conclusion must account for. A report
            # may not assert that its coverage is explicit while a class it never mentions
            # sits outside the matrix entirely.
            undeclared = [
                key for key in VARIANT_CLASSES
                if not isinstance(capability.get(key), dict) or not capability[key].get("status")
            ]
            if undeclared:
                reasons.append(
                    "variant_class_coverage_explicit asserted while these variant classes "
                    f"carry no declared status: {undeclared}"
                )

        if audit.get("lod_described") is True:
            # Section 232: "não detectado" must mean "not detected above this method's
            # estimated capability". A class declared unavailable with no reason states the
            # opposite — that nothing is known about why.
            silent = [
                key for key, entry in capability.items()
                if isinstance(entry, dict)
                and not str(entry.get("reason") or entry.get("method") or "").strip()
            ]
            if not capability:
                # `all(...)` over nothing is true, and so is "no entry lacks a reason" over an
                # empty matrix. A limit of detection described for no class is not described.
                reasons.append(
                    "lod_described asserted while the manifest carries no capability matrix; "
                    "a limit of detection for no variant class is not a limit of detection"
                )
            elif silent:
                reasons.append(
                    "lod_described asserted while these capability entries give neither a "
                    f"method nor a reason: {sorted(silent)[:5]}"
                )

        if audit.get("complex_regions_flagged") is True:
            # Sections 174 and 238 name loci that a generic callset does not resolve. Flagged
            # means named, with a status, not merely believed.
            unflagged = [key for key in COMPLEX_LOCI if key not in capability]
            if unflagged:
                reasons.append(
                    f"complex_regions_flagged asserted while these loci are absent from the "
                    f"capability matrix: {unflagged}"
                )

        if audit.get("ancestry_reference_considered") is True:
            # Section 115: a population association carries the cohort it was estimated in.
            # Without it the effect is being transferred to this genome silently.
            contextless = [
                c.get("id") for c in claims
                if isinstance(c, dict)
                and (c.get("nature") == "ASSOCIAÇÃO" or _as_bool(c.get("prs")))
                and not str(c.get("ancestry_context") or "").strip()
            ]
            if contextless:
                reasons.append(
                    "ancestry_reference_considered asserted while association claims carry no "
                    f"ancestry_context: {contextless[:5]}"
                )

        if audit.get("absolute_vs_relative_risk_separated") is True:
            # Section 233 lists the measures that must not be conflated. A claim carrying a
            # magnitude has to say which one it is.
            unlabelled = [
                c.get("id") for c in claims
                if isinstance(c, dict)
                and any(c.get(field) is not None for field in RISK_MAGNITUDE_FIELDS)
                and c.get("risk_type") not in RISK_TYPES
            ]
            if unlabelled:
                reasons.append(
                    "absolute_vs_relative_risk_separated asserted while claims carry a risk "
                    f"magnitude with no risk_type from {list(RISK_TYPES)}: {unlabelled[:5]}"
                )

        if audit.get("report_has_technical_and_lay_layers") is True:
            # Section 148. What the engine can establish is that the manifest names both
            # layers and that each names a section this manifest actually carries; that the
            # rendered document really contains them is checked at render time, by the sealed
            # template contract. This refuses the bare boolean, not more than that.
            layers = manifest.get("report_layers")
            layers = layers if isinstance(layers, dict) else {}
            section_ids = {s.get("id") for s in sections if isinstance(s, dict)}
            for layer in ("technical", "lay"):
                reference = layers.get(layer)
                if not str(reference or "").strip():
                    reasons.append(
                        f"report_has_technical_and_lay_layers asserted while report_layers "
                        f"names no {layer!r} layer"
                    )
                elif reference not in section_ids:
                    reasons.append(
                        f"report_layers.{layer} points at {reference!r}, which is not a "
                        "section this manifest carries"
                    )

        if audit.get("scientific_novelty_radar") is True:
            # Sections 143 and 217: the radar is the act of re-consulting, and what shows it
            # happened is a query manifest whose entries say when they were run.
            undated = [
                entry.get("database") for entry in queries
                if not isinstance(entry, dict) or not _parse_iso_date(str(entry.get("queried_at", "")))
            ]
            if undated or not queries:
                reasons.append(
                    "scientific_novelty_radar asserted while the query manifest carries no "
                    f"readable queried_at: {undated[:5] if undated else 'no queries at all'}"
                )
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
