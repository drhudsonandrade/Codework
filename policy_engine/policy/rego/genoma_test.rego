package genoma.guard_test

import rego.v1
import data.genoma.guard

base_ruleset := {
  "status": "VIGENTE",
  "version": "v3.4",
  "effective_date": "17/08/2026",
  "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt",
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
  input_doc := object.union(object.remove(base, {"ruleset"}), {"ruleset": object.remove(base_ruleset, {"status"})})
  not guard.allow with input as input_doc
}

test_reject_missing_ruleset_version if {
  input_doc := object.union(object.remove(base, {"ruleset"}), {"ruleset": object.remove(base_ruleset, {"version"})})
  not guard.allow with input as input_doc
}

test_reject_missing_ruleset_effective_date if {
  input_doc := object.union(object.remove(base, {"ruleset"}), {"ruleset": object.remove(base_ruleset, {"effective_date"})})
  not guard.allow with input as input_doc
}

test_reject_missing_ruleset_canonical_filename if {
  input_doc := object.union(object.remove(base, {"ruleset"}), {"ruleset": object.remove(base_ruleset, {"canonical_filename"})})
  not guard.allow with input as input_doc
}

test_reject_missing_ruleset_sha256 if {
  input_doc := object.union(object.remove(base, {"ruleset"}), {"ruleset": object.remove(base_ruleset, {"sha256"})})
  not guard.allow with input as input_doc
}

# An entirely absent ruleset is a different input shape from a ruleset that is present
# but incomplete; each one has to fail closed on its own.
test_reject_absent_ruleset if {
  not guard.allow with input as object.remove(base, {"ruleset"})
}

test_ruleset_status_deny_message_is_stable if {
  input_doc := object.union(base, {"ruleset": object.union(base_ruleset, {"status": "PENDENTE"})})
  denials := guard.deny with input as input_doc
  "RULESET: status must be VIGENTE" in denials
}

test_reject_non_vigente_ruleset_status if {
  input_doc := object.union(base, {"ruleset": object.union(base_ruleset, {"status": "PENDENTE"})})
  not guard.allow with input as input_doc
}

test_reject_vus_conduct if {
  input_doc := object.union(base, {"claims":[{"nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P2","variant_classification":"VUS","changes_conduct":true,"confirmation":{"status":"PROPOSTO"}}]})
  not guard.allow with input as input_doc
}

test_vus_conduct_deny_message_is_stable if {
  input_doc := object.union(base, {"claims":[{"nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P2","variant_classification":"VUS","changes_conduct":true,"confirmation":{"status":"PROPOSTO"}}]})
  denials := guard.deny with input as input_doc
  "CLINICAL: claim[0] uses VUS to change conduct" in denials
  "CONFIRMATION: claim[0] conduct-changing claim is unconfirmed" in denials
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

test_inaccessible_verified_source_deny_message_is_stable if {
  input_doc := object.union(base, {"sources":[{"status":"VERIFICADO","accessible":false}]})
  denials := guard.deny with input as input_doc
  "CAPABILITY: source[0] verified while inaccessible" in denials
  not guard.allow with input as input_doc
}
