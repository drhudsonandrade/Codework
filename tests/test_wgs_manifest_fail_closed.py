import errno
import tempfile
import unittest
import unittest.mock
from pathlib import Path


class WgsManifestFailClosedTest(unittest.TestCase):
    """Sample-supplied manifest failures must produce a gate verdict, not a traceback."""

    def _assert_non_available_manifest(self, text: str, expected_error: str) -> None:
        from scripts.wgs_input_gate import validate_manifest

        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "sample-manifest.json"
            manifest.write_text(text, encoding="utf-8")

            result = validate_manifest(manifest)

            self.assertEqual(result["schema"], "genoma-wgs-input-gate-v1")
            self.assertEqual(result["status"], "NÃO DISPONÍVEL")
            self.assertEqual(result["inputs"], {})
            self.assertEqual(result["errors"], [expected_error])

    def test_malformed_json_is_a_non_available_verdict(self):
        self._assert_non_available_manifest(
            '{"sample_id": "S1", "input_type": ',
            "sample-manifest.json contains invalid JSON",
        )

    def test_json_root_must_be_an_object(self):
        for text in ("[]", '"text"', "null", "42"):
            with self.subTest(text=text):
                self._assert_non_available_manifest(
                    text,
                    "sample-manifest.json JSON root must be an object",
                )

    def test_unreadable_manifest_is_distinct_from_invalid_json(self):
        from scripts.wgs_input_gate import validate_manifest

        with tempfile.TemporaryDirectory() as td:
            manifest = Path(td) / "sample-manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with unittest.mock.patch.object(
                Path,
                "read_text",
                side_effect=OSError(errno.EACCES, "permission denied"),
            ):
                result = validate_manifest(manifest)

        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["inputs"], {})
        self.assertEqual(
            result["errors"],
            ["sample-manifest.json could not be read: PermissionError"],
        )


if __name__ == "__main__":
    unittest.main()
