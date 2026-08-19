from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from scripts import genoma_audit
from scripts.genoma_audit import audit, verify_ruleset_identity


class GenomaAuditTest(unittest.TestCase):
    def test_audit_never_grants_post_deployment(self):
        result = audit(allow_template_sealed_only=True)
        self.assertEqual(result["post_deployment_status"], "PENDENTE")
        self.assertIn("Production Witness", result["post_deployment_note"])

    def test_all_four_planes_are_explicit(self):
        result = audit(allow_template_sealed_only=True)
        self.assertEqual(set(result["four_planes"]), {"policy_control", "scientific_data", "evidence", "audit"})
        ids = {x["id"] for x in result["checks"]}
        self.assertIn("SCIENTIFIC_DATA_PLANE_ARRAY", ids)
        self.assertIn("EVIDENCE_ANNOTATION_PLANE", ids)
        self.assertIn("SUPPLY_CHAIN_LOCK", ids)
        self.assertIn("TEMPLATE_BINARY_SOURCE_STORE", ids)

    def test_ruleset_block_is_decoded_evidence_not_a_literal_claim(self):
        result = audit(allow_template_sealed_only=True)
        gate = next(c for c in result["checks"] if c["id"] == "RULESET_GATE")
        self.assertTrue(gate["blocking"])
        self.assertEqual(gate["state"], "PASS")
        ruleset = result["ruleset"]
        self.assertEqual(ruleset["status"], normative.STATUS)
        self.assertEqual(ruleset["version"], normative.VERSION)
        self.assertEqual(ruleset["effective_date"], normative.EFFECTIVE_DATE)
        self.assertEqual(ruleset["sha256"], normative.RAW_SHA256)
        self.assertEqual(ruleset["normative_identifier"], normative.NORMATIVE_IDENTIFIER)
        self.assertEqual(ruleset["section_count"], normative.SECTION_COUNT)
        self.assertIn("decoded", ruleset["verification"])

    def test_tampered_normative_source_blocks_the_policy_control_plane(self):
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td)
            shutil.copytree(ROOT / "normative", fake_root / "normative")
            shutil.copytree(ROOT / "manifests", fake_root / "manifests")
            part = next((fake_root / "normative/sealed/parts").glob("part-000.b64"))
            payload = bytearray(part.read_bytes())
            payload[10] = ord("A") if payload[10] != ord("A") else ord("B")
            part.write_bytes(bytes(payload))

            original = genoma_audit.ROOT
            genoma_audit.ROOT = fake_root
            try:
                ok, block, detail = verify_ruleset_identity()
            finally:
                genoma_audit.ROOT = original

        self.assertFalse(ok)
        self.assertEqual(block["status"], "NÃO DISPONÍVEL")
        self.assertIn("RULESET NÃO DISPONÍVEL/CONFLITANTE", detail)

    def test_second_active_ruleset_manifest_breaks_uniqueness(self):
        with tempfile.TemporaryDirectory() as td:
            fake_root = Path(td)
            shutil.copytree(ROOT / "normative", fake_root / "normative")
            shutil.copytree(ROOT / "manifests", fake_root / "manifests")
            # REGRA DE UNICIDADE: a second active manifest may not coexist.
            (fake_root / "manifests" / "RULESET_V9.9.sha256").write_text(
                f"{'0' * 64}  REGRAS_PROJETO_GENOMA_VIGENTE_v9.9_2026-12-31.txt\n",
                encoding="ascii",
            )
            original = genoma_audit.ROOT
            genoma_audit.ROOT = fake_root
            try:
                ok, block, detail = verify_ruleset_identity()
            finally:
                genoma_audit.ROOT = original

        self.assertFalse(ok)
        self.assertEqual(block["status"], "NÃO DISPONÍVEL")
        self.assertIn("unique_active_manifest", detail)


class PlaneAggregationTest(unittest.TestCase):
    """The top-level aggregator must not report PASS because it checked nothing.

    `all(... for c in checks if c["id"] in {...})` is vacuously True when the filter
    matches nothing, so renaming a check id silently turned its FAIL into a plane PASS —
    in the very function that declares the whole project VERIFICADO.
    """

    def _checks(self, **overrides):
        from scripts.genoma_audit import MIN_BLOCKING_CHECKS, PLANE_CHECKS

        names = [n for group in PLANE_CHECKS.values() for n in group]
        checks = [{"id": n, "state": "PASS", "blocking": True} for n in names]
        while len(checks) < MIN_BLOCKING_CHECKS:
            checks.append({"id": f"FILLER_{len(checks)}", "state": "PASS", "blocking": True})
        for name, state in overrides.items():
            for c in checks:
                if c["id"] == name:
                    c["state"] = state
        return checks

    def test_a_complete_passing_check_set_passes(self):
        from scripts.genoma_audit import _aggregate_planes

        planes = _aggregate_planes(self._checks())
        self.assertEqual(set(planes.values()), {"PASS"})

    def test_a_renamed_check_id_blocks_instead_of_vanishing(self):
        from scripts.genoma_audit import _aggregate_planes

        checks = self._checks()
        for c in checks:
            if c["id"] == "RULESET_GATE":
                c["id"] = "RULESET_GATE_V2"
                c["state"] = "FAIL"
        planes = _aggregate_planes(checks)
        self.assertEqual(planes["policy_control"], "BLOCKED")

    def test_an_empty_check_list_blocks_every_plane(self):
        from scripts.genoma_audit import _aggregate_planes

        planes = _aggregate_planes([])
        self.assertEqual(set(planes.values()), {"BLOCKED"})

    def test_too_few_blocking_checks_blocks_the_audit_plane(self):
        from scripts.genoma_audit import _aggregate_planes

        checks = self._checks()
        for c in checks:
            c["blocking"] = False
        self.assertEqual(_aggregate_planes(checks)["audit"], "BLOCKED")

    def test_a_failing_check_blocks_its_plane(self):
        from scripts.genoma_audit import _aggregate_planes

        planes = _aggregate_planes(self._checks(EVIDENCE_ANNOTATION_PLANE="FAIL"))
        self.assertEqual(planes["evidence"], "BLOCKED")
        self.assertEqual(planes["audit"], "BLOCKED")

    def test_the_real_audit_emits_every_check_the_planes_require(self):
        """Guards against the fix itself rotting: a renamed check now blocks, loudly."""
        from scripts.genoma_audit import PLANE_CHECKS, audit

        emitted = {c["id"] for c in audit()["checks"]}
        for plane, required in PLANE_CHECKS.items():
            for name in required:
                self.assertIn(name, emitted, f"{plane} requires {name}")


if __name__ == "__main__":
    unittest.main()
