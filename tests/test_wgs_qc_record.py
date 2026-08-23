"""Sections 6 and 114 are the two obligations a VCF cannot discharge by itself.

§6 — "AUDITORIA OBRIGATÓRIA QUANDO O WGS FOR ENVIADO / Antes de interpretar doenças, realizar
QC completo" — has no "quando possível" clause, and its list asks for depth distribution,
Ti/Tv, exon coverage and contamination, none of which is in a VCF. §114 — "Registrar sempre
se o DNA veio de: sangue; saliva; swab bucal; outro tecido" — asks for a fact no file
carries.

The projected-VCF lane therefore cannot publish on the VCF alone, and the honest fix is not
to relax the sections but to let the operator supply the laboratory's measurements as a
record this module refuses when it does not actually carry them.

These tests hold the three properties that make the record evidence rather than a form: it is
bound to the bytes it certifies, a missing determination cannot be achieved by omission, and
the material §114 requires has no unavailable branch.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from attestations import wgs_qc_record
from reporting.wgs_qc_record import (
    ALLOWED_MATERIAL,
    REQUIRED_METRICS,
    UNAVAILABLE,
    WgsQcError,
    audit_summary,
    load_record,
    validate_record,
)

CASE = "CASO-QC"
DIGEST = "b" * 64


class ACompleteRecordIsAcceptedTest(unittest.TestCase):
    def test_the_fixture_carries_every_determination_section_6_asks_for(self):
        self.assertEqual([], validate_record(wgs_qc_record(case_id=CASE)))

    def test_it_is_accepted_when_bound_to_the_right_case_and_bytes(self):
        record = wgs_qc_record(case_id=CASE, vcf_sha256=DIGEST)
        self.assertEqual([], validate_record(record, case_id=CASE, vcf_sha256=DIGEST))


class TheRecordIsBoundToTheBytesItCertifiesTest(unittest.TestCase):
    """A QC report from another sample is a QC report about that other sample."""

    def test_a_record_for_another_vcf_is_refused(self):
        record = wgs_qc_record(case_id=CASE, vcf_sha256="a" * 64)
        problems = validate_record(record, vcf_sha256=DIGEST)
        self.assertTrue(any("amostras distintas" in p for p in problems), problems)

    def test_a_record_for_another_case_is_refused(self):
        problems = validate_record(wgs_qc_record(case_id="OUTRO"), case_id=CASE)
        self.assertTrue(any("case_id" in p for p in problems), problems)

    def test_the_digest_must_look_like_a_digest(self):
        problems = validate_record(wgs_qc_record(case_id=CASE, vcf_sha256="curto"))
        self.assertTrue(any("SHA-256" in p for p in problems), problems)

    def test_case_is_ignored_when_the_caller_does_not_supply_one(self):
        """The binding is checked against what the caller knows, not invented."""
        self.assertEqual([], validate_record(wgs_qc_record(case_id="QUALQUER")))


class AGapMustBeWrittenDownTest(unittest.TestCase):
    def test_every_required_metric_is_required(self):
        for key in REQUIRED_METRICS:
            record = wgs_qc_record(case_id=CASE)
            del record["metrics"][key]
            with self.subTest(metric=key):
                problems = validate_record(record)
                self.assertTrue(any(key in p and "ausente" in p for p in problems), problems)

    def test_the_explicit_unavailable_form_is_accepted(self):
        record = wgs_qc_record(case_id=CASE)
        record["metrics"]["contamination_estimate"] = {
            "status": UNAVAILABLE, "reason": "não estimada pelo laboratório",
        }
        self.assertEqual([], validate_record(record))

    def test_unavailable_without_a_reason_is_refused(self):
        record = wgs_qc_record(case_id=CASE)
        record["metrics"]["ti_tv"] = {"status": UNAVAILABLE}
        problems = validate_record(record)
        self.assertTrue(any("sem motivo" in p for p in problems), problems)

    def test_an_object_that_is_not_the_unavailable_form_is_refused(self):
        record = wgs_qc_record(case_id=CASE)
        record["metrics"]["mean_depth"] = {"value": 30}
        problems = validate_record(record)
        self.assertTrue(any("mean_depth" in p for p in problems), problems)

    def test_a_percentage_outside_its_range_is_refused(self):
        for value in (-1, 101):
            record = wgs_qc_record(case_id=CASE)
            record["metrics"]["pct_bases_20x"] = value
            with self.subTest(value=value):
                self.assertTrue(validate_record(record))

    def test_a_boolean_is_not_a_measurement(self):
        """`True == 1` in Python, and 1× mean depth is not what a caller meant."""
        record = wgs_qc_record(case_id=CASE)
        record["metrics"]["mean_depth"] = True
        problems = validate_record(record)
        self.assertTrue(any("não é um número" in p for p in problems), problems)

    def test_the_reliability_map_section_6_asks_for_is_required(self):
        record = wgs_qc_record(case_id=CASE)
        del record["reliability_map"]
        problems = validate_record(record)
        self.assertTrue(any("MAPA DE CONFIABILIDADE" in p for p in problems), problems)

    def test_each_reliability_band_is_required(self):
        record = wgs_qc_record(case_id=CASE)
        del record["reliability_map"]["baixa_cobertura"]
        problems = validate_record(record)
        self.assertTrue(any("baixa_cobertura" in p for p in problems), problems)


class TheBiologicalMaterialHasNoUnavailableBranchTest(unittest.TestCase):
    """§114 says "registrar sempre", and mosaicism, CHIP, heteroplasmy and contamination are
    read differently depending on the answer."""

    def test_every_allowed_material_is_accepted(self):
        for material in ALLOWED_MATERIAL:
            with self.subTest(material=material):
                record = wgs_qc_record(case_id=CASE, biological_material=material)
                self.assertEqual([], validate_record(record))

    def test_an_unlisted_material_is_refused(self):
        record = wgs_qc_record(case_id=CASE, biological_material="PLASMA")
        problems = validate_record(record)
        self.assertTrue(any("vocabulário" in p for p in problems), problems)

    def test_declaring_it_unavailable_is_refused(self):
        record = wgs_qc_record(
            case_id=CASE,
            biological_material={"status": UNAVAILABLE, "reason": "não informado"},
        )
        problems = validate_record(record)
        self.assertTrue(any("seção 114" in p for p in problems), problems)

    def test_the_read_layout_vocabulary_is_closed(self):
        record = wgs_qc_record(case_id=CASE, read_layout="MATE-PAIR")
        self.assertTrue(validate_record(record))


class TheIdentityFieldsAreRequiredTest(unittest.TestCase):
    def test_a_record_naming_no_laboratory_is_refused(self):
        for key in ("laboratory", "report_date", "captured_by", "source", "case_id"):
            record = wgs_qc_record(case_id=CASE)
            record[key] = ""
            with self.subTest(field=key):
                problems = validate_record(record)
                self.assertTrue(any(key in p for p in problems), problems)

    def test_the_schema_must_be_declared(self):
        record = wgs_qc_record(case_id=CASE)
        record["schema"] = "outra-coisa"
        self.assertTrue(validate_record(record))

    def test_a_non_object_is_refused_without_raising(self):
        for value in (None, "registro", 42, []):
            with self.subTest(value=value):
                self.assertTrue(validate_record(value))


class LoadRaisesWithEveryProblemAtOnceTest(unittest.TestCase):
    def test_a_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qc.json"
            path.write_text(json.dumps(wgs_qc_record(case_id=CASE)), encoding="utf-8")
            self.assertEqual(CASE, load_record(path, case_id=CASE)["case_id"])

    def test_an_invalid_file_names_the_problems(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qc.json"
            record = wgs_qc_record(case_id=CASE)
            del record["metrics"]["ti_tv"]
            del record["metrics"]["mean_depth"]
            path.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaises(WgsQcError) as caught:
                load_record(path)
        self.assertIn("ti_tv", str(caught.exception))
        self.assertIn("mean_depth", str(caught.exception))

    def test_an_unreadable_file_raises_rather_than_defaulting(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "qc.json"
            path.write_text("{ not json", encoding="utf-8")
            with self.assertRaises(WgsQcError):
                load_record(path)


class TheSummarySaysHowMuchWasMeasuredTest(unittest.TestCase):
    """A record where most of §6 is unavailable must not read like a complete audit."""

    def test_a_full_record_counts_every_determination_as_measured(self):
        summary = audit_summary(wgs_qc_record(case_id=CASE))
        self.assertEqual(len(REQUIRED_METRICS), summary["measured_count"])
        self.assertEqual([], summary["not_measured"])

    def test_an_unavailable_metric_is_counted_as_not_measured(self):
        record = wgs_qc_record(case_id=CASE)
        record["metrics"]["cnv_count"] = {"status": UNAVAILABLE, "reason": "sem caller de CNV"}
        summary = audit_summary(record)
        self.assertIn("cnv_count", summary["not_measured"])
        self.assertEqual(len(REQUIRED_METRICS) - 1, summary["measured_count"])

    def test_the_basis_says_the_metrics_are_the_laboratory_s(self):
        basis = audit_summary(wgs_qc_record(case_id=CASE))["basis"]
        self.assertIn("não as recalcula", basis)
        self.assertIn("não recebeu leituras", basis)


if __name__ == "__main__":
    unittest.main()
