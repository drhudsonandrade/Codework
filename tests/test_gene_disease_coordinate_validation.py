from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import curate_gene_disease as CURATE


def _summary(sequence: str, position: int, deleted: str) -> dict:
    return {
        "result": {
            "uids": ["1"],
            "1": {
                "uid": "1",
                "accession": "VCV000000001",
                "title": "fixture",
                "variation_set": [
                    {"canonical_spdi": f"{sequence}:{position}:{deleted}:T"}
                ],
                "germline_classification": {
                    "description": "Pathogenic",
                    "review_status": "criteria provided",
                    "last_evaluated": "2026-08-24",
                    "trait_set": [{"trait_name": "Fixture disease", "trait_xrefs": []}],
                },
                "genes": [{"symbol": "GENE"}],
            },
        }
    }


class ClinvarCoordinateIdentityTests(unittest.TestCase):
    def _run(self, summary: dict) -> dict:
        search = {"esearchresult": {"idlist": ["1"]}}
        placement = {
            "GRCh38": {
                "seq_id": "NC_000001.11",
                "position": 101,
                "reference_allele": "A",
            }
        }
        with (
            patch.object(CURATE, "fetch_refsnp", return_value={"refsnp_id": "123"}),
            patch.object(CURATE, "placements", return_value=placement),
            patch.object(CURATE, "_json", side_effect=[search, summary]),
            patch.object(CURATE.time, "sleep"),
        ):
            return CURATE.fetch_clinvar_conditions("rs123")

    def test_matching_grch38_spdi_is_verified(self):
        result = self._run(_summary("NC_000001.11", 100, "A"))
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["coordinate_check"]["status"], "VERIFICADO")

    def test_wrong_coordinate_is_not_declared_verified(self):
        result = self._run(_summary("NC_000001.11", 999, "A"))
        self.assertEqual(result["status"], CURATE.UNAVAILABLE)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["records_rejected_by_coordinate"], 1)

    def test_wrong_sequence_or_reference_is_not_declared_verified(self):
        for summary in (
            _summary("NC_000002.12", 100, "A"),
            _summary("NC_000001.11", 100, "C"),
        ):
            with self.subTest(summary=summary):
                result = self._run(summary)
                self.assertEqual(result["status"], CURATE.UNAVAILABLE)
                self.assertEqual(result["records"], [])


if __name__ == "__main__":
    unittest.main()
