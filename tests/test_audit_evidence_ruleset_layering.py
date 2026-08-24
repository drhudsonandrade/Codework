from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = ROOT / ".github" / "governance"
INTEGRITY_RULESET = GOVERNANCE / "audit-evidence-integrity-ruleset.json"
PUBLISHER_RULESET = GOVERNANCE / "audit-evidence-publisher-ruleset.json"
DEPLOY_KEY_BYPASS = [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class AuditEvidenceRulesetLayeringTests(unittest.TestCase):
    def test_integrity_ruleset_has_no_bypass_for_history_protections(self) -> None:
        ruleset = _load(INTEGRITY_RULESET)
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["bypass_actors"], [])
        self.assertEqual(
            {rule["type"] for rule in ruleset["rules"]},
            {"deletion", "non_fast_forward"},
        )
        self.assertEqual(
            ruleset["conditions"]["ref_name"]["include"],
            ["refs/heads/audit-evidence"],
        )

    def test_publisher_bypass_applies_only_to_update_restriction(self) -> None:
        ruleset = _load(PUBLISHER_RULESET)
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["bypass_actors"], DEPLOY_KEY_BYPASS)
        self.assertEqual({rule["type"] for rule in ruleset["rules"]}, {"update"})
        update = ruleset["rules"][0]
        self.assertFalse(update["parameters"]["update_allows_fetch_and_merge"])
        self.assertEqual(
            ruleset["conditions"]["ref_name"]["include"],
            ["refs/heads/audit-evidence"],
        )

    def test_deploy_key_bypass_never_shares_a_ruleset_with_history_mutation_rules(self) -> None:
        for path in sorted(GOVERNANCE.glob("audit-evidence-*-ruleset.json")):
            ruleset = _load(path)
            if ruleset.get("bypass_actors") == DEPLOY_KEY_BYPASS:
                types = {rule["type"] for rule in ruleset["rules"]}
                self.assertTrue(types.isdisjoint({"deletion", "non_fast_forward"}), path.name)


if __name__ == "__main__":
    unittest.main()
