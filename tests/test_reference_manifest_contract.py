"""The editorial reference manifest is an active, portable, single-axis artifact.

It pins the v3.0 report template suite and nothing else. Two failure modes are pinned
here: silently drifting into a stale historical copy, and leaking machine-local paths
or a second normative identity into a file that must only describe templates.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.template_v3 import TemplateV3Error, load_reference_manifest
from scripts import install_report_templates, verify_template_store
from scripts.build_report_coordinate_pack import compile_pack
from scripts.sealed_ruleset import EXPECTED_DATE, EXPECTED_SHA, EXPECTED_VERSION

MANIFEST_PATH = ROOT / "reporting" / "reference_v3_manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
# Detect POSIX absolute paths from the beginning of a token and Windows drive paths.
# Deliberately exclude ':' as a POSIX prefix so URLs such as https://... are not paths.
ABSOLUTE_PATH = re.compile(r'(?:^|["\s=])(?:/(?!/)[^\s"]+|[A-Za-z]:\\)')


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


class ReferenceManifestLifecycleTest(unittest.TestCase):
    def test_manifest_declares_itself_active(self):
        self.assertEqual(MANIFEST["lifecycle"], "ACTIVE")

    def test_template_loader_reads_and_rejects_a_divergent_runtime_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            divergent = Path(td) / "reference.json"
            divergent.write_text('{"schema": "wrong", "reports": {}}\n', encoding="utf-8")
            with self.assertRaises(TemplateV3Error):
                load_reference_manifest(divergent)

    def test_template_loader_fails_when_runtime_manifest_is_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(FileNotFoundError):
                load_reference_manifest(Path(td) / "missing-reference.json")

    def test_template_store_verifier_reads_the_reference_manifest_at_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            divergent = Path(td) / "reference.json"
            divergent.write_text('{"reports": {}}\n', encoding="utf-8")
            with mock.patch.object(verify_template_store, "REFERENCE", divergent):
                with self.assertRaisesRegex(ValueError, "reference manifest report IDs differ"):
                    verify_template_store.verify(allow_sealed_only=True)

    def test_coordinate_compiler_reads_the_supplied_reference_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(FileNotFoundError):
                compile_pack(root / "templates", root / "missing-reference.json")

    def test_template_installer_calls_the_runtime_reference_loader(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing = root / "missing-reference.json"

            def missing_loader():
                return load_reference_manifest(missing)

            with mock.patch.object(install_report_templates, "load_reference_manifest", side_effect=missing_loader) as loader:
                with self.assertRaises(FileNotFoundError):
                    install_report_templates.install(root / "source", root / "target")
            loader.assert_called_once_with()


class AbsolutePathDetectorTest(unittest.TestCase):
    """The detector itself is pinned; a pattern that matches nothing proves nothing."""

    NON_PORTABLE = (
        r"C:\Users\dev\file.pdf",
        r"d:\Volumes\build\out.pdf",
        '"C:\\Users\\dev\\file.pdf"',
        "/Users/dev/file.pdf",
        "/home/dev/file.pdf",
        "/Volumes/External/file.pdf",
        "/opt/homebrew/bin/pdftocairo",
        "/tmp/template.pdf",
        "/var/tmp/template.pdf",
        "/usr/local/bin/tool",
        'source = "/home/dev/file.pdf"',
    )
    PORTABLE = (
        "template_store/v3.0/MANIFEST.json",
        "reporting/reference_v3_manifest.json",
        "scripts/build_report_coordinate_pack.py",
        "GENOMA v3.0",
        "https://example.invalid/reference.json",
    )

    def test_machine_local_paths_are_detected(self):
        for value in self.NON_PORTABLE:
            with self.subTest(value=value):
                self.assertIsNotNone(ABSOLUTE_PATH.search(value))

    def test_repository_relative_paths_and_urls_are_not_flagged(self):
        for value in self.PORTABLE:
            with self.subTest(value=value):
                self.assertIsNone(ABSOLUTE_PATH.search(value))


class ReferenceManifestPortabilityTest(unittest.TestCase):
    def test_manifest_contains_no_absolute_or_machine_local_paths(self):
        offenders = [s for s in _strings(MANIFEST) if ABSOLUTE_PATH.search(s)]
        self.assertEqual(offenders, [], f"non-portable paths in {MANIFEST_PATH.name}: {offenders}")

    def test_declared_repository_paths_exist(self):
        self.assertTrue((ROOT / MANIFEST["template_store_manifest"]).is_file())
        self.assertTrue((ROOT / MANIFEST["coordinate_compiler"]["script"]).is_file())


class ReferenceManifestIdentityAxisTest(unittest.TestCase):
    """Template suite version and normative ruleset version are separate axes."""

    def test_manifest_pins_the_template_suite_axis(self):
        self.assertEqual(MANIFEST["reference_suite"], "GENOMA v3.0")
        self.assertEqual(MANIFEST["identity_axes"]["template_suite"], MANIFEST["reference_suite"])

    def test_suite_version_matches_the_template_store_it_points_at(self):
        store_relative = MANIFEST["template_store_manifest"]
        suite_version = MANIFEST["reference_suite"].split()[-1]
        self.assertIn(f"template_store/{suite_version}/", store_relative)
        self.assertTrue((ROOT / store_relative).is_file())
        for report in MANIFEST["reports"].values():
            self.assertIn(f"_{suite_version}.pdf", report["filename"])

    def test_manifest_never_declares_a_normative_ruleset_identity(self):
        blob = json.dumps(MANIFEST, ensure_ascii=False)
        self.assertNotIn(EXPECTED_SHA, blob)
        self.assertNotIn(EXPECTED_DATE, blob)
        for forbidden in ("ruleset_version", "renderer_version", "suite_version", "source_root", "output_root"):
            self.assertNotIn(forbidden, MANIFEST, f"{forbidden} does not belong in the template manifest")

    def test_ruleset_identity_lives_only_in_the_sealed_manifest(self):
        sealed = json.loads((ROOT / "normative" / "sealed" / "MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(sealed["version"], EXPECTED_VERSION)
        self.assertEqual(sealed["raw_sha256"], EXPECTED_SHA)
        # The suite version must not be mistaken for the ruleset version.
        self.assertNotEqual(MANIFEST["reference_suite"].split()[-1], EXPECTED_VERSION)


class ReferenceManifestReportSetTest(unittest.TestCase):
    def test_all_eleven_reports_are_pinned_with_complete_identity(self):
        self.assertEqual(set(MANIFEST["reports"]), {f"{i:02d}" for i in range(1, 12)})
        for report_id, meta in MANIFEST["reports"].items():
            for field in ("filename", "sha256", "size_bytes", "page_count"):
                self.assertIn(field, meta, report_id)
            self.assertRegex(meta["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(meta["size_bytes"], 0)
            self.assertGreater(meta["page_count"], 0)


if __name__ == "__main__":
    unittest.main()
