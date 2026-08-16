from __future__ import annotations
import unittest
from pathlib import Path
from genoma_policy.attestation import validate_section_attestation
from genoma_policy.paths import resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
ROOT=Path(__file__).resolve().parents[1]; RULESET=resolve_ruleset_path(ROOT)
class AttestationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls): cls.section=load_ruleset(RULESET).sections[0]
 def valid(self):
  s=self.section
  return {"section":s.number,"rule_id":s.rule_id,"rule_sha256":s.sha256,"applicability":"APPLICABLE","status":"VERIFICADO","decision":"SATISFIED","justification":"explicit review","evidence_refs":["ev:1"],"trace":{"attestation_id":"att:000","created_at":"2026-08-15T23:00:00-03:00","actor_type":"SOFTWARE","actor_id":"genoma-policy-engine","method":"deterministic+attestation","run_id":"run:1","input_sha256":["a"*64],"output_sha256":["b"*64],"tool_versions":{"genoma-policy-engine":"0.2.0"}}}
 def test_valid_traced_attestation_passes(self): self.assertEqual(validate_section_attestation(self.valid(),self.section,{"ev:1"}),[])
 def test_missing_justification_fails(self):
  a=self.valid(); a["justification"]=""; self.assertTrue(any("justification" in r for r in validate_section_attestation(a,self.section,{"ev:1"})))
 def test_satisfied_without_evidence_fails(self):
  a=self.valid(); a["evidence_refs"]=[]; self.assertTrue(any("evidence" in r for r in validate_section_attestation(a,self.section,set())))
 def test_mismatched_rule_hash_fails(self):
  a=self.valid(); a["rule_sha256"]="0"*64; self.assertTrue(any("rule_sha256" in r for r in validate_section_attestation(a,self.section,{"ev:1"})))
 def test_proposed_cannot_claim_satisfied(self):
  a=self.valid(); a["status"]="PROPOSTO"; self.assertTrue(any("PROPOSTO" in r and "SATISFIED" in r for r in validate_section_attestation(a,self.section,{"ev:1"})))
 def test_not_applicable_pair_is_structured(self):
  a=self.valid(); a.update({"applicability":"NOT_APPLICABLE","status":"VERIFICADO","decision":"NOT_APPLICABLE","justification":"not applicable","evidence_refs":[]}); self.assertEqual(validate_section_attestation(a,self.section,set()),[])
if __name__=="__main__": unittest.main()
