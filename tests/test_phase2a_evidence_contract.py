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
DEIDENTIFIED_BASELINE_COMMAND_SHA256 = {
    "git_endpoint_continuity": "d5a85d93862d27ac8e340346375f73d872562fceb9744ca23f2420d0aef0e6f0",
    "repository_metadata": "2792dd719238e5a7067f402776895bef599ff7025cd77fdc396d1034ccdbd54e",
    "rulesets": "e54587564b15269b7741dbb5d8b84fdc10f48c737958877af66530f6825bdb93",
}
DEIDENTIFIED_BASELINE_SUMMARY_SHA256 = {
    "git_endpoint_continuity": "a436f690db5b7a3cff0e20929d433a0e2936ec940620f58bcd2d23380a7f63d1",
    "repository_metadata": "0038c91f3803f6ba3b011cfeaeb17ee16f1045d1cad8a8d149f79d8a94ff50aa",
    "rulesets": "9dd6f9751d20d160d6a8d7eabb196fa5598b147708ccbf445b1c49e59d4186ed",
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
        if "reproduction_command" in record:
            self.assertEqual(record["historical_status"], "PASS")
            self.assertEqual(record["historical_exit_code"], 0)
            self.assertRegex(record["historical_command_sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(record["reproduction_command"].strip())
            environment = record["historical_environment"]
        else:
            self.assertEqual(record["status"], "PASS")
            self.assertIsInstance(record["command"], str)
            self.assertTrue(record["command"].strip())
            self.assertEqual(record["exit_code"], 0)
            environment = record["environment"]
        self.assertIn(environment, environments)
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

    def test_deidentified_baseline_commands_separate_method_from_historical_execution(self) -> None:
        records = self.evidence["baseline_provenance"]
        for name, command_sha256 in DEIDENTIFIED_BASELINE_COMMAND_SHA256.items():
            with self.subTest(name=name):
                record = records[name]
                self.assertNotIn("command", record)
                self.assertNotIn("exit_code", record)
                self.assertNotIn("status", record)
                self.assertTrue(record["reproduction_command"].strip())
                self.assertEqual(
                    record["reproduction_command_status"],
                    "DOCUMENTED_METHOD_NOT_HISTORICAL_LITERAL_EXECUTION",
                )
                self.assertEqual(record["historical_command_sha256"], command_sha256)
                self.assertEqual(record["historical_exit_code"], 0)
                self.assertEqual(record["historical_status"], "PASS")
                output = record["output"]
                self.assertEqual(
                    output["historical_summary_sha256"],
                    DEIDENTIFIED_BASELINE_SUMMARY_SHA256[name],
                )
                self.assertIn(
                    output["summary_provenance"],
                    {
                        "DEIDENTIFIED_DERIVATIVE_OF_HISTORICAL_OUTPUT",
                        "HISTORICAL_SUMMARY_RETAINED",
                    },
                )

    def test_spec_status_and_baseline_reference_are_current(self) -> None:
        text = SPEC.read_text(encoding="utf-8")
        self.assertNotIn("Implementation has not started", text)
        self.assertIn("Phase 2A implementation exists", text)
        self.assertIn(EVIDENCE.relative_to(ROOT).as_posix(), text)


if __name__ == "__main__":
    unittest.main()
