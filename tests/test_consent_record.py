"""Consent must be a record bound to a person and to bytes, not three fields anyone can type.

CONSENT_GATE checks `verified`, `version` and a non-empty `authorized_domains`, and the
orchestrator forwarded whatever JSON the operator supplied. So

    --consent '{"verified": true, "version": "x", "authorized_domains": ["CLÍNICO"]}'

cleared the gate that stands between a genomic file and a published report about a person.
Nothing bound the record to the subject, to the bytes analysed, or to a date; and nothing
checked that the report being published fell inside what was authorised — a record for
ANCESTRALIDADE published a clinical report, because the engine evaluates consent once for the
whole run and knows nothing about which of the eleven reports is being built.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.catalog import load_catalog
from reporting.consent import (
    ALLOWED_DOMAINS,
    CONSENT_ARTIFACT,
    REPORT_DOMAINS,
    REQUIRED_AFFIRMATIONS,
    ConsentError,
    domain_for,
    load_record,
    scope_verdict,
    validate_record,
)
from reporting.provenance import Artifact, PayloadCompiler, ProvenanceError, UNAVAILABLE
from tests.attestations import POLICY_PASS, consent_file, consent_record, policy_evaluation_file

ARTIFACT = {"metrics": {"call_rate": 0.99}}


def compiler(root: Path, *, report_id: str = "09", consent: Path | None = None, case_id="CASO-C"):
    built = PayloadCompiler(
        case_id=case_id,
        report_id=report_id,
        policy_evaluation=policy_evaluation_file(root, POLICY_PASS),
        consent=consent,
    )
    built.register(Artifact.from_payload("array-qc", ARTIFACT))
    built.derive(
        "summary", artifact="array-qc", locator="metrics.call_rate",
        status="VERIFICADO", basis="call rate",
    )
    built.state("sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO")
    built.state("limitations", "escopo", kind="case_control", basis="e", status="VERIFICADO")
    return built


class TheRecordMustBeComplete(unittest.TestCase):
    def test_a_complete_record_validates(self):
        self.assertTrue(validate_record(consent_record(case_id="C")))

    def test_every_required_field_is_checked_on_its_own(self):
        from reporting.consent import REQUIRED_FIELDS

        for field in REQUIRED_FIELDS:
            record = consent_record(case_id="C")
            del record[field]
            with self.subTest(field=field), self.assertRaises(ConsentError) as caught:
                validate_record(record)
            self.assertIn(field, str(caught.exception))

    def test_the_schema_must_be_this_one(self):
        with self.assertRaises(ConsentError):
            validate_record(consent_record(case_id="C", schema="algum-outro-schema"))

    def test_a_non_object_is_refused(self):
        for value in (None, [], "consentimento", 7):
            with self.subTest(value=value), self.assertRaises(ConsentError):
                validate_record(value)


class VerifiedIsTheConclusionOfTheAffirmations(unittest.TestCase):
    """`verified` was a boolean someone wrote. It is now the end of a set of statements."""

    def test_verified_true_without_an_affirmation_is_refused(self):
        for missing in REQUIRED_AFFIRMATIONS:
            record = consent_record(case_id="C")
            record["affirmations"][missing] = False
            with self.subTest(affirmation=missing), self.assertRaises(ConsentError) as caught:
                validate_record(record)
            self.assertIn(missing, str(caught.exception))

    def test_an_empty_affirmations_block_does_not_pass_by_vacuity(self):
        with self.assertRaises(ConsentError):
            validate_record(consent_record(case_id="C", affirmations={}))

    def test_verified_false_authorises_nothing(self):
        record = consent_record(case_id="C")
        record["verified"] = False
        with self.assertRaises(ConsentError) as caught:
            validate_record(record)
        self.assertIn("não autoriza", str(caught.exception))


class TheRecordIsBoundToThisRunTest(unittest.TestCase):
    def test_a_record_for_another_case_is_refused(self):
        with self.assertRaises(ConsentError) as caught:
            validate_record(consent_record(case_id="CASO-A"), case_id="CASO-B")
        self.assertIn("não viaja entre casos", str(caught.exception))

    def test_a_record_for_other_bytes_is_refused(self):
        with self.assertRaises(ConsentError) as caught:
            validate_record(
                consent_record(case_id="C", input_sha256="a" * 64), input_sha256="b" * 64
            )
        self.assertIn("não viaja entre arquivos", str(caught.exception))

    def test_an_expired_record_is_refused(self):
        record = consent_record(case_id="C", granted_at="2020-01-01", expires_at="2020-12-31")
        with self.assertRaises(ConsentError) as caught:
            validate_record(record)
        self.assertIn("expirou", str(caught.exception))

    def test_a_record_still_inside_its_window_is_accepted(self):
        record = consent_record(case_id="C", granted_at="2026-01-01", expires_at="2026-12-31")
        self.assertTrue(validate_record(record, today=date(2026, 6, 1)))

    def test_a_record_granted_in_the_future_is_refused(self):
        record = consent_record(case_id="C", granted_at="2099-01-01")
        with self.assertRaises(ConsentError) as caught:
            validate_record(record)
        self.assertIn("futuro", str(caught.exception))

    def test_an_unreadable_date_is_refused_rather_than_ignored(self):
        for bad in (None, "", "ontem", 17):
            with self.subTest(granted_at=bad), self.assertRaises(ConsentError):
                validate_record(consent_record(case_id="C", granted_at=bad))


class TheDomainVocabularyIsClosedTest(unittest.TestCase):
    def test_an_unknown_domain_is_refused_not_ignored(self):
        with self.assertRaises(ConsentError) as caught:
            validate_record(consent_record(case_id="C", authorized_domains=["CLINICO"]))
        # Without the accent it is a different string, authorising nothing while reading to a
        # human as though it authorised the clinical domain.
        self.assertIn("CLINICO", str(caught.exception))

    def test_an_empty_domain_list_is_refused(self):
        with self.assertRaises(ConsentError):
            validate_record(consent_record(case_id="C", authorized_domains=[]))

    def test_every_report_in_the_catalogue_has_a_domain(self):
        """A report added without deciding what consent covers it must not publish."""
        self.assertEqual(sorted(load_catalog()), sorted(REPORT_DOMAINS))
        for report_id, domain in REPORT_DOMAINS.items():
            with self.subTest(report=report_id):
                self.assertIn(domain, ALLOWED_DOMAINS)

    def test_a_report_outside_the_table_refuses_rather_than_defaulting(self):
        with self.assertRaises(ConsentError):
            domain_for("99")


class ConsentForOneScopeIsNotConsentForAnotherTest(unittest.TestCase):
    def test_a_record_covering_the_domain_passes(self):
        record = consent_record(case_id="C", authorized_domains=["CLÍNICO"])
        self.assertIs(scope_verdict(record, "01")["covers"], True)

    def test_a_record_for_another_domain_does_not_cover_this_report(self):
        record = consent_record(case_id="C", authorized_domains=["ANCESTRALIDADE"])
        verdict = scope_verdict(record, "01")
        self.assertIs(verdict["covers"], False)
        self.assertIn("não é consentimento para este", verdict["basis"])

    def test_no_record_covers_nothing(self):
        self.assertIs(scope_verdict(None, "01")["covers"], False)

    def test_carrier_screening_is_its_own_domain(self):
        """Report 03 reports on relatives as well as on the subject."""
        self.assertEqual(REPORT_DOMAINS["03"], "REPRODUTIVO")
        clinical = consent_record(case_id="C", authorized_domains=["CLÍNICO"])
        self.assertIs(scope_verdict(clinical, "03")["covers"], False)


class TheCompilerReadsTheRecordFromDiskTest(unittest.TestCase):
    def test_the_reserved_artifact_name_cannot_be_registered(self):
        with tempfile.TemporaryDirectory() as td:
            built = compiler(Path(td))
            with self.assertRaises(ProvenanceError) as caught:
                built.register(
                    Artifact.from_payload(CONSENT_ARTIFACT, consent_record(case_id="CASO-C"))
                )
        self.assertIn("consent=<path>", str(caught.exception))

    def test_extra_cannot_supply_the_consent_block(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ProvenanceError):
                compiler(Path(td)).compile(extra={"consent": {"covers": True}})

    def test_a_covering_record_sets_the_scope_key_and_names_its_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = consent_file(root, case_id="CASO-C", authorized_domains=["TÉCNICO"])
            data = compiler(root, report_id="09", consent=path).compile()
        self.assertIs(data["publication_gate"]["consent_scope_verified"], True)
        self.assertEqual(data["consent"]["origin"], "operator-record")
        self.assertEqual(
            data["consent"]["record_sha256"], data["artifacts"][CONSENT_ARTIFACT]["sha256"]
        )

    def test_a_record_for_another_domain_withholds_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = consent_file(root, case_id="CASO-C", authorized_domains=["ANCESTRALIDADE"])
            data = compiler(root, report_id="09", consent=path).compile()
        self.assertIs(data["publication_gate"]["consent_scope_verified"], False)
        self.assertIn("ANCESTRALIDADE", data["consent"]["basis"])

    def test_an_invalid_record_refuses_without_stopping_the_measurements(self):
        """The matrix is a fact about the file whether or not consent is in order."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "consent-record.json"
            path.write_text(
                json.dumps(consent_record(case_id="OUTRO-CASO")), encoding="utf-8"
            )
            data = compiler(root, report_id="09", consent=path).compile()
        self.assertIs(data["publication_gate"]["consent_scope_verified"], False)
        self.assertIn("não é válido", data["consent"]["basis"])
        self.assertEqual(data["summary"], 0.99)

    def test_the_engine_verdict_alone_cannot_grant_the_scope(self):
        """`consent_scope_verified` is strictly subtractive; a PASS cannot supply it."""
        with tempfile.TemporaryDirectory() as td:
            data = compiler(Path(td), report_id="09").compile()
        self.assertIs(data["publication_gate"]["consent_verified"], True)
        self.assertIs(data["publication_gate"]["consent_scope_verified"], False)


class RenderRefusesOutsideTheAuthorisedScopeTest(unittest.TestCase):
    def test_final_is_blocked_when_the_report_is_outside_the_scope(self):
        from reporting.engine import ReportReleaseError, render_document

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = consent_file(root, case_id="CASO-C", authorized_domains=["ANCESTRALIDADE"])
            data = compiler(root, report_id="09", consent=path).compile()
            with self.assertRaises(ReportReleaseError) as caught:
                render_document("09", data, mode="FINAL")
        self.assertIn("publication_gate:consent_scope_verified", str(caught.exception))

    def test_final_proceeds_inside_the_scope(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = consent_file(root, case_id="CASO-C", authorized_domains=["TÉCNICO"])
            data = compiler(root, report_id="09", consent=path).compile()
            self.assertIn("markdown", render_document("09", data, mode="FINAL"))


class LayoutQaGetsAFixtureRecordTest(unittest.TestCase):
    def test_the_fixture_payload_declares_its_consent_as_a_fixture(self):
        from reporting.provenance import fixture_payload

        data = fixture_payload(case_id="QA", report_id="09", summary="s", basis="qa")
        self.assertIs(data["publication_gate"]["consent_scope_verified"], True)
        self.assertEqual(data["consent"]["origin"], "fixture")
        self.assertEqual(data["operational_status"], UNAVAILABLE)

    def test_a_fixture_consent_cannot_sit_beside_a_measured_value(self):
        with tempfile.TemporaryDirectory() as td:
            built = compiler(Path(td))  # `summary` is derived from a real artifact
            built._install_consent(
                Artifact.from_payload(CONSENT_ARTIFACT, consent_record(case_id="CASO-C")),
                fixture=True,
            )
            with self.assertRaises(ProvenanceError):
                built.compile()


class TheCaptureCliProducesAValidRecordTest(unittest.TestCase):
    def _run(self, root: Path, *extra: str, affirm_all: bool = True):
        import subprocess

        source = root / "array.csv"
        source.write_text("rsid,chromosome,position,genotype\n", encoding="utf-8")
        out = root / "consent.json"
        command = [
            sys.executable, str(ROOT / "scripts/capture_consent.py"),
            "--case-id", "CASO-CLI", "--subject-id", "SUJEITO-CLI",
            "--input", str(source), "--version", "TCLE v1",
            "--instrument", "termo assinado", "--instrument-version", "1.0",
            "--captured-by", "operador", "--domain", "CLÍNICO",
            "--granted-at", "2026-01-01", "--basis", "arquivo 2026-001",
            "--output", str(out), *extra,
        ]
        if affirm_all:
            command.append("--affirm-all")
        return subprocess.run(command, capture_output=True, text=True), out

    def test_it_writes_a_record_the_validator_accepts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            completed, out = self._run(root)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            record, sha = load_record(out, case_id="CASO-CLI")
        self.assertIs(record["verified"], True)
        self.assertEqual(record["authorized_domains"], ["CLÍNICO"])
        self.assertEqual(len(sha), 64)

    def test_partial_affirmations_refuse_instead_of_writing_a_record(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            completed, out = self._run(
                root, "--affirm", "identity_confirmed", affirm_all=False
            )
        self.assertEqual(completed.returncode, 2)
        self.assertFalse(out.exists())

    def test_there_is_no_flag_that_sets_verified_directly(self):
        source = (ROOT / "scripts/capture_consent.py").read_text(encoding="utf-8")
        self.assertNotIn('"--verified"', source)
        self.assertIn('"verified": all(affirmations.values())', source)


if __name__ == "__main__":
    unittest.main()
