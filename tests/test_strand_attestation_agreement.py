"""The strand attestation must agree with the file, and with the value it is unlocking.

`BUILD_STRAND_GATE` exists for one reason: every registry this project compares against is
written on the plus strand, so a file reported on the other strand yields inverted answers at
every locus. A Factor V Leiden carrier (rs6025, plus alleles C/T) reads `CT` on the plus
strand and `GA` on the minus one, and the classifier — which asks whether the assessed allele
`T` appears in the call — answers NÃO DETECTADO for a carrier. At a palindromic locus the
inversion runs the other way and produces OBSERVADO in someone who carries nothing.

The gate checked that an attestation existed, was VERIFICADO/SATISFIED and was bound to the
input's SHA-256. It never checked what the attestation *said*. Two consequences, both
reproduced below before they were fixed:

* `provenance_probe` correctly determines that a flipped file is `reverse` and used to emit a
  full attestation saying so. Handed to `--strand forward` — the only strand the CLI offers —
  it validated and the gate passed. The probe's own honest finding became the credential that
  certified its opposite.
* A hand-written attestation asserting `forward` over a file whose own markers say otherwise
  had nothing checking it at all.
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

from array_pipeline.completeness import NAO_REPORTAVEL, build_completeness_matrix
from array_pipeline.provenance_probe import COMPLEMENT, attestation_from_probe, probe
from array_pipeline.qc import _verified_provenance, inspect_array
from tests.attestations import attestation

HEADER = "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
MARKERS = ROOT / "config/array_provenance_markers.json"

#: Non-palindromic markers from the pinned table, with their plus-strand genotypes.
PANEL = [
    ("rs429358", "19", 45411941, "TT"),
    ("rs7412", "19", 45412079, "CC"),
    ("rs6025", "1", 169519049, "CT"),
    ("rs1799963", "11", 46761055, "GG"),
    ("rs9923231", "16", 31107689, "CT"),
    ("rs4149056", "12", 21331549, "CT"),
]

TARGETS = {
    "schema": "genoma-partial-genome-targets-v1",
    "id": "TEST-STRAND",
    "version": "test.1",
    "targets": [
        {"rsid": "rs6025", "gene": "F5", "scope": "CLINICO", "label": "Factor V Leiden",
         "assessed_allele": "T", "queries": {"clinvar": {"term": "rs6025"}}},
    ],
}


def _flip(genotype: str) -> str:
    return "".join(COMPLEMENT[base] for base in genotype)


def _array(root: Path, *, reverse: bool) -> Path:
    path = root / "array.csv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        for rsid, chrom, position, genotype in PANEL:
            call = _flip(genotype) if reverse else genotype
            fh.write(f"{rsid},{chrom},{position},{call},consensus,{call},{call},GM\n")
    return path


class ProbeAttestationTest(unittest.TestCase):
    def test_a_reverse_verdict_produces_no_strand_attestation(self):
        """The determination is real; it is not permission to read the file as forward."""
        with tempfile.TemporaryDirectory() as td:
            result = probe(_array(Path(td), reverse=True), MARKERS)
        self.assertEqual(result["strand"]["status"], "VERIFICADO")
        self.assertEqual(result["strand"]["value"], "reverse")
        self.assertIsNone(attestation_from_probe(result, "strand"))
        # The build verdict is unaffected: coordinates do not depend on orientation.
        self.assertIsNotNone(attestation_from_probe(result, "reference_build"))

    def test_a_forward_verdict_still_attests_and_names_its_value(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe(_array(Path(td), reverse=False), MARKERS)
            payload = json.loads(attestation_from_probe(result, "strand"))
        self.assertEqual(payload["asserted_value"], "forward")
        self.assertEqual(json.loads(attestation_from_probe(result, "reference_build"))["asserted_value"], "GRCh37")


class AttestationAgreementTest(unittest.TestCase):
    SHA = "a" * 64

    def test_an_attestation_for_another_value_does_not_verify_this_one(self):
        reverse = json.dumps(attestation(self.SHA, "reverse"))
        self.assertFalse(
            _verified_provenance(reverse, self.SHA, kind="strand", expected_value="forward")
        )
        self.assertTrue(
            _verified_provenance(reverse, self.SHA, kind="strand", expected_value="reverse")
        )

    def test_spelling_variants_of_the_same_claim_still_agree(self):
        plus = json.dumps(attestation(self.SHA, "plus"))
        self.assertTrue(
            _verified_provenance(plus, self.SHA, kind="strand", expected_value="forward")
        )

    def test_an_attestation_that_names_no_value_verifies_nothing(self):
        payload = attestation(self.SHA, "forward")
        del payload["asserted_value"]
        blank = json.dumps(payload)
        # Structurally it is still a valid attestation...
        self.assertTrue(_verified_provenance(blank, self.SHA))
        # ...but it cannot support a declared value, because it never states one.
        self.assertFalse(
            _verified_provenance(blank, self.SHA, kind="strand", expected_value="forward")
        )

    def test_a_build_attestation_does_not_verify_the_strand(self):
        """One object standing in for two assertions was the shape the hole hid in."""
        build = json.dumps(attestation(self.SHA, "GRCh37"))
        self.assertTrue(
            _verified_provenance(build, self.SHA, kind="reference_build", expected_value="GRCh37")
        )
        self.assertFalse(
            _verified_provenance(build, self.SHA, kind="strand", expected_value="forward")
        )


class GateRefusesAFlippedFileTest(unittest.TestCase):
    def _sha(self, path: Path) -> str:
        import hashlib

        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_a_hand_signed_forward_attestation_loses_to_the_file_itself(self):
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=True)
            sha = self._sha(array)
            qc = inspect_array(
                array, case_id="REV", build="GRCh37", strand="forward",
                build_evidence=json.dumps(attestation(sha, "GRCh37")),
                strand_evidence=json.dumps(attestation(sha, "forward")),
            )
        gate = qc["gates"]["BUILD_STRAND_GATE"]
        self.assertEqual(gate["state"], "BLOCKED")
        self.assertTrue(any("contradiz" in reason for reason in gate["reasons"]))
        self.assertEqual(qc["operational_status"], "NÃO DISPONÍVEL")
        self.assertIs(qc["input"]["strand_evidence_verified"], False)
        self.assertEqual(qc["metrics"]["strand_markers_minus_only"], len(PANEL))
        self.assertEqual(qc["metrics"]["strand_markers_plus_only"], 0)
        # The per-locus orientation was decided before the vote was counted; it must not be
        # left claiming VERIFICADO in the same file whose gate refused the strand.
        for hit in qc["baseline_marker_observations"]:
            self.assertEqual(hit["orientation_operational_status"], "NÃO DISPONÍVEL")

    def test_an_intact_forward_file_still_passes(self):
        """The refusal has to be about the flip, not about strictness in general."""
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=False)
            sha = self._sha(array)
            qc = inspect_array(
                array, case_id="FWD", build="GRCh37", strand="forward",
                build_evidence=json.dumps(attestation(sha, "GRCh37")),
                strand_evidence=json.dumps(attestation(sha, "forward")),
            )
        self.assertEqual(qc["gates"]["BUILD_STRAND_GATE"]["state"], "PASS")
        self.assertEqual(qc["metrics"]["strand_markers_plus_only"], len(PANEL))
        self.assertEqual(qc["metrics"]["strand_markers_minus_only"], 0)

    def test_a_carrier_is_never_reported_negative_on_a_flipped_file(self):
        """The consequence the gate is for, stated as an outcome rather than a state.

        rs6025 CT is a Factor V Leiden carrier. On a flipped file the call reads GA, and the
        assessed allele T appears nowhere in it — so an unguarded classifier answers
        NÃO DETECTADO for a carrier. The matrix must refuse the locus instead.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = _array(root, reverse=True)
            sha = self._sha(array)
            qc = inspect_array(
                array, case_id="REV", build="GRCh37", strand="reverse",
                build_evidence=json.dumps(attestation(sha, "GRCh37")),
                strand_evidence=json.dumps(attestation(sha, "reverse")),
            )
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            targets = root / "targets.json"
            targets.write_text(json.dumps(TARGETS), encoding="utf-8")
            matrix = build_completeness_matrix(array, qc_path, targets)

        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs6025")
        self.assertEqual(entry["classification"], NAO_REPORTAVEL)
        self.assertFalse(entry["interpretable"])
        self.assertIn("orientação", entry["basis"])

    def test_a_declared_reverse_strand_blocks_the_gate_by_name(self):
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=True)
            sha = self._sha(array)
            qc = inspect_array(
                array, case_id="REV", build="GRCh37", strand="reverse",
                build_evidence=json.dumps(attestation(sha, "GRCh37")),
                strand_evidence=json.dumps(attestation(sha, "reverse")),
            )
        reasons = qc["gates"]["BUILD_STRAND_GATE"]["reasons"]
        self.assertTrue(any("fita reversa" in reason for reason in reasons))


class CliAgreementTest(unittest.TestCase):
    def _module(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "run_snp_array_under_test", ROOT / "scripts/run_snp_array.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_cli_refuses_evidence_that_contradicts_the_declared_strand(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=True)
            import hashlib

            sha = hashlib.sha256(array.read_bytes()).hexdigest()
            reverse = json.dumps(attestation(sha, "reverse"))
            with self.assertRaises(ValueError) as caught:
                module.load_verified_attestation(
                    reverse, assertion="strand", input_path=array, declared_value="forward"
                )
        message = str(caught.exception)
        self.assertIn("reverse", message)
        self.assertIn("forward", message)
        self.assertIn("contradicts", message)

    def test_an_inline_attestation_without_a_slash_in_it_is_still_read(self):
        """`Path(value).is_file()` raises ENAMETOOLONG on a 255+ byte path component.

        The inline form is documented and CI never uses it, so this crashed for every real
        payload that happened to contain no `/`. The one existing inline fixture contained
        the word "Vendor/reference", which split the string into short components and hid it.
        """
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=False)
            import hashlib

            sha = hashlib.sha256(array.read_bytes()).hexdigest()
            payload = attestation(
                sha, "forward", justification="sem barra alguma nesta frase", evidence_ref="fixture"
            )
            inline = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("/", inline)
            self.assertGreater(len(inline), 255)
            loaded = module.load_verified_attestation(
                inline, assertion="strand", input_path=array, declared_value="forward"
            )
        self.assertEqual(loaded["asserted_value"], "forward")

    def test_the_cli_requires_the_attestation_to_name_its_value(self):
        module = self._module()
        with tempfile.TemporaryDirectory() as td:
            array = _array(Path(td), reverse=False)
            import hashlib

            sha = hashlib.sha256(array.read_bytes()).hexdigest()
            payload = attestation(sha, "forward")
            del payload["asserted_value"]
            with self.assertRaises(ValueError):
                module.load_verified_attestation(
                    json.dumps(payload), assertion="strand", input_path=array,
                    declared_value="forward",
                )


if __name__ == "__main__":
    unittest.main()
