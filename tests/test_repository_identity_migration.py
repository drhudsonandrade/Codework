from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositoryIdentityMigrationTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_active_repository_identity_uses_omnigenis(self):
        active = [
            "AGENTS.md",
            "docs/BRANCH_GOVERNANCE.md",
            "docs/GITHUB_MOBILE_IMPORT.md",
            "docs/MAGALU_PRIVATE_MCP_SETUP.md",
            "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md",
        ]
        for path in active:
            text = self.read(path)
            self.assertNotIn("drhudsonandrade/Codework", text, path)
        self.assertIn("GENOMA OmniGenis", self.read("AGENTS.md"))

    def test_public_repository_state_is_documented(self):
        self.assertIn(
            "Public, reproducible genomics execution repository",
            self.read("README.md"),
        )
        self.assertIn(
            "public, reproducible genomics runtime",
            self.read("AGENTS.md"),
        )

    def test_historical_repository_urls_are_preserved(self):
        self.assertIn(
            "https://github.com/drhudsonandrade/Codework/pull/60",
            self.read("docs/POLICY_CODE_LANGUAGE_INVENTORY.md"),
        )
        self.assertIn(
            "https://github.com/drhudsonandrade/Codework/pull/61",
            self.read("docs/REPORTING_CODE_LANGUAGE_INVENTORY.md"),
        )

    def test_phase_two_b_runtime_contract_uses_omnigenis(self) -> None:
        self.assertIn("WORKDIR /opt/omnigenis", self.read("Dockerfile"))

    def test_phase_two_c_runner_contract_is_not_started(self) -> None:
        legacy_runner_pool = "code" + "work" + "-isolated"
        for path in (
            ".github/workflows/genoma-audit.yml",
            ".github/workflows/genoma-policy-engine.yml",
            ".github/workflows/scaffold-validation.yml",
        ):
            text = self.read(path)
            self.assertIn(legacy_runner_pool, text)
            self.assertNotIn("omnigenis-isolated", text)


    def test_recovery_doc_requires_live_verification_of_app_and_legacy_pr(self):
        text = self.read("docs/GITHUB_MOBILE_IMPORT.md")
        self.assertNotIn("The GitHub App is now installed", text)
        self.assertIn("Verify the GitHub App installation and PR #2 state", text)
        self.assertIn("evidence artifact", text)

    def test_migration_evidence_attests_raw_captures_and_ruleset_semantics(self):
        evidence = json.loads(
            self.read(
                "docs/superpowers/evidence/"
                "2026-09-10-omnigenis-repository-identity-migration.json"
            )
        )
        attestation = evidence["raw_capture_attestation"]
        for phase in ("pre", "post"):
            record = attestation[phase]
            self.assertRegex(record["manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("sha256sum -c manifest.sha256", record["verification_command"])
            self.assertTrue(record["location"].startswith("/tmp/omnigenis-rename-"))

        before = evidence["ruleset_semantics_pre"]
        after = evidence["ruleset_semantics_post"]
        self.assertEqual(before, after)
        self.assertEqual(set(before), {"21303100", "22347095"})
        for ruleset in before.values():
            for key in (
                "enforcement",
                "conditions",
                "rules",
                "bypass_actors",
                "required_status_contexts",
            ):
                self.assertIn(key, ruleset)

    def test_migration_plan_uses_fail_closed_reference_and_phase_two_gates(self):
        plan = self.read(
            "docs/superpowers/plans/"
            "2026-09-10-omnigenis-repository-identity-migration.md"
        )
        self.assertIn("unexpected_old_references", plan)
        self.assertIn("allowed_historical_old_references", plan)
        self.assertIn("phase2_changed_paths", plan)
        self.assertNotIn(
            "git grep -n 'drhudsonandrade/Codework' -- "
            "':!docs/history/**' ':!docs/superpowers/specs/",
            plan,
        )

    def test_migration_plan_compares_complete_ruleset_semantics(self):
        plan = self.read(
            "docs/superpowers/plans/"
            "2026-09-10-omnigenis-repository-identity-migration.md"
        )
        self.assertIn("def normalize_ruleset", plan)
        self.assertIn("bypass_actors", plan)
        self.assertIn("required_status_contexts", plan)
        self.assertIn("ruleset_semantics_pre", plan)
        self.assertIn("ruleset_semantics_post", plan)


if __name__ == "__main__":
    unittest.main()
