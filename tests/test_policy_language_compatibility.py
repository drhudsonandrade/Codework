"""Preserve policy wire values while exposing English implementation names."""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
import pickle
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from policy_engine.genoma_policy import attestation, gates_common, ledger
from policy_engine.genoma_policy.gates_core import CoreGates
from policy_engine.genoma_policy.models import (
    ClaimNature,
    Domain,
    EvaluationReport,
    GateState,
    OperationalStatus,
    RulesetSection,
    canonical_manifest_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
ENUM_CASES = (
    (OperationalStatus, (
        ("EXECUTED", "EXECUTADO", "EXECUTADO"),
        ("VERIFIED", "VERIFICADO", "VERIFICADO"),
        ("INFERRED", "INFERIDO", "INFERIDO"),
        ("PROPOSED", "PROPOSTO", "PROPOSTO"),
        ("UNAVAILABLE", "NAO_DISPONIVEL", "NÃO DISPONÍVEL"),
    )),
    (ClaimNature, (
        ("CONFIRMED_FACT", "FATO_CONFIRMADO", "FATO CONFIRMADO"),
        ("INFERENCE", "INFERENCIA", "INFERÊNCIA"),
        ("ASSOCIATION", "ASSOCIACAO", "ASSOCIAÇÃO"),
        ("HYPOTHESIS", "HIPOTESE", "HIPÓTESE"),
        ("UNKNOWN", "DESCONHECIDO", "DESCONHECIDO"),
    )),
    (Domain, (
        ("CLINICAL", "CLINICO", "CLÍNICO"),
        ("PREDISPOSITION", "PREDISPOSICAO", "PREDISPOSIÇÃO"),
        ("RESEARCH", "PESQUISA", "PESQUISA"),
        ("CURIOSITY", "CURIOSIDADE", "CURIOSIDADE"),
    )),
)
TEST_RENAMES = {
    "policy_engine/tests/test_policy_engine.py": {
        "test_duplicate_vigente_fails_closed":
            "test_duplicate_active_ruleset_fails_closed",
        "test_ruleset_gate_rejects_non_vigente_status":
            "test_ruleset_gate_rejects_inactive_status",
    },
    "policy_engine/tests/test_schema_contract.py": {
        "test_ruleset_requires_vigente_status":
            "test_ruleset_requires_active_status",
    },
}


class PolicyLanguageCompatibilityTest(unittest.TestCase):
    """Check additive names against independent legacy values and real gates."""

    def _english_member(self, enum_type, name):
        """Fail explicitly when an intended English access name is missing."""
        self.assertIn(name, enum_type.__members__)
        return enum_type[name]

    def test_english_aliases_preserve_legacy_member_identity(self):
        """New names must retain lookup, reflection, hashing and pickling."""
        for enum_type, cases in ENUM_CASES:
            for english, legacy, wire in cases:
                with self.subTest(enum=enum_type.__name__, name=english):
                    member = self._english_member(enum_type, english)
                    self.assertIs(member, enum_type[legacy])
                    self.assertEqual(member.value, wire)
                    self.assertIs(member, enum_type(wire))
                    self.assertEqual(member.name, legacy)
                    self.assertEqual(str(member), str(enum_type[legacy]))
                    self.assertEqual(repr(member), repr(enum_type[legacy]))
                    self.assertEqual(hash(member), hash(wire))
                    self.assertIs(pickle.loads(pickle.dumps(member)), member)

    def test_iteration_and_existing_symbolic_names_remain_unchanged(self):
        """Aliases must not add normative states or reorder existing members."""
        for enum_type, cases in ENUM_CASES:
            with self.subTest(enum=enum_type.__name__):
                self.assertEqual(
                    [(member.name, member.value) for member in enum_type],
                    [(legacy, wire) for _, legacy, wire in cases],
                )
                self.assertEqual(len(enum_type), len(cases))

    def test_validators_keep_exact_closed_wire_vocabularies(self):
        """Membership tables retain independent baseline spellings and accents."""
        expected = [{wire for _, _, wire in cases} for _, cases in ENUM_CASES]
        self.assertEqual(gates_common.ALLOWED_OPERATIONAL, expected[0])
        self.assertEqual(attestation.ALLOWED_OPERATIONAL, expected[0])
        self.assertEqual(gates_common.ALLOWED_NATURE, expected[1])
        self.assertEqual(gates_common.ALLOWED_DOMAIN, expected[2])
        self.assertEqual(
            attestation.SATISFYING_STATUSES,
            {"EXECUTADO", "VERIFICADO", "INFERIDO"},
        )

    def test_taxonomy_accepts_all_existing_wire_combinations(self):
        """Exercise the real taxonomy gate on all 100 valid combinations."""
        values = [[wire for _, _, wire in cases] for _, cases in ENUM_CASES]
        for status, nature, domain in itertools.product(*values):
            with self.subTest(status=status, nature=nature, domain=domain):
                claim = dict(status=status, nature=nature, domain=domain,
                             priority="P3")
                result = CoreGates()._taxonomy_gate({"claims": [claim]})
                self.assertIs(result.state, GateState.PASS)
                self.assertEqual(result.reasons, ())

    def test_english_names_are_not_new_wire_values(self):
        """Implementation aliases must not silently broaden accepted payloads."""
        for field, (enum_type, cases) in zip(
            ("status", "nature", "domain"), ENUM_CASES, strict=True
        ):
            for english, _, _ in cases:
                with self.subTest(field=field, value=english):
                    self._english_member(enum_type, english)
                    with self.assertRaises(ValueError):
                        enum_type(english)
                    claim = dict(status="EXECUTADO", nature="FATO CONFIRMADO",
                                 domain="PESQUISA", priority="P3")
                    claim[field] = english
                    result = CoreGates()._taxonomy_gate({"claims": [claim]})
                    self.assertIs(result.state, GateState.FAIL)
                    self.assertTrue(result.blocking)
                    self.assertTrue(result.reasons)

    def test_alias_payload_preserves_json_manifest_and_ledger_digest(self):
        """Serializing enum objects keeps exact Unicode bytes and audit hashes."""
        payload = {
            "status": self._english_member(OperationalStatus, "UNAVAILABLE"),
            "nature": self._english_member(ClaimNature, "INFERENCE"),
            "domain": self._english_member(Domain, "CLINICAL"),
        }
        expected_bytes = (
            '{"domain":"CLÍNICO","nature":"INFERÊNCIA",'
            '"status":"NÃO DISPONÍVEL"}'
        ).encode("utf-8")
        expected = json.loads(expected_bytes)
        actual_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(actual_bytes, expected_bytes)
        expected_digest = hashlib.sha256(expected_bytes).hexdigest()
        self.assertEqual(canonical_manifest_sha256(payload), expected_digest)
        self.assertEqual(canonical_manifest_sha256(expected), expected_digest)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            for content in (payload, expected):
                event = ledger.append_event(path, "SYNTHETIC", content)
                self.assertEqual(event["payload_sha256"], expected_digest)
            self.assertEqual(ledger.verify_ledger(path), (True, []))

    def test_evaluation_serialization_remains_wire_compatible(self):
        """English access must not change the public or internal report form."""
        status = self._english_member(OperationalStatus, "EXECUTED")
        manifest = {"execution_manifest": [{"status": status}]}
        baseline = {"execution_manifest": [{"status": "EXECUTADO"}]}
        actual = EvaluationReport(ruleset={}, evaluated_manifest=manifest)
        expected = EvaluationReport(ruleset={}, evaluated_manifest=baseline)
        for actual_value, expected_value in (
            (actual.to_dict(), expected.to_dict()),
            (actual.to_internal_dict(), expected.to_internal_dict()),
        ):
            self.assertEqual(
                json.dumps(actual_value, ensure_ascii=False, sort_keys=True),
                json.dumps(expected_value, ensure_ascii=False, sort_keys=True),
            )

    def test_attestation_decisions_remain_fail_closed(self):
        """Only the three existing satisfying statuses accept a valid proof."""
        section = RulesetSection(1, "Synthetic section", "", "0" * 64)
        for english, _, wire in ENUM_CASES[0][1]:
            with self.subTest(status=english):
                member = self._english_member(OperationalStatus, english)
                proof = {
                    "section": 1,
                    "rule_id": section.rule_id,
                    "rule_sha256": section.sha256,
                    "applicability": "APPLICABLE",
                    "status": member.value,
                    "decision": "SATISFIED",
                    "justification": "Synthetic compatibility fixture",
                    "evidence_refs": ["fixture:proof"],
                    "trace": {
                        "attestation_id": "fixture-1",
                        "actor_type": "SOFTWARE",
                        "actor_id": "fixture",
                        "method": "unit-test",
                        "run_id": "fixture-run",
                        "created_at": "2026-09-09T00:00:00Z",
                        "tool_versions": {},
                        "input_sha256": ["0" * 64],
                        "output_sha256": ["1" * 64],
                    },
                }
                reasons = attestation.validate_section_attestation(
                    proof, section, {"fixture:proof"}
                )
                if wire in {"EXECUTADO", "VERIFICADO", "INFERIDO"}:
                    self.assertEqual(reasons, [])
                else:
                    self.assertEqual(reasons, [
                        f"section 1 status {wire} cannot claim SATISFIED"
                    ])
                proof["evidence_refs"] = []
                reasons = attestation.validate_section_attestation(
                    proof, section, {"fixture:proof"}
                )
                self.assertIn(
                    "section 1 SATISFIED decision requires explicit evidence",
                    reasons,
                )

    def test_private_policy_test_names_use_english(self):
        """The three inventoried test names change without changing fixtures."""
        for relative, renames in TEST_RENAMES.items():
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            names = {
                node.name for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
            }
            for legacy, english in renames.items():
                with self.subTest(path=relative, name=english):
                    self.assertNotIn(legacy, names)
                    self.assertIn(english, names)


if __name__ == "__main__":
    unittest.main()
