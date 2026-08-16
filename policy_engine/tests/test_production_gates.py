from __future__ import annotations

import unittest
from pathlib import Path

from genoma_policy.engine import PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset
from genoma_policy.scaffold import scaffold_manifest

ROOT = Path(__file__).resolve().parents[1]
RULESET = resolve_ruleset_path(ROOT)
HASH_MANIFEST = resolve_manifest_path(RULESET, ROOT)


class ProductionSafetyGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruleset = load_ruleset(RULESET)
        cls.engine = PolicyEngine(cls.ruleset, external_manifest=HASH_MANIFEST)

    def base(self):
        m = scaffold_manifest(self.ruleset, case_id="PROD-GATE")
        m["operation"].update({"analysis_relevant": False, "requires_real_calling": False, "output": "ANALYSIS"})
        m["section_attestations"] = []
        return m

    def test_cross_build_comparison_requires_harmonization(self):
        m = self.base()
        m["claims"] = [{
            "id": "x", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": [],
            "cross_build_comparison": True, "source_build": "GRCh37", "target_build": "GRCh38",
            "build_harmonized": False, "ref_alt_verified": False, "strand_verified": False,
        }]
        gate = next(g for g in self.engine.evaluate(m).gates if g.gate == "BUILD_HARMONIZATION_GATE")
        self.assertEqual(gate.state.value, "FAIL")

    def test_cross_build_comparison_passes_after_full_harmonization(self):
        m = self.base()
        m["claims"] = [{
            "id": "x", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": [],
            "cross_build_comparison": True, "source_build": "GRCh37", "target_build": "GRCh38",
            "build_harmonized": True, "ref_alt_verified": True, "strand_verified": True,
        }]
        gate = next(g for g in self.engine.evaluate(m).gates if g.gate == "BUILD_HARMONIZATION_GATE")
        self.assertEqual(gate.state.value, "PASS")

    def test_clinvar_conflict_rejects_simple_vote(self):
        m = self.base()
        m["claims"] = [{
            "id": "x", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": [],
            "clinvar_conflict": True, "clinvar_simple_vote": True,
            "clinvar_conflict_resolution": {},
        }]
        gate = next(g for g in self.engine.evaluate(m).gates if g.gate == "CLINVAR_CONFLICT_GATE")
        self.assertEqual(gate.state.value, "FAIL")

    def test_clinvar_conflict_requires_full_dossier(self):
        m = self.base()
        m["claims"] = [{
            "id": "x", "nature": "ASSOCIAÇÃO", "domain": "PESQUISA", "status": "INFERIDO", "priority": "P5", "evidence_refs": [],
            "clinvar_conflict": True, "clinvar_simple_vote": False,
            "clinvar_conflict_resolution": {
                "review_status_considered": True, "vcep_considered": True, "condition_matched": True,
                "evidence_reviewed": True, "dates_reviewed": True, "conflict_dossier": True,
            },
        }]
        gate = next(g for g in self.engine.evaluate(m).gates if g.gate == "CLINVAR_CONFLICT_GATE")
        self.assertEqual(gate.state.value, "PASS")


if __name__ == "__main__":
    unittest.main()
