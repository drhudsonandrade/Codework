from pathlib import Path
import hashlib
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/superpowers/evidence/2026-09-10-omnigenis-phase2a-identity-contract.json"
PHASE1_EVIDENCE = ROOT / "docs/superpowers/evidence/2026-09-10-omnigenis-repository-identity-migration.json"
SPEC = ROOT / "docs/superpowers/specs/2026-09-10-omnigenis-phase2-internal-identity-migration-design.md"

REQUIRED_VALIDATION_GATES = {
    "project_identity_guard",
    "validate_repo",
    "supply_chain",
    "code_language",
    "residual_language",
    "developer_documentation_tests",
    "shell_syntax",
    "diff_check",
    "root_suite",
    "ci_trigger_closure",
    "evidence_contract",
}
REQUIRED_BASELINE_CHECKS = {
    "repository_metadata",
    "rulesets",
    "git_endpoint_continuity",
    "validate_repo",
    "root_suite",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Phase2AEvidenceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def assert_provenance_record(self, record: dict, environments: dict) -> None:
        self.assertEqual(record["status"], "PASS")
        self.assertIsInstance(record["command"], str)
        self.assertTrue(record["command"].strip())
        self.assertEqual(record["exit_code"], 0)
        self.assertIn(record["environment"], environments)
        output = record["output"]
        self.assertTrue(output["locator"].startswith("inline:"))
        self.assertTrue(output["summary"].strip())
        self.assertEqual(output["sha256"], sha256_text(output["summary"]))

    def test_validation_gates_have_reproducible_provenance(self) -> None:
        self.assertEqual(
            self.evidence["schema"],
            "omnigenis-phase2a-identity-contract-evidence-v2",
        )
        environments = self.evidence["environments"]
        records = self.evidence["validation_provenance"]
        self.assertTrue(REQUIRED_VALIDATION_GATES.issubset(records))
        for name in REQUIRED_VALIDATION_GATES:
            self.assert_provenance_record(records[name], environments)

    def test_verified_baseline_has_reproducible_provenance(self) -> None:
        environments = self.evidence["environments"]
        records = self.evidence["baseline_provenance"]
        self.assertEqual(set(records), REQUIRED_BASELINE_CHECKS)
        for record in records.values():
            self.assert_provenance_record(record, environments)
        source = self.evidence["provenance_sources"]["phase1_migration_evidence"]
        self.assertEqual(source["path"], PHASE1_EVIDENCE.relative_to(ROOT).as_posix())
        self.assertEqual(
            source["sha256"],
            hashlib.sha256(PHASE1_EVIDENCE.read_bytes()).hexdigest(),
        )

    def test_spec_status_and_baseline_reference_are_current(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertNotIn("Implementation has not started", text)
        self.assertIn("Phase 2A implementation exists", text)
        self.assertIn(EVIDENCE.relative_to(ROOT).as_posix(), text)


if __name__ == "__main__":
    unittest.main()
