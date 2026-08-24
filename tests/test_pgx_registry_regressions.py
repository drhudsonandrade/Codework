from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from array_pipeline.allele_discrimination import partition_alleles
from scripts import build_pgx_panel, build_pgx_registry, expand_clinvar_targets, verify_provenance_markers


class CpicRetryPolicyTest(unittest.TestCase):
    def test_non_transient_http_error_is_not_retried(self):
        error = urllib.error.HTTPError(
            "https://api.cpicpgx.org/v1/gene", 404, "Not Found", None, None
        )
        with patch.object(build_pgx_registry.urllib.request, "urlopen", side_effect=error) as opened:
            with patch.object(build_pgx_registry.time, "sleep") as slept:
                with self.assertRaises(build_pgx_registry.CpicError):
                    build_pgx_registry._get("gene", attempts=4)
        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()

    def test_transient_http_error_is_retried(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([]).encode()
        error = urllib.error.HTTPError(
            "https://api.cpicpgx.org/v1/gene", 503, "Unavailable", None, None
        )
        with patch.object(
            build_pgx_registry.urllib.request, "urlopen", side_effect=[error, response]
        ) as opened:
            with patch.object(build_pgx_registry.time, "sleep") as slept:
                self.assertEqual(build_pgx_registry._get("gene", attempts=2), [])
        self.assertEqual(opened.call_count, 2)
        slept.assert_called_once_with(1)


class SharedHttpRetryPolicyTest(unittest.TestCase):
    @staticmethod
    def _marker_error(code: int):
        http = urllib.error.HTTPError("https://dbsnp", code, "error", None, None)
        try:
            raise verify_provenance_markers.MarkerVerificationError("fetch failed") from http
        except verify_provenance_markers.MarkerVerificationError as exc:
            return exc

    def test_dbsnp_permanent_http_error_is_not_retried(self):
        error = self._marker_error(404)
        with patch.object(
            verify_provenance_markers,
            "fetch_refsnp",
            side_effect=error,
        ) as fetched:
            with patch.object(verify_provenance_markers.time, "sleep") as slept:
                with self.assertRaises(
                    verify_provenance_markers.MarkerVerificationError
                ):
                    verify_provenance_markers._fetch_with_retries("rs1", attempts=4)
        self.assertEqual(fetched.call_count, 1)
        slept.assert_not_called()

    def test_invalid_dbsnp_identifier_fails_before_fetch(self):
        with patch.object(verify_provenance_markers, "fetch_refsnp") as fetched:
            with self.assertRaises(
                verify_provenance_markers.MarkerVerificationError
            ):
                verify_provenance_markers._fetch_with_retries("not-an-rsid")
        fetched.assert_not_called()

    def test_bulk_download_permanent_http_error_is_not_retried(self):
        error = urllib.error.HTTPError("https://clinvar", 403, "Forbidden", None, None)
        with patch.object(
            expand_clinvar_targets.urllib.request,
            "urlopen",
            side_effect=error,
        ) as opened:
            with patch.object(expand_clinvar_targets.time, "sleep") as slept:
                with self.assertRaises(RuntimeError):
                    expand_clinvar_targets._fetch("https://clinvar", attempts=4)
        self.assertEqual(opened.call_count, 1)
        slept.assert_not_called()


class PartialDefinitionTest(unittest.TestCase):
    def test_builder_marks_partial_definition_and_panel_incomplete(self):
        rows = {
            "allele": [{"name": "*2", "definitionid": 1}],
            "allele_definition": [
                {"id": 1, "matchesreferencesequence": False, "structuralvariation": False}
            ],
            "sequence_location": [
                {"id": 10, "dbsnpid": "rs1", "position": 1},
                {"id": 11, "dbsnpid": "", "position": 2},
            ],
            "gene": [{"chr": "chr1", "chromosequenceid": "NC_000001.11"}],
            "allele_location_value": [
                {"alleledefinitionid": 1, "locationid": 10, "variantallele": "A"},
                {"alleledefinitionid": 1, "locationid": 11, "variantallele": "T"},
            ],
            "diplotype": [],
        }

        def fake_get(path, **_params):
            return rows[path]

        with patch.object(build_pgx_registry, "_get", side_effect=fake_get):
            with patch.object(build_pgx_registry.time, "sleep"):
                record = build_pgx_registry.fetch_gene("TEST")

        definition = record["alleles"]["TEST*2"]
        self.assertFalse(record["complete_panel"])
        self.assertFalse(definition["definition_complete"])
        self.assertIn("TEST*2 (parcial)", record["alleles_without_usable_snp_definition"])

    def test_consumer_refuses_a_partial_definition_even_when_observed(self):
        spec = {
            "alleles": {
                "TEST*2": {
                    "definition_complete": False,
                    "defining": [{"rsid": "rs1", "allele": "A"}],
                }
            }
        }
        result = partition_alleles(spec, {"rs1": "OBSERVADO"})
        self.assertEqual(result["discriminable"], [])
        self.assertEqual(result["indiscriminable"], ["TEST*2"])
        self.assertIn("definição parcial", result["alleles"]["TEST*2"]["basis"])


class PgxPanelIdentityTest(unittest.TestCase):
    @staticmethod
    def _registry(position=10):
        return {
            "id": "fixture",
            "version": "1",
            "source": "fixture",
            "genes": {
                "G": {
                    "alleles": {
                        "G*2": {
                            "defining": [{
                                "rsid": "rs1", "allele": "A", "position": 10,
                                "chromosome": "chr1", "reference_accession": "NC_000001.11",
                                "cpic_location": "loc", "chromosome_location": "1:10",
                            }]
                        },
                        "G*3": {
                            "defining": [{
                                "rsid": "rs1", "allele": "T", "position": position,
                                "chromosome": "chr1", "reference_accession": "NC_000001.11",
                                "cpic_location": "loc", "chromosome_location": "1:10",
                            }]
                        },
                    }
                }
            },
        }

    def test_conflicting_coordinates_for_one_rsid_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "rs1.*position"):
            build_pgx_panel.build_panel(self._registry(position=11))

    def test_version_changes_when_registry_content_changes(self):
        first = build_pgx_panel.build_panel(self._registry())
        second_registry = self._registry()
        second_registry["version"] = "2"
        second = build_pgx_panel.build_panel(second_registry)
        self.assertNotEqual(first["version"], second["version"])


if __name__ == "__main__":
    unittest.main()
