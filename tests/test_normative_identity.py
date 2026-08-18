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

    def test_exactly_one_active_ruleset_manifest(self):
        """REGRA DE UNICIDADE: only one source may be marked VIGENTE."""
        active = sorted(p.name for p in (ROOT / "manifests").glob("RULESET_V*.sha256"))
        self.assertEqual(active, [Path(normative.SHA_MANIFEST_RELATIVE).name])

    def test_no_superseded_ruleset_identity_survives_in_the_tree(self):
        """The project is governed by one version; stale identities must not linger."""
        import subprocess

        # Include untracked-but-present files: a new file would otherwise slip past this
        # guard until the moment it was staged.
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.split()
        stale = []
        for rel in tracked:
            if rel.startswith("normative/sealed/parts/") or rel == "tests/test_normative_identity.py":
                continue
            path = ROOT / rel
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for token in ("v3.3", "V3.3", "14/08/2026", "2026-08-14"):
                if token not in text:
                    continue
                # The only legitimate survivor is the literal printed inside the sealed v3.0
                # template PDFs: it is the search key used to REPLACE that text with the
                # current identity, so removing it would leave the old string visible.
                if token == "v3.3" and "GENOMA-HUDSON-RULESET-v3.3" in text:
                    residual = text.replace("GENOMA-HUDSON-RULESET-v3.3", "")
                    if token not in residual:
                        continue
                stale.append(f"{rel}:{token}")
        self.assertEqual(stale, [], f"superseded ruleset identity still present: {stale}")

    def test_companion_sources_are_pinned_but_never_normative(self):
        """The prompt-fonte is integrity-pinned; it must not become a second norm."""
        self.assertTrue(normative.COMPANION_SOURCES)
        for name, spec in normative.COMPANION_SOURCES.items():
            self.assertIs(spec["normative"], False, f"{name} must not be normative")
            self.assertRegex(spec["sha256"], r"^[0-9a-f]{64}$")
            self.assertNotEqual(spec["sha256"], normative.RAW_SHA256)
            self.assertIn("NÃO NORMATIVA", spec["nature"])

    def test_companion_manifest_matches_the_pinned_identities(self):
        text = (ROOT / normative.COMPANION_MANIFEST_RELATIVE).read_text(encoding="utf-8")
        self.assertIn("NÃO NORMATIVAS", text)
        pinned = {
            parts[1]: parts[0]
            for line in text.splitlines()
            if not line.startswith("#") and len(parts := line.split()) == 2
        }
        self.assertEqual(
            pinned, {name: spec["sha256"] for name, spec in normative.COMPANION_SOURCES.items()}
        )

    def test_companion_verification_fails_closed_on_swap_or_unknown(self):
        import tempfile

        name = "PROMPT_FONTE_GERACAO_RELATORIOS_GENOMICOS_v1.2.txt"
        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / name
            good.write_bytes(b"not the real companion")
            swapped = normative.verify_companion(name, good)
            self.assertEqual(swapped["status"], "NÃO DISPONÍVEL")
            self.assertEqual(swapped["reason"], "SHA-256 mismatch")
            self.assertIs(swapped["normative"], False)

            missing = normative.verify_companion(name, Path(td) / "absent.txt")
            self.assertEqual(missing["status"], "NÃO DISPONÍVEL")

            unknown = normative.verify_companion("UNREGISTERED.txt", good)
            self.assertEqual(unknown["status"], "NÃO DISPONÍVEL")
            self.assertIs(unknown["normative"], False)

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
