from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.project_instructions_attestation import (
    ProjectInstructionsAttestationError,
    verify_project_instructions_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "deploy" / "attestations" / "project-instructions-v3.4.txt"
ATTESTATION = ROOT / "deploy" / "attestations" / "project-instructions-v3.4.json"
EXPECTED_SOURCE_SHA256 = "c1cf295a7aede4efd2fb6270505d2aa3229e19e8e4fb20acb18dd87340ce4164"
EXPECTED_ATTESTATION_SHA256 = "b943b07b26cd3d48db69cb68a71bb0583e15f9ce65dee9b264ee70f591285829"


class CommittedProjectInstructionsAttestationTests(unittest.TestCase):
    def test_committed_owner_export_is_digest_bound_snapshot_only(self) -> None:
        self.assertTrue(SOURCE.is_file())
        self.assertTrue(ATTESTATION.is_file())
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), EXPECTED_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(ATTESTATION.read_bytes()).hexdigest(), EXPECTED_ATTESTATION_SHA256)

        evidence = verify_project_instructions_attestation(ATTESTATION, source_path=SOURCE)
        self.assertEqual(evidence["status"], "VERIFICADO")
        self.assertEqual(evidence["evidence_classification"], "VERIFIED_OWNER_SNAPSHOT_ONLY")
        self.assertFalse(evidence["project_bootstrap_installed"])
        self.assertEqual(evidence["installation_status"], "NÃO DISPONÍVEL")
        self.assertEqual(evidence["source_sha256"], EXPECTED_SOURCE_SHA256)
        self.assertEqual(evidence["file_sha256"], EXPECTED_ATTESTATION_SHA256)
        self.assertEqual(evidence["source_locator"], "project-instructions://GENOMA/instructions")
        self.assertEqual(evidence["ruleset_identity"], "v3.4/VIGENTE/17/08/2026")

    def test_local_snapshot_cannot_be_promoted_to_installed_by_editing_json(self) -> None:
        payload = json.loads(ATTESTATION.read_text(encoding="utf-8"))
        payload["project_bootstrap_installed"] = True
        payload["installation_status"] = "VERIFICADO"
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / ATTESTATION.name
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ProjectInstructionsAttestationError, "identity mismatch"):
                verify_project_instructions_attestation(target, source_path=SOURCE)


if __name__ == "__main__":
    unittest.main()
