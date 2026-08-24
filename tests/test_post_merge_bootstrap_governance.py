from __future__ import annotations

import importlib.util
import inspect
import unittest
from pathlib import Path

from scripts import bootstrap_attestation

ROOT = Path(__file__).resolve().parents[1]


class PostMergeBootstrapGovernanceTests(unittest.TestCase):
    def test_project_instructions_attestation_verifier_exists(self) -> None:
        self.assertIsNotNone(
            importlib.util.find_spec("scripts.project_instructions_attestation"),
            "PROJECT_BOOTSTRAP_INSTALLED needs an independent Project Instructions attestation verifier",
        )

    def test_live_smoke_does_not_reuse_ruleset_bootstrap_as_installation_proof(self) -> None:
        text = (ROOT / "scripts" / "run_live_post_deployment_smoke.py").read_text(encoding="utf-8")
        self.assertIn("verify_project_instructions_attestation", text)
        self.assertNotIn('"bootstrap_installed": bootstrap_ok', text)
        self.assertIn('"bootstrap_installed": project_bootstrap_ok', text)

    def test_bootstrap_verifier_supports_runtime_main_sha_binding(self) -> None:
        parameters = inspect.signature(bootstrap_attestation.verify_bootstrap_attestation).parameters
        self.assertIn("expected_source_revision", parameters)
        self.assertIn("expected_file_sha256", parameters)

    def test_production_witness_generates_fresh_bootstrap_for_exact_main_sha(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-witness.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m scripts.bootstrap_attestation --write", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--project-instructions-attestation", text)
        self.assertNotIn(
            "--bootstrap-attestation deploy/attestations/bootstrap-project-v3.4.json",
            text,
        )

    def test_manual_ceremony_uses_same_external_bootstrap_contract(self) -> None:
        text = (ROOT / ".github" / "workflows" / "genoma-production-ceremony.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("python3 -m scripts.bootstrap_attestation --write", text)
        self.assertIn("--expected-source-commit \"$GITHUB_SHA\"", text)
        self.assertIn("--project-instructions-attestation", text)


if __name__ == "__main__":
    unittest.main()
