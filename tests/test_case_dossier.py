"""The administrative record is the operator's, and cannot be invented on their behalf.

Roughly 60% of every template is identification, consent, custody and signature. None of it
is in a genotype file and none of it is fetchable from a public source, so this module
supplies intake rather than content. What it must guarantee is that intake cannot make a
document look better documented than it is.
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

from reporting.case_dossier import (
    CONSENT_REQUIRED_TOGETHER,
    SCHEMA,
    SECTIONS,
    CaseDossierError,
    dossier_values,
    load_dossier,
)

COMPLETE = {
    "schema": "genoma-case-dossier-v1",
    "case_id": "CASE-001",
    "identification": {
        "pseudonymised_id": "PSEUDO-77",
        "date_of_birth": "1980-04-12",
        "requesting_professional": "Dra. Exemplo",
        "requesting_service": "Ambulatório de Genética",
    },
    "sample": {
        "sample_type": "Saliva",
        "sample_identifier": "AM-2026-001",
        "collection_date": "12/03/2026",
        "laboratory": "Laboratório Exemplo",
        "platform": "Microarranjo de SNP",
    },
    "consent": {
        "consent_id": "TCLE-9",
        "consent_version": "2.1",
        "consent_date": "2026-03-01",
        "authorised_purposes": ["genomic_analysis"],
        "authorised_reports": ["05", "06", "09"],
    },
    "release": {"responsible_professional": "Dr. Exemplo", "issue_date": "2026-08-19"},
}


def _write(payload, directory: Path) -> Path:
    path = directory / "dossier.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class DossierValidationTest(unittest.TestCase):
    def _load(self, payload, **kwargs):
        with tempfile.TemporaryDirectory() as td:
            return load_dossier(_write(payload, Path(td)), **kwargs)

    def test_a_complete_dossier_loads_and_normalises_dates(self):
        dossier = self._load(COMPLETE, expected_case_id="CASE-001")
        self.assertEqual(dossier["identification"]["date_of_birth"], "12/04/1980")
        self.assertEqual(dossier["sample"]["collection_date"], "12/03/2026")
        self.assertTrue(dossier["consent_documented"])

    def test_a_dossier_for_another_case_is_refused(self):
        """An identity block attached to another person's data is the worst failure here."""
        with self.assertRaises(CaseDossierError) as ctx:
            self._load(COMPLETE, expected_case_id="CASE-OUTRO")
        self.assertIn("does not match the analysed case", str(ctx.exception))

    def test_a_dossier_without_a_case_id_is_refused(self):
        payload = dict(COMPLETE, case_id="")
        with self.assertRaises(CaseDossierError):
            self._load(payload)

    def test_a_partial_consent_block_is_refused_rather_than_printed(self):
        """Half a consent reads on the page as documented consent."""
        payload = json.loads(json.dumps(COMPLETE))
        del payload["consent"]["consent_date"]
        with self.assertRaises(CaseDossierError) as ctx:
            self._load(payload)
        message = str(ctx.exception)
        self.assertIn("partial consent", message)
        self.assertIn("consent_date", message)

    def test_no_consent_at_all_is_accepted_as_an_honest_absence(self):
        payload = json.loads(json.dumps(COMPLETE))
        payload["consent"] = {}
        dossier = self._load(payload)
        self.assertFalse(dossier["consent_documented"])

    def test_an_unknown_field_is_refused_rather_than_ignored(self):
        """A typo that silently did nothing looks like a field the operator forgot."""
        payload = json.loads(json.dumps(COMPLETE))
        payload["identification"]["nome_completo"] = "X"
        with self.assertRaises(CaseDossierError) as ctx:
            self._load(payload)
        self.assertIn("nome_completo", str(ctx.exception))

    def test_an_unknown_section_is_refused(self):
        payload = json.loads(json.dumps(COMPLETE))
        payload["diagnostico"] = {"x": 1}
        with self.assertRaises(CaseDossierError):
            self._load(payload)

    def test_a_malformed_date_is_caught_at_intake_not_printed(self):
        payload = json.loads(json.dumps(COMPLETE))
        payload["sample"]["collection_date"] = "março de 2026"
        with self.assertRaises(CaseDossierError) as ctx:
            self._load(payload)
        self.assertIn("collection_date", str(ctx.exception))

    def test_absent_fields_are_listed_so_completeness_is_visible(self):
        payload = json.loads(json.dumps(COMPLETE))
        payload["release"] = {}
        dossier = self._load(payload)
        self.assertIn("release.signature_reference", dossier["fields_absent"])
        self.assertLess(dossier["fields_supplied"], dossier["fields_possible"])

    def test_the_shipped_example_is_a_valid_shape_but_supplies_nothing(self):
        """The example must parse, and must not smuggle in placeholder identities."""
        example = json.loads(
            (ROOT / "config/case_dossier.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sorted(set(example) - {"schema", "case_id", "notes"}), sorted(SECTIONS))
        with tempfile.TemporaryDirectory() as td:
            dossier = load_dossier(_write(example, Path(td)))
        self.assertEqual(dossier["fields_supplied"], 0)
        self.assertFalse(dossier["consent_documented"])

    def test_the_consent_group_is_the_one_the_module_documents(self):
        for field in CONSENT_REQUIRED_TOGETHER:
            self.assertIn(field, SECTIONS["consent"])


class DossierToTemplateTest(unittest.TestCase):
    def test_supplied_fields_reach_the_template_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            dossier = load_dossier(_write(COMPLETE, Path(td)))
        values = dossier_values(dossier)
        self.assertEqual(values["NOME_OU_ID_PSEUDONIMIZADO"], "PSEUDO-77")
        self.assertEqual(values["DATA_NASCIMENTO_OU_NAO_INFORMADA"], "12/04/1980")
        self.assertIn("Dra. Exemplo", values["PROFISSIONAL_OU_SERVICO_SOLICITANTE"])
        self.assertIn("TCLE-9", values["ID_VERSAO_DATA_CONSENTIMENTO"])

    def test_absent_fields_produce_no_token_at_all(self):
        """Leaving the token out is what lets template_fill mark it NÃO DISPONÍVEL."""
        payload = json.loads(json.dumps(COMPLETE))
        payload["release"] = {}
        payload["consent"] = {}
        with tempfile.TemporaryDirectory() as td:
            dossier = load_dossier(_write(payload, Path(td)))
        values = dossier_values(dossier)
        for token in ("ASSINATURAS", "ID_VERSAO_DATA_CONSENTIMENTO", "RESPONSAVEL"):
            self.assertNotIn(token, values)

    def test_no_dossier_yields_no_values(self):
        self.assertEqual(dossier_values(None), {})
        self.assertEqual(dossier_values({}), {})

    def test_the_dossier_overrides_the_generic_resolver_fallback(self):
        """Without a dossier the case id stands in for a name; with one, the name wins."""
        import os

        template_dir = os.environ.get("GENOMA_TEMPLATE_DIR")
        if not template_dir:
            self.skipTest("set GENOMA_TEMPLATE_DIR to an installed template pack")
        from reporting.editorial_v3 import _verified_coordinate_manifest
        from reporting.provenance import fixture_payload
        from reporting.template_fill import build_template_fields

        detailed, _ = _verified_coordinate_manifest(Path(template_dir))
        payload = fixture_payload(
            case_id="CASE-001", report_id="09", summary="fixture", basis="fixture"
        )
        with tempfile.TemporaryDirectory() as td:
            dossier = load_dossier(_write(COMPLETE, Path(td)), expected_case_id="CASE-001")

        without = build_template_fields("09", payload, detailed)
        with_dossier = build_template_fields("09", payload, detailed, dossier)

        field = next(
            f["field_id"]
            for f in detailed["reports"]["09"]["fields"]
            if f["token"] == "[[NOME_OU_ID_PSEUDONIMIZADO]]" and not f.get("guidance_only")
        )
        self.assertEqual(without["fields"][field], "CASE-001")
        self.assertEqual(with_dossier["fields"][field], "PSEUDO-77")
        self.assertIn("NOME_OU_ID_PSEUDONIMIZADO", with_dossier["from_dossier"])
        self.assertGreater(with_dossier["derived_count"], without["derived_count"])


class DossierTokenSetTest(unittest.TestCase):
    """The closed set of tokens a dossier can answer is used as a security boundary.

    The PDF stamp check refuses to attribute a field to the administrative record unless
    that field is one a dossier is actually capable of answering. If the constant drifts
    from `dossier_values`, the boundary stops describing reality — either a legitimate field
    is refused or an arbitrary one becomes attributable.
    """

    def _full_dossier(self) -> dict:
        return {
            "identification": {
                "pseudonymised_id": "X", "date_of_birth": "1980-01-01",
                "sex_recorded_at_birth": "feminino", "requesting_professional": "Dr",
                "requesting_service": "Serviço",
            },
            "sample": {
                "sample_type": "Saliva", "sample_identifier": "S1",
                "laboratory": "Lab", "platform": "Array", "collection_date": "2026-01-01",
            },
            "consent": {
                "consent_id": "C1", "consent_version": "1", "consent_date": "2026-01-01",
                "authorised_purposes": ["a"], "authorised_reports": ["01"],
                "granular_preferences": ["p"], "delivery_preference": "email",
                "authorised_recipients": ["r"], "retention_policy": "5 anos",
            },
            "release": {
                "responsible_professional": "Dr", "responsible_registration": "CRM",
                "signature_reference": "sig", "issue_date": "2026-08-20",
            },
        }

    def test_the_constant_matches_what_dossier_values_can_produce(self):
        from reporting.case_dossier import DOSSIER_TOKENS, dossier_values

        produced = set(dossier_values(self._full_dossier()))
        self.assertEqual(
            produced,
            set(DOSSIER_TOKENS),
            "DOSSIER_TOKENS drifted from dossier_values; the stamp check uses it as a boundary",
        )

    def test_an_empty_dossier_produces_nothing(self):
        from reporting.case_dossier import dossier_values

        self.assertEqual(dossier_values(None), {})
        self.assertEqual(dossier_values({}), {})

    def test_every_produced_token_is_in_the_closed_set(self):
        from reporting.case_dossier import DOSSIER_TOKENS, dossier_values

        partial = {"identification": {"pseudonymised_id": "X"}}
        self.assertTrue(set(dossier_values(partial)) <= set(DOSSIER_TOKENS))


if __name__ == "__main__":
    unittest.main()


class ConsentDocumentedTest(unittest.TestCase):
    """"Consentimento documentado" must mean an instrument was identified.

    The all-or-nothing rule covers id/version/date/purposes, but the rest of the consent
    block — which reports, which recipients, how long to retain — is outside it. A dossier
    carrying only those parsed cleanly and still reported `consent_documented`, which is a
    delivery policy printed as a consent record.
    """

    def _write(self, root: Path, consent: dict) -> Path:
        path = root / "dossier.json"
        path.write_text(
            json.dumps({"schema": SCHEMA, "case_id": "CASE-1", "consent": consent}),
            encoding="utf-8",
        )
        return path

    def test_preferences_without_an_instrument_are_not_documented_consent(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(
                Path(td),
                {"authorised_reports": ["05", "06"], "retention_policy": "uso pessoal"},
            )
            dossier = load_dossier(path)
        self.assertFalse(dossier["consent_documented"])
        self.assertTrue(dossier["consent_preferences_only"])

    def test_a_complete_instrument_is_documented_consent(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(
                Path(td),
                {
                    "consent_id": "TCLE-1",
                    "consent_version": "1.0",
                    "consent_date": "2026-08-19",
                    "authorised_purposes": ["análise farmacogenômica"],
                    "authorised_reports": ["05", "06"],
                },
            )
            dossier = load_dossier(path)
        self.assertTrue(dossier["consent_documented"])
        self.assertFalse(dossier["consent_preferences_only"])

    def test_an_empty_consent_block_is_neither(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._write(Path(td), {})
            dossier = load_dossier(path)
        self.assertFalse(dossier["consent_documented"])
        self.assertFalse(dossier["consent_preferences_only"])
