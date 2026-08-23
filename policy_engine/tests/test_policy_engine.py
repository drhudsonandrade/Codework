from __future__ import annotations
import os, shutil, tempfile, unittest
from pathlib import Path
from genoma_policy.engine import CRITICAL_FINAL_AUDIT_KEYS, PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import RulesetError, enforce_unique_active_ruleset, load_ruleset, verify_external_manifest
from genoma_policy.scaffold import scaffold_manifest
from genoma_policy.smoke import run_smoke
ROOT=Path(__file__).resolve().parents[1]; RULESET=resolve_ruleset_path(ROOT); HASH_MANIFEST=resolve_manifest_path(RULESET,ROOT); EXPECTED_SHA256="ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
class RulesetTests(unittest.TestCase):
 def test_normative_identity_hash_and_263_sections(self):
  r=load_ruleset(RULESET); self.assertEqual(r.status,"VIGENTE"); self.assertEqual(r.version,"v3.4"); self.assertEqual(r.effective_date,"17/08/2026");
  if os.environ.get("GENOMA_EXPECT_CANONICAL_SHA")=="1": self.assertEqual(r.sha256,EXPECTED_SHA256)
  self.assertEqual([s.number for s in r.sections],list(range(263))); verify_external_manifest(r,HASH_MANIFEST)
 def test_duplicate_vigente_fails_closed(self):
  with tempfile.TemporaryDirectory() as td:
   target=Path(td)/RULESET.name; shutil.copyfile(RULESET,target); shutil.copyfile(RULESET,Path(td)/"REGRAS_PROJETO_GENOMA_DUPLICATE.txt")
   with self.assertRaises(RulesetError): enforce_unique_active_ruleset(td,target)
class PolicyEngineTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.ruleset=load_ruleset(RULESET); cls.engine=PolicyEngine(cls.ruleset,external_manifest=HASH_MANIFEST)
 def valid_analysis_manifest(self):
  m=scaffold_manifest(self.ruleset,case_id="TEST"); m["session_id"]="test-session"; m["inputs"]=[{"id":"input-1","kind":"vcf","source":"test-fixture","sha256":"abc123"}]; m["consent"]={"verified":True,"version":"test-v1","authorized_domains":["research"]}; m["qc"]={"status":"EXECUTADO","passed":True,"evidence_refs":["fixture:qc"]}; m["sources"]=[{"id":"fixture:attestation","mutable":False,"status":"VERIFICADO","accessible":True,"locator":"fixture://attestation","retrieval_evidence":{"method":"fixture","result_digest":"sha256:fixture"}}]
  # This fixture used to attest all 263 rules NOT_APPLICABLE under one repeated
  # justification, which is the shape an external audit rode to a passing FINAL report over
  # zero sources and zero findings. A fixture that models the bypass cannot also be the
  # baseline every other test builds on, so it now models an honest triage: the execution
  # bootstrap is applicable and satisfied with evidence, and the rules that genuinely do
  # not apply say why per rule rather than sharing one sentence.
  for a in m["section_attestations"]:
   a.update({"applicability":"NOT_APPLICABLE","status":"VERIFICADO","decision":"NOT_APPLICABLE","justification":f"rule {a['section']} is not triggered by this fixture's operation","evidence_refs":[]}); a["trace"].update({"run_id":"test-session","created_at":"2026-08-15T23:00:00-03:00"})
  bootstrap=next(a for a in m["section_attestations"] if a["section"]==0)
  bootstrap.update({"applicability":"APPLICABLE","status":"VERIFICADO","decision":"SATISFIED","justification":"execution bootstrap consulted before this analysis","evidence_refs":["fixture:attestation"]})
  bootstrap["trace"].update({"input_sha256":["a"*64],"output_sha256":["b"*64]})
  return m
 def test_post_deployment_is_nonblocking_pending_by_default(self):
  r=self.engine.evaluate(self.valid_analysis_manifest()); g=next(g for g in r.gates if g.gate=="POST_DEPLOYMENT_GATE"); self.assertEqual(g.state.value,"PENDING"); self.assertFalse(g.blocking); self.assertTrue(r.ready)
 def test_vus_cannot_change_conduct_without_confirmation(self):
  m=self.valid_analysis_manifest(); m["claims"]=[{"id":"v1","nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P2","evidence_refs":["clinvar"],"variant_classification":"VUS","changes_conduct":True,"confirmation":{"status":"PROPOSTO"}}]; m["sources"]=[{"id":"clinvar","mutable":True,"status":"VERIFICADO","accessible":True,"version":"fixture","checked_at":"2026-08-15","locator":"https://www.ncbi.nlm.nih.gov/clinvar/","primary_or_official":True,"retrieval_evidence":{"method":"fixture","result_digest":"sha256:fixture"}}]; r=self.engine.evaluate(m); self.assertEqual(next(g for g in r.gates if g.gate=="CLINICAL_CONFIRMATION_GATE").state.value,"FAIL"); self.assertFalse(r.ready)
 def test_runtime_gate_is_session_specific(self):
  m=self.valid_analysis_manifest(); m["operation"]["requires_real_calling"]=True; m["runtime_resource_gate"]={"session_id":"old-session","checks":{}}; r=self.engine.evaluate(m); self.assertEqual(next(g for g in r.gates if g.gate=="RUNTIME_RESOURCE_GATE").state.value,"FAIL")
 def publishable_final_manifest(self):
  """A FINAL manifest that carries the substance a final audited report describes.

  The fifteen criteria are booleans the manifest sets about itself. Passing them is
  necessary and, on its own, was sufficient — which is how a final report could be declared
  complete over nothing. This fixture supplies what those booleans claim exists.
  """
  m=self.valid_analysis_manifest(); m["operation"]["output"]="FINAL_AUDITED_REPORT"
  m["claims"]=[{"id":"c1","nature":"ASSOCIAÇÃO","domain":"PESQUISA","status":"INFERIDO","priority":"P5","evidence_refs":["fixture:attestation"],"ancestry_context":"coorte de descoberta do fixture, ancestralidade declarada"}]
  m["sections"]=[{"id":"s1","title":"Resumo","body":"conteúdo do fixture"},{"id":"s-tec","title":"Camada técnica","body":"t"},{"id":"s-leigo","title":"Camada simples","body":"l"}]
  m["report_layers"]={"technical":"s-tec","lay":"s-leigo"}
  m["remaining_gaps"]=["nenhuma região difícil foi interrogada por este fixture"]
  m["database_query_manifest"]=[{"database":"fixture","version":"1","queried_at":"2026-08-15"}]
  # The classes section 117 requires accounted for and the loci sections 174/238 name, each
  # with the reason that is its limit of detection. Asserting the booleans without these is
  # what `_final_audit_substance_reasons` now refuses.
  m["capability_matrix"]={
   **{k:{"status":"NÃO DISPONÍVEL","reason":f"{k} não é medido por este fixture"}
      for k in ("indel","CNV","SV","repeat_expansion","mtDNA","HLA","KIR","noncoding","mosaicism",
                "CYP2D6","SMN1_SMN2","PMS2","GBA1")},
   "SNV":{"status":"EXECUTADO","method":"fixture de teste"},
  }
  m["final_audit"]={k:True for k in CRITICAL_FINAL_AUDIT_KEYS}
  return m
 def test_final_audit_requires_all_15_criteria(self):
  m=self.publishable_final_manifest(); m["final_audit"]={k:True for k in CRITICAL_FINAL_AUDIT_KEYS[:-1]}; self.assertEqual(next(g for g in self.engine.evaluate(m).gates if g.gate=="FINAL_AUDIT_GATE").state.value,"FAIL"); m["final_audit"][CRITICAL_FINAL_AUDIT_KEYS[-1]]=True; self.assertEqual(next(g for g in self.engine.evaluate(m).gates if g.gate=="FINAL_AUDIT_GATE").state.value,"PASS")
 def test_report_exposes_four_plane_states(self):
  r=self.engine.evaluate(self.valid_analysis_manifest()).to_dict(); self.assertEqual(set(r["planes"]),{"policy_control","scientific_data","evidence","audit"}); self.assertEqual(r["planes"]["policy_control"]["state"],"PASS")
 def test_deterministic_safety_smoke_15_of_15(self):
  r=run_smoke(self.engine); self.assertTrue(r["all_pass"]); self.assertEqual((r["passed"],r["total"]),(15,15)); self.assertEqual(r["post_deployment_claim"],"NOT_GRANTED_BY_THIS_SUITE")


class SelfAttestationBypassTests(unittest.TestCase):
 """The manifest declares its own compliance, so each declaration needs a check behind it.

 An external audit obtained ready_for_requested_operation=true and a FINAL report from a
 manifest that attested all 263 rules NOT_APPLICABLE under one repeated justification, cited
 zero sources, carried zero findings and set every final-audit boolean itself. Each test here
 rebuilds one piece of that manifest and requires the engine to refuse it.
 """
 @classmethod
 def setUpClass(cls):
  cls.ruleset=load_ruleset(RULESET); cls.engine=PolicyEngine(cls.ruleset,external_manifest=HASH_MANIFEST)

 def _base(self):
  helper=PolicyEngineTests(); helper.ruleset=self.ruleset; helper.engine=self.engine
  return helper.publishable_final_manifest()

 def _gate(self,manifest,name):
  return next(g for g in self.engine.evaluate(manifest).gates if g.gate==name)

 def test_the_reported_bypass_manifest_is_refused(self):
  # The whole shape at once, as the audit described it.
  m=self._base(); m["sources"]=[]; m["claims"]=[]; m["sections"]=[]
  for a in m["section_attestations"]:
   a.update({"applicability":"NOT_APPLICABLE","status":"VERIFICADO","decision":"NOT_APPLICABLE","justification":"smoke fixture","evidence_refs":[]})
  r=self.engine.evaluate(m); self.assertFalse(r.ready)
  self.assertEqual(self._gate(m,"RULE_COVERAGE_GATE").state.value,"FAIL")
  self.assertEqual(self._gate(m,"FINAL_AUDIT_GATE").state.value,"FAIL")

 def test_every_rule_not_applicable_is_refused_for_an_analysis(self):
  m=self._base()
  for a in m["section_attestations"]:
   a.update({"applicability":"NOT_APPLICABLE","decision":"NOT_APPLICABLE","status":"VERIFICADO","evidence_refs":[],"justification":f"rule {a['section']} not triggered"})
  reasons=" ".join(self._gate(m,"RULE_COVERAGE_GATE").reasons)
  self.assertIn("no rule of",reasons)

 def test_the_execution_bootstrap_cannot_be_declared_inapplicable(self):
  m=self._base()
  next(a for a in m["section_attestations"] if a["section"]==0).update({"applicability":"NOT_APPLICABLE","decision":"NOT_APPLICABLE","evidence_refs":[],"justification":"rule 0 not triggered"})
  self.assertIn("execution bootstrap"," ".join(self._gate(m,"RULE_COVERAGE_GATE").reasons))

 def test_one_justification_cannot_answer_every_inapplicable_rule(self):
  m=self._base()
  for a in m["section_attestations"]:
   if a["applicability"]=="NOT_APPLICABLE": a["justification"]="não se aplica"
  self.assertIn("share a single justification"," ".join(self._gate(m,"RULE_COVERAGE_GATE").reasons))

 def test_grouping_rules_under_a_few_honest_reasons_is_allowed(self):
  # The check targets one text answering everything, not repetition itself: several rules
  # genuinely sharing a reason is how an honest triage reads.
  m=self._base()
  na=[a for a in m["section_attestations"] if a["applicability"]=="NOT_APPLICABLE"]
  for idx,a in enumerate(na): a["justification"]=f"grupo {idx%4}: domínio não solicitado"
  self.assertEqual(self._gate(m,"RULE_COVERAGE_GATE").state.value,"PASS")

 def test_a_final_report_over_zero_sources_is_refused(self):
  m=self._base(); m["sources"]=[]
  self.assertIn("declares no source"," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_a_final_report_over_zero_findings_is_refused(self):
  m=self._base(); m["claims"]=[]
  self.assertIn("declares no claim"," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_a_criterion_asserted_without_its_evidence_is_a_false_declaration(self):
  for key,mutate,needle in (
   ("no_accidental_empty_sections",lambda m: m.update({"sections":[]}),"no section at all"),
   ("remaining_gaps_listed",lambda m: m.pop("remaining_gaps",None),"lists no gap"),
   ("master_database_query_manifest",lambda m: m.pop("database_query_manifest",None),"no query manifest"),
   ("qc_documented",lambda m: m["qc"].update({"evidence_refs":[]}),"no evidence_refs"),
  ):
   with self.subTest(criterion=key):
    m=self._base(); mutate(m)
    self.assertIn(needle," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_domains_separated_is_checked_against_the_claims(self):
  m=self._base(); m["claims"]=[{"id":"c1","nature":"ASSOCIAÇÃO","domain":"","status":"INFERIDO","priority":"P5","evidence_refs":["fixture:attestation"]}]
  self.assertIn("domains_separated"," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_every_one_of_the_fifteen_criteria_now_has_a_check_behind_it(self):
  """Seven of the fifteen were checked; the other eight were booleans the manifest set.

  A final audited report could therefore declare its variant-class coverage explicit with no
  capability matrix at all, its complex regions flagged with none named, its ancestry
  references considered over associations that named no cohort, and its two reading layers
  present with no layer anywhere in the manifest. Each row below removes exactly the
  substance one criterion asserts and requires the gate to name that criterion.
  """
  for key,mutate,needle in (
   ("critical_databases_current",
    lambda m: m["sources"].append({"id":"mutavel","mutable":True,"status":"VERIFICADO","accessible":True,"version":"1","locator":"https://x","retrieval_evidence":{"method":"f","result_digest":"sha256:f"}}),
    "no readable checked_at"),
   ("variant_class_coverage_explicit",
    lambda m: m["capability_matrix"].pop("mtDNA",None),
    "carry no declared status"),
   ("lod_described",
    lambda m: m["capability_matrix"].update({"CNV":{"status":"NÃO DISPONÍVEL"}}),
    "neither a method nor a reason"),
   ("complex_regions_flagged",
    lambda m: m["capability_matrix"].pop("CYP2D6",None),
    "absent from the capability matrix"),
   ("ancestry_reference_considered",
    lambda m: m["claims"][0].pop("ancestry_context",None),
    "carry no ancestry_context"),
   ("absolute_vs_relative_risk_separated",
    lambda m: m["claims"][0].update({"odds_ratio":1.4}),
    "no risk_type"),
   ("report_has_technical_and_lay_layers",
    lambda m: m.pop("report_layers",None),
    "names no 'technical' layer"),
   ("scientific_novelty_radar",
    lambda m: m["database_query_manifest"][0].pop("queried_at",None),
    "no readable queried_at"),
  ):
   with self.subTest(criterion=key):
    m=self._base(); mutate(m)
    joined=" ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons)
    self.assertIn(needle,joined)
    self.assertIn(key,joined)

 def test_a_limit_of_detection_for_no_variant_class_is_not_a_limit_of_detection(self):
  """`all(...)` over an empty matrix is true, and so is "no entry lacks a reason"."""
  m=self._base(); m["capability_matrix"]={}
  self.assertIn("no capability matrix"," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_a_risk_magnitude_with_a_declared_type_is_accepted(self):
  # Negative control: the check refuses an unlabelled magnitude, not every magnitude.
  m=self._base(); m["claims"][0].update({"odds_ratio":1.4,"risk_type":"OR"})
  self.assertEqual(self._gate(m,"FINAL_AUDIT_GATE").state.value,"PASS")

 def test_a_layer_pointing_at_a_section_that_does_not_exist_is_refused(self):
  m=self._base(); m["report_layers"]={"technical":"s-tec","lay":"s-inexistente"}
  self.assertIn("not a section this manifest carries"," ".join(self._gate(m,"FINAL_AUDIT_GATE").reasons))

 def test_a_substantive_final_manifest_still_passes(self):
  # Negative control: the refusals must not have made publication impossible in general.
  self.assertEqual(self._gate(self._base(),"FINAL_AUDIT_GATE").state.value,"PASS")
  self.assertEqual(self._gate(self._base(),"RULE_COVERAGE_GATE").state.value,"PASS")


if __name__=="__main__": unittest.main()
