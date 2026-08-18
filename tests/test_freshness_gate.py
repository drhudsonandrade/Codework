import unittest
from datetime import datetime, timezone

NOW = datetime(2026, 8, 17, 13, tzinfo=timezone.utc)
CHECKED_AT = "2026-08-17T12:00:00Z"


def _complete_state(**overrides):
    """A state that genuinely satisfies the gate: full component and source coverage."""
    from scripts.freshness_gate import REQUIRED_COMPONENTS, REQUIRED_EVIDENCE_SOURCES

    state = {
        "checked_at": CHECKED_AT,
        "max_age_hours": 24,
        "components": [
            {
                "name": name,
                "validated_version": "1.0",
                "latest_version": "1.0",
                "candidate_canary": "PASS",
                "promotion_status": "VERIFICADO",
            }
            for name in sorted(REQUIRED_COMPONENTS)
        ],
        "evidence_sources": [
            {"name": name, "status": "VERIFICADO", "checked_at": CHECKED_AT}
            for name in sorted(REQUIRED_EVIDENCE_SOURCES)
        ],
    }
    state.update(overrides)
    return state


class FreshnessGateTest(unittest.TestCase):
    def test_blocks_dna_read_when_candidate_is_newer_than_validated_stack(self):
        from scripts.freshness_gate import evaluate_readiness

        state = _complete_state()
        state["components"][0].update(
            {"name": "samtools", "validated_version": "1.24", "latest_version": "1.25",
             "candidate_canary": "PENDING", "promotion_status": "PENDING"}
        )
        result = evaluate_readiness(state, now=NOW)
        self.assertFalse(result["ready_for_dna"])
        self.assertIn("samtools:newer_candidate_not_promoted", result["blockers"])

    def test_passes_only_when_latest_stack_is_promoted_and_canary_passed(self):
        from scripts.freshness_gate import evaluate_readiness

        result = evaluate_readiness(_complete_state(), now=NOW)
        self.assertTrue(result["ready_for_dna"])
        self.assertEqual(result["blockers"], [])

    def test_stale_freshness_check_blocks_analysis(self):
        from scripts.freshness_gate import evaluate_readiness

        state = _complete_state(checked_at="2026-08-18T12:00:00Z")
        result = evaluate_readiness(state, now=NOW)
        self.assertFalse(result["ready_for_dna"])
        self.assertIn("freshness_state:stale", result["blockers"])

    def test_state_with_only_a_fresh_timestamp_is_not_ready(self):
        """A truncated state must not satisfy every check vacuously."""
        from scripts.freshness_gate import evaluate_readiness

        result = evaluate_readiness({"checked_at": CHECKED_AT, "max_age_hours": 24}, now=NOW)
        self.assertFalse(result["ready_for_dna"])
        self.assertTrue(any(b.endswith(":component_absent") for b in result["blockers"]))
        self.assertTrue(any(b.endswith(":evidence_source_absent") for b in result["blockers"]))

    def test_empty_component_and_source_lists_are_not_ready(self):
        from scripts.freshness_gate import evaluate_readiness

        result = evaluate_readiness(
            {"checked_at": CHECKED_AT, "max_age_hours": 24, "components": [], "evidence_sources": []},
            now=NOW,
        )
        self.assertFalse(result["ready_for_dna"])

    def test_every_required_component_must_be_present(self):
        from scripts.freshness_gate import evaluate_readiness

        state = _complete_state()
        dropped = state["components"].pop()["name"]
        result = evaluate_readiness(state, now=NOW)
        self.assertFalse(result["ready_for_dna"])
        self.assertIn(f"{dropped}:component_absent", result["blockers"])

    def test_every_required_evidence_source_must_be_present(self):
        from scripts.freshness_gate import evaluate_readiness

        state = _complete_state()
        dropped = state["evidence_sources"].pop()["name"]
        result = evaluate_readiness(state, now=NOW)
        self.assertFalse(result["ready_for_dna"])
        self.assertIn(f"{dropped}:evidence_source_absent", result["blockers"])

    def test_required_sets_track_the_real_runtime_and_adapter_registries(self):
        from evidence_adapters import ADAPTERS
        from scripts.freshness_gate import REQUIRED_COMPONENTS, REQUIRED_EVIDENCE_SOURCES
        from scripts.runtime_stack import MANAGED_RUNTIME_PACKAGES

        self.assertEqual(REQUIRED_COMPONENTS, frozenset(MANAGED_RUNTIME_PACKAGES))
        self.assertEqual(REQUIRED_EVIDENCE_SOURCES, frozenset(ADAPTERS))


if __name__ == "__main__":
    unittest.main()
