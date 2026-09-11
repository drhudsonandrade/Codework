"""Verify that Phase 2B legacy identities are retired without widening budgets."""

from pathlib import Path
import json
import unittest

from scripts.project_identity_guard import scan_legacy_identities

ROOT = Path(__file__).resolve().parents[1]


class Phase2BLegacySealTest(unittest.TestCase):
    """Seal the Phase 2B legacy-identity boundary."""
    def load_ledger(self) -> dict:
        """Load the reviewed migration ledger from the repository."""
        return json.loads((ROOT / "config/legacy_identity_ledger.json").read_text(encoding="utf-8"))

    def test_every_phase_two_b_identity_is_retired_from_active_content(self) -> None:
        """Require every Phase 2B retirement entry to have zero active locations."""
        ledger = self.load_ledger()
        report = scan_legacy_identities(ROOT, ledger)
        self.assertEqual(report["unclassified"], [])
        self.assertEqual(report["over_budget"], [])
        phase2b_entries = [entry for entry in ledger["entries"] if entry.get("retire_by") == "2B"]
        self.assertTrue(phase2b_entries)
        for entry in phase2b_entries:
            self.assertEqual(entry["locations"], {}, entry["id"])
        phase2b_ids = {entry["id"] for entry in phase2b_entries}
        observed = report["counts"]
        self.assertEqual({key for key in observed if key in phase2b_ids}, set())

    def test_remaining_active_legacy_categories_are_later_or_historical_only(self) -> None:
        """Allow only later-phase or historical legacy categories after Phase 2B."""
        ledger = self.load_ledger()
        report = scan_legacy_identities(ROOT, ledger)
        allowed = {
            "runner-pool",
            "ci-test-function-name",
            "coderabbit-bin-env",
            "historical-runtime-zip",
            "repository-old-full-name-test",
            "historical-repository-pr-urls",
        }
        self.assertEqual(report["unclassified"], [])
        self.assertEqual(report["over_budget"], [])
        self.assertLessEqual(set(report["counts"]), allowed)


if __name__ == "__main__":
    unittest.main()
