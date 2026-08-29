from __future__ import annotations

import json
import unittest
from pathlib import Path

from array_pipeline.provenance_probe import load_markers

ROOT = Path(__file__).resolve().parents[1]


class ProvenanceMarkerEvidenceTest(unittest.TestCase):
    def test_shipped_marker_table_matches_pinned_dbsnp_evidence(self):
        table = load_markers(ROOT / "config/array_provenance_markers.json")
        evidence = json.loads(
            (ROOT / "docs/evidence/ARRAY_PROVENANCE_MARKERS_DBSNP.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(evidence["status"], "VERIFICADO")
        self.assertEqual(evidence["discrepancies"], [])
        self.assertTrue(table["markers"], "tabela de marcadores vazia")
        self.assertEqual(evidence["markers_checked"], len(table["markers"]))
        self.assertEqual(
            evidence["marker_table"],
            {"id": table["id"], "version": table["version"]},
        )
        observed = {record["rsid"]: record for record in evidence["results"]}
        self.assertEqual(set(observed), {marker["rsid"] for marker in table["markers"]})
        # Indexing by rsid silently drops duplicates: two records for one marker, even with
        # conflicting placements, would collapse to whichever came last and every assertion
        # below would still pass. Counts have to agree on all three sides.
        self.assertEqual(len(evidence["results"]), len(table["markers"]))
        self.assertEqual(len(observed), len(table["markers"]))

        for marker in table["markers"]:
            with self.subTest(rsid=marker["rsid"]):
                record = observed[marker["rsid"]]
                for assembly, key in (("GRCh37", "grch37"), ("GRCh38", "grch38")):
                    placement = record["assemblies"][assembly]
                    self.assertEqual(placement["status"], "CONFERE")
                    self.assertEqual(placement["declared"], marker[key])
                    self.assertEqual(placement["dbsnp"], marker[key])
                alleles = record["alleles"]
                self.assertEqual(alleles["status"], "CONFERE")
                self.assertEqual(alleles["declared"], sorted(marker["plus_alleles"]))
                self.assertEqual(alleles["dbsnp_reference"], marker["reference_allele"])
                self.assertEqual(
                    alleles["dbsnp_major_alternate"], marker["alternate_allele"]
                )
                self.assertEqual(
                    alleles["declared_palindromic"], marker["palindromic"]
                )
                self.assertEqual(
                    alleles["dbsnp_palindromic"], marker["palindromic"]
                )


if __name__ == "__main__":
    unittest.main()
