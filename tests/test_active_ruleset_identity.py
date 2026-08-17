import unittest


EXPECTED = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}


class ActiveRulesetIdentityTest(unittest.TestCase):
    def test_array_qc_and_annotation_emit_canonical_v34_identity(self):
        import array_pipeline
        from array_pipeline import annotation, qc

        self.assertEqual(array_pipeline.RULESET, EXPECTED)
        self.assertEqual(qc.RULESET, EXPECTED)
        self.assertEqual(annotation.RULESET, EXPECTED)

    def test_policy_post_deployment_identity_is_not_hard_coded_to_v33(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1] / "policy_engine" / "genoma_policy" / "gates_audit.py").read_text(encoding="utf-8")
        self.assertIn('expected_identity = f"{self.ruleset.version}/VIGENTE/{self.ruleset.effective_date}"', text)
        self.assertNotIn('identity_recovered") == "v3.3/VIGENTE/14/08/2026"', text)


if __name__ == "__main__":
    unittest.main()
