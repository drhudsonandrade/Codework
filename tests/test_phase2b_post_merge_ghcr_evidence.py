"""Verify the Phase 2B protected-main GHCR publication prerequisite."""

from pathlib import Path
import json
import unittest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/superpowers/evidence/2026-09-11-omnigenis-phase2b-post-merge-ghcr.json"
MERGE_COMMIT = "a1e669dd613f68f4d82ca7f1f565772ec8098cb1"
IMAGE_REFERENCE = (
    "ghcr.io/drhudsonandrade/omnigenis-genome@"
    "sha256:b34cddd157132f0b039bebb1674abb4957e024fd0332568fc3ae9c2ca0fa8454"
)


class Phase2BPostMergeGhcrEvidenceTest(unittest.TestCase):
    """Require durable proof that Phase 2B published the canonical image."""

    def load(self) -> dict:
        """Load the required Phase 2B post-merge evidence."""
        self.assertTrue(EVIDENCE.is_file(), f"missing evidence: {EVIDENCE}")
        return json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_publication_identity_is_exact(self) -> None:
        """Bind the publication to the merged commit and canonical digest."""
        evidence = self.load()
        self.assertEqual(evidence["schema"], "omnigenis-phase2b-post-merge-ghcr-v1")
        self.assertEqual(evidence["merge_commit"], MERGE_COMMIT)
        self.assertEqual(evidence["workflow_run_id"], 34617560951)
        self.assertEqual(evidence["successful_attempt"], 2)
        self.assertEqual(evidence["publish_job_id"], 103363105798)
        self.assertEqual(evidence["status"], "VERIFIED")
        self.assertEqual(evidence["image_reference"], IMAGE_REFERENCE)
        self.assertEqual(evidence["artifact_id"], 10276395379)

    def test_initial_failure_is_recorded_as_transient_upstream(self) -> None:
        """Keep the failed first attempt distinct from repository failure."""
        evidence = self.load()
        self.assertEqual(evidence["attempt_1_failure_class"], "UPSTREAM_DOCKER_HUB_502")
        self.assertEqual(evidence["attempt_1_conclusion"], "failure")
        self.assertEqual(evidence["attempt_2_conclusion"], "success")
        self.assertEqual(evidence["package_read_verification"], "NOT_AVAILABLE")


if __name__ == "__main__":
    unittest.main()
