from __future__ import annotations

from typing import Any

from .gates_common import ALLOWED_OPERATIONAL, _gate, _get_list, _parse_iso_date


class EvidenceGates:
    def _evidence_gate(self, manifest: dict[str, Any]):
        """Require attributable, reproducible and time-bounded evidence references.

        A status label alone is not proof. Mutable sources must carry a resolvable
        locator plus retrieval evidence (query/snapshot digest). Clinical and
        predisposition claims must reference at least one primary or official source.
        """
        reasons: list[str] = []
        sources = {s.get("id"): s for s in _get_list(manifest, "sources") if isinstance(s, dict) and s.get("id")}
        for source_id, source in sources.items():
            if source.get("status") == "VERIFICADO" and not source.get("locator"):
                reasons.append(f"verified source {source_id} missing locator")
            retrieval = source.get("retrieval_evidence") if isinstance(source.get("retrieval_evidence"), dict) else {}
            if source.get("status") == "VERIFICADO":
                if not retrieval.get("method"):
                    reasons.append(f"verified source {source_id} missing retrieval_evidence.method")
                if not (retrieval.get("result_digest") or retrieval.get("snapshot_id") or retrieval.get("query_id")):
                    reasons.append(f"verified source {source_id} missing retrieval_evidence result_digest/snapshot_id/query_id")
            if source.get("mutable") is True:
                if source.get("status") != "VERIFICADO": reasons.append(f"mutable source {source_id} not VERIFICADO")
                if not source.get("version"): reasons.append(f"mutable source {source_id} missing version")
                if not _parse_iso_date(str(source.get("checked_at", ""))): reasons.append(f"mutable source {source_id} missing valid checked_at date")
                if not source.get("locator"): reasons.append(f"mutable source {source_id} missing locator")
                if not retrieval: reasons.append(f"mutable source {source_id} missing retrieval_evidence")
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict): continue
            refs = claim.get("evidence_refs", []) if isinstance(claim.get("evidence_refs"), list) else []
            clinical = claim.get("domain") in {"CLÍNICO", "PREDISPOSIÇÃO"}
            if clinical and not refs: reasons.append(f"claim[{idx}] clinical/predisposition claim lacks evidence_refs")
            known_refs: list[dict[str, Any]] = []
            for ref in refs:
                if ref not in sources:
                    reasons.append(f"claim[{idx}] references unknown evidence source {ref}")
                else:
                    known_refs.append(sources[ref])
            if clinical and known_refs and not any(source.get("primary_or_official") is True for source in known_refs):
                reasons.append(f"claim[{idx}] clinical/predisposition claim lacks primary/official evidence source")
        return _gate("EVIDENCE_RECENCY_GATE", not reasons, reasons)

    def _capability_honesty_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, item in enumerate(_get_list(manifest, "execution_manifest")):
            if not isinstance(item, dict): reasons.append(f"execution_manifest[{idx}] is not an object"); continue
            status = item.get("status")
            if status not in ALLOWED_OPERATIONAL: reasons.append(f"execution_manifest[{idx}] invalid status")
            if status in {"EXECUTADO", "VERIFICADO"} and not item.get("evidence_refs"): reasons.append(f"execution_manifest[{idx}] {status} without evidence_refs")
            if item.get("claimed_performed") is True and status in {"PROPOSTO", "NÃO DISPONÍVEL"}: reasons.append(f"execution_manifest[{idx}] claims performance but status is {status}")
        for idx, source in enumerate(_get_list(manifest, "sources")):
            if isinstance(source, dict) and source.get("status") == "VERIFICADO" and source.get("accessible") is False: reasons.append(f"source[{idx}] marked VERIFICADO while inaccessible")
        return _gate("CAPABILITY_HONESTY_GATE", not reasons, reasons)

    def _clinical_safety_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict): continue
            vc = str(claim.get("variant_classification", "")).upper()
            if vc == "VUS" and claim.get("changes_conduct") is True: reasons.append(f"claim[{idx}] uses VUS as isolated conduct-changing evidence")
            if claim.get("changes_conduct") is True:
                conf = claim.get("confirmation", {}) if isinstance(claim.get("confirmation"), dict) else {}
                if conf.get("status") not in {"EXECUTADO", "VERIFICADO"}: reasons.append(f"claim[{idx}] may change conduct without appropriate confirmation")
                if not conf.get("method"): reasons.append(f"claim[{idx}] conduct-changing claim lacks confirmation method")
            if claim.get("association_only") is True and claim.get("nature") == "FATO CONFIRMADO": reasons.append(f"claim[{idx}] converts association into confirmed causal fact")
        return _gate("CLINICAL_CONFIRMATION_GATE", not reasons, reasons)

    def _negative_evidence_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict) or claim.get("negative_result") is not True: continue
            if not claim.get("completeness_ref"): reasons.append(f"claim[{idx}] negative result lacks Genome Completeness reference")
            if not claim.get("scope_statement"): reasons.append(f"claim[{idx}] negative result lacks method/locus/class scope statement")
            if claim.get("disease_excluded") is True and claim.get("all_relevant_mechanisms_assessed") is not True: reasons.append(f"claim[{idx}] excludes disease beyond assessed mechanisms")
        return _gate("NEGATIVE_EVIDENCE_SCOPE_GATE", not reasons, reasons)

    def _build_harmonization_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict) or claim.get("cross_build_comparison") is not True: continue
            if not claim.get("source_build") or not claim.get("target_build"): reasons.append(f"claim[{idx}] cross-build comparison missing source/target build")
            if claim.get("build_harmonized") is not True: reasons.append(f"claim[{idx}] build not harmonized before comparison")
            if claim.get("ref_alt_verified") is not True: reasons.append(f"claim[{idx}] REF/ALT not verified after harmonization")
            if claim.get("strand_verified") is not True: reasons.append(f"claim[{idx}] strand not verified before concordance/conflict conclusion")
            if claim.get("concordance_or_conflict_concluded") is True and any(claim.get(key) is not True for key in ("build_harmonized", "ref_alt_verified", "strand_verified")):
                reasons.append(f"claim[{idx}] concluded concordance/conflict before complete harmonization")
        return _gate("BUILD_HARMONIZATION_GATE", not reasons, reasons)

    def _clinvar_conflict_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        required = ("review_status_considered", "vcep_considered", "condition_matched", "evidence_reviewed", "dates_reviewed", "conflict_dossier")
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict) or claim.get("clinvar_conflict") is not True: continue
            if claim.get("clinvar_simple_vote") is True: reasons.append(f"claim[{idx}] resolves ClinVar conflict by simple vote")
            resolution = claim.get("clinvar_conflict_resolution", {}) if isinstance(claim.get("clinvar_conflict_resolution"), dict) else {}
            for key in required:
                if resolution.get(key) is not True: reasons.append(f"claim[{idx}] ClinVar conflict resolution missing {key}")
        return _gate("CLINVAR_CONFLICT_GATE", not reasons, reasons)

    def _ancestry_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict): continue
            if claim.get("uses_haplogroup") is True and claim.get("direct_ethnicity_or_descent") is True: reasons.append(f"claim[{idx}] converts haplogroup into ethnicity/direct descent")
            if claim.get("prs") is True and claim.get("ancestry_calibrated") is not True: reasons.append(f"claim[{idx}] PRS lacks ancestry/population calibration")
        return _gate("ANCESTRY_AWARE_GATE", not reasons, reasons)

    def _reproductive_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []; repro = manifest.get("reproductive", {}) if isinstance(manifest.get("reproductive"), dict) else {}
        if not repro: return _gate("REPRODUCTIVE_GATE", True)
        if repro.get("integrate_couple") is True and repro.get("scopes_comparable") is not True: reasons.append("couple results integrated before harmonizing panel/classes/coverage")
        if repro.get("both_carriers_same_gene") is True:
            for key in ("causal_combination_verified", "inheritance_verified", "phase_addressed"):
                if repro.get(key) is not True: reasons.append(f"both-carrier risk calculation missing {key}")
        if repro.get("pgt_p_used_as_clinically_validated") is True: reasons.append("PGT-P must not be represented as established clinical practice")
        if repro.get("carrier_partner_recommendation") is True and repro.get("partner_full_relevant_scope") is not True: reasons.append("partner testing recommendation does not cover full relevant gene/classes and residual risk")
        return _gate("REPRODUCTIVE_GATE", not reasons, reasons)

    def _pgx_complex_locus_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if not isinstance(claim, dict) or not claim.get("pgx_gene"): continue
            gene = str(claim.get("pgx_gene")).upper()
            if gene in {"CYP2D6", "CYP2B6", "HLA-A", "HLA-B", "UGT1A1"} and claim.get("generic_vcf_only") is True and claim.get("specialized_haplotype_workflow") is not True: reasons.append(f"claim[{idx}] {gene} diplotype inferred from generic VCF without specialized workflow")
        return _gate("PGX_COMPLEX_LOCUS_GATE", not reasons, reasons)

    def _trait_determinism_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if isinstance(claim, dict) and claim.get("trait") in {"personality", "intelligence", "talent", "ethics", "gender_identity"} and claim.get("single_candidate_variant_deterministic") is True: reasons.append(f"claim[{idx}] uses deterministic single-variant explanation for complex trait")
        return _gate("TRAIT_NONDETERMINISM_GATE", not reasons, reasons)

    def _screening_diagnosis_gate(self, manifest: dict[str, Any]):
        reasons: list[str] = []
        for idx, claim in enumerate(_get_list(manifest, "claims")):
            if isinstance(claim, dict) and claim.get("test_type") in {"cfDNA", "NIPT", "screening"} and claim.get("diagnosis_closed") is True: reasons.append(f"claim[{idx}] converts screening result into definitive diagnosis")
        return _gate("SCREENING_DIAGNOSIS_GATE", not reasons, reasons)
