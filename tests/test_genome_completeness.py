"""A silent locus must never read as a negative result.

Report 09 exists so that "not in the report" and "tested and absent" stop being the same
sentence. These tests pin the distinction at the boundary where it is easiest to lose: a
locus the chip never carried, a locus that failed to call, and a locus whose orientation was
never verified must all stay outside the interpretable set, however convenient it would be
to fold them into "nothing found".
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

from tests.attestations import provenance_for
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
        qc = inspect_array(
            array, case_id="SYN-GCM",
            **provenance_for(array, evidence_ref="synthetic-completeness-fixture",
                             actor_id="tests.test_genome_completeness"),
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

    def test_a_non_interpretable_locus_does_not_carry_its_genotype(self):
        """A conflicting record still has a called value; carrying it invited arbitration.

        Consumers printed `genotype or classification`, so an unreliable call was displayed
        exactly like a usable one.
        """
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(self._rows(), Path(td))
        for entry in matrix["entries"]:
            with self.subTest(rsid=entry["rsid"]):
                if not entry["interpretable"]:
                    self.assertIsNone(entry["genotype"])
        conflicted = next(e for e in matrix["entries"] if e["rsid"] == "rs1800562")
        self.assertTrue(conflicted["genotype_withheld"])
        observed = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertEqual(observed["genotype"], "CT")
        self.assertFalse(observed["genotype_withheld"])

    def test_duplicate_rows_with_conflicting_genotypes_are_not_arbitrated(self):
        """Keeping only the first row silently picked a winner between disagreeing rows."""
        rows = (
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
            "rs1799807,3,165548529,GG,consensus,GG,GG,GM\n"
        ) + self._rows().replace("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n", "")
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(rows, Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertEqual(entry["classification"], NAO_REPORTAVEL)
        self.assertIsNone(entry["genotype"])
        self.assertIn("duplicadas", entry["basis"])

    def test_duplicate_rows_that_agree_are_not_penalised(self):
        rows = (
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
        ) + self._rows().replace("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n", "")
        with tempfile.TemporaryDirectory() as td:
            matrix = self._build(rows, Path(td))
        entry = next(e for e in matrix["entries"] if e["rsid"] == "rs1799807")
        self.assertEqual(entry["classification"], OBSERVADO)
        self.assertEqual(entry["genotype"], "CT")

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

    def test_a_panel_scale_blind_spot_list_is_bounded_and_nothing_is_lost(self):
        """55,916 targets against a chip that reaches 4% is ~53,900 blind spots.

        Listing each one individually produced a 275 MB payload no renderer can turn into a
        document, and a report that names every blind spot names none of them. The cap is
        only honest if the remainder is still counted exactly and still points at the
        artifact that holds it, so both are asserted here.
        """
        import json as _json

        from scripts.build_completeness_report import (
            MAX_ENUMERATED_BLIND_SPOTS,
            build_payload,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix, matrix_path, qc_path = self._artifacts(root)
            extra = MAX_ENUMERATED_BLIND_SPOTS + 120
            matrix["entries"].extend(
                {
                    "rsid": f"rs{8_000_000 + i}",
                    "gene": f"GENE{i % 37}",
                    "scope": "CURIOSIDADE" if i % 5 else "CLINICO",
                    "classification": NAO_TESTADO,
                    "basis": "ausente do array nesta simulação",
                    "interpretable": False,
                    "genotype": None,
                    "genotype_withheld": True,
                }
                for i in range(extra)
            )
            blind_total = sum(1 for e in matrix["entries"] if not e["interpretable"])
            matrix["totals"]["targets"] = len(matrix["entries"])
            matrix["totals"][f"class_{NAO_TESTADO}"] = blind_total
            matrix_path.write_text(
                _json.dumps(matrix, ensure_ascii=False), encoding="utf-8"
            )
            payload = build_payload(matrix_path, qc_path)

        individual = [f for f in payload["findings"] if f["id"] != "GCM-RESTANTE"]
        aggregate = [f for f in payload["findings"] if f["id"] == "GCM-RESTANTE"]
        self.assertEqual(len(individual), MAX_ENUMERATED_BLIND_SPOTS)
        self.assertEqual(len(aggregate), 1, "the remainder must be reported, not dropped")

        remainder = blind_total - MAX_ENUMERATED_BLIND_SPOTS
        self.assertIn(str(remainder), aggregate[0]["observed_data"])
        # And it must say where the ones it did not name can be found.
        self.assertIn("completeness-matrix:", aggregate[0]["evidence_refs"])

    def test_the_bounded_list_names_the_clinical_loci_first(self):
        # A curiosity locus displacing a clinical one from the enumeration would make the cap
        # a loss of information rather than a change of presentation.
        import json as _json

        from scripts.build_completeness_report import (
            MAX_ENUMERATED_BLIND_SPOTS,
            build_payload,
        )

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix, matrix_path, qc_path = self._artifacts(root)
            matrix["entries"].extend(
                {
                    "rsid": f"rs{7_000_000 + i}",
                    "gene": f"CURIO{i}",
                    "scope": "CURIOSIDADE",
                    "classification": NAO_TESTADO,
                    "basis": "ausente do array nesta simulação",
                    "interpretable": False,
                    "genotype": None,
                    "genotype_withheld": True,
                }
                for i in range(MAX_ENUMERATED_BLIND_SPOTS * 2)
            )
            clinical = {
                e["rsid"] for e in matrix["entries"]
                if not e["interpretable"] and e.get("scope") == "CLINICO"
            }
            matrix["totals"]["targets"] = len(matrix["entries"])
            matrix_path.write_text(
                _json.dumps(matrix, ensure_ascii=False), encoding="utf-8"
            )
            payload = build_payload(matrix_path, qc_path)

        named = {f["id"].removeprefix("GCM-") for f in payload["findings"]}
        self.assertTrue(clinical, "fixture must contain clinical blind spots")
        self.assertTrue(clinical <= named, "a clinical blind spot was displaced by a curiosity")

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


class QCEnforcementTest(unittest.TestCase):
    """A failed QC has to stop the matrix, because everything else is built on it.

    Found by feeding the pipeline an array whose coordinate column was fabricated: QC
    returned STRUCTURE_GATE FAIL and `ready: false`, and the orchestrator went on to produce
    all ten patient reports — one of them naming 27 actionable findings and a specific
    pathogenic call — with exit status 0 and no report mentioning that the QC had failed.
    The status flag was there; nothing consumed it.
    """

    def _matrix_from(self, qc: dict, root: Path, array: Path):
        qc_path = root / "qc.json"
        qc_path.write_text(json.dumps(qc), encoding="utf-8")
        targets_path = root / "targets.json"
        targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
        return build_completeness_matrix(array, qc_path, targets_path)

    def _array_and_qc(self, root: Path, rows: str):
        array = root / "array.csv.gz"
        with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
            fh.write(HEADER)
            fh.write(rows)
        return array, inspect_array(array, case_id="SYN-GCM")

    def test_an_impossible_coordinate_refuses_the_matrix_and_names_the_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # chr21 ends near 48.1 Mb; a marker at 200 Mb is on no assembly.
            array, qc = self._array_and_qc(root, "rs1799807,21,200000000,CT,consensus,CT,CT,GM\n")
            self.assertEqual(qc["gates"]["STRUCTURE_GATE"]["state"], "FAIL")
            with self.assertRaises(ValueError) as caught:
                self._matrix_from(qc, root, array)
        self.assertIn("beyond the end of their own chromosome", str(caught.exception))

    def test_duplicate_rsids_do_not_refuse_because_the_matrix_resolves_them(self):
        # The line between the two severities: a duplicate row is a real harmonized export's
        # quirk, classified locus by locus, not a reason to withhold the whole array.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array, qc = self._array_and_qc(
                root,
                "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
                "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n",
            )
            self.assertEqual(qc["gates"]["STRUCTURE_GATE"]["state"], "FAIL")
            self.assertEqual(qc["gates"]["STRUCTURE_GATE"]["blocking_reasons"], [])
            matrix = self._matrix_from(qc, root, array)
        self.assertEqual(matrix["operational_status"], "NÃO DISPONÍVEL")

    def test_a_qc_file_predating_the_severity_split_is_read_fail_closed(self):
        # An older QC artifact has no blocking_reasons key. Treating "unstated" as "not
        # blocking" would quietly reopen the hole for every artifact already on disk.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array, qc = self._array_and_qc(root, "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            qc["gates"]["STRUCTURE_GATE"] = {"state": "FAIL", "reasons": ["invalid positions=7"]}
            with self.assertRaises(ValueError) as caught:
                self._matrix_from(qc, root, array)
        self.assertIn("invalid positions=7", str(caught.exception))

    def test_a_non_passing_gate_travels_with_the_matrix_as_a_stated_reservation(self):
        # Without this the reports inherit NÃO DISPONÍVEL and cannot say why: the reason was
        # left behind in the QC file that no reader of the report ever sees.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array, qc = self._array_and_qc(root, "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            matrix = self._matrix_from(qc, root, array)
        gates = {r["gate"] for r in matrix["qc_reservations"]}
        self.assertIn("BUILD_STRAND_GATE", gates)
        self.assertTrue(all(r["reasons"] for r in matrix["qc_reservations"]))

    def test_a_clean_matrix_states_an_empty_reservation_list(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array = root / "array.csv.gz"
            with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
                fh.write(HEADER)
                fh.write("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            qc = inspect_array(
                array, case_id="SYN-GCM",
                **provenance_for(array, evidence_ref="synthetic-completeness-fixture",
                                 actor_id="tests.test_genome_completeness"),
            )
            matrix = self._matrix_from(qc, root, array)
        self.assertEqual(matrix["qc_reservations"], [])
        self.assertTrue(matrix["qc_gate_passed"])


if __name__ == "__main__":
    unittest.main()
