from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from array_pipeline.provenance_probe import (
    ProvenanceProbeError,
    _read_markers_from_array,
    load_markers,
)


class ProvenanceProbeRegressionTest(unittest.TestCase):
    def _write_markers(self, root: Path, marker: object) -> Path:
        path = root / "markers.json"
        path.write_text(json.dumps({
            "schema": "genoma-array-provenance-markers-v1",
            "source": "fixture",
            "markers": [marker],
        }), encoding="utf-8")
        return path

    def test_marker_entries_must_be_objects(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for marker in (None, 7, "rs1"):
                with self.subTest(marker=marker):
                    with self.assertRaisesRegex(ProvenanceProbeError, "marker.*object"):
                        load_markers(self._write_markers(root, marker))

    def test_rsid_must_be_a_non_empty_string(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for marker in ({}, {"rsid": None}, {"rsid": ""}, {"rsid": "   "}, {"rsid": 7}):
                with self.subTest(marker=marker):
                    with self.assertRaisesRegex(ProvenanceProbeError, "rsid.*non-empty string"):
                        load_markers(self._write_markers(root, marker))

    def test_invalid_plus_allele_is_domain_error_not_keyerror(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "markers.json"
            path.write_text(json.dumps({
                "schema": "genoma-array-provenance-markers-v1",
                "source": "fixture",
                "markers": [{
                    "rsid": "rs1",
                    "grch37": {"chromosome": "1", "position": 1},
                    "grch38": {"chromosome": "1", "position": 2},
                    "plus_alleles": ["A", None],
                }],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ProvenanceProbeError, "rs1.*A, C, G or T"):
                load_markers(path)

    def test_duplicate_and_unresolved_markers_are_discarded(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "array.csv"
            path.write_text(
                "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
                "rs1,1,10,AA,consensus,AA,AA,GM\n"
                "rs1,1,10,AA,consensus,AA,AA,GM\n"
                "rs2,1,20,AA,genotype_conflict,AA,AG,GM\n"
                "rs3,1,30,AA,consensus,AA,AA,GM\n",
                encoding="utf-8",
            )
            found = _read_markers_from_array(path, {"rs1", "rs2", "rs3"})
            self.assertEqual(set(found), {"rs3"})


if __name__ == "__main__":
    unittest.main()
