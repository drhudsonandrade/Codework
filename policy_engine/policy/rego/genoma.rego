package genoma.guard

import rego.v1

default allow := false

allowed_status := {"EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL"}
allowed_nature := {"FATO CONFIRMADO", "INFERÊNCIA", "ASSOCIAÇÃO", "HIPÓTESE", "DESCONHECIDO"}
allowed_domain := {"CLÍNICO", "PREDISPOSIÇÃO", "PESQUISA", "CURIOSIDADE"}
allowed_priority := {"P1", "P2", "P3", "P4", "P5"}

# Without this the checks below are all undefined when `ruleset` is absent, so no deny
# fires and a manifest carrying no ruleset at all is allowed. object.get supplies a
# defined default, since a built-in applied to a missing key is undefined rather than false.
deny contains "RULESET: ruleset block is required" if not is_object(object.get(input, "ruleset", null))

deny contains "RULESET: status must be VIGENTE" if object.get(input.ruleset, "status", "") != "VIGENTE"
deny contains "RULESET: version must be v3.4" if object.get(input.ruleset, "version", "") != "v3.4"
deny contains "RULESET: effective date must be 17/08/2026" if object.get(input.ruleset, "effective_date", "") != "17/08/2026"
deny contains "RULESET: canonical filename mismatch" if object.get(input.ruleset, "canonical_filename", "") != "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
deny contains "RULESET: canonical SHA-256 mismatch" if object.get(input.ruleset, "sha256", "") != "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"

deny contains "DATA-FIRST: analysis-relevant operation requires input artifacts" if {
  input.operation.analysis_relevant == true
  count(object.get(input, "inputs", [])) == 0
}

deny contains "CONSENT: analysis-relevant operation requires verified consent" if {
  input.operation.analysis_relevant == true
  object.get(object.get(input, "consent", {}), "verified", false) != true
}

deny contains "QC-FIRST: analysis-relevant operation requires passed QC" if {
  input.operation.analysis_relevant == true
  object.get(object.get(input, "qc", {}), "passed", false) != true
}

deny contains msg if {
  some i
  claim := input.claims[i]
  not claim.nature in allowed_nature
  msg := sprintf("TAXONOMY: claim[%d] invalid nature", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  not claim.domain in allowed_domain
  msg := sprintf("TAXONOMY: claim[%d] invalid domain", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  not claim.status in allowed_status
  msg := sprintf("TAXONOMY: claim[%d] invalid operational status", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  not claim.priority in allowed_priority
  msg := sprintf("TAXONOMY: claim[%d] invalid priority", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  upper(object.get(claim, "variant_classification", "")) == "VUS"
  object.get(claim, "changes_conduct", false) == true
  msg := sprintf("CLINICAL: claim[%d] uses VUS to change conduct", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "changes_conduct", false) == true
  status := object.get(object.get(claim, "confirmation", {}), "status", "")
  status != "EXECUTADO"
  status != "VERIFICADO"
  msg := sprintf("CONFIRMATION: claim[%d] conduct-changing claim is unconfirmed", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "negative_result", false) == true
  object.get(claim, "completeness_ref", "") == ""
  msg := sprintf("COMPLETENESS: claim[%d] negative result lacks completeness reference", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "cross_build_comparison", false) == true
  object.get(claim, "build_harmonized", false) != true
  msg := sprintf("BUILD: claim[%d] comparison before build harmonization", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "cross_build_comparison", false) == true
  object.get(claim, "ref_alt_verified", false) != true
  msg := sprintf("BUILD: claim[%d] REF/ALT not verified", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "cross_build_comparison", false) == true
  object.get(claim, "strand_verified", false) != true
  msg := sprintf("BUILD: claim[%d] strand not verified", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "clinvar_conflict", false) == true
  object.get(claim, "clinvar_simple_vote", false) == true
  msg := sprintf("CLINVAR: claim[%d] conflict resolved by simple vote", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "clinvar_conflict", false) == true
  resolution := object.get(claim, "clinvar_conflict_resolution", {})
  some field in {"review_status_considered", "vcep_considered", "condition_matched", "evidence_reviewed", "dates_reviewed", "conflict_dossier"}
  object.get(resolution, field, false) != true
  msg := sprintf("CLINVAR: claim[%d] incomplete Conflict Dossier field %s", [i, field])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "uses_haplogroup", false) == true
  object.get(claim, "direct_ethnicity_or_descent", false) == true
  msg := sprintf("ANCESTRY: claim[%d] converts haplogroup to ethnicity/direct descent", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "prs", false) == true
  object.get(claim, "ancestry_calibrated", false) != true
  msg := sprintf("PRS: claim[%d] lacks ancestry calibration", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "test_type", "") in {"cfDNA", "NIPT", "screening"}
  object.get(claim, "diagnosis_closed", false) == true
  msg := sprintf("SCREENING: claim[%d] converts screening to diagnosis", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "pgx_gene", "") == "CYP2D6"
  object.get(claim, "generic_vcf_only", false) == true
  object.get(claim, "specialized_haplotype_workflow", false) != true
  msg := sprintf("PGX: claim[%d] CYP2D6 called from generic VCF without specialized workflow", [i])
}

deny contains msg if {
  some i
  claim := input.claims[i]
  object.get(claim, "trait", "") == "personality"
  object.get(claim, "single_candidate_variant_deterministic", false) == true
  msg := sprintf("TRAIT: claim[%d] deterministic personality inference", [i])
}

deny contains msg if {
  some i
  source := input.sources[i]
  object.get(source, "status", "") == "VERIFICADO"
  object.get(source, "accessible", true) == false
  msg := sprintf("CAPABILITY: source[%d] verified while inaccessible", [i])
}

deny contains "REPRODUCTION: PGT-P cannot be treated as established clinical practice" if {
  object.get(object.get(input, "reproductive", {}), "pgt_p_used_as_clinically_validated", false) == true
}

allow if count(deny) == 0
