from __future__ import annotations

from copy import deepcopy
from typing import Any

from .engine import PolicyEngine
from .ruleset import Ruleset
from .scaffold import scaffold_manifest


def _baseline(ruleset: Ruleset) -> dict[str, Any]:
    m = scaffold_manifest(ruleset, case_id="SMOKE")
    m["operation"].update({"analysis_relevant": False, "requires_real_calling": False, "output": "ANALYSIS"})
    m["consent"] = {"verified": True, "version": "smoke", "authorized_domains": ["research"]}
    m["qc"] = {"status": "EXECUTADO", "passed": True, "evidence_refs": ["smoke:qc"]}
    m["section_attestations"] = []; m["post_deployment"] = {}; return m


def _claim(**overrides: Any) -> dict[str, Any]:
    claim = {"id": "C1", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": []}
    claim.update(overrides); return claim


def _all_na(ruleset: Ruleset) -> list[dict[str, Any]]:
    return [{"section": s.number, "rule_id": s.rule_id, "rule_sha256": s.sha256, "applicability": "NOT_APPLICABLE", "status": "VERIFICADO", "decision": "NOT_APPLICABLE", "justification": "smoke fixture", "evidence_refs": [], "trace": {"attestation_id": f"smoke:{s.rule_id}", "created_at": "2026-08-15T23:00:00-03:00", "actor_type": "SOFTWARE", "actor_id": "genoma-policy-smoke", "method": "fixture", "run_id": "SMOKE", "input_sha256": [], "output_sha256": [], "tool_versions": {"genoma-policy-engine": "0.3.0"}}} for s in ruleset.sections]


def smoke_cases(ruleset: Ruleset) -> list[tuple[str, str, dict[str, Any]]]:
    cases: list[tuple[str, str, dict[str, Any]]] = []
    m=_baseline(ruleset); m["claims"]=[_claim(negative_result=True,disease_excluded=True,all_relevant_mechanisms_assessed=False)]; cases.append(("SMOKE-01","NEGATIVE_EVIDENCE_SCOPE_GATE",m))
    m=_baseline(ruleset); m["operation"]["analysis_relevant"]=True; m["inputs"]=[{"id":"x","kind":"vcf","source":"fixture","sha256":"abc"}]; m["qc"]={"status":"EXECUTADO","passed":False,"evidence_refs":["smoke:qc"]}; m["claims"]=[_claim(nature="FATO CONFIRMADO",technical_quality_flag="LOW")]; m["section_attestations"]=_all_na(ruleset); cases.append(("SMOKE-02","QC_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(cross_build_comparison=True,source_build="GRCh37",target_build="GRCh38",build_harmonized=False,ref_alt_verified=False,strand_verified=False)]; cases.append(("SMOKE-03","BUILD_HARMONIZATION_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(clinvar_conflict=True,clinvar_simple_vote=True,clinvar_conflict_resolution={"review_status_considered":False,"vcep_considered":False,"condition_matched":False,"evidence_reviewed":False,"dates_reviewed":False,"conflict_dossier":False})]; cases.append(("SMOKE-04","CLINVAR_CONFLICT_GATE",m))
    m=_baseline(ruleset); m["reproductive"]={"carrier_partner_recommendation":True,"partner_full_relevant_scope":False}; cases.append(("SMOKE-05","REPRODUCTIVE_GATE",m))
    m=_baseline(ruleset); m["reproductive"]={"both_carriers_same_gene":True,"causal_combination_verified":False,"inheritance_verified":True,"phase_addressed":False}; cases.append(("SMOKE-06","REPRODUCTIVE_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(prs=True,ancestry_calibrated=False)]; cases.append(("SMOKE-07","ANCESTRY_AWARE_GATE",m))
    m=_baseline(ruleset); m["reproductive"]={"pgt_p_used_as_clinically_validated":True}; cases.append(("SMOKE-08","REPRODUCTIVE_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(test_type="cfDNA",diagnosis_closed=True)]; cases.append(("SMOKE-09","SCREENING_DIAGNOSIS_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(pgx_gene="CYP2D6",generic_vcf_only=True,specialized_haplotype_workflow=False)]; cases.append(("SMOKE-10","PGX_COMPLEX_LOCUS_GATE",m))
    m=_baseline(ruleset); m["sources"]=[{"id":"db","mutable":False,"status":"VERIFICADO","accessible":False}]; cases.append(("SMOKE-11","CAPABILITY_HONESTY_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(trait="personality",single_candidate_variant_deterministic=True)]; cases.append(("SMOKE-12","TRAIT_NONDETERMINISM_GATE",m))
    m=_baseline(ruleset); m["claims"]=[_claim(uses_haplogroup=True,direct_ethnicity_or_descent=True)]; cases.append(("SMOKE-13","ANCESTRY_AWARE_GATE",m))
    m=_baseline(ruleset); m["operation"]["analysis_relevant"]=True; m["inputs"]=[{"id":"wgs","kind":"wgs","source":"fixture","sha256":"abc"}]; m["consent"]={"verified":True,"version":"smoke","authorized_domains":["clinical"]}; m["qc"]={"status":"PROPOSTO","passed":False,"evidence_refs":[]}; m["section_attestations"]=_all_na(ruleset); cases.append(("SMOKE-14","QC_GATE",m))
    m=_baseline(ruleset); m["operation"]["output"]="FINAL_AUDITED_REPORT"; m["final_audit"]={}; cases.append(("SMOKE-15","FINAL_AUDIT_GATE",m))
    return cases


def run_smoke(engine: PolicyEngine) -> dict[str, Any]:
    results=[]; passed=0
    for case_id, expected_gate, manifest in smoke_cases(engine.ruleset):
        report=engine.evaluate(deepcopy(manifest)); matched=[g for g in report.gates if g.gate==expected_gate and g.state.value=="FAIL"]; ok=bool(matched); passed+=int(ok)
        results.append({"case":case_id,"expected_blocking_gate":expected_gate,"pass":ok,"observed":[g.to_dict() for g in report.gates if g.gate==expected_gate]})
    return {"suite":"GENOMA v3.3 independent deterministic safety smoke","passed":passed,"total":len(results),"all_pass":passed==len(results),"post_deployment_claim":"NOT_GRANTED_BY_THIS_SUITE","results":results}
