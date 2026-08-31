from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import MagicMock, patch

from array_pipeline.allele_discrimination import partition_alleles
from scripts import build_pgx_panel, build_pgx_registry, expand_clinvar_targets, verify_provenance_markers


class CpicRetryPolicyTest(unittest.TestCase):
    """Which CPIC fetch failures are retried and which are not."""
    def test_non_transient_http_error_is_not_retried(self):
        """A 404 is a fact about the request and is not retried."""
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
        """A 503 is transient and is retried."""
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
    """The same retry policy, applied by the dbSNP and ClinVar fetchers."""
    @staticmethod
    def _marker_error(code: int):
        """A MarkerVerificationError caused by an HTTPError with this status."""
        http = urllib.error.HTTPError("https://dbsnp", code, "error", None, None)
        try:
            raise verify_provenance_markers.MarkerVerificationError("fetch failed") from http
        except verify_provenance_markers.MarkerVerificationError as exc:
            return exc

    def test_dbsnp_permanent_http_error_is_not_retried(self):
        """A permanent dbSNP error is raised on the first attempt, with no sleep."""
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

    def test_transient_dbsnp_error_is_retried_and_then_succeeds(self):
        """The retry branch itself had no coverage.

        The suite pinned only the permanent-error path and the invalid rsid, so a regression
        that propagated every MarkerVerificationError immediately — losing the retry that
        exists for 429/5xx/URLError — would have left both existing tests green.
        """
        payload = {"refsnp_id": "1"}
        for transient in (429, 503):
            with self.subTest(transient=transient):
                with patch.object(
                    verify_provenance_markers,
                    "fetch_refsnp",
                    side_effect=[self._marker_error(transient), payload],
                ) as fetched, patch.object(
                    verify_provenance_markers.time, "sleep"
                ) as slept:
                    result = verify_provenance_markers._fetch_with_retries(
                        "rs1", attempts=4
                    )
                self.assertEqual(result, payload)
                self.assertEqual(fetched.call_count, 2)
                self.assertEqual(slept.call_count, 1)

    def test_invalid_dbsnp_identifier_fails_before_fetch(self):
        """An identifier that is not an rsid fails before any fetch is attempted."""
        with patch.object(verify_provenance_markers, "fetch_refsnp") as fetched:
            with self.assertRaises(
                verify_provenance_markers.MarkerVerificationError
            ):
                verify_provenance_markers._fetch_with_retries("not-an-rsid")
        fetched.assert_not_called()

    def test_bulk_download_permanent_http_error_is_not_retried(self):
        """A permanent error on the ClinVar bulk download is not retried."""
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
    """An allele CPIC defines only partially, and what the consumer may do with it."""
    def test_builder_marks_partial_definition_and_panel_incomplete(self):
        """The builder marks a partial definition and the panel it belongs to as incomplete."""
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
            """Serve the fixture rows for this CPIC endpoint."""
            return rows[path]

        with patch.object(build_pgx_registry, "_get", side_effect=fake_get):
            with patch.object(build_pgx_registry.time, "sleep"):
                record = build_pgx_registry.fetch_gene("TEST")

        definition = record["alleles"]["TEST*2"]
        self.assertFalse(record["complete_panel"])
        self.assertFalse(definition["definition_complete"])
        self.assertIn("TEST*2 (parcial)", record["alleles_without_usable_snp_definition"])

    def test_consumer_refuses_a_partial_definition_even_when_observed(self):
        """The consumer refuses a partial definition even when its positions were observed."""
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
    """The panel's identity, derived from the registry rather than declared."""
    @staticmethod
    def _registry(position=10):
        """A registry whose two alleles place rs1 at these positions."""
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
        """Two coordinates for one rsid are rejected instead of one being picked."""
        with self.assertRaisesRegex(ValueError, "rs1.*position"):
            build_pgx_panel.build_panel(self._registry(position=11))

    def test_version_changes_when_registry_content_changes(self):
        """The panel version changes when the registry content changes."""
        first = build_pgx_panel.build_panel(self._registry())
        second_registry = self._registry()
        second_registry["version"] = "2"
        second = build_pgx_panel.build_panel(second_registry)
        self.assertNotEqual(first["version"], second["version"])


if __name__ == "__main__":
    unittest.main()
