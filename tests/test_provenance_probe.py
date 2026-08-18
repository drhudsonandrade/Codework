"""The probe unlocks BUILD_STRAND_GATE, so it must be unable to unlock it on bad evidence.

A real harmonized export carries no `##reference=` or `##strand=` header, which left two
options: leave the data unusable, or hand-write an attestation asserting a build and strand
nobody had checked. This module derives both from the file's own content — which means it is
now the component most worth attacking. Every test here is a negative control.
"""
from __future__ import annotations

import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.provenance_probe import (
    COMPLEMENT,
    ProvenanceProbeError,
    attestation_from_probe,
    load_markers,
    probe,
)

HEADER = "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
MARKERS_PATH = ROOT / "config/array_provenance_markers.json"

#: (rsid, chr, grch37 pos, grch38 pos, plus-strand genotype)
PANEL = [
    ("rs429358", "19", 45411941, 44908684, "TT"),
    ("rs7412", "19", 45412079, 44908822, "CC"),
    ("rs6025", "1", 169519049, 169549811, "CC"),
    ("rs1799963", "11", 46761055, 46739505, "GG"),
    ("rs9923231", "16", 31107689, 31096368, "CT"),
    ("rs4149056", "12", 21331549, 21178615, "CT"),
]


def _flip(genotype: str) -> str:
    return "".join(COMPLEMENT[base] for base in genotype)


def _write(root: Path, rows: list[tuple[str, str, int, str]]) -> Path:
    path = root / "array.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        for rsid, chrom, pos, gt in rows:
            fh.write(f"{rsid},{chrom},{pos},{gt},consensus,{gt},{gt},GM\n")
    return path


def _rows(build: str = "grch37", *, flip: bool = False, limit: int | None = None):
    out = []
    for rsid, chrom, p37, p38, gt in PANEL[:limit]:
        out.append((rsid, chrom, p37 if build == "grch37" else p38, _flip(gt) if flip else gt))
    return out


class BuildDeterminationTest(unittest.TestCase):
    def test_grch37_coordinates_are_recognised(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37")), MARKERS_PATH)
        self.assertEqual(result["build"]["status"], "VERIFICADO")
        self.assertEqual(result["build"]["value"], "GRCh37")
        self.assertEqual(result["build"]["grch38_matches"], 0)

    def test_grch38_coordinates_are_not_reported_as_grch37(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch38")), MARKERS_PATH)
        self.assertEqual(result["build"]["value"], "GRCh38")
        self.assertEqual(result["build"]["grch37_matches"], 0)

    def test_mixed_coordinates_are_inconclusive_not_majority_wins(self):
        """A file half-lifted between assemblies must not be declared either one."""
        rows = _rows("grch37", limit=3) + _rows("grch38")[3:]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        self.assertEqual(result["build"]["status"], "NÃO DISPONÍVEL")
        self.assertIsNone(result["build"]["value"])

    def test_too_few_matching_markers_is_inconclusive(self):
        """One coincidence is not a determination."""
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37", limit=2)), MARKERS_PATH)
        self.assertEqual(result["build"]["status"], "NÃO DISPONÍVEL")
        self.assertLess(result["build"]["grch37_matches"], result["build"]["threshold"])

    def test_unknown_coordinates_match_nothing(self):
        rows = [(rsid, chrom, 999_000_000, gt) for rsid, chrom, _p, gt in _rows("grch37")]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        self.assertEqual(result["build"]["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["build"]["grch37_matches"], 0)
        self.assertEqual(result["build"]["grch38_matches"], 0)


class StrandDeterminationTest(unittest.TestCase):
    def test_forward_strand_genotypes_are_recognised(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37")), MARKERS_PATH)
        self.assertEqual(result["strand"]["status"], "VERIFICADO")
        self.assertEqual(result["strand"]["value"], "forward")
        self.assertEqual(result["strand"]["minus_matches"], 0)

    def test_a_reverse_strand_file_is_never_called_forward(self):
        """The consequential failure: calling a flipped file forward inverts every allele."""
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37", flip=True)), MARKERS_PATH)
        self.assertEqual(result["strand"]["value"], "reverse")
        self.assertNotEqual(result["strand"]["value"], "forward")
        self.assertEqual(result["strand"]["plus_matches"], 0)

    def test_a_mixed_strand_file_is_inconclusive(self):
        rows = _rows("grch37", limit=3) + _rows("grch37", flip=True)[3:]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        self.assertEqual(result["strand"]["status"], "NÃO DISPONÍVEL")
        self.assertIsNone(result["strand"]["value"])

    def test_palindromic_markers_never_vote(self):
        """A/T and C/G read identically on both strands and carry no orientation signal."""
        rows = _rows("grch37") + [
            ("rs738409", "22", 44324727, "CG"),
            ("rs17580", "14", 94847262, "AT"),
        ]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        verdicts = {e["rsid"]: e["verdict"] for e in result["strand"]["evidence"]}
        self.assertIn("palindrômico", verdicts["rs738409"])
        self.assertIn("palindrômico", verdicts["rs17580"])
        # Their presence must not change the counts.
        self.assertEqual(result["strand"]["plus_matches"], len(PANEL))

    def test_indel_codes_carry_no_strand_information(self):
        rows = _rows("grch37") + [("rs6025", "1", 169519049, "II")]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        # The first occurrence of a marker wins, so rs6025 is still its SNP call here; what
        # matters is that a non-ACGT genotype never contributes a vote.
        for entry in result["strand"]["evidence"]:
            if entry["genotype"] in {"II", "DD", "DI"}:
                self.assertIn("não é SNP", entry["verdict"])

    def test_only_palindromic_markers_yield_no_determination(self):
        rows = [("rs738409", "22", 44324727, "CG"), ("rs17580", "14", 94847262, "AT")]
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), rows), MARKERS_PATH)
        self.assertEqual(result["strand"]["status"], "NÃO DISPONÍVEL")


class AttestationTest(unittest.TestCase):
    def test_an_inconclusive_verdict_produces_no_attestation(self):
        """Silence must not become an attestation by omission."""
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37", limit=2)), MARKERS_PATH)
        self.assertIsNone(attestation_from_probe(result, "reference_build"))
        self.assertIsNone(attestation_from_probe(result, "strand"))

    def test_the_attestation_is_accepted_by_the_qc_gate_and_binds_the_input(self):
        from array_pipeline.qc import _verified_provenance, inspect_array

        with tempfile.TemporaryDirectory() as td:
            array = _write(Path(td), _rows("grch37"))
            result = probe(array, MARKERS_PATH)
            build_att = attestation_from_probe(result, "reference_build")
            strand_att = attestation_from_probe(result, "strand")
            self.assertTrue(_verified_provenance(build_att, result["input_sha256"]))
            self.assertTrue(_verified_provenance(strand_att, result["input_sha256"]))
            # Bound to this file only: another input's hash must not validate it.
            self.assertFalse(_verified_provenance(build_att, "0" * 64))

            qc = inspect_array(
                array, case_id="PROBE",
                build=result["build"]["value"], strand=result["strand"]["value"],
                build_evidence=build_att, strand_evidence=strand_att,
            )
        self.assertEqual(qc["gates"]["BUILD_STRAND_GATE"]["state"], "PASS")
        self.assertIs(qc["input"]["strand_evidence_verified"], True)

    def test_the_attestation_records_the_marker_table_verification_status(self):
        """The table is curated by hand; a report must be able to see that."""
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37")), MARKERS_PATH)
        payload = json.loads(attestation_from_probe(result, "strand"))
        self.assertIn("marker_table_verification_status", payload["trace"])
        self.assertIn("plus/minus allele-set", payload["trace"]["method"])

    def test_an_unknown_attestation_kind_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe(_write(Path(td), _rows("grch37")), MARKERS_PATH)
        with self.assertRaises(ProvenanceProbeError):
            attestation_from_probe(result, "ancestry")


class MarkerTableTest(unittest.TestCase):
    def _table(self, **overrides):
        table = json.loads(MARKERS_PATH.read_text(encoding="utf-8"))
        table.update(overrides)
        return table

    def _load(self, table):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.json"
            path.write_text(json.dumps(table), encoding="utf-8")
            return load_markers(path)

    def test_the_shipped_table_is_valid(self):
        table = load_markers(MARKERS_PATH)
        self.assertTrue(table["markers"])

    def test_a_table_without_a_cited_source_is_refused(self):
        with self.assertRaises(ProvenanceProbeError):
            self._load(self._table(source=""))

    def test_a_wrong_schema_is_refused(self):
        with self.assertRaises(ProvenanceProbeError):
            self._load(self._table(schema="something-else"))

    def test_an_unflagged_palindromic_pair_is_refused(self):
        """Unflagged, it would cast a meaningless vote in the strand verdict."""
        table = self._table()
        for marker in table["markers"]:
            if marker["rsid"] == "rs738409":
                marker["palindromic"] = False
        with self.assertRaises(ProvenanceProbeError) as ctx:
            self._load(table)
        self.assertIn("palindromic", str(ctx.exception))

    def test_every_shipped_palindromic_marker_is_flagged(self):
        for marker in load_markers(MARKERS_PATH)["markers"]:
            pair = {str(a).upper() for a in marker["plus_alleles"]}
            is_palindromic = pair in ({"A", "T"}, {"C", "G"})
            self.assertEqual(bool(marker.get("palindromic")), is_palindromic, marker["rsid"])

    def test_the_two_assemblies_never_share_a_coordinate_for_a_marker(self):
        """Identical positions would make a marker unable to discriminate the build."""
        for marker in load_markers(MARKERS_PATH)["markers"]:
            self.assertNotEqual(
                (marker["grch37"]["chromosome"], marker["grch37"]["position"]),
                (marker["grch38"]["chromosome"], marker["grch38"]["position"]),
                marker["rsid"],
            )


if __name__ == "__main__":
    unittest.main()
