"""A one-page summary is where "nothing found" replaces "nothing was tested for".

Report 10 is read in thirty seconds and is therefore the most dangerous document in the
suite. It is built as a derivation of reports that already refused to overstate, so these
tests check that it inherits their refusals rather than smoothing them into a clean page.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_genome_completeness import CompletenessMatrixTest, TARGETS  # noqa: F401


class OnePageSummaryTest(unittest.TestCase):
    def _artifacts(self, root: Path):
        from array_pipeline.completeness import write_matrix
        from array_pipeline.pharmacogenomics import build_pharmacogenomic_passport, write_passport

        base = CompletenessMatrixTest()
        clean = (
            "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
            "rs1800562,6,26093141,AG,consensus,AG,AG,GM\n"
            "rs4149056,12,21331549,TT,consensus,TT,TT,GM\n"
            "rs999999,1,100,AA,consensus,AA,AA,GM\n"
        )
        matrix = base._build(clean, root)
        matrix_path = write_matrix(matrix, root / "completeness.json")
        passport = build_pharmacogenomic_passport(matrix_path, root / "targets.json")
        passport_path = write_passport(passport, root / "passport.json")
        return matrix_path, passport_path

    def _payload(self, root: Path, with_passport: bool = True):
        from scripts.build_one_page_summary import build_payload

        matrix_path, passport_path = self._artifacts(root)
        return build_payload(matrix_path, passport_path if with_passport else None)

    def test_the_sections_match_the_catalogue_for_report_10(self):
        from reporting.engine import load_catalog
        from scripts.build_one_page_summary import SECTIONS

        self.assertEqual(tuple(load_catalog()["10"]["sections"]), SECTIONS)

    def test_the_compiled_payload_passes_the_provenance_gate(self):
        from reporting.provenance import provenance_blockers

        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(provenance_blockers(self._payload(Path(td))), [])

    def test_the_headline_keeps_the_coverage_classes_apart(self):
        """Collapsing OBSERVADO, NÃO DETECTADO and NÃO TESTADO is the failure a one-pager invites."""
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        summary = payload["summary"]
        for phrase in ("carregam o alelo avaliado", "testados e não o carregam", "sem chamada"):
            self.assertIn(phrase, summary)
        self.assertIn("Ausência só é afirmável", summary)

    def test_clinical_priority_and_action_are_never_derived(self):
        """This pipeline does not decide conduct, and a one-pager must not imply it does."""
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        self.assertEqual(payload["sections"]["Prioridade e confirmação"], "NÃO DISPONÍVEL")

    def test_structural_blind_spots_reach_the_page_itself(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        alerts = payload["sections"]["Alertas e pontos cegos"]
        for blind in ("CNV", "CYP2D6"):
            self.assertIn(blind, alerts)

    def test_the_summary_states_when_no_passport_was_compiled(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td), with_passport=False)
        self.assertIn("NÃO DISPONÍVEL", payload["sections"]["Alertas e pontos cegos"])

    def test_a_passport_from_another_input_is_refused(self):
        from scripts.build_one_page_summary import build_payload

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            matrix_path, passport_path = self._artifacts(root)
            tampered = json.loads(passport_path.read_text(encoding="utf-8"))
            tampered["input_sha256"] = "0" * 64
            passport_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                build_payload(matrix_path, passport_path)
        self.assertIn("different inputs", str(ctx.exception))

    def test_the_page_renders_and_says_it_does_not_replace_the_full_reports(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            markdown = render_document("10", self._payload(Path(td)), mode="FINAL")["markdown"]
        self.assertIn("não substitui os relatórios completos", markdown)


if __name__ == "__main__":
    unittest.main()
