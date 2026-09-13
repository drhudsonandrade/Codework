from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT_DERIVED_CHECK_SHA256 = "13148c18c6ce9155ee89d2c0de0435a9ff86e658bc56851d2a8ec24062134bf7"


class RepositoryIdentityMigrationTest(unittest.TestCase):
    @staticmethod
    def read(path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_active_repository_identity_uses_omnigenis(self):
        identity = json.loads(self.read("config/project_identity.json"))
        self.assertEqual(
            identity["repository"],
            {"repository_id": 1212760346, "repository_name": "OmniGenis"},
        )
        self.assertNotIn("full_name", identity["repository"])
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

    def test_repository_contract_avoids_account_qualified_identity(self):
        identity = json.loads(self.read("config/project_identity.json"))
        self.assertEqual(identity["repository"]["repository_id"], 1212760346)
        self.assertEqual(identity["repository"]["repository_name"], "OmniGenis")

    def test_phase_two_b_runtime_contract_uses_omnigenis(self) -> None:
        """Require the Phase 2B runtime root to use the OmniGenis identity."""
        self.assertIn("WORKDIR /opt/omnigenis", self.read("Dockerfile"))

    def test_phase_two_c_runner_contract_uses_omnigenis(self) -> None:
        """Require canonical runner routing while legacy labels remain rollback-only."""
        legacy_runner_pool = "code" + "work" + "-isolated"
        for path in (
            ".github/workflows/genoma-audit.yml",
            ".github/workflows/genoma-policy-engine.yml",
            ".github/workflows/scaffold-validation.yml",
        ):
            text = self.read(path)
            self.assertNotIn(legacy_runner_pool, text)
            self.assertIn("omnigenis-isolated", text)


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

    def test_authenticated_recovery_evidence_does_not_invent_account_login(self) -> None:
        evidence = json.loads(
            self.read(
                "docs/superpowers/evidence/"
                "2026-09-10-omnigenis-repository-identity-migration.json"
            )
        )
        installation = evidence[
            "authenticated_recovery_reference_verification"
        ]["github_app_installation"]
        self.assertNotIn("account_login", installation)
        self.assertEqual(installation["installation_id"], 153834452)
        self.assertEqual(installation["repository_id"], 1212760346)
        self.assertIs(installation["repository_access_verified"], True)

    def test_deidentified_ruleset_evidence_uses_typed_fingerprint_not_fake_context(self) -> None:
        evidence = json.loads(
            self.read(
                "docs/superpowers/evidence/"
                "2026-09-10-omnigenis-repository-identity-migration.json"
            )
        )
        fake_identity = "legacy-" + "operator" + "andrade"
        serialized = json.dumps(evidence, sort_keys=True)
        self.assertNotIn(fake_identity, serialized)
        fingerprint = {
            "context_fingerprint": {
                "algorithm": "sha256",
                "digest": ACCOUNT_DERIVED_CHECK_SHA256,
                "case_sensitive": True,
                "provider_family": "dependency-security",
            }
        }
        self.assertIn(fingerprint, evidence["required_status_contexts"])
        for phase in ("ruleset_semantics_pre", "ruleset_semantics_post"):
            protected = evidence[phase]["21303100"]
            self.assertIn(fingerprint, protected["required_status_contexts"])
            status_rule = next(
                rule
                for rule in protected["rules"]
                if rule["type"] == "required_status_checks"
            )
            self.assertIn(
                fingerprint,
                status_rule["parameters"]["required_status_checks"],
            )

        for relative in (
            "docs/superpowers/checkpoints/2026-09-03-local-first-ci-session.md",
            "docs/superpowers/plans/2026-09-10-omnigenis-repository-identity-migration.md",
        ):
            self.assertNotIn(fake_identity, self.read(relative), relative)

    def test_deidentified_evidence_references_are_runtime_resolvable(self) -> None:
        """Require migrated evidence references to resolve without persisted owner identity."""
        records = {
            "docs/POLICY_CODE_LANGUAGE_INVENTORY.md": "5596016415",
            "docs/REPORTING_CODE_LANGUAGE_INVENTORY.md": "5601896618",
            "docs/superpowers/plans/2026-09-09-policy-evidence-audit-english.md": "5596016415",
            "docs/superpowers/plans/2026-09-09-reporting-english-locale.md": "5601896618",
        }
        for path, comment_id in records.items():
            with self.subTest(path=path):
                text = self.read(path)
                self.assertIn("gh api repositories/1212760346 --jq .full_name", text)
                self.assertIn(f"issues/comments/{comment_id}", text)
                self.assertNotIn("](repository_id=", text)

    def test_phase_one_evidence_uses_typed_repository_locators(self) -> None:
        """Keep deidentified provenance typed instead of masquerading as URLs/full_name."""
        evidence = json.loads(
            self.read(
                "docs/superpowers/evidence/"
                "2026-09-10-omnigenis-repository-identity-migration.json"
            )
        )
        endpoint = evidence["git_endpoint_verification"]
        self.assertNotIn("new_url", endpoint)
        self.assertNotIn("old_url", endpoint)
        self.assertEqual(endpoint["new_locator"]["repository_id"], 1212760346)
        self.assertEqual(endpoint["new_locator"]["repository_name"], "OmniGenis")
        self.assertEqual(endpoint["old_locator"]["repository_id"], 1212760346)
        self.assertIn("historical_repository_name", endpoint["old_locator"])

    def test_migration_plan_uses_fail_closed_reference_and_phase_two_gates(self):
        plan = self.read(
            "docs/superpowers/plans/"
            "2026-09-10-omnigenis-repository-identity-migration.md"
        )
        self.assertIn("unexpected_old_references", plan)
        self.assertIn("allowed_historical_old_references", plan)
        self.assertIn("phase2_changed_paths", plan)
        self.assertIn("if phase2_changed_paths:", plan)
        phase_two_gate = plan.split("if phase2_changed_paths:", 1)[1].split(
            "print('PHASE2_PRESERVATION_GATE=PASS')",
            1,
        )[0]
        self.assertIn("raise SystemExit(", phase_two_gate)

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
