import tempfile
import unittest
from pathlib import Path


def passing_policy_evaluation():
    return {
        "ready_for_requested_operation": True,
        "planes": {
            "policy_control": {"state": "PASS"},
            "scientific_data": {"state": "PASS"},
            "evidence": {"state": "PASS"},
            "audit": {"state": "PASS"},
        },
        "gates": [
            {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
            {"gate": "POST_DEPLOYMENT_GATE", "state": "PENDING", "blocking": False},
        ],
    }


class ReportEngineTest(unittest.TestCase):
    def test_catalog_contains_all_eleven_v3_models(self):
        from reporting.engine import load_catalog

        catalog = load_catalog()
        self.assertEqual(sorted(catalog), [f"{i:02d}" for i in range(1, 12)])
        self.assertEqual(catalog["01"]["slug"], "genoma-clinico")
        self.assertEqual(catalog["11"]["slug"], "guia-editorial-matriz-preenchimento")

    def test_model_mode_is_explicitly_non_result(self):
        from reporting.engine import render_document

        result = render_document("01", {}, mode="MODEL")
        self.assertIn("MODELO — NÃO É RESULTADO GENÉTICO", result["markdown"])
        self.assertEqual(result["metadata"]["mode"], "MODEL")

    def test_final_mode_fails_closed_without_publication_gate(self):
        from reporting.engine import ReportReleaseError, render_document

        with self.assertRaises(ReportReleaseError):
            render_document("01", {"case_id": "CASE-001"}, mode="FINAL")

    def test_final_mode_rejects_unready_policy_evaluation(self):
        from reporting.engine import ReportReleaseError, render_document

        data = {
            "case_id": "CASE-001",
            "ruleset": {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026"},
            "publication_gate": {"passed": True, "consent_verified": True, "qc_verified": True, "evidence_verified": True, "placeholders_resolved": True},
            "policy_evaluation": {"ready_for_requested_operation": False, "planes": {}, "gates": []},
        }
        with self.assertRaises(ReportReleaseError):
            render_document("01", data, mode="FINAL")

    def test_final_mode_requires_final_audit_pass(self):
        from reporting.engine import ReportReleaseError, render_document

        policy = passing_policy_evaluation()
        policy["gates"] = [{"gate": "FINAL_AUDIT_GATE", "state": "FAIL", "blocking": True}]
        data = {
            "case_id": "CASE-001",
            "ruleset": {"status": "VIGENTE", "version": "v3.4", "effective_date": "17/08/2026"},
            "publication_gate": {"passed": True, "consent_verified": True, "qc_verified": True, "evidence_verified": True, "placeholders_resolved": True},
            "policy_evaluation": policy,
        }
        with self.assertRaises(ReportReleaseError):
            render_document("01", data, mode="FINAL")

    def test_final_mode_writes_json_markdown_and_html_when_gate_passes(self):
        from reporting.engine import render_document, write_bundle
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-001",
            report_id="01",
            summary="Nenhum achado fictício é inserido pelo motor.",
            basis="fixture de motor",
        )
        rendered = render_document("01", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="case-001-genoma-clinico")
            self.assertEqual(set(paths), {"json", "markdown", "html", "checksums"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertNotIn("[[", paths["markdown"].read_text(encoding="utf-8"))
            self.assertIn("POST-DEPLOYMENT: PENDENTE", paths["markdown"].read_text(encoding="utf-8"))

    def test_the_checksum_sidecar_covers_every_file_written_including_the_json(self):
        """`artifact_sha256` covered the markdown and the HTML and stopped there.

        Not the JSON written on the next line, and not the PDF a separate renderer produces
        from the same payload. A manifest that omits the artifacts actually delivered cannot
        be used to verify a delivery, which is the only thing it is for.
        """
        import hashlib
        import tempfile
        from pathlib import Path

        from reporting.engine import render_document, write_bundle
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-002", report_id="01", summary="fixture", basis="fixture"
        )
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(render_document("01", data, mode="FINAL"), Path(td), stem="c2")
            recorded = {}
            for line in paths["checksums"].read_text(encoding="utf-8").splitlines():
                digest, _, name = line.partition("  ")
                recorded[name] = digest

            self.assertEqual(set(recorded), {"c2.json", "c2.md", "c2.html"})
            for key in ("json", "markdown", "html"):
                with self.subTest(artifact=key):
                    self.assertEqual(
                        recorded[paths[key].name],
                        hashlib.sha256(paths[key].read_bytes()).hexdigest(),
                        "the sidecar must describe the bytes on disk, not the strings in memory",
                    )

    def test_the_sidecar_accepts_an_artifact_added_by_a_later_renderer(self):
        # The PDF is produced by a different entry point, so one manifest can only cover
        # both if the second writer can extend it rather than replace it.
        import tempfile
        from pathlib import Path

        from reporting.engine import render_document, write_bundle, write_checksums
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-003", report_id="01", summary="fixture", basis="fixture"
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = write_bundle(render_document("01", data, mode="FINAL"), root, stem="c3")
            later = root / "GENOMA-01.pdf"
            later.write_bytes(b"%PDF-1.4 fixture")
            write_checksums(root, "c3", [later])
            names = {
                line.partition("  ")[2]
                for line in paths["checksums"].read_text(encoding="utf-8").splitlines()
                if line
            }
        self.assertEqual(names, {"c3.json", "c3.md", "c3.html", "GENOMA-01.pdf"})

    def test_final_report_records_the_governing_ruleset_in_its_execution_manifest(self):
        """A published report must be auditable without CI logs (prompt-fonte 2.4)."""
        import sys
        from pathlib import Path as _Path

        sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
        import normative
        from reporting.engine import render_document
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-001", report_id="01", summary="fixture", basis="fixture de motor"
        )
        original_manifest = dict(data["execution_manifest"])
        rendered = render_document("01", data, mode="FINAL")
        manifest = rendered["data"]["execution_manifest"]
        self.assertEqual(manifest["RULESET"], "VERIFICADO")
        self.assertEqual(manifest["VERSÃO"], normative.VERSION)
        self.assertEqual(manifest["VIGÊNCIA"], normative.EFFECTIVE_DATE)
        self.assertEqual(manifest["RULESET_SHA256"], normative.RAW_SHA256)
        self.assertIn(normative.VERSION, rendered["markdown"])
        # The caller's payload must not be mutated by rendering.
        self.assertEqual(data["execution_manifest"], original_manifest)


if __name__ == "__main__":
    unittest.main()
