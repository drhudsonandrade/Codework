import unittest
from datetime import datetime, timezone


class FreshnessGateTest(unittest.TestCase):
    def test_blocks_dna_read_when_candidate_is_newer_than_validated_stack(self):
        from scripts.freshness_gate import evaluate_readiness

        state = {
            "checked_at": "2026-08-16T12:00:00Z",
            "max_age_hours": 24,
            "components": [
                {
                    "name": "samtools",
                    "validated_version": "1.24",
                    "latest_version": "1.25",
                    "candidate_canary": "PENDING",
                    "promotion_status": "PENDING",
                }
            ],
            "evidence_sources": [
                {"name": "ClinVar", "status": "VERIFICADO", "checked_at": "2026-08-16T12:00:00Z"}
            ],
        }
        result = evaluate_readiness(state, now=datetime(2026, 8, 16, 13, tzinfo=timezone.utc))
        self.assertFalse(result["ready_for_dna"])
        self.assertIn("samtools:newer_candidate_not_promoted", result["blockers"])

    def test_passes_only_when_latest_stack_is_promoted_and_canary_passed(self):
        from scripts.freshness_gate import evaluate_readiness

        state = {
            "checked_at": "2026-08-16T12:00:00Z",
            "max_age_hours": 24,
            "components": [
                {
                    "name": "samtools",
                    "validated_version": "1.25",
                    "latest_version": "1.25",
                    "candidate_canary": "PASS",
                    "promotion_status": "VERIFICADO",
                },
                {
                    "name": "GRCh38-core",
                    "validated_version": "lock-2026-08-16",
                    "latest_version": "lock-2026-08-16",
                    "candidate_canary": "PASS",
                    "promotion_status": "VERIFICADO",
                },
            ],
            "evidence_sources": [
                {"name": "ClinVar", "status": "VERIFICADO", "checked_at": "2026-08-16T12:00:00Z"},
                {"name": "ClinGen", "status": "VERIFICADO", "checked_at": "2026-08-16T12:00:00Z"},
            ],
        }
        result = evaluate_readiness(state, now=datetime(2026, 8, 16, 13, tzinfo=timezone.utc))
        self.assertTrue(result["ready_for_dna"])
        self.assertEqual(result["blockers"], [])

    def test_stale_freshness_check_blocks_analysis(self):
        from scripts.freshness_gate import evaluate_readiness

        state = {
            "checked_at": "2026-08-14T12:00:00Z",
            "max_age_hours": 24,
            "components": [],
            "evidence_sources": [],
        }
        result = evaluate_readiness(state, now=datetime(2026, 8, 16, 13, tzinfo=timezone.utc))
        self.assertFalse(result["ready_for_dna"])
        self.assertIn("freshness_state:stale", result["blockers"])


if __name__ == "__main__":
    unittest.main()
