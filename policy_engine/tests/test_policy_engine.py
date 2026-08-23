from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from genoma_policy.engine import CRITICAL_FINAL_AUDIT_KEYS, PolicyEngine
from genoma_policy.paths import resolve_manifest_path, resolve_ruleset_path
from genoma_policy.ruleset import (
    EXPECTED_CANONICAL,
    EXPECTED_SHA256,
    RulesetError,
    enforce_unique_active_ruleset,
    load_ruleset,
    verify_external_manifest,
)
from genoma_policy.scaffold import scaffold_manifest
from genoma_policy.smoke import run_smoke

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
RULESET = resolve_ruleset_path(ROOT)
HASH_MANIFEST = resolve_manifest_path(RULESET, ROOT)
HISTORICAL_IDENTITY_FIXTURE = REPO_ROOT / "docs" / "history" / "v3.3" / "superseded-identities.json"


class HistoricalIdentityFixtureMissingError(RuntimeError):
    def __init__(self, path: Path) -> None:
        super().__init__(f"superseded identity fixture missing: {path}")


if not HISTORICAL_IDENTITY_FIXTURE.is_file():
    raise HistoricalIdentityFixtureMissingError(HISTORICAL_IDENTITY_FIXTURE)
HISTORICAL_IDENTITY = json.loads(HISTORICAL_IDENTITY_FIXTURE.read_text(encoding="utf-8"))


class RulesetTests(unittest.TestCase):
    def test_normative_identity_hash_and_263_sections(self):
        ruleset = load_ruleset(RULESET)
        self.assertEqual(ruleset.status, "VIGENTE")
        self.assertEqual(ruleset.version, "v3.4")
        self.assertEqual(ruleset.effective_date, "17/08/2026")
        # Unconditional: this is the canonical identity test, and every consumer of
        # that identity is held to the same oracle. Gating it on an environment
        # variable let the suite run in a mode where the one assertion that names
        # the digest was simply absent, while test_server asserted it regardless.
        self.assertEqual(ruleset.sha256, EXPECTED_SHA256)
        self.assertEqual(ruleset.canonical_filename, EXPECTED_CANONICAL)
        self.assertEqual(ruleset.path.name, EXPECTED_CANONICAL)
        self.assertEqual([section.number for section in ruleset.sections], list(range(263)))
        verify_external_manifest(ruleset, HASH_MANIFEST)

    def test_duplicate_vigente_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / RULESET.name
            shutil.copyfile(RULESET, target)
            shutil.copyfile(RULESET, Path(td) / "REGRAS_PROJETO_GENOMA_DUPLICATE.txt")
            with self.assertRaises(RulesetError):
                enforce_unique_active_ruleset(td, target)


class PolicyEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ruleset = load_ruleset(RULESET)
        cls.engine = PolicyEngine(cls.ruleset, external_manifest=HASH_MANIFEST)

    def valid_analysis_manifest(self):
        manifest = scaffold_manifest(self.ruleset, case_id="TEST")
        manifest["session_id"] = "test-session"
        manifest["inputs"] = [
            {"id": "input-1", "kind": "vcf", "source": "test-fixture", "sha256": "abc123"}
        ]
        manifest["consent"] = {
            "verified": True,
            "version": "test-v1",
            "authorized_domains": ["research"],
        }
        manifest["qc"] = {
            "status": "EXECUTADO",
            "passed": True,
            "evidence_refs": ["fixture:qc"],
        }
        manifest["sources"] = [
            {
                "id": "fixture:attestation",
                "mutable": False,
                "status": "VERIFICADO",
                "accessible": True,
                "locator": "fixture://attestation",
                "retrieval_evidence": {"method": "fixture", "result_digest": "sha256:fixture"},
            }
        ]
        for attestation in manifest["section_attestations"]:
            attestation.update(
                {
                    "applicability": "NOT_APPLICABLE",
                    "status": "VERIFICADO",
                    "decision": "NOT_APPLICABLE",
                    "justification": "not triggered by this fixture",
                    "evidence_refs": [],
                }
            )
            attestation["trace"].update(
                {"run_id": "test-session", "created_at": "2026-08-22T18:46:00-03:00"}
            )
        return manifest

    def _assert_ruleset_gate_rejects(self, manifest):
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "RULESET_GATE")
        self.assertEqual(gate.state.value, "FAIL")
        self.assertFalse(report.ready)

    def test_ruleset_gate_rejects_missing_ruleset_object(self):
        manifest = self.valid_analysis_manifest()
        manifest.pop("ruleset")
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_missing_status(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"].pop("status")
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_non_vigente_status(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"]["status"] = "PENDENTE"
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_wrong_version(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"]["version"] = "v3.5"
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_wrong_effective_date(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"]["effective_date"] = "18/08/2026"
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_wrong_sha256(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"]["sha256"] = "0" * 64
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_missing_canonical_filename(self):
        """Every other identity field being right must not carry an unnamed ruleset."""
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"].pop("canonical_filename")
        self._assert_ruleset_gate_rejects(manifest)

    def test_ruleset_gate_rejects_wrong_canonical_filename(self):
        manifest = self.valid_analysis_manifest()
        manifest["ruleset"]["canonical_filename"] = "REGRAS_PROJETO_GENOMA_VIGENTE_v9.9_2030-01-01.txt"
        self._assert_ruleset_gate_rejects(manifest)

    def test_post_deployment_is_nonblocking_pending_by_default(self):
        report = self.engine.evaluate(self.valid_analysis_manifest())
        gate = next(gate for gate in report.gates if gate.gate == "POST_DEPLOYMENT_GATE")
        self.assertEqual(gate.state.value, "PENDING")
        self.assertFalse(gate.blocking)
        self.assertTrue(report.ready)

    def test_post_deployment_pass_requires_all_five_canonical_criteria(self):
        manifest = self.valid_analysis_manifest()
        manifest["post_deployment"] = {
            "single_active_ruleset": True,
            "bootstrap_installed": True,
            "live_smoke_passed": True,
            "live_smoke_count": 15,
            "critical_failures": 0,
            "identity_recovered": "v3.4/VIGENTE/17/08/2026",
        }
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "POST_DEPLOYMENT_GATE")
        self.assertEqual(gate.state.value, "PASS")
        self.assertFalse(gate.blocking)

    def test_post_deployment_remains_pending_for_superseded_or_wrong_date_identity(self):
        base = {
            "single_active_ruleset": True,
            "bootstrap_installed": True,
            "live_smoke_passed": True,
            "live_smoke_count": 15,
            "critical_failures": 0,
        }
        bad_identities = (
            f"{HISTORICAL_IDENTITY['version']}/VIGENTE/{HISTORICAL_IDENTITY['effective_date']}",
            "v3.4/VIGENTE/18/08/2026",
        )
        for identity in bad_identities:
            with self.subTest(identity=identity):
                manifest = self.valid_analysis_manifest()
                manifest["post_deployment"] = {**base, "identity_recovered": identity}
                report = self.engine.evaluate(manifest)
                gate = next(gate for gate in report.gates if gate.gate == "POST_DEPLOYMENT_GATE")
                self.assertEqual(gate.state.value, "PENDING")
                self.assertFalse(gate.blocking)

    def test_vus_cannot_change_conduct_without_confirmation(self):
        manifest = self.valid_analysis_manifest()
        manifest["claims"] = [
            {
                "id": "v1",
                "nature": "INFERÊNCIA",
                "domain": "CLÍNICO",
                "status": "INFERIDO",
                "priority": "P2",
                "evidence_refs": ["clinvar"],
                "variant_classification": "VUS",
                "changes_conduct": True,
                "confirmation": {"status": "PROPOSTO"},
            }
        ]
        manifest["sources"] = [
            {
                "id": "clinvar",
                "mutable": True,
                "status": "VERIFICADO",
                "accessible": True,
                "version": "fixture",
                "checked_at": "2026-08-22",
                "locator": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "primary_or_official": True,
                "retrieval_evidence": {"method": "fixture", "result_digest": "sha256:fixture"},
            }
        ]
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "CLINICAL_CONFIRMATION_GATE")
        self.assertEqual(gate.state.value, "FAIL")
        self.assertFalse(report.ready)

    def test_runtime_gate_is_session_specific(self):
        manifest = self.valid_analysis_manifest()
        manifest["operation"]["requires_real_calling"] = True
        manifest["runtime_resource_gate"] = {"session_id": "old-session", "checks": {}}
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "RUNTIME_RESOURCE_GATE")
        self.assertEqual(gate.state.value, "FAIL")

    def test_final_audit_requires_all_15_criteria(self):
        manifest = self.valid_analysis_manifest()
        manifest["operation"]["output"] = "FINAL_AUDITED_REPORT"
        manifest["final_audit"] = {key: True for key in CRITICAL_FINAL_AUDIT_KEYS[:-1]}
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "FINAL_AUDIT_GATE")
        self.assertEqual(gate.state.value, "FAIL")
        manifest["final_audit"][CRITICAL_FINAL_AUDIT_KEYS[-1]] = True
        report = self.engine.evaluate(manifest)
        gate = next(gate for gate in report.gates if gate.gate == "FINAL_AUDIT_GATE")
        self.assertEqual(gate.state.value, "PASS")

    def test_report_exposes_four_plane_states(self):
        report = self.engine.evaluate(self.valid_analysis_manifest()).to_dict()
        self.assertEqual(set(report["planes"]), {"policy_control", "scientific_data", "evidence", "audit"})
        self.assertEqual(report["planes"]["policy_control"]["state"], "PASS")

    def test_deterministic_safety_smoke_15_of_15(self):
        result = run_smoke(self.engine)
        self.assertTrue(result["all_pass"])
        self.assertEqual((result["passed"], result["total"]), (15, 15))
        self.assertEqual(result["post_deployment_claim"], "NOT_GRANTED_BY_THIS_SUITE")

    def test_smoke_rejects_divergent_ruleset_identity(self):
        divergent = replace(self.ruleset, sha256="0" * 64)
        with self.assertRaises(RulesetError):
            run_smoke(PolicyEngine(divergent))

    def test_smoke_rejects_metadata_matching_ruleset_without_263_sections(self):
        incomplete = replace(self.ruleset, sections=())
        with self.assertRaises(RulesetError):
            run_smoke(PolicyEngine(incomplete))


if __name__ == "__main__":
    unittest.main()
