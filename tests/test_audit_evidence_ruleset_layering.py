from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE = ROOT / ".github" / "governance"
INTEGRITY_RULESET = GOVERNANCE / "audit-evidence-integrity-ruleset.json"
PUBLISHER_RULESET = GOVERNANCE / "audit-evidence-publisher-ruleset.json"
DEPLOY_KEY_BYPASS = [{"actor_id": None, "actor_type": "DeployKey", "bypass_mode": "always"}]
HISTORY_RULE_TYPES = {"deletion", "non_fast_forward"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_strict_publisher_ruleset(ruleset: dict) -> None:
    if ruleset.get("enforcement") != "active":
        raise AssertionError("publisher ruleset must remain active")
    if ruleset.get("bypass_actors") != DEPLOY_KEY_BYPASS:
        raise AssertionError("publisher bypass actor contract changed")
    rules = ruleset.get("rules")
    if not isinstance(rules, list) or len(rules) != 1:
        raise AssertionError("publisher ruleset must contain exactly one rule")
    update = rules[0]
    if update.get("type") != "update":
        raise AssertionError("publisher ruleset must contain only the update restriction")
    if update.get("parameters", {}).get("update_allows_fetch_and_merge") is not False:
        raise AssertionError("publisher update restriction must remain fail-closed")


def _assert_deploy_key_never_bypasses_history_protections(ruleset: dict) -> None:
    bypass_actors = ruleset.get("bypass_actors", [])
    if not isinstance(bypass_actors, list):
        raise AssertionError("bypass_actors must be a list")
    has_deploy_key = any(
        isinstance(actor, dict) and actor.get("actor_type") == "DeployKey"
        for actor in bypass_actors
    )
    if not has_deploy_key:
        return
    rules = ruleset.get("rules", [])
    if not isinstance(rules, list):
        raise AssertionError("rules must be a list")
    types = {rule.get("type") for rule in rules if isinstance(rule, dict)}
    if not types.isdisjoint(HISTORY_RULE_TYPES):
        raise AssertionError("DeployKey bypass must not apply to history-mutation protections")


class AuditEvidenceRulesetLayeringTests(unittest.TestCase):
    def test_integrity_ruleset_has_no_bypass_for_history_protections(self) -> None:
        ruleset = _load(INTEGRITY_RULESET)
        self.assertEqual(ruleset["enforcement"], "active")
        self.assertEqual(ruleset["bypass_actors"], [])
        self.assertEqual(
            {rule["type"] for rule in ruleset["rules"]},
            HISTORY_RULE_TYPES,
        )
        self.assertEqual(
            ruleset["conditions"]["ref_name"]["include"],
            ["refs/heads/audit-evidence"],
        )

    def test_publisher_bypass_applies_only_to_one_strict_update_restriction(self) -> None:
        ruleset = _load(PUBLISHER_RULESET)
        _assert_strict_publisher_ruleset(ruleset)
        self.assertEqual(
            ruleset["conditions"]["ref_name"]["include"],
            ["refs/heads/audit-evidence"],
        )

        permissive = copy.deepcopy(ruleset)
        permissive["rules"].append(
            {"type": "update", "parameters": {"update_allows_fetch_and_merge": True}}
        )
        with self.assertRaises(AssertionError):
            _assert_strict_publisher_ruleset(permissive)

    def test_deploy_key_bypass_never_shares_a_ruleset_with_history_mutation_rules(self) -> None:
        for path in sorted(GOVERNANCE.glob("audit-evidence-*-ruleset.json")):
            _assert_deploy_key_never_bypasses_history_protections(_load(path))

        mixed_actor_mutation = {
            "bypass_actors": [
                {"actor_id": 1, "actor_type": "Team", "bypass_mode": "always"},
                *DEPLOY_KEY_BYPASS,
            ],
            "rules": [{"type": "deletion"}],
        }
        with self.assertRaises(AssertionError):
            _assert_deploy_key_never_bypasses_history_protections(mixed_actor_mutation)


if __name__ == "__main__":
    unittest.main()
