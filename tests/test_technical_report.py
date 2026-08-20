"""Report 05 is what an auditor reads to decide whether to believe the other ten.

So it must publish its own weaknesses, not only what worked: unresolved cross-platform
records, withheld genotypes, structural blind spots, the basis of the strand call, and each
gate's own stated reasons. A technical report that listed only successes would be the least
honest document in the suite.
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

from array_pipeline.completeness import build_completeness_matrix, write_matrix
from array_pipeline.qc import inspect_array

HEADER = "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"

TARGETS = {
    "schema": "genoma-partial-genome-targets-v1",
    "id": "TEST-TEC",
    "version": "test.1",
    "targets": [
        {"rsid": "rs1799807", "gene": "BCHE", "scope": "CLINICO", "label": "a",
         "queries": {"clinvar": {"term": "rs1799807"}}},
        {"rsid": "rs6025", "gene": "F5", "scope": "CLINICO", "label": "b",
         "queries": {"clinvar": {"term": "rs6025"}}},
    ],
}

CLEAN_ROWS = (
    "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
    "rs6025,1,169519049,CC,consensus,CC,CC,GM\n"
    "rs999999,1,100,AA,consensus,AA,AA,GM\n"
)

def _padding(count: int) -> str:
    """Clean consensus rows, so one conflict stays under the 0.5% conflict-rate threshold.

    With a three-row fixture a single conflict is a 100% conflict rate and the
    cross-platform gate blocks — correctly, but that then tests the blocked path rather
    than the reporting of an unresolved record inside a passing run.
    """
    return "".join(
        f"rs{900000 + i},1,{200000 + i},AA,consensus,AA,AA,GM\n" for i in range(count)
    )


#: One unresolved conflict inside an otherwise clean run, so the limitations section has
#: something real to report while QC still passes.
CONFLICTED_ROWS = (
    "rs1799807,3,165548529,CT,consensus,CT,CT,GM\n"
    "rs6025,1,169519049,CC,genotype_conflict,CC,TT,GM\n"
    + _padding(400)
)


def _artifacts(root: Path, rows: str = CLEAN_ROWS, *, evidence: bool = True):
    array = root / "array.csv.gz"
    with gzip.open(array, "wt", encoding="utf-8", newline="") as fh:
        fh.write(HEADER)
        fh.write(rows)
    sha = hashlib.sha256(array.read_bytes()).hexdigest()
    attestation = json.dumps({
        "status": "VERIFICADO", "decision": "SATISFIED",
        "justification": "Fixture determinístico declara build e fita.",
        "evidence_refs": ["synthetic-tec-fixture"],
        "trace": {
            "attestation_id": "tec-fixture", "created_at": "2026-08-19T00:00:00Z",
            "actor_type": "SOFTWARE", "actor_id": "tests.test_technical_report",
            "method": "deterministic fixture", "run_id": "unit-test",
            "input_sha256": [sha], "output_sha256": [], "tool_versions": {"test": "1"},
        },
    })
    kwargs = (
        {"build": "GRCh37", "strand": "forward", "build_evidence": attestation, "strand_evidence": attestation}
        if evidence
        else {}
    )
    qc = inspect_array(array, case_id="SYN-TEC", **kwargs)
    qc_path = root / "array-qc.json"
    qc_path.write_text(json.dumps(qc), encoding="utf-8")
    targets_path = root / "targets.json"
    targets_path.write_text(json.dumps(TARGETS), encoding="utf-8")
    matrix_path = write_matrix(
        build_completeness_matrix(array, qc_path, targets_path), root / "completeness.json"
    )
    return qc_path, matrix_path


class TechnicalReportTest(unittest.TestCase):
    def _payload(self, root: Path, rows: str = CLEAN_ROWS, *, evidence: bool = True, probe: dict | None = None):
        from scripts.build_technical_report import build_payload

        qc_path, matrix_path = _artifacts(root, rows, evidence=evidence)
        probe_path = None
        if probe is not None:
            probe_path = root / "probe.json"
            probe_path.write_text(json.dumps(probe), encoding="utf-8")
        return build_payload(qc_path, matrix_path, probe_path)

    def _probe(self):
        return {
            "schema": "genoma-array-provenance-probe-v1",
            "evaluated_at": "2026-08-19T00:00:00Z",
            "input_sha256": "0" * 64,
            "marker_table": {
                "id": "GENOMA-PROVENANCE-MARKERS", "version": "test.1",
                "source": "fixture", "verification_status": "VERIFICADO",
            },
            "build": {"status": "VERIFICADO", "value": "GRCh37", "grch37_matches": 11,
                      "grch38_matches": 0, "threshold": 3, "evidence": []},
            "strand": {"status": "VERIFICADO", "value": "forward", "plus_matches": 9,
                       "minus_matches": 0, "threshold": 3, "evidence": []},
        }

    def test_the_sections_match_the_catalogue_for_report_05(self):
        from reporting.engine import load_catalog
        from scripts.build_technical_report import SECTIONS

        self.assertEqual(tuple(load_catalog()["05"]["sections"]), SECTIONS)

    def test_the_compiled_payload_passes_the_provenance_gate(self):
        from reporting.provenance import provenance_blockers

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        self.assertEqual(provenance_blockers(payload), [])

    def test_the_report_renders_and_states_measured_numbers(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
            markdown = render_document("05", payload, mode="FINAL")["markdown"]
        self.assertIn("call rate", markdown.lower())
        self.assertIn("3 linhas", markdown)

    def test_every_qc_gate_becomes_its_own_visible_finding(self):
        """A single aggregate verdict could hide a blocked prerequisite."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._payload(root)
            qc = json.loads((root / "array-qc.json").read_text(encoding="utf-8"))
        reported = {f["id"].removeprefix("QC-") for f in payload["findings"]}
        self.assertEqual(reported, set(qc["gates"]))

    def test_unresolved_records_are_reported_not_hidden(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td), CONFLICTED_ROWS)
            markdown = render_document("05", payload, mode="FINAL")["markdown"]
        self.assertIn("genotype_conflict", markdown)
        self.assertIn("nunca são arbitrados", markdown)

    def test_structural_blind_spots_appear_in_the_limitations(self):
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
            markdown = render_document("05", payload, mode="FINAL")["markdown"]
        for blind in ("CNV", "repeat expansions", "CYP2D6"):
            self.assertIn(blind, markdown)

    def test_the_runtime_gate_section_says_not_applicable_rather_than_borrowing_a_pass(self):
        """Section 259 forbids inheriting another session's PASS; an array opens no NGS resource."""
        from reporting.engine import render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
            markdown = render_document("05", payload, mode="FINAL")["markdown"]
        section = markdown.split("## Runtime/Resource Gate")[1].split("##")[0]
        self.assertIn("NÃO APLICÁVEL", section)
        self.assertIn("259", section)
        self.assertNotIn("PASS", section.replace("Nenhum PASS de outra sessão", ""))

    def test_the_strand_basis_is_disclosed_when_a_probe_ran(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td), probe=self._probe())
        section = payload["sections"]["Contrato de entrada e cadeia de custódia"]
        self.assertIn("9 plus vs 0 minus", section)
        self.assertIn("palindrômicos excluídos", section)

    def test_the_absence_of_a_probe_is_stated_not_omitted(self):
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        section = payload["sections"]["Contrato de entrada e cadeia de custódia"]
        self.assertIn("Nenhum probe de proveniência foi executado", section)

    def test_a_blocked_qc_cannot_publish_the_technical_report(self):
        from reporting.engine import ReportReleaseError, render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td), evidence=False)
            self.assertEqual(payload["operational_status"], "NÃO DISPONÍVEL")
            with self.assertRaises(ReportReleaseError):
                render_document("05", payload, mode="FINAL")

    def test_a_hand_edited_call_rate_is_refused_at_render_time(self):
        from reporting.engine import ReportReleaseError, render_document

        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
            payload["summary"] = "719762 variantes analisadas, call rate 100.00%."
            with self.assertRaises(ReportReleaseError) as ctx:
                render_document("05", payload, mode="FINAL")
        self.assertIn("provenance:mismatch:summary", str(ctx.exception))

    def test_the_report_records_the_hashes_needed_to_reproduce_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = self._payload(root)
            qc = json.loads((root / "array-qc.json").read_text(encoding="utf-8"))
        section = payload["sections"]["Pipeline reproduzível"]
        self.assertIn(qc["input"]["sha256"], section)
        self.assertIn("ARRAY_QC_SHA256", payload["execution_manifest"])
        self.assertIn("COMPLETENESS_MATRIX_SHA256", payload["execution_manifest"])

    def test_a_gate_that_did_not_pass_states_its_reason_not_just_its_state(self):
        # "BUILD_STRAND_GATE=BLOCKED" tells a reader that something is wrong and nothing
        # about what. The reason lived only in the QC file, which nobody reading the report
        # opens.
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td), evidence=False)
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertIn("Razões dos gates que não passaram", blob)
        self.assertIn("BUILD_STRAND_GATE", blob)
        self.assertIn("provenance", blob)

    def test_a_clean_run_says_so_instead_of_leaving_the_sentence_out(self):
        # An absent sentence reads the same as a forgotten one; the all-clear is stated.
        with tempfile.TemporaryDirectory() as td:
            payload = self._payload(Path(td))
        blob = json.dumps(payload, ensure_ascii=False)
        self.assertIn("Nenhum gate do QC ficou com ressalva", blob)
        self.assertNotIn("Razões dos gates que não passaram", blob)


if __name__ == "__main__":
    unittest.main()
