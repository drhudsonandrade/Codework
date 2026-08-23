package genoma.guard_test

import rego.v1
import data.genoma.guard

base_ruleset := {
  "status": "VIGENTE",
  "version": "v3.4",
  "effective_date": "17/08/2026",
  "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}

base := {
  "ruleset": base_ruleset,
  "operation": {"analysis_relevant": false},
  "claims": [],
  "sources": [],
}

test_valid_baseline if guard.allow with input as base

test_reject_missing_ruleset_status if {
  input_doc := object.union(base, {"ruleset": object.remove(base_ruleset, {"status"})})
  not guard.allow with input as input_doc
}

test_reject_non_vigente_ruleset_status if {
  input_doc := object.union(base, {"ruleset": object.union(base_ruleset, {"status": "PENDENTE"})})
  not guard.allow with input as input_doc
}

test_reject_vus_conduct if {
  input_doc := object.union(base, {"claims":[{"nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P2","variant_classification":"VUS","changes_conduct":true,"confirmation":{"status":"PROPOSTO"}}]})
  not guard.allow with input as input_doc
}

test_reject_universal_prs if {
  input_doc := object.union(base, {"claims":[{"nature":"ASSOCIAÇÃO","domain":"PREDISPOSIÇÃO","status":"INFERIDO","priority":"P4","prs":true,"ancestry_calibrated":false}]})
  not guard.allow with input as input_doc
}

test_reject_cfdna_as_diagnosis if {
  input_doc := object.union(base, {"claims":[{"nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P1","test_type":"cfDNA","diagnosis_closed":true}]})
  not guard.allow with input as input_doc
}

test_reject_haplogroup_direct_descent if {
  input_doc := object.union(base, {"claims":[{"nature":"INFERÊNCIA","domain":"CURIOSIDADE","status":"INFERIDO","priority":"P5","uses_haplogroup":true,"direct_ethnicity_or_descent":true}]})
  not guard.allow with input as input_doc
}

test_reject_cross_build_before_harmonization if {
  input_doc := object.union(base, {"claims":[{"nature":"ASSOCIAÇÃO","domain":"PESQUISA","status":"INFERIDO","priority":"P5","cross_build_comparison":true,"build_harmonized":false,"ref_alt_verified":false,"strand_verified":false}]})
  not guard.allow with input as input_doc
}

test_reject_clinvar_simple_vote if {
  input_doc := object.union(base, {"claims":[{"nature":"ASSOCIAÇÃO","domain":"PESQUISA","status":"INFERIDO","priority":"P5","clinvar_conflict":true,"clinvar_simple_vote":true,"clinvar_conflict_resolution":{}}]})
  not guard.allow with input as input_doc
}
