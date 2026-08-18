"""The normative identity must have exactly one meaning across the repository.

`policy_engine/` is a standalone installable package and cannot import the repository
root, so it restates the canonical constants. That duplication is the exact mechanism
that let the repository keep attesting to a superseded ruleset, so it is pinned here:
if the two copies ever disagree, this fails closed.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative


class NormativeIdentityTest(unittest.TestCase):
    def test_policy_engine_constants_match_shared_identity(self):
        sys.path.insert(0, str(ROOT / "policy_engine"))
        try:
            from genoma_policy import ruleset as pe_ruleset
            from genoma_policy import paths as pe_paths
        finally:
            sys.path.remove(str(ROOT / "policy_engine"))

        self.assertEqual(pe_ruleset.EXPECTED_STATUS, normative.STATUS)
        self.assertEqual(pe_ruleset.EXPECTED_VERSION, normative.VERSION)
        self.assertEqual(pe_ruleset.EXPECTED_DATE, normative.EFFECTIVE_DATE)
        self.assertEqual(pe_ruleset.EXPECTED_CANONICAL, normative.CANONICAL_FILENAME)
        self.assertEqual(pe_ruleset.EXPECTED_SECTIONS, normative.SECTION_COUNT)
        self.assertEqual(pe_ruleset.EXPECTED_LAST_SECTION, normative.LAST_SECTION)
        self.assertEqual(pe_paths.CANONICAL_RULESET_NAME, normative.CANONICAL_FILENAME)
        self.assertEqual(
            pe_paths.CANONICAL_MANIFEST_RELATIVE.as_posix(), normative.SHA_MANIFEST_RELATIVE
        )

    def test_sealed_manifest_declares_the_shared_identity(self):
        manifest = json.loads((ROOT / "normative/sealed/MANIFEST.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], normative.STATUS)
        self.assertEqual(manifest["version"], normative.VERSION)
        self.assertEqual(manifest["effective_date"], normative.EFFECTIVE_DATE)
        self.assertEqual(manifest["canonical_filename"], normative.CANONICAL_FILENAME)
        self.assertEqual(manifest["normative_identifier"], normative.NORMATIVE_IDENTIFIER)
        self.assertEqual(manifest["raw_sha256"], normative.RAW_SHA256)
        self.assertEqual(manifest["raw_size_bytes"], normative.RAW_SIZE_BYTES)
        self.assertEqual(manifest["section_count"], normative.SECTION_COUNT)
        self.assertIs(manifest["active_at_rest"], False)

    def test_external_sha_manifest_matches_shared_identity(self):
        fields = (ROOT / normative.SHA_MANIFEST_RELATIVE).read_text(encoding="ascii").split()
        self.assertEqual(fields, [normative.RAW_SHA256, normative.CANONICAL_FILENAME])

    def test_superseded_version_is_archived_not_active(self):
        superseded = normative.SUPERSEDED
        self.assertEqual(superseded["status"], "OBSOLETA")
        self.assertNotEqual(superseded["version"], normative.VERSION)
        self.assertNotEqual(superseded["raw_sha256"], normative.RAW_SHA256)
        archived = ROOT / superseded["archived_manifest"]
        self.assertTrue(archived.is_file(), "superseded manifest must survive as provenance")
        self.assertIn(superseded["raw_sha256"], archived.read_text(encoding="utf-8"))
        # REGRA DE UNICIDADE: only the current manifest may sit in the active directory.
        active = sorted(p.name for p in (ROOT / "manifests").glob("RULESET_V*.sha256"))
        self.assertEqual(active, [Path(normative.SHA_MANIFEST_RELATIVE).name])

    def test_rule_ids_are_bound_to_the_current_version(self):
        self.assertEqual(normative.rule_id(0), "GENOMA-V3.4-S000")
        self.assertEqual(normative.rule_id(normative.LAST_SECTION), "GENOMA-V3.4-S262")
        with self.assertRaises(ValueError):
            normative.rule_id(normative.SECTION_COUNT)

    def test_attested_block_is_verified_against_the_sealed_transport(self):
        block = normative.attested_ruleset_block()
        self.assertEqual(block["attestation"], "VERIFICADO")
        self.assertEqual(block["status"], normative.STATUS)
        self.assertEqual(block["sha256"], normative.RAW_SHA256)
        self.assertEqual(block["section_count"], normative.SECTION_COUNT)

    def test_attested_block_degrades_instead_of_claiming_compliance(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            block = normative.attested_ruleset_block(sealed_dir=td)
        # An unverifiable source must never still print status VIGENTE.
        self.assertEqual(block["attestation"], "NÃO DISPONÍVEL")
        self.assertEqual(block["status"], "NÃO DISPONÍVEL")
        self.assertIn("not verifiable", block["reason"])

    def test_gate_artifacts_share_one_ruleset_block(self):
        from array_pipeline import annotation, qc
        from reporting.engine import EXPECTED_RULESET

        expected = normative.ruleset_block()
        self.assertEqual(qc.RULESET, expected)
        self.assertEqual(annotation.RULESET, expected)
        self.assertEqual(EXPECTED_RULESET, normative.ruleset_block(include_sha256=False))


if __name__ == "__main__":
    unittest.main()
