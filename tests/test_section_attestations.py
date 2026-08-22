"""RULE_COVERAGE_GATE asks 263 questions, and the answers are judgements, not defaults.

The gate requires, for every section of the vigente ruleset, a statement of whether the rule
applies to the operation and — if it does — how it was satisfied, with evidence that exists in
the run. It has been the last blocking gate open precisely because there is no way to compute
those answers.

They are curated in `config/section_attestations_array.json`, one per section, written against
the section's text and pinned to it by SHA-256. What this suite checks is not that the answers
are *right* — no test can check a judgement — but that the machinery around them cannot
manufacture one: the curation is complete and internally consistent, a judgement made against
changed text is refused, an attestation cannot cite evidence the run does not produce, and the
trace is bound to the run rather than stored.

An external audit once reached `ready_for_requested_operation: true` by attesting all 263 rules
NOT_APPLICABLE with a single boilerplate justification. That shape is refused twice over now:
by the engine, and by the curation validator before a run ever starts.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from reporting.section_attestations import (
    ALLOWED_APPLICABILITY,
    ARRAY_CURATION_PATH,
    SATISFYING_STATUSES,
    CurationError,
    build_attestations,
    coverage_report,
    load_curation,
    pending,
    rule_id_for,
    validate_curation,
)

ARTIFACTS = {
    "array-input": "a" * 64,
    "array-qc": "b" * 64,
    "partial-annotation": "c" * 64,
    f"ruleset-{normative.VERSION}": normative.RAW_SHA256,
}


class TheCurationIsCompleteAndConsistentTest(unittest.TestCase):
    def setUp(self):
        self.curation = load_curation()

    def test_every_section_of_the_vigente_ruleset_has_a_judgement(self):
        self.assertEqual([], pending(self.curation))
        self.assertEqual(normative.SECTION_COUNT, len(self.curation["sections"]))

    def test_the_curation_has_no_internal_problems(self):
        self.assertEqual([], validate_curation(self.curation))

    def test_every_justification_is_its_own(self):
        """263 distinct answers, because 263 distinct rules were asked about."""
        justifications = [e["justification"] for e in self.curation["sections"].values()]
        self.assertEqual(len(justifications), len(set(justifications)))

    def test_no_justification_is_a_placeholder(self):
        for key, entry in self.curation["sections"].items():
            with self.subTest(section=key):
                # Short enough to be a label rather than a reason is the shape the blanket
                # NOT_APPLICABLE manifest had.
                self.assertGreater(len(entry["justification"]), 60)

    def test_the_operation_is_not_declared_inapplicable_as_a_whole(self):
        applicable = [
            e for e in self.curation["sections"].values() if e["applicability"] == "APPLICABLE"
        ]
        self.assertGreater(len(applicable), 100)
        self.assertEqual("APPLICABLE", self.curation["sections"]["0"]["applicability"])

    def test_the_curation_is_pinned_to_the_vigente_ruleset(self):
        self.assertEqual(normative.RAW_SHA256, self.curation["ruleset"]["sha256"])

    def test_the_coverage_report_says_complete(self):
        report = coverage_report(self.curation)
        self.assertEqual("COMPLETA", report["status"])
        self.assertEqual(0, report["pending"])

    def test_the_file_on_disk_is_the_one_the_loader_reads(self):
        self.assertTrue(ARRAY_CURATION_PATH.is_file())
        self.assertEqual(
            json.loads(ARRAY_CURATION_PATH.read_text(encoding="utf-8")), self.curation
        )


class AJudgementIsAboutTheTextItWasWrittenAgainstTest(unittest.TestCase):
    def test_a_curation_for_another_ruleset_is_refused_at_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "curation.json"
            payload = load_curation()
            payload["ruleset"]["sha256"] = "0" * 64
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(CurationError) as caught:
                load_curation(path)
        self.assertIn("recurar", str(caught.exception))

    def test_each_entry_carries_the_hash_of_the_section_it_judges(self):
        for key, entry in load_curation()["sections"].items():
            with self.subTest(section=key):
                self.assertRegex(entry["rule_sha256"], r"^[0-9a-f]{64}$")

    def test_the_rule_ids_are_derived_the_way_the_engine_derives_them(self):
        self.assertEqual("GENOMA-V3.4-S000", rule_id_for(0))
        self.assertEqual("GENOMA-V3.4-S262", rule_id_for(262))

    def test_a_missing_schema_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "curation.json"
            path.write_text(json.dumps({"sections": {}}), encoding="utf-8")
            with self.assertRaises(CurationError):
                load_curation(path)


class TheValidatorCatchesWhatTheGateWouldTest(unittest.TestCase):
    """Caught while curating rather than discovered as a failed analysis."""

    def _broken(self, **changes):
        curation = copy.deepcopy(load_curation())
        curation["sections"]["10"].update(changes)
        return curation

    def test_an_invalid_applicability_is_named(self):
        problems = validate_curation(self._broken(applicability="TALVEZ"))
        self.assertTrue(any("applicability" in p for p in problems))

    def test_a_not_applicable_rule_cannot_decide_satisfied(self):
        problems = validate_curation(
            self._broken(applicability="NOT_APPLICABLE", decision="SATISFIED")
        )
        self.assertTrue(any("NOT_APPLICABLE" in p for p in problems))

    def test_an_applicable_rule_cannot_decide_not_applicable(self):
        problems = validate_curation(
            self._broken(applicability="APPLICABLE", decision="NOT_APPLICABLE")
        )
        self.assertTrue(any("cannot decide" in p for p in problems))

    def test_satisfied_requires_a_status_that_can_claim_it(self):
        problems = validate_curation(self._broken(status="PROPOSTO"))
        self.assertTrue(any("cannot claim SATISFIED" in p for p in problems))
        self.assertNotIn("PROPOSTO", SATISFYING_STATUSES)

    def test_satisfied_requires_evidence(self):
        problems = validate_curation(self._broken(evidence_refs=[]))
        self.assertTrue(any("evidence_refs" in p for p in problems))

    def test_an_empty_justification_is_refused(self):
        problems = validate_curation(self._broken(justification="   "))
        self.assertTrue(any("justification" in p for p in problems))

    def test_one_justification_for_every_inapplicable_rule_is_refused(self):
        curation = copy.deepcopy(load_curation())
        for entry in curation["sections"].values():
            if entry["applicability"] == "NOT_APPLICABLE":
                entry["justification"] = "não se aplica"
        problems = validate_curation(curation)
        self.assertTrue(any("one text cannot be the reason" in p for p in problems))

    def test_the_allowed_vocabularies_match_the_engine(self):
        from genoma_policy.attestation import (  # noqa: PLC0415
            ALLOWED_APPLICABILITY as ENGINE_APPLICABILITY,
        )

        self.assertEqual(set(ALLOWED_APPLICABILITY), ENGINE_APPLICABILITY)


class TheTraceIsBoundToTheRunTest(unittest.TestCase):
    def setUp(self):
        self.attestations = build_attestations(
            load_curation(),
            artifact_sha256=ARTIFACTS,
            input_sha256=ARTIFACTS["array-input"],
            run_id="corrida-de-teste",
        )

    def test_one_attestation_per_section_in_order(self):
        self.assertEqual(normative.SECTION_COUNT, len(self.attestations))
        self.assertEqual(
            list(range(normative.SECTION_COUNT)), [a["section"] for a in self.attestations]
        )

    def test_a_satisfied_attestation_names_the_digests_this_run_produced(self):
        satisfied = [a for a in self.attestations if a["decision"] == "SATISFIED"]
        self.assertTrue(satisfied)
        for attestation in satisfied:
            with self.subTest(section=attestation["section"]):
                trace = attestation["trace"]
                self.assertEqual([ARTIFACTS["array-input"]], trace["input_sha256"])
                self.assertEqual(
                    [ARTIFACTS[ref] for ref in attestation["evidence_refs"]],
                    trace["output_sha256"],
                )
                self.assertEqual("corrida-de-teste", trace["run_id"])

    def test_an_inapplicable_attestation_claims_no_digests(self):
        for attestation in self.attestations:
            if attestation["decision"] == "NOT_APPLICABLE":
                with self.subTest(section=attestation["section"]):
                    self.assertEqual([], attestation["trace"]["input_sha256"])
                    self.assertEqual([], attestation["trace"]["output_sha256"])
                    self.assertEqual([], attestation["evidence_refs"])

    def test_evidence_the_run_does_not_produce_is_refused_not_dropped(self):
        curation = copy.deepcopy(load_curation())
        curation["sections"]["10"]["evidence_refs"] = ["base-que-nao-existe"]
        with self.assertRaises(CurationError) as caught:
            build_attestations(
                curation,
                artifact_sha256=ARTIFACTS,
                input_sha256=ARTIFACTS["array-input"],
                run_id="x",
            )
        self.assertIn("base-que-nao-existe", str(caught.exception))

    def test_no_digest_is_stored_in_the_curation_file(self):
        """A stored hash would certify an execution that did not happen."""
        raw = ARRAY_CURATION_PATH.read_text(encoding="utf-8")
        self.assertNotIn("input_sha256", raw)
        self.assertNotIn("output_sha256", raw)
        self.assertNotIn("trace", raw)


class TheEngineAcceptsWhatTheBuilderProducesTest(unittest.TestCase):
    """The curation and the gate must agree, or a complete curation still refuses."""

    def _sections(self):
        from genoma_policy.ruleset import load_ruleset  # noqa: PLC0415
        import subprocess  # noqa: PLC0415

        directory = Path(tempfile.mkdtemp())
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/materialize_ruleset.py"),
             "--output-dir", str(directory)],
            check=True, capture_output=True, text=True,
        )
        canonical = next(directory.glob("REGRAS_PROJETO_GENOMA_VIGENTE_*.txt"))
        try:
            return load_ruleset(canonical).sections
        finally:
            canonical.unlink(missing_ok=True)

    def test_every_attestation_validates_against_the_live_ruleset_section(self):
        from genoma_policy.attestation import validate_section_attestation  # noqa: PLC0415

        sections = self._sections()
        attestations = build_attestations(
            load_curation(),
            artifact_sha256=ARTIFACTS,
            input_sha256=ARTIFACTS["array-input"],
            run_id="corrida-de-teste",
        )
        evidence_ids = set(ARTIFACTS)
        problems: list[str] = []
        for attestation in attestations:
            problems.extend(
                validate_section_attestation(
                    attestation, sections[attestation["section"]], evidence_ids
                )
            )
        self.assertEqual([], problems)

    def test_the_curated_hashes_are_the_live_section_hashes(self):
        """The pin is only worth something if it matches the text in force."""
        curation = load_curation()
        for section in self._sections():
            with self.subTest(section=section.number):
                self.assertEqual(
                    section.sha256, curation["sections"][str(section.number)]["rule_sha256"]
                )


if __name__ == "__main__":
    unittest.main()
