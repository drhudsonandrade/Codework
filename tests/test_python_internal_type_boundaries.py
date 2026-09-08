"""Characterize runtime contracts preserved by the Python type-checker cleanup."""
from __future__ import annotations

import gzip
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from array_pipeline.qc import _text_stream
from policy_engine.genoma_policy import gates_audit
from reporting import engine


class PythonInternalTypeBoundaryTest(unittest.TestCase):
    """Keep heterogeneous input handling unchanged while making its types explicit."""

    def test_plain_gzip_and_zip_streams_preserve_text_and_close(self):
        """All supported containers expose the same strictly decoded text stream."""
        expected = "RSID,CHROMOSOME,POSITION,RESULT\nrs1,1,1,AA\n"
        raw = ("\ufeff" + expected).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sample.csv").write_bytes(raw)
            (root / "sample.csv.gz").write_bytes(gzip.compress(raw))
            with zipfile.ZipFile(root / "sample.zip", "w") as archive:
                archive.writestr("sample.csv", raw)
            for name in ("sample.csv", "sample.csv.gz", "sample.zip"):
                with self.subTest(container=name):
                    stream, _source = _text_stream(root / name)
                    with stream:
                        self.assertEqual(stream.read(), expected)
                    self.assertTrue(stream.closed)

    def test_section_gate_only_forwards_nonempty_string_source_ids(self):
        """Malformed source identifiers never enter the attestation evidence set."""
        gate = gates_audit.AuditGates()
        gate.ruleset = SimpleNamespace(sections=[object()])
        manifest = {
            "operation": {"analysis_relevant": True},
            "section_attestations": [
                {"section": 0, "applicability": "NOT_APPLICABLE", "decision": "SATISFIED"}
            ],
            "sources": [
                None, 1, "source", {}, {"id": None}, {"id": False}, {"id": 7},
                {"id": []}, {"id": {}}, {"id": ""}, {"id": "trace-a"},
                {"id": "trace-a"}, {"id": "trace-b"},
            ],
        }
        original = deepcopy(manifest)
        with patch.object(gates_audit, "validate_section_attestation", return_value=[]) as check:
            result = gate._section_coverage_gate(manifest)
        check.assert_called_once()
        self.assertEqual(check.call_args.args[2], {"trace-a", "trace-b"})
        self.assertEqual(result.state.value, "PASS")
        self.assertEqual(manifest, original)

    def test_final_write_boundary_normalizes_nonmapping_payloads_and_still_refuses(self):
        """Nonmapping data reaches the refusal gate as an empty mapping, not as evidence."""
        for invalid in (None, False, 0, [], "payload"):
            with self.subTest(payload=invalid):
                rendered = {
                    "metadata": {"mode": "FINAL", "report_id": "01"},
                    "_render_mode": "FINAL",
                    "data": invalid,
                }
                with (
                    patch.object(
                        engine, "_publication_blockers", return_value=["fixture-refusal"]
                    ) as check,
                    self.assertRaisesRegex(engine.ReportReleaseError, "fixture-refusal"),
                ):
                    engine._assert_serializable_provenance(rendered)
                check.assert_called_once_with({}, "01")

    def test_final_write_boundary_passes_the_original_mapping_to_the_gate(self):
        """Normalizing the local type does not copy or replace a supplied mapping."""
        data = {"marker": "fixture"}
        rendered = {
            "metadata": {"mode": "FINAL", "report_id": "01"},
            "_render_mode": "FINAL",
            "data": data,
        }
        with (
            patch.object(
                engine, "_publication_blockers", return_value=["fixture-refusal"]
            ) as check,
            self.assertRaisesRegex(engine.ReportReleaseError, "fixture-refusal"),
        ):
            engine._assert_serializable_provenance(rendered)
        self.assertIs(check.call_args.args[0], data)
        self.assertEqual(data, {"marker": "fixture"})


if __name__ == "__main__":
    unittest.main()
