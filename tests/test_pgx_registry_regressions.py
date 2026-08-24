from __future__ import annotations

import json
import urllib.error
import unittest
from unittest.mock import patch

from array_pipeline.allele_discrimination import partition_alleles
from scripts import build_pgx_registry


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
        response = unittest.mock.MagicMock()
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


if __name__ == "__main__":
    unittest.main()
