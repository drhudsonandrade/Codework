from __future__ import annotations
import os, shutil, tempfile, unittest
from pathlib import Path
from genoma_policy.engine import CRITICAL_FINAL_AUDIT_KEYS, PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import RulesetError, enforce_unique_active_ruleset, load_ruleset, verify_external_manifest
from genoma_policy.scaffold import scaffold_manifest
from genoma_policy.smoke import run_smoke
ROOT=Path(__file__).resolve().parents[1]; RULESET=resolve_ruleset_path(ROOT); HASH_MANIFEST=resolve_manifest_path(RULESET,ROOT); EXPECTED_SHA256="187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a"
class RulesetTests(unittest.TestCase):
 def test_normative_identity_hash_and_263_sections(self):
  r=load_ruleset(RULESET); self.assertEqual(r.status,"VIGENTE"); self.assertEqual(r.version,"v3.3"); self.assertEqual(r.effective_date,"14/08/2026");
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
  for a in m["section_attestations"]: a.update({"applicability":"NOT_APPLICABLE","status":"VERIFICADO","decision":"NOT_APPLICABLE","justification":"not triggered by this fixture","evidence_refs":[]}); a["trace"].update({"run_id":"test-session","created_at":"2026-08-15T23:00:00-03:00"})
  return m
 def test_post_deployment_is_nonblocking_pending_by_default(self):
  r=self.engine.evaluate(self.valid_analysis_manifest()); g=next(g for g in r.gates if g.gate=="POST_DEPLOYMENT_GATE"); self.assertEqual(g.state.value,"PENDING"); self.assertFalse(g.blocking); self.assertTrue(r.ready)
 def test_vus_cannot_change_conduct_without_confirmation(self):
  m=self.valid_analysis_manifest(); m["claims"]=[{"id":"v1","nature":"INFERÊNCIA","domain":"CLÍNICO","status":"INFERIDO","priority":"P2","evidence_refs":["clinvar"],"variant_classification":"VUS","changes_conduct":True,"confirmation":{"status":"PROPOSTO"}}]; m["sources"]=[{"id":"clinvar","mutable":True,"status":"VERIFICADO","accessible":True,"version":"fixture","checked_at":"2026-08-15","locator":"https://www.ncbi.nlm.nih.gov/clinvar/","primary_or_official":True,"retrieval_evidence":{"method":"fixture","result_digest":"sha256:fixture"}}]; r=self.engine.evaluate(m); self.assertEqual(next(g for g in r.gates if g.gate=="CLINICAL_CONFIRMATION_GATE").state.value,"FAIL"); self.assertFalse(r.ready)
 def test_runtime_gate_is_session_specific(self):
  m=self.valid_analysis_manifest(); m["operation"]["requires_real_calling"]=True; m["runtime_resource_gate"]={"session_id":"old-session","checks":{}}; r=self.engine.evaluate(m); self.assertEqual(next(g for g in r.gates if g.gate=="RUNTIME_RESOURCE_GATE").state.value,"FAIL")
 def test_final_audit_requires_all_15_criteria(self):
  m=self.valid_analysis_manifest(); m["operation"]["output"]="FINAL_AUDITED_REPORT"; m["final_audit"]={k:True for k in CRITICAL_FINAL_AUDIT_KEYS[:-1]}; self.assertEqual(next(g for g in self.engine.evaluate(m).gates if g.gate=="FINAL_AUDIT_GATE").state.value,"FAIL"); m["final_audit"][CRITICAL_FINAL_AUDIT_KEYS[-1]]=True; self.assertEqual(next(g for g in self.engine.evaluate(m).gates if g.gate=="FINAL_AUDIT_GATE").state.value,"PASS")
 def test_report_exposes_four_plane_states(self):
  r=self.engine.evaluate(self.valid_analysis_manifest()).to_dict(); self.assertEqual(set(r["planes"]),{"policy_control","scientific_data","evidence","audit"}); self.assertEqual(r["planes"]["policy_control"]["state"],"PASS")
 def test_deterministic_safety_smoke_15_of_15(self):
  r=run_smoke(self.engine); self.assertTrue(r["all_pass"]); self.assertEqual((r["passed"],r["total"]),(15,15)); self.assertEqual(r["post_deployment_claim"],"NOT_GRANTED_BY_THIS_SUITE")
if __name__=="__main__": unittest.main()
