"""The marker table must never drift from what dbSNP actually said.

`config/array_provenance_markers.json` decides which reference build and which strand a
SNP-array file uses, and that verdict unlocks BUILD_STRAND_GATE for everything downstream.
It shipped as PROPOSTO because hand curation was the one place in this design where a
mistake propagates silently into every report.

`scripts/verify_provenance_markers.py` removed the hand curation by fetching each entry
from dbSNP, and recorded the comparison in an evidence file. These tests pin the shipped
table to that evidence **offline**, so CI needs no network while the table still cannot be
edited away from its source.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.provenance_probe import COMPLEMENT, load_markers

MARKERS_PATH = ROOT / "config/array_provenance_markers.json"
EVIDENCE_PATH = ROOT / "docs/evidence/ARRAY_PROVENANCE_MARKERS_DBSNP.json"


class MarkerEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = load_markers(MARKERS_PATH)
        cls.evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        cls.by_rsid = {r["rsid"]: r for r in cls.evidence["results"]}

    def test_the_evidence_records_no_discrepancy(self):
        self.assertEqual(self.evidence["discrepancies"], [])
        self.assertEqual(self.evidence["status"], "VERIFICADO")

    def test_the_table_is_promoted_and_cites_dbsnp(self):
        self.assertEqual(self.table["verification_status"], "VERIFICADO")
        self.assertIn("dbSNP", self.table["source"])
        self.assertIn("ARRAY_PROVENANCE_MARKERS_DBSNP.json", self.table["source"])

    def test_the_evidence_covers_every_shipped_marker(self):
        self.assertEqual(
            sorted(m["rsid"] for m in self.table["markers"]), sorted(self.by_rsid)
        )
        self.assertEqual(self.evidence["markers_checked"], len(self.table["markers"]))

    def test_every_coordinate_matches_dbsnp(self):
        for marker in self.table["markers"]:
            record = self.by_rsid[marker["rsid"]]
            for assembly, key in (("GRCh37", "grch37"), ("GRCh38", "grch38")):
                with self.subTest(rsid=marker["rsid"], assembly=assembly):
                    entry = record["assemblies"][assembly]
                    self.assertEqual(entry["status"], "CONFERE")
                    self.assertEqual(
                        entry["dbsnp"],
                        {
                            "chromosome": str(marker[key]["chromosome"]),
                            "position": int(marker[key]["position"]),
                        },
                    )

    def test_every_allele_pair_matches_the_dbsnp_reference_and_major_alternate(self):
        for marker in self.table["markers"]:
            record = self.by_rsid[marker["rsid"]]["alleles"]
            with self.subTest(rsid=marker["rsid"]):
                self.assertEqual(record["status"], "CONFERE")
                self.assertEqual(marker["reference_allele"], record["dbsnp_reference"])
                self.assertEqual(marker["alternate_allele"], record["dbsnp_major_alternate"])
                self.assertEqual(
                    sorted(marker["plus_alleles"]),
                    sorted({record["dbsnp_reference"], record["dbsnp_major_alternate"]}),
                )

    def test_the_palindromic_flag_is_recomputed_not_trusted(self):
        for marker in self.table["markers"]:
            pair = {str(a).upper() for a in marker["plus_alleles"]}
            with self.subTest(rsid=marker["rsid"]):
                self.assertEqual(
                    bool(marker["palindromic"]),
                    pair in ({"A", "T"}, {"C", "G"}),
                )
                self.assertEqual(
                    bool(marker["palindromic"]),
                    self.by_rsid[marker["rsid"]]["alleles"]["dbsnp_palindromic"],
                )

    def test_the_reference_allele_is_part_of_the_declared_pair(self):
        for marker in self.table["markers"]:
            with self.subTest(rsid=marker["rsid"]):
                self.assertIn(marker["reference_allele"], marker["plus_alleles"])
                self.assertNotEqual(marker["reference_allele"], marker["alternate_allele"])

    def test_the_alternate_allele_has_real_frequency_support(self):
        """A pair invented from a singleton submission would not discriminate anything."""
        for marker in self.table["markers"]:
            with self.subTest(rsid=marker["rsid"]):
                self.assertIsInstance(marker["alternate_frequency"], float)
                self.assertGreater(marker["alternate_frequency"], 0.0)
                self.assertLess(marker["alternate_frequency"], 1.0)

    def test_non_palindromic_pairs_are_disjoint_from_their_complement(self):
        """This disjointness is the entire basis of the strand test."""
        for marker in self.table["markers"]:
            pair = {str(a).upper() for a in marker["plus_alleles"]}
            complement = {COMPLEMENT[a] for a in pair}
            with self.subTest(rsid=marker["rsid"]):
                if marker["palindromic"]:
                    self.assertEqual(pair, complement)
                else:
                    self.assertFalse(pair & complement, f"{marker['rsid']} cannot discriminate strand")

    def test_at_least_three_markers_can_actually_determine_the_strand(self):
        """The probe's threshold is 3; a table of palindromes would silently never conclude."""
        from array_pipeline.provenance_probe import MIN_STRAND_MARKERS

        informative = [m for m in self.table["markers"] if not m["palindromic"]]
        self.assertGreaterEqual(len(informative), MIN_STRAND_MARKERS)

    def test_the_evidence_names_its_source_and_the_spdi_convention(self):
        self.assertIn("dbSNP", self.evidence["source"])
        self.assertIn("plus strand", self.evidence["source_note"])
        self.assertIn("0-based", self.evidence["source_note"])


if __name__ == "__main__":
    unittest.main()
