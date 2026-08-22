from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_array_case_manifest import build_manifest

ROOT = Path(__file__).resolve().parents[1]


class ArrayScientificDataPlaneTest(unittest.TestCase):
    def test_main_nextflow_dispatches_array_mode_fail_closed(self):
        main = (ROOT / "main.nf").read_text(encoding="utf-8")
        self.assertIn("include { ARRAY_PRODUCTION } from './workflows/array'", main)
        self.assertIn("else if (params.mode == 'array')", main)
        for name in ["array_input", "array_build", "array_strand", "array_build_evidence", "array_strand_evidence"]:
            self.assertIn(name, main)
        self.assertIn("Allowed: canary, wgs, array", main)

    def test_array_workflow_has_all_four_planes_handoffs(self):
        text = (ROOT / "workflows" / "array.nf").read_text(encoding="utf-8")
        for process in ["ARRAY_QC", "ARRAY_ANNOTATE", "ARRAY_BUILD_MANIFEST", "ARRAY_POLICY_EVALUATE", "ARRAY_GENERATE_REPORTS"]:
            self.assertIn(f"process {process}", text)
        self.assertIn("LIMITED_INTERPRETATION_GATE", text)
        self.assertIn("partial-genome-annotation.json", text)
        self.assertIn("generate_all_reports.py", text)

    def test_case_manifest_never_claims_array_is_wgs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path = root / "qc.json"
            ann_path = root / "ann.json"
            qc = {
                "operational_status": "VERIFICADO",
                "case_id": "SYN",
                "input": {"sha256": "a" * 64, "build": "GRCh37", "strand": "forward",
                          "schema": "harmonized_genera_myheritage_v1"},
                "metrics": {"unique_rsids": 2, "call_rate": 1.0},
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "limitations": [],
            }
            ann = {
                "case_id": "SYN",
                "input_sha256": "a" * 64,
                "operational_status": "PROPOSTO",
                "mode": "plan-only",
                "evidence_gate": {"state": "BLOCKED"},
                "observations": [],
                "evidence_retrievals": [],
                "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            ann_path.write_text(json.dumps(ann), encoding="utf-8")
            payload = build_manifest(qc, ann, qc_path, ann_path)
            self.assertEqual(payload["capability_matrix"]["CNV"]["status"], "NÃO DISPONÍVEL")
            self.assertEqual(payload["capability_matrix"]["SV"]["status"], "NÃO DISPONÍVEL")
            self.assertEqual(payload["capability_matrix"]["genome_wide_negative"]["status"], "NÃO DISPONÍVEL")
            self.assertFalse(payload["publication_gate"]["passed"])
            self.assertEqual(payload["post_deployment_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
