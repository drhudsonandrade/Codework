from __future__ import annotations

from copy import deepcopy
from typing import Any

from .engine import PolicyEngine
from .ruleset import (
    EXPECTED_CANONICAL,
    EXPECTED_DATE,
    EXPECTED_STATUS,
    EXPECTED_VERSION,
    Ruleset,
    RulesetError,
)
from .scaffold import scaffold_manifest

EXPECTED_SMOKE_RULESET_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


def _require_canonical_smoke_ruleset(ruleset: Ruleset) -> None:
    expected = {
        "status": EXPECTED_STATUS,
        "version": EXPECTED_VERSION,
        "effective_date": EXPECTED_DATE,
        "canonical_filename": EXPECTED_CANONICAL,
        "sha256": EXPECTED_SMOKE_RULESET_SHA256,
    }
    observed = {
        "status": ruleset.status,
        "version": ruleset.version,
        "effective_date": ruleset.effective_date,
        "canonical_filename": ruleset.canonical_filename,
        "sha256": ruleset.sha256,
    }
    mismatches = [f"{key}={observed[key]!r}" for key, value in expected.items() if observed[key] != value]
    if mismatches:
        raise RulesetError("RULESET NÃO DISPONÍVEL/CONFLITANTE: smoke requires canonical v3.4 identity: " + "; ".join(mismatches))


def _baseline(ruleset: Ruleset) -> dict[str, Any]:
    manifest = scaffold_manifest(ruleset, case_id="SMOKE")
    manifest["operation"].update({"analysis_relevant": False, "requires_real_calling": False, "output": "ANALYSIS"})
    manifest["consent"] = {"verified": True, "version": "smoke", "authorized_domains": ["research"]}
    manifest["qc"] = {"status": "EXECUTADO", "passed": True, "evidence_refs": ["smoke:qc"]}
    manifest["section_attestations"] = []
    manifest["post_deployment"] = {}
    return manifest


def _claim(**overrides: Any) -> dict[str, Any]:
    claim = {
        "id": "C1",
        "nature": "ASSOCIAÇÃO",
        "domain": "PESQUISA",
        "status": "INFERIDO",
        "priority": "P5",
        "evidence_refs": [],
    }
    claim.update(overrides)
    return claim


def _all_na(ruleset: Ruleset) -> list[dict[str, Any]]:
    return [
        {
            "section": section.number,
            "rule_id": section.rule_id,
            "rule_sha256": section.sha256,
            "applicability": "NOT_APPLICABLE",
            "status": "VERIFICADO",
            "decision": "NOT_APPLICABLE",
            "justification": "smoke fixture",
            "evidence_refs": [],
            "trace": {
                "attestation_id": f"smoke:{section.rule_id}",
                "created_at": "2026-08-22T18:46:00-03:00",
                "actor_type": "SOFTWARE",
                "actor_id": "genoma-policy-smoke",
                "method": "fixture",
                "run_id": "SMOKE",
                "input_sha256": [],
                "output_sha256": [],
                "tool_versions": {"genoma-policy-engine": "0.4.0"},
            },
        }
        for section in ruleset.sections
    ]


def smoke_cases(ruleset: Ruleset) -> list[tuple[str, str, dict[str, Any]]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(negative_result=True, disease_excluded=True, all_relevant_mechanisms_assessed=False)]
    cases.append(("SMOKE-01", "NEGATIVE_EVIDENCE_SCOPE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["operation"]["analysis_relevant"] = True
    manifest["inputs"] = [{"id": "x", "kind": "vcf", "source": "fixture", "sha256": "abc"}]
    manifest["qc"] = {"status": "EXECUTADO", "passed": False, "evidence_refs": ["smoke:qc"]}
    manifest["claims"] = [_claim(nature="FATO CONFIRMADO", technical_quality_flag="LOW")]
    manifest["section_attestations"] = _all_na(ruleset)
    cases.append(("SMOKE-02", "QC_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [
        _claim(
            cross_build_comparison=True,
            source_build="GRCh37",
            target_build="GRCh38",
            build_harmonized=False,
            ref_alt_verified=False,
            strand_verified=False,
        )
    ]
    cases.append(("SMOKE-03", "BUILD_HARMONIZATION_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [
        _claim(
            clinvar_conflict=True,
            clinvar_simple_vote=True,
            clinvar_conflict_resolution={
                "review_status_considered": False,
                "vcep_considered": False,
                "condition_matched": False,
                "evidence_reviewed": False,
                "dates_reviewed": False,
                "conflict_dossier": False,
            },
        )
    ]
    cases.append(("SMOKE-04", "CLINVAR_CONFLICT_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["reproductive"] = {"carrier_partner_recommendation": True, "partner_full_relevant_scope": False}
    cases.append(("SMOKE-05", "REPRODUCTIVE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["reproductive"] = {
        "both_carriers_same_gene": True,
        "causal_combination_verified": False,
        "inheritance_verified": True,
        "phase_addressed": False,
    }
    cases.append(("SMOKE-06", "REPRODUCTIVE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(prs=True, ancestry_calibrated=False)]
    cases.append(("SMOKE-07", "ANCESTRY_AWARE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["reproductive"] = {"pgt_p_used_as_clinically_validated": True}
    cases.append(("SMOKE-08", "REPRODUCTIVE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(test_type="cfDNA", diagnosis_closed=True)]
    cases.append(("SMOKE-09", "SCREENING_DIAGNOSIS_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(pgx_gene="CYP2D6", generic_vcf_only=True, specialized_haplotype_workflow=False)]
    cases.append(("SMOKE-10", "PGX_COMPLEX_LOCUS_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["sources"] = [{"id": "db", "mutable": False, "status": "VERIFICADO", "accessible": False}]
    cases.append(("SMOKE-11", "CAPABILITY_HONESTY_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(trait="personality", single_candidate_variant_deterministic=True)]
    cases.append(("SMOKE-12", "TRAIT_NONDETERMINISM_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["claims"] = [_claim(uses_haplogroup=True, direct_ethnicity_or_descent=True)]
    cases.append(("SMOKE-13", "ANCESTRY_AWARE_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["operation"]["analysis_relevant"] = True
    manifest["inputs"] = [{"id": "wgs", "kind": "wgs", "source": "fixture", "sha256": "abc"}]
    manifest["consent"] = {"verified": True, "version": "smoke", "authorized_domains": ["clinical"]}
    manifest["qc"] = {"status": "PROPOSTO", "passed": False, "evidence_refs": []}
    manifest["section_attestations"] = _all_na(ruleset)
    cases.append(("SMOKE-14", "QC_GATE", manifest))

    manifest = _baseline(ruleset)
    manifest["operation"]["output"] = "FINAL_AUDITED_REPORT"
    manifest["final_audit"] = {}
    cases.append(("SMOKE-15", "FINAL_AUDIT_GATE", manifest))
    return cases


def run_smoke(engine: PolicyEngine) -> dict[str, Any]:
    _require_canonical_smoke_ruleset(engine.ruleset)
    results = []
    passed = 0
    for case_id, expected_gate, manifest in smoke_cases(engine.ruleset):
        report = engine.evaluate(deepcopy(manifest))
        matched = [gate for gate in report.gates if gate.gate == expected_gate and gate.state.value == "FAIL"]
        ok = bool(matched)
        passed += int(ok)
        results.append(
            {
                "case": case_id,
                "expected_blocking_gate": expected_gate,
                "pass": ok,
                "observed": [gate.to_dict() for gate in report.gates if gate.gate == expected_gate],
            }
        )
    return {
        "suite": "GENOMA v3.4 independent deterministic safety smoke",
        "passed": passed,
        "total": len(results),
        "all_pass": passed == len(results),
        "post_deployment_claim": "NOT_GRANTED_BY_THIS_SUITE",
        "results": results,
    }
