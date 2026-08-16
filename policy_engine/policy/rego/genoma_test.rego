package genoma.guard_test

import rego.v1
import data.genoma.guard

base := {"ruleset":{"version":"v3.3","effective_date":"14/08/2026","sha256":"187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"},"operation":{"analysis_relevant":false},"claims":[],"sources":[]}

test_valid_baseline if guard.allow with input as base

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
