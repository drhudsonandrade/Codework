"""A silent locus must never read as a negative result.

Report 09 exists so that "not in the report" and "tested and absent" stop being the same
sentence. These tests pin the distinction at the boundary where it is easiest to lose: a
locus the chip never carried, a locus that failed to call, and a locus whose orientation was
never verified must all stay outside the interpretable set, however convenient it would be
to fold them into "nothing found".
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.completeness import (
    CLASSES,
    NAO_DETECTADO,
    NAO_REPORTAVEL,
    NAO_TESTADO,
    NO_CALL,
    OBSERVADO,
    build_completeness_matrix,
)
from array_pipeline.qc import inspect_array

HEADER = "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"

TARGETS = {
    "schema": "genoma-partial-genome-targets-v1",
    "id": "TEST-COMPLETENESS",
    "version": "test.1",
    "targets": [
        {"rsid": "rs1799807", "gene": "BCHE", "scope": "CLINICO", "label": "observado",
         "queries": {"clinvar": {"term": "rs1799807"}}},
        {"rsid": "rs6025", "gene": "F5", "scope": "CLINICO", "label": "no-call",
         "queries": {"clinvar": {"term": "rs6025"}}},
        {"rsid": "rs1799963", "gene": "F2", "scope": "CLINICO", "label": "ausente do chip",
         "queries": {"clinvar": {"term": "rs1799963"}}},
        {"rsid": "rs1800562", "gene": "HFE", "scope": "CLINICO", "label": "conflito",
         "queries": {"clinvar": {"term": "rs1800562"}}},
        {"rsid": "rs4149056", "gene": "SLCO1B1", "scope": "CLINICO", "label": "alelo avaliado declarado",
         "assessed_allele": "C",
         "queries": {"clinvar": {"term": "rs4149056"}}},
    ],
}


class CompletenessMatrixTest(unittest.TestCase):
    def _build(self, rows: str, root: Path):
        array = root / "array.csv.gz"
        with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
            fh.write(HEADER)
            fh.write(rows)
        sha = hashlib.sha256(array.read_bytes()).hexdigest()
        evidence = json.dumps({
            "status": "VERIFICADO",
            "decision": "SATISFIED",
            "justification": "Fixture determinístico declara build e fita.",
            "evidence_refs": ["synthetic-completeness-fixture"],
            "trace": {
                "attestation_id": "completeness-fixture",
                "created_at": "2026-08-18T00:00:00Z",
                "actor_type": "SOFTWARE",
                "actor_id": "tests.test_genome_completeness",
                "method": "deterministic fixture",
                "run_id": "unit-test",
                "input_sha256": [sha],
                "output_sha256": [],
                "tool_versions": {"test": "1"},
            },
        })
        qc = inspect_array(
            array, case_id="SYN-GCM", build="GRCh37", strand="forward",
            build_evidence=evidence, strand_evidence=evidence,
        )
        qc_path = root / "qc.json"
        qc_path.write_text(json.dumps(qc), encoding="utf-8")
        targets_path = root / "targets.json"
        targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
        return build_completeness_matrix(array, qc_path, targets_path)

    def _classes(self, matrix) -> dict[str, str]:
        return {e["rsid"]: e["classification"] for e in matrix["entries"]}

    def _rows(self) -> str:
        return (
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
            # present on the chip, but this sample produced no valid genotype
            "rs6025,1,169519049,--,consensus,--,--,GM\n"
            # both platforms disagree and the conflict was never resolved
            "rs1800562,6,26093141,AG,genotype_conflict,AG,GG,GM\n"
            "rs4149056,12,21331549,TT,consensus,TT,TT,GM\n"
            # a non-target locus; must not appear in the matrix at all
            "rs999999,1,100,AA,consensus,AA,AA,GM\n"
        )

    def test_every_registry_target_is_classified_exactly_once(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        rsids = [e["rsid"] for e in matrix["entries"]]
        self.assertEqual(sorted(rsids), sorted(t["rsid"] for t in TARGETS["targets"]))
        self.assertEqual(len(rsids), len(set(rsids)))
        for entry in matrix["entries"]:
            self.assertIn(entry["classification"], CLASSES)

    def test_a_locus_absent_from_the_chip_is_nao_testado_not_negative(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799963")
        self.assertEqual(entry["classification"], NAO_TESTADO)
        self.assertFalse(entry["interpretable"])
        self.assertNotEqual(entry["classification"], NAO_DETECTADO)

    def test_a_missing_genotype_is_no_call_not_negative(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs6025")
        self.assertEqual(entry["classification"], NO_CALL)
        self.assertFalse(entry["interpretable"])

    def test_an_unresolved_cross_platform_conflict_is_nao_reportavel(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1800562")
        self.assertEqual(entry["classification"], NAO_REPORTAVEL)
        self.assertFalse(entry["interpretable"])
        self.assertIn("genotype_conflict", entry["basis"])

    def test_absence_is_only_claimed_when_the_assessed_allele_is_declared(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        classes = self._classes(matrix)
        # rs4149056 declares assessed_allele C and the call is TT -> absence is licensed.
        self.assertEqual(classes["rs4149056"], NAO_DETECTADO)
        # rs1799807 declares no assessed allele, so absence cannot be established even
        # though the locus was called cleanly.
        self.assertEqual(classes["rs1799807"], OBSERVADO)
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertIn("não declara o alelo avaliado", entry["basis"])

    def test_a_present_assessed_allele_stays_observado(self):
        rows = self._rows().replace(
            "rs4149056,12,21331549,TT,consensus,TT,TT,GM\n",
            "rs4149056,12,21331549,CT,consensus,CT,CT,GM\n",
        )
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(rows, Path(td))
        self.assertEqual(self._classes(matrix)["rs4149056"], OBSERVADO)

    def test_a_locus_without_established_orientation_is_nao_reportavel(self):
        """A reported allele whose strand is unknown may be the complement of the truth.

        This guard used to read orientation back from the QC baseline-marker list, which
        covers only 14 rsids, so every other target skipped the check entirely.
        """
        rows = self._rows().replace(
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n",
            # Present in neither platform's verified orientation set.
            "rs1799807,3,165548529,CT,consensus,CT,CT,X\n",
        )
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(rows, Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertEqual(entry["classification"], NAO_REPORTAVEL)
        self.assertFalse(entry["interpretable"])
        self.assertIn("orientação", entry["basis"])

    def test_a_genera_only_locus_is_still_interpretable_as_inferido(self):
        """INFERIDO orientation is weaker than VERIFICADO but is not a blind spot."""
        rows = self._rows().replace(
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n",
            "rs1799807,3,165548529,CT,consensus,CT,,G\n",
        )
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(rows, Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertEqual(entry["classification"], OBSERVADO)

    def test_totals_agree_with_the_entries(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        totals = matrix["totals"]
        self.assertEqual(totals["targets"], len(matrix["entries"]))
        self.assertEqual(sum(totals[f"class_{name}"] for name in CLASSES), totals["targets"])
        self.assertEqual(
            totals["interpretable"],
            sum(1 for e in matrix["entries"] if e["interpretable"]),
        )

    def test_structural_blind_spots_are_reported_as_platform_limits(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        classes = {b["class"] for b in matrix["structural_blind_spots"]}
        self.assertIn("CNV", classes)
        self.assertIn("repeat expansions", classes)
        for blind in matrix["structural_blind_spots"]:
            self.assertEqual(blind["status"], "NÃO DISPONÍVEL")

    def test_the_matrix_is_not_verified_when_the_qc_gate_did_not_pass(self):
        """Coverage is a measurement; it cannot outrank the QC that established it."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write(self._rows())
            # No build/strand evidence: BUILD_STRAND_GATE blocks.
            qc = inspect_array(array, case_id="SYN-GCM")
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
            matrix = build_completeness_matrix(array, qc_path, targets_path)
        self.assertEqual(matrix["operational_status"], "NÃO DISPONÍVEL")
        self.assertFalse(matrix["qc_gate_passed"])

    def test_a_qc_file_from_another_input_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix_root = root / "a"
            matrix_root.mkdir()
            self._build(self._rows(), matrix_root)
            other = root / "other.csv.gz"
            with gzip.open(other, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write("rs1799807,3,165548529,CC,consensus,CC,CC,GM\n")
            with self.assertRaises(ValueError) as ctx:
                build_completeness_matrix(other, matrix_root / "qc.json", matrix_root / "targets.json")
        self.assertIn("SHA-256", str(ctx.exception))

    def test_the_matrix_hash_covers_its_own_content(self):
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        from array_pipeline.targets import sha256_json

        recomputed = sha256_json({k: v for k, v in matrix.items() if k != "sha256"})
        self.assertEqual(matrix["sha256"], recomputed)


class CompletenessReportTest(unittest.TestCase):
    """Report 09 end to end: matrix -> anchored payload -> rendered document."""

    #: A QC-passing array: every present locus is a clean cross-platform consensus call, so
    #: the call-rate and conflict gates pass. Two registry targets are simply absent from
    #: the chip, which is what supplies the blind spots without degrading QC.
    CLEAN_ROWS = (
        "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
        "rs1800562,6,26093141,AG,consensus,AG,AG,GM\n"
        "rs4149056,12,21331549,TT,consensus,TT,TT,GM\n"
        "rs999999,1,100,AA,consensus,AA,AA,GM\n"
    )

    def _artifacts(self, root: Path, rows: str | None = None):
        base = CompletenessMatrixTest()
        matrix = base._build(rows if rows is not None else self.CLEAN_ROWS, root)
        from array_pipeline.completeness import write_matrix

        matrix_path = write_matrix(matrix, root / "completeness.json")
        return matrix, matrix_path, root / "qc.json"

    def test_the_compiled_payload_passes_the_provenance_gate(self):
        from reporting.provenance import provenance_blockers
        from scripts.build_completeness_report import build_payload

        with tempfile.TemporaryDirectory() as td:
            _matrix, matrix_path, qc_path = self._artifacts(Path(td))
            payload = build_payload(matrix_path, qc_path)
        self.assertEqual(provenance_blockers(payload), [])

    def test_the_report_renders_and_states_the_real_counts(self):
        from reporting.engine import render_document
        from scripts.build_completeness_report import build_payload

        with tempfile.TemporaryDirectory() as td:
            matrix, matrix_path, qc_path = self._artifacts(Path(td))
            payload = build_payload(matrix_path, qc_path)
            rendered = render_document("09", payload, mode="FINAL")

        markdown = rendered["markdown"]
        totals = matrix["totals"]
        self.assertIn(f"{totals['interpretable']} de {totals['targets']}", markdown)
        # The blind spots reach the page as structured findings, not as prose.
        self.assertIn("GCM-rs1799963", markdown)
        self.assertIn("GCM-rs6025", markdown)
        self.assertIn(NAO_TESTADO, markdown)
        # A locus the chip never carried must never be summarised as a negative result.
        self.assertNotIn(f"rs1799963={NAO_DETECTADO}", markdown)

    def test_every_non_interpretable_locus_becomes_a_visible_finding(self):
        from scripts.build_completeness_report import build_payload

        with tempfile.TemporaryDirectory() as td:
            matrix, matrix_path, qc_path = self._artifacts(Path(td))
            payload = build_payload(matrix_path, qc_path)

        blind = {e["rsid"] for e in matrix["entries"] if not e["interpretable"]}
        reported = {f["id"].removeprefix("GCM-") for f in payload["findings"]}
        self.assertEqual(reported, blind)
        self.assertTrue(blind, "fixture must contain at least one blind spot")

    def test_a_hand_edited_count_is_refused_at_render_time(self):
        """The headline number is the one most worth faking; it is anchored."""
        from reporting.engine import ReportReleaseError, render_document
        from scripts.build_completeness_report import build_payload

        with tempfile.TemporaryDirectory() as td:
            _matrix, matrix_path, qc_path = self._artifacts(Path(td))
            payload = build_payload(matrix_path, qc_path)
            payload["summary"] = "5 de 5 alvos do registro são interpretáveis (100.0%)."
            with self.assertRaises(ReportReleaseError) as ctx:
                render_document("09", payload, mode="FINAL")
        self.assertIn("provenance:mismatch:summary", str(ctx.exception))

    def test_an_unverified_matrix_produces_a_payload_that_cannot_publish(self):
        """A blocked QC must not yield a publishable completeness report."""
        from reporting.engine import ReportReleaseError, render_document
        from scripts.build_completeness_report import build_payload
        from array_pipeline.completeness import build_completeness_matrix, write_matrix

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write(CompletenessMatrixTest()._rows())
            qc = inspect_array(array, case_id="SYN-GCM")  # no build/strand evidence
            qc_path = root / "qc.json"
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            targets_path = root / "targets.json"
            targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
            matrix = build_completeness_matrix(array, qc_path, targets_path)
            matrix_path = write_matrix(matrix, root / "completeness.json")
            payload = build_payload(matrix_path, qc_path)

            self.assertEqual(payload["operational_status"], "NÃO DISPONÍVEL")
            with self.assertRaises(ReportReleaseError):
                render_document("09", payload, mode="FINAL")

    def test_the_sections_match_the_catalogue_for_report_09(self):
        from reporting.engine import load_catalog
        from scripts.build_completeness_report import SECTIONS

        self.assertEqual(tuple(load_catalog()["09"]["sections"]), SECTIONS)


if __name__ == "__main__":
    unittest.main()
