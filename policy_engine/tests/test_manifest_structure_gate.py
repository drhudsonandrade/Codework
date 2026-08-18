"""A manifest that cannot be honestly evaluated must fail, not silence the control plane.

`analysis_relevant` and `requires_real_calling` switch the provenance, consent, QC and
runtime gates off when false. A manifest omitting `operation` — or supplying a non-boolean
— therefore turned those gates into unconditional PASS while the report still looked clean.
The execution-manifest schema declares the fields required; MANIFEST_STRUCTURE_GATE
enforces the same contract at evaluation time.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from genoma_policy.engine import PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import load_ruleset

ROOT = Path(__file__).resolve().parents[1]
RULESET = resolve_ruleset_path(ROOT)
HASH_MANIFEST = resolve_manifest_path(RULESET, ROOT)

SILENCED_BY_ANALYSIS_FLAG = ("DATA_PROVENANCE_GATE", "CONSENT_GATE", "QC_GATE")


class ManifestStructureGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ruleset = load_ruleset(RULESET)
        cls.engine = PolicyEngine(ruleset, external_manifest=HASH_MANIFEST)
        cls.ruleset_block = {
            "version": ruleset.version,
            "effective_date": ruleset.effective_date,
            "sha256": ruleset.sha256,
        }

    def _gates(self, manifest):
        report = self.engine.evaluate(manifest)
        return {gate.gate: gate for gate in report.gates}

    def _manifest(self, operation=..., **overrides):
        payload = {
            "case_id": "CASE-STRUCTURE",
            "session_id": "session-structure",
            "ruleset": dict(self.ruleset_block),
            "operation": {
                "name": "structure-probe",
                "analysis_relevant": False,
                "requires_real_calling": False,
                "output": "ANALYSIS",
            },
            "section_attestations": [],
        }
        if operation is not ...:
            if operation is None:
                payload.pop("operation")
            else:
                payload["operation"] = operation
        payload.update(overrides)
        return payload

    def test_well_formed_manifest_passes_the_structure_gate(self):
        gate = self._gates(self._manifest())["MANIFEST_STRUCTURE_GATE"]
        self.assertEqual(gate.state.value, "PASS")
        self.assertEqual(tuple(gate.reasons), ())

    def test_gate_is_blocking(self):
        gate = self._gates(self._manifest())["MANIFEST_STRUCTURE_GATE"]
        self.assertTrue(gate.blocking)

    def test_missing_operation_block_fails_instead_of_silencing_core_gates(self):
        gates = self._gates(self._manifest(operation=None))
        self.assertEqual(gates["MANIFEST_STRUCTURE_GATE"].state.value, "FAIL")
        # The gates that the missing flag would have silenced still report PASS; the
        # structure gate is what stops the manifest from being trusted.
        for name in SILENCED_BY_ANALYSIS_FLAG:
            self.assertIn(name, gates)

    def test_non_boolean_analysis_flag_is_rejected(self):
        for bogus in ("false", 0, None, "true", 1):
            manifest = self._manifest()
            manifest["operation"]["analysis_relevant"] = bogus
            gate = self._gates(manifest)["MANIFEST_STRUCTURE_GATE"]
            self.assertEqual(gate.state.value, "FAIL", f"{bogus!r} was accepted")
            self.assertTrue(any("analysis_relevant" in r for r in gate.reasons))

    def test_non_boolean_real_calling_flag_is_rejected(self):
        manifest = self._manifest()
        manifest["operation"]["requires_real_calling"] = "no"
        gate = self._gates(manifest)["MANIFEST_STRUCTURE_GATE"]
        self.assertEqual(gate.state.value, "FAIL")
        self.assertTrue(any("requires_real_calling" in r for r in gate.reasons))

    def test_unknown_output_kind_is_rejected(self):
        manifest = self._manifest()
        manifest["operation"]["output"] = "WHATEVER"
        gate = self._gates(manifest)["MANIFEST_STRUCTURE_GATE"]
        self.assertEqual(gate.state.value, "FAIL")
        self.assertTrue(any("operation.output" in r for r in gate.reasons))

    def test_identity_and_attestation_fields_are_required(self):
        for key in ("case_id", "session_id", "ruleset", "section_attestations"):
            manifest = self._manifest()
            manifest.pop(key)
            gate = self._gates(manifest)["MANIFEST_STRUCTURE_GATE"]
            self.assertEqual(gate.state.value, "FAIL", f"{key} was not required")
            self.assertTrue(any(key in r for r in gate.reasons))

    def test_blank_identifiers_are_rejected(self):
        manifest = self._manifest(case_id="   ")
        gate = self._gates(manifest)["MANIFEST_STRUCTURE_GATE"]
        self.assertEqual(gate.state.value, "FAIL")


if __name__ == "__main__":
    unittest.main()
