from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_wgs_curated_manifest import _verified_ruleset_identity

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_wgs_curated_manifest.py"
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"


class WgsCuratedManifestEntrypointTests(unittest.TestCase):
    """Nextflow runs this file by path; the test suite runs it as a package module.

    Both entrypoints must import the sealed transport, so neither mode may depend on the
    repository root already being on sys.path.
    """

    def _run(self, argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *argv, "--help"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )

    def test_direct_file_execution_resolves_the_sealed_transport_import(self) -> None:
        # cwd is deliberately outside the repository, exactly as a Nextflow work dir is.
        result = self._run([str(SCRIPT)], Path(SCRIPT.anchor))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_module_execution_still_works(self) -> None:
        result = self._run(["-m", "scripts.build_wgs_curated_manifest"], ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ModuleNotFoundError", result.stderr)


class WgsCuratedManifestRulesetTests(unittest.TestCase):
    def test_verified_ruleset_identity_comes_from_sealed_transport(self) -> None:
        identity = _verified_ruleset_identity()
        self.assertEqual(identity["status"], "VIGENTE")
        self.assertEqual(identity["version"], "v3.4")
        self.assertEqual(identity["effective_date"], "17/08/2026")
        self.assertEqual(identity["sha256"], EXPECTED_SHA)
        self.assertEqual(identity["canonical_filename"], EXPECTED_NAME)

    def test_verified_ruleset_identity_rejects_wrong_canonical_filename_with_valid_sha(self) -> None:
        bad = {
            "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_WRONG.txt",
            "raw_sha256": EXPECTED_SHA,
            "version": "v3.4",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_transport_digest_mismatch(self) -> None:
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": "0" * 64,
            "version": "v3.4",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_wrong_version_with_valid_name_and_sha(self) -> None:
        # Filename and digest are the ones this build expects; only the declared version
        # drifts, so the version comparison has to fail on its own.
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": EXPECTED_SHA,
            "version": "v9.9",
            "effective_date": "17/08/2026",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()

    def test_verified_ruleset_identity_rejects_wrong_effective_date_with_valid_name_and_sha(self) -> None:
        bad = {
            "canonical_filename": EXPECTED_NAME,
            "raw_sha256": EXPECTED_SHA,
            "version": "v3.4",
            "effective_date": "01/01/2030",
        }
        with patch("scripts.build_wgs_curated_manifest.verify_transport", return_value=bad):
            with self.assertRaisesRegex(SystemExit, "RULESET NÃO DISPONÍVEL/CONFLITANTE"):
                _verified_ruleset_identity()


if __name__ == "__main__":
    unittest.main()
