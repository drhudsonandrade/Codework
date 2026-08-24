from __future__ import annotations

import unittest

from genoma_policy.engine import PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
from genoma_policy.scaffold import scaffold_manifest


class EvidenceGateHardeningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = __import__("pathlib").Path(__file__).resolve().parents[1]
        ruleset_path = resolve_ruleset_path(root)
        cls.ruleset = load_ruleset(ruleset_path)
        cls.engine = PolicyEngine(cls.ruleset, external_manifest=resolve_manifest_path(ruleset_path, root))

    def manifest(self):
        m = scaffold_manifest(self.ruleset, case_id="EVIDENCE-HARDENING")
        m["session_id"] = "evidence-session"
        m["inputs"] = [{"id":"input-1","kind":"vcf","source":"fixture","sha256":"abc123"}]
        m["consent"] = {"verified": True, "version":"v1", "authorized_domains":["clinical"]}
        m["qc"] = {"status":"EXECUTADO", "passed":True, "evidence_refs":["fixture:qc"]}
        for a in m["section_attestations"]:
            a.update({"applicability":"NOT_APPLICABLE","status":"VERIFICADO","decision":"NOT_APPLICABLE","justification":"fixture","evidence_refs":[]})
            a["trace"].update({"run_id":"evidence-session","created_at":"2026-08-16T12:00:00Z"})
        return m

    def test_mutable_verified_source_requires_locator_and_query_trace(self):
        m = self.manifest()
        m["sources"] = [{
            "id":"clinvar",
            "mutable":True,
            "status":"VERIFICADO",
            "accessible":True,
            "version":"2026-08-16",
            "checked_at":"2026-08-16",
        }]
        m["claims"] = [{"id":"c1","domain":"CLÍNICO","nature":"ASSOCIAÇÃO","status":"INFERIDO","priority":"P3","evidence_refs":["clinvar"]}]
        result = self.engine.evaluate(m)
        gate = next(g for g in result.gates if g.gate == "EVIDENCE_RECENCY_GATE")
        self.assertEqual(gate.state.value, "FAIL")
        self.assertTrue(any("locator" in reason for reason in gate.reasons))
        self.assertTrue(any("retrieval_evidence" in reason for reason in gate.reasons))

    def test_mutable_source_with_trace_passes_evidence_gate(self):
        m = self.manifest()
        m["sources"] = [{
            "id":"clinvar",
            "mutable":True,
            "status":"VERIFICADO",
            "accessible":True,
            "version":"2026-08-16",
            "checked_at":"2026-08-16",
            "locator":"https://www.ncbi.nlm.nih.gov/clinvar/",
            "primary_or_official":True,
            "retrieval_evidence":{"method":"https","result_digest":"sha256:fixture"},
        }]
        m["claims"] = [{"id":"c1","domain":"CLÍNICO","nature":"ASSOCIAÇÃO","status":"INFERIDO","priority":"P3","evidence_refs":["clinvar"]}]
        result = self.engine.evaluate(m)
        gate = next(g for g in result.gates if g.gate == "EVIDENCE_RECENCY_GATE")
        self.assertEqual(gate.state.value, "PASS")

    def test_clinical_claim_requires_at_least_one_primary_or_official_source(self):
        m = self.manifest()
        m["sources"] = [{
            "id":"secondary",
            "mutable":False,
            "status":"VERIFICADO",
            "accessible":True,
            "locator":"https://example.invalid/review",
            "primary_or_official":False,
            "retrieval_evidence":{"method":"file","result_digest":"sha256:fixture"},
        }]
        m["claims"] = [{"id":"c1","domain":"CLÍNICO","nature":"ASSOCIAÇÃO","status":"INFERIDO","priority":"P3","evidence_refs":["secondary"]}]
        result = self.engine.evaluate(m)
        gate = next(g for g in result.gates if g.gate == "EVIDENCE_RECENCY_GATE")
        self.assertEqual(gate.state.value, "FAIL")
        self.assertTrue(any("primary/official" in reason for reason in gate.reasons))


if __name__ == "__main__":
    unittest.main()
