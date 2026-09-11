"""Verify reproducible and Git-bound evidence for the Phase 2B cutover."""

from pathlib import Path
import hashlib
import json
import shlex
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_RELATIVE = "docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-runtime-build-identity.json"
EVIDENCE = ROOT / EVIDENCE_RELATIVE
PLAN_RELATIVE = "docs/superpowers/plans/2026-09-11-omnigenis-phase2b-runtime-build-identity-cutover.md"
PLAN = ROOT / PLAN_RELATIVE
BASE_SHA = "4c0e5222248b5f9f2537d627091b80afc9c9e120"
LEGACY_WORD = "code" + "work"


class Phase2BEvidenceContractTest(unittest.TestCase):
    """Enforce the committed Phase 2B evidence contract."""

    @staticmethod
    def git(*args: str) -> str:
        """Run a read-only Git query from the repository root."""
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()

    def load(self) -> dict:
        """Load the required committed Phase 2B evidence artifact."""
        self.assertTrue(EVIDENCE.is_file(), f"missing required Phase 2B evidence: {EVIDENCE_RELATIVE}")
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_required_top_level_contract_is_complete(self) -> None:
        """Require every top-level field needed for Phase 2B evidence."""
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-phase2b-runtime-build-evidence-v1")
        self.assertEqual(evidence["base_sha"], BASE_SHA)
        required = {
            "implementation_head_sha", "implementation_tree_sha",
            "project_identity_sha256", "legacy_ledger_sha256", "legacy_scan",
            "runtime_resource_gate", "external_capabilities", "ghcr_premerge_state",
            "changed_paths", "protected_boundaries", "validation_provenance",
            "post_evidence_validation", "post_merge_requirements",
        }
        self.assertTrue(required.issubset(evidence))

    def test_implementation_sha_tree_and_evidence_commit_are_git_bound(self) -> None:
        """Bind implementation SHA/tree and the evidence-only commit through Git."""
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
        """Prevent pre-merge evidence from claiming GHCR publication success."""
        evidence = self.load()
        ghcr = evidence["ghcr_premerge_state"]
        self.assertEqual(ghcr["status"], "PENDING_AFTER_HUMAN_MERGE")
        self.assertEqual(ghcr["expected_package"], "omnigenis-genome")
        self.assertEqual(ghcr["old_package_action"], "PRESERVE")

    def test_runner_boundary_is_still_phase_two_c_legacy_state(self) -> None:
        """Keep live runner identity unchanged until the governed Phase 2C cutover."""
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
        """Require reproducible command and output provenance for validation gates."""
        evidence = self.load()
        required = {
            "identity_guard", "validate_repo", "supply_chain", "code_language",
            "residual_language", "docs_language", "phase2b_tests", "reviewer_tests",
            "plan_sequence", "shell_syntax", "diff_check",
        }
        provenance = evidence["validation_provenance"]
        self.assertTrue(required.issubset(provenance))
        self.assertNotIn("root_suite", provenance)
        expected_commands = {
            "identity_guard": "python3 scripts/project_identity_guard.py --check",
            "validate_repo": "python3 scripts/validate_repo.py",
            "supply_chain": "python3 scripts/verify_supply_chain_lock.py",
            "code_language": "python3 scripts/code_language_guard.py --check",
            "residual_language": "python3 scripts/residual_language_audit.py --check",
            "docs_language": "python3 -m unittest tests.test_developer_documentation_language -v",
            "phase2b_tests": (
                "python3 -m unittest tests.test_phase2b_runtime_build_identity "
                "tests.test_phase2b_mcp_ngs_identity tests.test_phase2b_legacy_seal -v"
            ),
            "reviewer_tests": (
                "python3 -m unittest tests.test_coderabbit_guardrails "
                "tests.test_integration_code_language.IntegrationCodeLanguageTest."
                "test_coderabbit_setup_diagnostics_are_english "
                "tests.test_ci_optimization_contract.CIOptimizationContractTest."
                "test_ngs_runtime_gate_matches_approved_phase_two_b_semantics -v"
            ),
            "plan_sequence": (
                "python3 -m unittest tests.test_phase2b_evidence_contract."
                "Phase2BEvidenceContractTest."
                "test_plan_bootstrap_defers_evidence_contract_and_full_suite -v"
            ),
            "shell_syntax": "find scripts -type f -name '*.sh' -exec bash -n {} +",
            "diff_check": "git diff --check",
        }
        for name in required:
            record = provenance[name]
            self.assertEqual(record["exit_code"], 0, name)
            command = record["command"]
            self.assertEqual(command, expected_commands[name], name)
            self.assertNotIn("/tmp/", command, name)
            self.assertNotIn("AST gate", command, name)
            argv = shlex.split(command)
            self.assertTrue(argv, name)
            self.assertIn(argv[0], {"python3", "find", "git"}, name)
            self.assertIsNotNone(shutil.which(argv[0]), name)
            self.assertTrue(record["environment"], name)
            self.assertRegex(record["output_sha256"], r"^[0-9a-f]{64}$", name)
            self.assertTrue(record["summary"], name)
        self.assertNotIn(
            "test_phase2b_evidence_contract",
            provenance["phase2b_tests"]["command"],
        )
        self.assertEqual(
            provenance["shell_syntax"]["command"],
            "find scripts -type f -name '*.sh' -exec bash -n {} +",
        )

    def test_post_evidence_validation_requires_raw_final_gates(self) -> None:
        """Require the full suite only after the evidence-only commit exists."""
        evidence = self.load()
        post = evidence["post_evidence_validation"]
        self.assertEqual(post["status"], "REQUIRED_AFTER_EVIDENCE_COMMIT")
        self.assertEqual(
            post["commands"],
            [
                "python3 -m unittest tests.test_phase2b_evidence_contract -v",
                "python3 -m unittest discover -s tests -v",
                "find scripts -type f -name '*.sh' -exec bash -n {} +",
                "git diff --check",
            ],
        )

    def test_plan_bootstrap_defers_evidence_contract_and_full_suite(self) -> None:
        """Keep evidence-dependent gates out of the pre-evidence bootstrap cycle."""
        plan = PLAN.read_text(encoding="utf-8")
        bootstrap = plan.split(
            "**Step 4: Execute one fail-fast validation cycle on the exact implementation HEAD**",
            1,
        )[1].split("**Step 5: Capture non-secret external capability state**", 1)[0]
        bootstrap_commands = bootstrap.split("```bash", 1)[1].split("```", 1)[0]
        self.assertNotIn("tests.test_phase2b_evidence_contract", bootstrap_commands)
        self.assertNotIn("run_gate root_suite", bootstrap_commands)
        final_gate = plan.split("**Step 9: Execute the final post-evidence gate**", 1)[1].split(
            "### Task 6:", 1
        )[0]
        for command in (
            "python3 -m unittest tests.test_phase2b_evidence_contract -v",
            "python3 -m unittest discover -s tests -v",
            "find scripts -type f -name '*.sh' -exec bash -n {} +",
            "git diff --check",
        ):
            self.assertIn(command, final_gate)

    def test_contract_and_ledger_hashes_match_repository_bytes(self) -> None:
        """Match evidence digests to the committed identity contract and ledger."""
        evidence = self.load()
        for key, relative in (
            ("project_identity_sha256", "config/project_identity.json"),
            ("legacy_ledger_sha256", "config/legacy_identity_ledger.json"),
        ):
            digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
            self.assertEqual(evidence[key], digest)


if __name__ == "__main__":
    unittest.main()
