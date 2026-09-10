from pathlib import Path
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

    def test_phase_two_internal_contracts_are_unchanged(self):
        self.assertIn("WORKDIR /opt/codework", self.read("Dockerfile"))
        self.assertIn(
            "codework-isolated",
            self.read(".github/workflows/scaffold-validation.yml"),
        )
        self.assertIn(
            '"name": "codework-genome-mcp"',
            self.read("mcp/package.json"),
        )
        self.assertIn("name: codework-ngs", self.read("environment.yml"))
        self.assertIn(
            "name = 'codework/genome-runtime'",
            self.read("nextflow.config"),
        )
        self.assertIn(
            "CODEWORK_CODERABBIT_BIN_DIR",
            self.read("scripts/codex/setup-coderabbit.sh"),
        )


if __name__ == "__main__":
    unittest.main()
