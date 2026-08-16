import unittest
from unittest.mock import patch


class FakeAdapter:
    def __init__(self, name, status="VERIFICADO"):
        self.name = name
        self.status = status

    def query(self, query, *, checked_at):
        return {
            "name": self.name,
            "status": self.status,
            "checked_at": checked_at,
            "locator": f"https://example.invalid/{self.name}",
            "version": "fixture-v1",
            "retrieval_evidence": {"method": "HTTPS", "result_digest": "a" * 64},
        }


class EvidenceFreshnessTest(unittest.TestCase):
    def test_refresh_attaches_every_critical_source_to_freshness_state(self):
        import scripts.refresh_evidence_sources as module

        with patch.object(module, "get_adapter", side_effect=lambda name: FakeAdapter(name)):
            result = module.refresh({"schema": "state"}, checked_at="2026-08-16T15:00:00Z")
        self.assertEqual(
            {item["name"] for item in result["evidence_sources"]},
            {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"},
        )
        self.assertTrue(all(item["status"] == "VERIFICADO" for item in result["evidence_sources"]))

    def test_freshness_gate_blocks_if_one_critical_source_is_unavailable(self):
        import scripts.refresh_evidence_sources as module
        from scripts.freshness_gate import evaluate_readiness
        from datetime import datetime, timezone

        def factory(name):
            return FakeAdapter(name, "NÃO DISPONÍVEL" if name == "gnomad" else "VERIFICADO")

        base = {
            "checked_at": "2026-08-16T15:00:00Z",
            "max_age_hours": 24,
            "components": [
                {
                    "name": "samtools",
                    "validated_version": "1.24",
                    "latest_version": "1.24",
                    "candidate_canary": "PASS",
                    "promotion_status": "VERIFICADO",
                }
            ],
        }
        with patch.object(module, "get_adapter", side_effect=factory):
            state = module.refresh(base, checked_at="2026-08-16T15:00:00Z")
        result = evaluate_readiness(state, now=datetime(2026, 8, 16, 15, 1, tzinfo=timezone.utc))
        self.assertFalse(result["ready_for_dna"])
        self.assertIn("gnomad:not_verified", result["blockers"])


if __name__ == "__main__":
    unittest.main()
