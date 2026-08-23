import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_SHA = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
SUPERSEDED_FIXTURE = next((ROOT / "docs" / "history").glob("*/superseded-identities.json"))
SUPERSEDED = json.loads(SUPERSEDED_FIXTURE.read_text(encoding="utf-8"))


class SealedRulesetContractTest(unittest.TestCase):
    def test_chunked_transport_is_single_source_of_truth(self):
        from scripts.sealed_ruleset import load_manifest, verify_transport

        manifest = load_manifest(ROOT / "normative" / "sealed")
        self.assertEqual(manifest["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(manifest["status"], EXPECTED_STATUS)
        self.assertEqual(manifest["version"], EXPECTED_VERSION)
        self.assertEqual(manifest["effective_date"], EXPECTED_DATE)
        self.assertEqual(manifest["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(len(manifest["transport_parts"]), 13)

        sealed_root = ROOT / "normative" / "sealed"
        legacy_monolith = sealed_root / f"GENOMA_RULESET_{SUPERSEDED['version']}.txt.gz.b64"
        current_monolith = sealed_root / f"GENOMA_RULESET_{EXPECTED_VERSION}.txt.gz.b64"
        self.assertFalse(legacy_monolith.exists())
        self.assertFalse(current_monolith.exists())

        evidence = verify_transport(sealed_root)
        self.assertEqual(evidence["canonical_filename"], EXPECTED_NAME)
        self.assertEqual(evidence["status"], EXPECTED_STATUS)
        self.assertEqual(evidence["version"], EXPECTED_VERSION)
        self.assertEqual(evidence["effective_date"], EXPECTED_DATE)
        self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
        self.assertEqual(evidence["section_count"], 263)
        self.assertEqual(evidence["section_range"], [0, 262])

    def test_materialization_is_byte_exact_and_read_only(self):
        from scripts.sealed_ruleset import materialize

        with tempfile.TemporaryDirectory() as td:
            target, evidence = materialize(ROOT / "normative" / "sealed", Path(td))
            self.assertEqual(evidence["raw_sha256"], EXPECTED_SHA)
            self.assertEqual(hashlib.sha256(Path(target).read_bytes()).hexdigest(), EXPECTED_SHA)
            self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o444)
            self.assertFalse(
                os.access(target, os.W_OK)
                and (stat.S_IMODE(os.stat(target).st_mode) & 0o222)
            )


class MaterializerIdempotencyTest(unittest.TestCase):
    """Re-running the canonical materialization is safe; anything else still blocks."""

    SEALED = ROOT / "normative" / "sealed"

    def test_second_run_on_the_canonical_artifact_is_a_verified_no_op(self):
        from scripts.sealed_ruleset import materialize

        with tempfile.TemporaryDirectory() as td:
            first, first_evidence = materialize(self.SEALED, Path(td))
            self.assertFalse(first_evidence["idempotent_reuse"])
            first_stat = os.stat(first)

            second, second_evidence = materialize(self.SEALED, Path(td))
            self.assertEqual(second, first)
            self.assertTrue(second_evidence["idempotent_reuse"])
            self.assertEqual(second_evidence["raw_sha256"], EXPECTED_SHA)
            self.assertEqual(hashlib.sha256(Path(second).read_bytes()).hexdigest(), EXPECTED_SHA)
            self.assertEqual(stat.S_IMODE(os.stat(second).st_mode), 0o444)
            # The verified artifact is reused, never rewritten.
            self.assertEqual(os.stat(second).st_mtime_ns, first_stat.st_mtime_ns)
            self.assertEqual(os.stat(second).st_ino, first_stat.st_ino)

    def test_a_second_different_vigente_still_blocks(self):
        from scripts.sealed_ruleset import SealedRulesetError, materialize

        with tempfile.TemporaryDirectory() as td:
            materialize(self.SEALED, Path(td))
            intruder = Path(td) / "REGRAS_PROJETO_GENOMA_OUTRO.txt"
            intruder.write_text("STATUS NORMATIVO: VIGENTE\n", encoding="utf-8")
            with self.assertRaises(SealedRulesetError):
                materialize(self.SEALED, Path(td))

    def test_a_vigente_under_a_different_filename_still_blocks(self):
        from scripts.sealed_ruleset import SealedRulesetError, materialize

        with tempfile.TemporaryDirectory() as td:
            rogue = Path(td) / "REGRAS_PROJETO_GENOMA_VIGENTE_v9.9_2030-01-01.txt"
            rogue.write_text("STATUS NORMATIVO: VIGENTE\n", encoding="utf-8")
            with self.assertRaises(SealedRulesetError):
                materialize(self.SEALED, Path(td))

    def test_drifted_bytes_under_the_canonical_name_still_block(self):
        from scripts.sealed_ruleset import SealedRulesetError, materialize

        with tempfile.TemporaryDirectory() as td:
            target, _ = materialize(self.SEALED, Path(td))
            os.chmod(target, 0o644)
            original = Path(target).read_text(encoding="utf-8")
            Path(target).write_text(original + "\ntampered\n", encoding="utf-8")
            os.chmod(target, 0o444)
            with self.assertRaises(SealedRulesetError):
                materialize(self.SEALED, Path(td))

    def test_a_writable_canonical_file_still_blocks(self):
        from scripts.sealed_ruleset import SealedRulesetError, materialize

        with tempfile.TemporaryDirectory() as td:
            target, _ = materialize(self.SEALED, Path(td))
            os.chmod(target, 0o644)
            with self.assertRaises(SealedRulesetError):
                materialize(self.SEALED, Path(td))

    def test_idempotent_reuse_still_verifies_provenance_first(self):
        from scripts.sealed_ruleset import SealedRulesetError, materialize

        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as sealed_td:
            materialize(self.SEALED, Path(td))
            # An unverifiable sealed transport must fail even though the destination
            # already holds the correct canonical artifact.
            with self.assertRaises(SealedRulesetError):
                materialize(Path(sealed_td), Path(td))

    def test_cli_wrapper_is_idempotent_too(self):
        import sys

        from scripts.materialize_ruleset import materialize as cli_materialize

        with tempfile.TemporaryDirectory() as td:
            first, _ = cli_materialize(Path(td))
            second, evidence = cli_materialize(Path(td))
            self.assertEqual(first, second)
            self.assertTrue(evidence["idempotent_reuse"])
            self.assertTrue(sys.executable)


if __name__ == "__main__":
    unittest.main()
