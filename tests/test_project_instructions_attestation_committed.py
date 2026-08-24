from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from scripts.project_instructions_attestation import verify_project_instructions_attestation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy" / "attestations" / "project-instructions-v3.4.txt"
ATTESTATION = ROOT / "deploy" / "attestations" / "project-instructions-v3.4.json"
EXPECTED_SOURCE_SHA256 = "c1cf295a7aede4efd2fb6270505d2aa3229e19e8e4fb20acb18dd87340ce4164"
EXPECTED_ATTESTATION_SHA256 = "91a1e1e7f5705079d0ae892c80bb7e6a97d02e0279a0f6dea7799d10a1fe7391"


class CommittedProjectInstructionsAttestationTests(unittest.TestCase):
    def test_committed_owner_export_is_digest_bound_and_verifiable(self) -> None:
        self.assertTrue(SOURCE.is_file())
        self.assertTrue(ATTESTATION.is_file())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), EXPECTED_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(ATTESTATION.read_bytes()).hexdigest(), EXPECTED_ATTESTATION_SHA256)

        evidence = verify_project_instructions_attestation(ATTESTATION, source_path=SOURCE)
        self.assertEqual(evidence["status"], "VERIFICADO")
        self.assertTrue(evidence["project_bootstrap_installed"])
        self.assertEqual(evidence["source_sha256"], EXPECTED_SOURCE_SHA256)
        self.assertEqual(evidence["file_sha256"], EXPECTED_ATTESTATION_SHA256)
        self.assertEqual(evidence["source_locator"], "chatgpt-project://GENOMA/instructions")
        self.assertEqual(evidence["ruleset_identity"], "v3.4/VIGENTE/17/08/2026")


if __name__ == "__main__":
    unittest.main()
