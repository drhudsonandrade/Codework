import base64
import gzip
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from ruleset_test_support import RULESET

ROOT = Path(__file__).resolve().parents[1]


def _minimal_reference_manifest() -> dict:
    reports = {
        f"{index:02d}": {
            "filename": f"{index:02d}.pdf",
            "sha256": "0" * 64,
            "page_count": 1,
            "page_size_pt": [595.303955, 841.889771],
        }
        for index in range(1, 12)
    }
    return {
        "schema": "genoma-editorial-v3-reference-manifest-v1",
        "reports": reports,
    }


class TemplateV3ContractTest(unittest.TestCase):
    def test_manifest_is_complete_for_all_eleven_reference_models(self):
        from reporting.template_v3 import load_reference_manifest

        manifest = load_reference_manifest()
        self.assertEqual(set(manifest["reports"]), {f"{i:02d}" for i in range(1, 12)})
        expected_pages = {
            "01": 10,
            "02": 10,
            "03": 10,
            "04": 10,
            "05": 11,
            "06": 9,
            "07": 9,
            "08": 9,
            "09": 9,
            "10": 1,
            "11": 12,
        }
        self.assertEqual({rid: int(meta["page_count"]) for rid, meta in manifest["reports"].items()}, expected_pages)
        for meta in manifest["reports"].values():
            self.assertRegex(meta["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual(len(meta["page_size_pt"]), 2)
            self.assertTrue(all(float(value) > 0 for value in meta["page_size_pt"]))
        self.assertRegex(manifest["external_coordinate_manifest"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest["external_coordinate_detail"]["sha256"], r"^[0-9a-f]{64}$")

    def test_reference_manifest_rejects_missing_page_size_without_external_pack(self):
        from reporting.template_v3 import TemplateV3Error, load_reference_manifest

        manifest = _minimal_reference_manifest()
        manifest["reports"]["04"].pop("page_size_pt")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reference.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(TemplateV3Error, "page_size_pt"):
                load_reference_manifest(path)

    def test_reference_manifest_rejects_malformed_page_size_without_external_pack(self):
        from reporting.template_v3 import TemplateV3Error, load_reference_manifest

        manifest = _minimal_reference_manifest()
        manifest["reports"]["07"]["page_size_pt"] = [595.303955]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reference.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(TemplateV3Error, "page_size_pt"):
                load_reference_manifest(path)

    def test_missing_or_wrong_template_pack_fails_closed(self):
        from reporting.template_v3 import TemplateV3Error, verify_template_pack

        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TemplateV3Error):
                verify_template_pack(Path(td))

    def test_coordinate_detail_is_bound_to_decoded_manifest_content(self):
        from reporting.template_v3 import TemplateV3Error, verify_coordinate_detail

        manifest = b'{"schema":"fixture"}\n'
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            canonical = base64.b64encode(gzip.compress(manifest, mtime=0)) + b"\n"
            path = root / "detail.json.gz.b64"
            path.write_bytes(canonical)
            meta = {
                "filename": path.name,
                "sha256": hashlib.sha256(canonical).hexdigest(),
            }
            verified = verify_coordinate_detail(path, meta, manifest)
            self.assertEqual(
                verified["content_sha256"], hashlib.sha256(manifest).hexdigest()
            )
            self.assertTrue(verified["container_sha256_matches_pinned"])

            # A different gzip header is acceptable only because the decoded, pinned bytes
            # remain byte-identical; its distinct container identity is still disclosed.
            path.write_bytes(base64.b64encode(gzip.compress(manifest, mtime=1)) + b"\n")
            recompressed = verify_coordinate_detail(path, meta, manifest)
            self.assertEqual(recompressed["content_sha256"], verified["content_sha256"])
            self.assertFalse(recompressed["container_sha256_matches_pinned"])

            multi_member = gzip.compress(manifest, mtime=0) + gzip.compress(
                b"unexpected", mtime=0
            )
            path.write_bytes(base64.b64encode(multi_member) + b"\n")
            with self.assertRaisesRegex(
                TemplateV3Error, "incomplete or multi-member"
            ):
                verify_coordinate_detail(path, meta, manifest)

            path.write_bytes(base64.b64encode(gzip.compress(b"different", mtime=0)) + b"\n")
            with self.assertRaisesRegex(TemplateV3Error, "decoded content mismatch"):
                verify_coordinate_detail(path, meta, manifest)

    def test_noncanonical_template_ruleset_labels_fail_closed(self):
        from reporting.template_v3 import (
            CURRENT_RULESET_TEMPLATE_LABEL,
            CURRENT_RULESET_TEMPLATE_SOURCE,
            TemplateV3Error,
            _system_value_for_source,
        )

        self.assertEqual(CURRENT_RULESET_TEMPLATE_LABEL, "GENOMA-RULESET-v3.4")
        systems = {"OTHER": "value"}
        self.assertEqual(
            _system_value_for_source(CURRENT_RULESET_TEMPLATE_SOURCE, systems),
            CURRENT_RULESET_TEMPLATE_LABEL,
        )
        with self.assertRaises(TemplateV3Error):
            _system_value_for_source("GENOMA-HUDSON-RULESET-v2.8", systems)
        self.assertEqual(_system_value_for_source("OTHER", systems), "value")
        self.assertIsNone(_system_value_for_source("UNKNOWN", systems))

    def test_coordinate_pack_accepts_only_complete_canonical_ruleset_marker(self):
        from scripts.build_report_coordinate_pack import _ruleset_control_sources

        canonical = "GENOMA-HUDSON-RULESET-v3.4"
        self.assertEqual(_ruleset_control_sources(canonical), [canonical])
        malformed = (
            "GENOMA-HUDSON-RULESET-v3.3",
            "GENOMA-HUDSON-RULESET-v3.4-TEST",
            "GENOMA-HUDSON-RULESET-v3.4beta",
            "GENOMA-HUDSON-RULESET-v3.4_alterado",
            "GENOMA-HUDSON-RULESET-v3.4.5",
            "XGENOMA-HUDSON-RULESET-v3.4",
        )
        for marker in malformed:
            with self.subTest(marker=marker):
                with self.assertRaises(RuntimeError):
                    _ruleset_control_sources(marker)

    def test_docx_svg_patch_rejects_zip_slip_member(self):
        from reporting.template_v3 import TemplateV3Error, _patch_docx_svg

        with tempfile.TemporaryDirectory() as td:
            malicious = Path(td) / "malicious.docx"
            with zipfile.ZipFile(malicious, "w") as archive:
                archive.writestr("../escaped.txt", "no")
            with self.assertRaisesRegex(TemplateV3Error, "unsafe DOCX archive member"):
                _patch_docx_svg(malicious, [])

    def test_docx_svg_patch_rejects_duplicate_archive_members(self):
        from reporting.template_v3 import TemplateV3Error, _patch_docx_svg

        with tempfile.TemporaryDirectory() as td:
            duplicated = Path(td) / "duplicated.docx"
            with zipfile.ZipFile(duplicated, "w") as archive:
                archive.writestr("word/document.xml", "<original/>")
                archive.writestr("word/document.xml", "<replacement/>")
            with self.assertRaisesRegex(TemplateV3Error, "duplicate DOCX extraction target"):
                _patch_docx_svg(duplicated, [])

    def test_docx_svg_patch_rejects_members_with_same_normalized_target(self):
        from reporting.template_v3 import TemplateV3Error, _patch_docx_svg

        with tempfile.TemporaryDirectory() as td:
            duplicated = Path(td) / "normalized-duplicate.docx"
            with zipfile.ZipFile(duplicated, "w") as archive:
                archive.writestr("word/document.xml", "<original/>")
                archive.writestr("word/./document.xml", "<replacement/>")
            with self.assertRaisesRegex(TemplateV3Error, "duplicate DOCX extraction target"):
                _patch_docx_svg(duplicated, [])

    def test_poppler_failure_keeps_the_converter_diagnostics(self):
        import subprocess

        from reporting.template_v3 import TemplateV3Error, _run_poppler

        with self.assertRaises(TemplateV3Error) as caught:
            _run_poppler(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.stderr.write('Syntax Error: Couldn\\'t find trailer dictionary\\n'); sys.exit(3)",
                ],
                7,
            )
        message = str(caught.exception)
        self.assertIn("exit code 3", message)
        self.assertIn("template page 7", message)
        self.assertIn("Couldn't find trailer dictionary", message)
        self.assertNotIsInstance(caught.exception, subprocess.CalledProcessError)

    def test_poppler_timeout_fails_closed_with_page_context(self):
        import subprocess
        from unittest.mock import patch

        from reporting.template_v3 import POPPLER_TIMEOUT_SECONDS, TemplateV3Error, _run_poppler

        with patch(
            "reporting.template_v3.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["pdftoppm"], timeout=POPPLER_TIMEOUT_SECONDS),
        ):
            with self.assertRaisesRegex(
                TemplateV3Error,
                rf"pdftoppm timed out on template page 4 after {POPPLER_TIMEOUT_SECONDS}s",
            ):
                _run_poppler(["pdftoppm"], 4)

    def test_single_line_fit_shrinks_for_the_box_height_too(self):
        from reporting.template_v3 import SINGLE_LINE_LEADING, _fit_single_line_size

        wide_box = 10_000.0
        unconstrained = _fit_single_line_size("VALOR", wide_box, 12.0, "Helvetica-Bold")
        self.assertEqual(unconstrained, 12.0)

        constrained = _fit_single_line_size("VALOR", wide_box, 12.0, "Helvetica-Bold", max_height=9.0)
        self.assertLess(constrained, unconstrained)
        self.assertLessEqual(constrained * SINGLE_LINE_LEADING, 9.0)

        roomy = _fit_single_line_size("VALOR", wide_box, 12.0, "Helvetica-Bold", max_height=100.0)
        self.assertEqual(roomy, 12.0)

    @unittest.skipUnless(os.environ.get("GENOMA_REPORT_TEMPLATE_DIR"), "external v3 template pack not mounted")
    def test_external_template_pack_verifies_and_report10_strict_docx_is_editable(self):
        from reporting.editorial_v3 import write_editorial_bundle
        from reporting.engine import render_document
        from reporting.template_v3 import load_reference_manifest, verify_template_pack

        template_dir = Path(os.environ["GENOMA_REPORT_TEMPLATE_DIR"])
        verification = verify_template_pack(template_dir)
        self.assertEqual(verification["verified_reports"], 11)
        detailed = load_reference_manifest(template_dir / "GENOMA_V3_TEMPLATE_MANIFEST.json")
        meta = detailed["reports"]["10"]
        fields = {
            item["field_id"]: "NÃO DISP."
            for item in meta["fields"]
            if not item.get("guidance_only")
        }
        from reporting.provenance import fixture_payload

        data = fixture_payload(
            case_id="CASE-TEMPLATE-10",
            report_id="10",
            summary="fixture",
            basis="fixture de contrato do template v3",
            extra={
                "editorial_mode": "template-v3",
                "template_fields_complete": True,
                "template_fields": fields,
            },
        )
        data["ruleset"] = dict(RULESET)
        data["publication_gate"]["placeholders_resolved"] = True
        rendered = render_document("10", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = write_editorial_bundle(rendered, root, stem="10")
            self.assertTrue(paths["pdf"].is_file())
            self.assertTrue(paths["docx"].is_file())
            with zipfile.ZipFile(paths["docx"]) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
                self.assertIn("GENOMA_FIELD_", xml)
                self.assertIn("svgBlip", xml)


if __name__ == "__main__":
    unittest.main()
