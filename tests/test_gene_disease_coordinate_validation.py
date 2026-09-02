from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts import curate_gene_disease as CURATE


def _summary(sequence: str, position: int, deleted: str) -> dict:
    """A ClinVar summary placing the variant at this SPDI."""
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
    """A ClinVar record is accepted only when its own coordinate matches the target's."""
    def _run(self, summary: dict) -> dict:
        """Run the curation against this ClinVar summary."""
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

    def test_dbsnp_failure_is_local_to_one_locus(self):
        """A dbSNP failure is local to one locus and does not abort the curation."""
        from scripts.verify_provenance_markers import MarkerVerificationError

        search = {"esearchresult": {"count": "1", "idlist": ["1"]}}
        summary = _summary("NC_000001.11", 100, "A")
        placement = {
            "GRCh38": {
                "seq_id": "NC_000001.11",
                "position": 101,
                "reference_allele": "A",
            }
        }
        with (
            patch.object(
                CURATE,
                "fetch_refsnp",
                side_effect=[
                    MarkerVerificationError("temporary dbSNP failure"),
                    {"refsnp_id": "2"},
                ],
            ),
            patch.object(CURATE, "placements", return_value=placement),
            patch.object(CURATE, "_json", side_effect=[search, summary]),
            patch.object(CURATE.time, "sleep"),
        ):
            first = CURATE._clinvar_for_locus("rs1")
            second = CURATE._clinvar_for_locus("rs2")
        self.assertEqual(first["status"], CURATE.UNAVAILABLE)
        self.assertIn("temporary dbSNP failure", first["reason"])
        self.assertEqual(second["status"], "VERIFICADO")
        self.assertEqual(second["records"][0]["accession"], "VCV000000001")

    def test_cross_host_gwas_study_link_is_not_requested(self):
        payload = {
            "_embedded": {
                "associations": [
                    {
                        "pvalue": 1e-9,
                        "efoTraits": [{"trait": "fixture", "shortForm": "EFO_1"}],
                        "_links": {
                            "study": {"href": "https://example.invalid/studies/1"}
                        },
                        "loci": [],
                    }
                ]
            }
        }
        with (
            patch.object(CURATE, "_json", return_value=payload) as fetched,
            patch.object(CURATE.time, "sleep"),
        ):
            result = CURATE.fetch_gwas_associations("rs1")
        self.assertEqual(fetched.call_count, 1)
        ancestry = result["traits"][0]["ancestry"]
        self.assertEqual(ancestry["status"], CURATE.UNAVAILABLE)
        self.assertIn("autoridade autorizada", ancestry["reason"])

    def test_clinvar_pagination_collects_every_uid(self):
        """ClinVar pagination collects every uid, not only the first page."""
        placement = {
            "GRCh38": {
                "seq_id": "NC_000001.11",
                "position": 101,
                "reference_allele": "A",
            }
        }
        ids = [str(index) for index in range(1, 22)]
        pages = [
            {"esearchresult": {"count": "21", "idlist": ids[:20]}},
            {"esearchresult": {"count": "21", "idlist": ids[20:]}},
        ]
        summary = {"result": {"uids": ids}}
        for uid in ids:
            summary["result"][uid] = _summary(
                "NC_000001.11", 100, "A"
            )["result"]["1"]
        with (
            patch.object(CURATE, "fetch_refsnp", return_value={}),
            patch.object(CURATE, "placements", return_value=placement),
            patch.object(CURATE, "_json", side_effect=[*pages, summary]) as fetched,
            patch.object(CURATE.time, "sleep"),
        ):
            result = CURATE.fetch_clinvar_conditions("rs123")
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertEqual(len(result["records"]), 21)
        self.assertEqual(fetched.call_count, 3)
        # The mock hands back the next page whatever URL it is asked for, so a regression
        # that sent retstart=0 on every iteration would consume all three responses and pass
        # on the count alone. The offsets are what prove the loop actually paginates.
        urls = [call.args[0] for call in fetched.call_args_list]
        self.assertIn("retstart=0", urls[0])
        self.assertIn("retstart=20", urls[1])

    def test_a_page_short_of_the_reported_count_is_refused_not_called_absence(self):
        """An incomplete collection is not the same fact as "ClinVar has no record".

        Under load NCBI answers esearch with `count > 0` and an empty `idlist`. The loop
        breaks on the empty page, and with the completeness check placed after the
        emptiness check the function returned `NÃO DISPONÍVEL: ClinVar não retorna registro`
        — a sentence asserting absence — so the locus entered the curated record as a
        verified gap. It has to refuse instead: order matters here, and only running it
        proves the order is right.
        """
        placement = {
            "GRCh38": {
                "seq_id": "NC_000001.11",
                "position": 101,
                "reference_allele": "A",
            }
        }
        for label, pages in (
            ("first page empty", [{"esearchresult": {"count": "1", "idlist": []}}]),
            (
                "second page empty",
                [
                    {"esearchresult": {"count": "40", "idlist": [str(i) for i in range(1, 21)]}},
                    {"esearchresult": {"count": "40", "idlist": []}},
                ],
            ),
        ):
            with self.subTest(case=label):
                with (
                    patch.object(CURATE, "fetch_refsnp", return_value={}),
                    patch.object(CURATE, "placements", return_value=placement),
                    patch.object(CURATE, "_json", side_effect=list(pages)),
                    patch.object(CURATE.time, "sleep"),
                ):
                    with self.assertRaises(CURATE.CurationError) as caught:
                        CURATE.fetch_clinvar_conditions("rs123")
                message = str(caught.exception)
                self.assertIn("refusing partial curation", message)
                self.assertNotIn("não retorna registro", message)

    def test_clinvar_fetch_failure_is_local_to_one_locus(self):
        """A ClinVar fetch failure is local to one locus."""
        with patch.object(
            CURATE,
            "fetch_clinvar_conditions",
            side_effect=[
                CURATE.CurationError("temporary ClinVar failure"),
                {"status": "VERIFICADO", "records": [{"accession": "VCV2"}]},
            ],
        ):
            first = CURATE._clinvar_for_locus("rs1")
            second = CURATE._clinvar_for_locus("rs2")
        self.assertEqual(first["status"], CURATE.UNAVAILABLE)
        self.assertIn("temporary ClinVar failure", first["reason"])
        self.assertEqual(second["status"], "VERIFICADO")

    def test_matching_grch38_spdi_is_verified(self):
        """A matching GRCh38 SPDI is VERIFICADO."""
        result = self._run(_summary("NC_000001.11", 100, "A"))
        self.assertEqual(result["status"], "VERIFICADO")
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["coordinate_check"]["status"], "VERIFICADO")

    def test_wrong_coordinate_is_not_declared_verified(self):
        """A record at the wrong coordinate is not declared verified: it is rejected and counted."""
        result = self._run(_summary("NC_000001.11", 999, "A"))
        self.assertEqual(result["status"], CURATE.UNAVAILABLE)
        self.assertEqual(result["records"], [])
        self.assertEqual(result["records_rejected_by_coordinate"], 1)

    def test_wrong_sequence_or_reference_is_not_declared_verified(self):
        """A wrong sequence or a wrong reference base is not declared verified either."""
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
