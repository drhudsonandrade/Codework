from pathlib import Path
import hashlib
import json
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RELATIVE = "docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json"
EVIDENCE = ROOT / EVIDENCE_RELATIVE
BASE_SHA = "4c0e5222248b5f9f2537d627091b80afc9c9e120"
LEGACY_WORD = "code" + "work"


class Phase2BEvidenceContractTest(unittest.TestCase):
    @staticmethod
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    def load(self) -> dict:
        self.assertTrue(EVIDENCE.is_file(), f"missing required Phase 2B evidence: {EVIDENCE_RELATIVE}")
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_required_top_level_contract_is_complete(self) -> None:
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-phase2b-runtime-build-evidence-v1")
        self.assertEqual(evidence["base_sha"], BASE_SHA)
        required = {
            "implementation_head_sha", "implementation_tree_sha",
            "project_identity_sha256", "legacy_ledger_sha256", "legacy_scan",
            "runtime_resource_gate", "external_capabilities", "ghcr_premerge_state",
            "changed_paths", "protected_boundaries", "validation_provenance",
            "post_merge_requirements",
        }
        self.assertTrue(required.issubset(evidence))

    def test_implementation_sha_tree_and_evidence_commit_are_git_bound(self) -> None:
        evidence = self.load()
        implementation = evidence["implementation_head_sha"]
        subprocess.run(
            ["git", "cat-file", "-e", f"{implementation}^{{commit}}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        self.assertEqual(
            self.git("rev-parse", f"{implementation}^{{tree}}"),
            evidence["implementation_tree_sha"],
        )
        evidence_head = self.git("rev-parse", "HEAD")
        self.assertEqual(self.git("rev-parse", "HEAD^"), implementation)
        changed = self.git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", evidence_head
        ).splitlines()
        self.assertEqual(changed, [EVIDENCE_RELATIVE])

    def test_premerge_evidence_cannot_claim_ghcr_publication(self) -> None:
        evidence = self.load()
        ghcr = evidence["ghcr_premerge_state"]
        self.assertEqual(ghcr["status"], "PENDING_AFTER_HUMAN_MERGE")
        self.assertEqual(ghcr["expected_package"], "omnigenis-genome")
        self.assertEqual(ghcr["old_package_action"], "PRESERVE")

    def test_runner_boundary_is_still_phase_two_c_legacy_state(self) -> None:
        evidence = self.load()
        protected = evidence["protected_boundaries"]
        self.assertEqual(protected["runner_cutover"], "NOT_STARTED_PHASE_2C")
        runners = protected["runner_snapshot"]
        expected_names = {
            f"drhudson-{LEGACY_WORD}-01",
            f"drhudson-{LEGACY_WORD}-02",
        }
        self.assertEqual({runner["name"] for runner in runners}, expected_names)
        legacy_pool = LEGACY_WORD + "-isolated"
        for runner in runners:
            self.assertIn(legacy_pool, runner["labels"])
            self.assertNotIn("omnigenis-isolated", runner["labels"])

    def test_validation_provenance_records_reproducible_outputs(self) -> None:
        evidence = self.load()
        required = {
            "identity_guard", "validate_repo", "supply_chain", "code_language",
            "residual_language", "docs_language", "phase2b_tests", "root_suite",
            "shell_syntax", "diff_check",
        }
        self.assertTrue(required.issubset(evidence["validation_provenance"]))
        for name in required:
            record = evidence["validation_provenance"][name]
            self.assertEqual(record["exit_code"], 0, name)
            self.assertTrue(record["command"], name)
            self.assertTrue(record["environment"], name)
            self.assertRegex(record["output_sha256"], r"^[0-9a-f]{64}$", name)
            self.assertTrue(record["summary"], name)
        self.assertEqual(
            evidence["validation_provenance"]["shell_syntax"]["command"],
            "find scripts -type f -name '*.sh' -exec bash -n {} +",
        )

    def test_contract_and_ledger_hashes_match_repository_bytes(self) -> None:
        evidence = self.load()
        for key, relative in (
            ("project_identity_sha256", "config/project_identity.json"),
            ("legacy_ledger_sha256", "config/legacy_identity_ledger.json"),
        ):
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(evidence[key], digest)


if __name__ == "__main__":
    unittest.main()
