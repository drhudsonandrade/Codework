"""A byte-level template change must become a new suite, not a repin under the old label.

`template_store/<suite>/README.md` states the contract: a report may not change its
filename, SHA-256, size or page count under a given suite, and any byte-level change
requires a new suite version and a new immutable manifest.

The sealer could not honour it. `STORE` was hardcoded to `v3.0`, so the only route for a
changed template was `--amend`, which repinned the hash *in place* — the one thing the
contract forbids. And it had already happened: report 11 was repinned under v3.0 on
2026-08-20, after which two different byte-sets both called themselves "GENOMA v3.0" with
nothing to tell them apart.

The pack in use is now sealed as v3.1, carrying that amendment as its lineage, and the
sealer refuses a repin under a suite that is already sealed.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.seal_template_store import (
    TemplateSealError,
    suite_paths,
    verify_against_pinned_identity,
)

STORE_ROOT = ROOT / "template_store"


def _materialized(suite: str) -> dict[str, bytes]:
    """The 11 templates of a sealed suite, as bytes."""
    from scripts.verify_template_store import verify

    with tempfile.TemporaryDirectory() as td:
        target = Path(td)
        verify(materialize=target, suite=suite)
        return {p.name: p.read_bytes() for p in sorted(target.glob("*.pdf"))}


class SuiteNameIsBoundedTest(unittest.TestCase):
    def test_a_suite_label_cannot_escape_the_store(self):
        for bad in ("../etc", "v3", "v3.0/../..", "", "latest"):
            with self.subTest(suite=bad), self.assertRaises(TemplateSealError):
                suite_paths(bad)

    def test_a_well_formed_label_resolves_inside_the_store(self):
        store, manifest, parts = suite_paths("v3.1")
        self.assertEqual(store, STORE_ROOT / "v3.1")
        self.assertEqual(manifest, STORE_ROOT / "v3.1" / "MANIFEST.json")
        self.assertTrue(str(parts).startswith(str(STORE_ROOT)))


class RepinUnderASealedSuiteIsRefusedTest(unittest.TestCase):
    """The defect that produced two byte-sets under one label."""

    def _changed_pack(self, suite: str) -> dict[str, bytes]:
        members = _materialized(suite)
        name = sorted(members)[-1]
        members[name] = members[name] + b"\n% alterado para o teste\n"
        return members

    def test_a_changed_template_cannot_be_repinned_in_place(self):
        with self.assertRaises(TemplateSealError) as caught:
            verify_against_pinned_identity(self._changed_pack("v3.1"), suite="v3.1")
        message = str(caught.exception)
        self.assertIn("requires a new suite version", message)
        self.assertIn("--from-suite v3.1", message)

    def test_an_unchanged_pack_still_verifies(self):
        """The refusal must be about the change, not about strictness in general."""
        manifest = verify_against_pinned_identity(_materialized("v3.1"), suite="v3.1")
        self.assertEqual(manifest["version"], "v3.1")

    def test_a_new_suite_must_name_what_it_descends_from(self):
        with self.assertRaises(TemplateSealError) as caught:
            verify_against_pinned_identity(_materialized("v3.1"), suite="v9.9")
        self.assertIn("--from-suite", str(caught.exception))

    def test_a_new_suite_must_be_explained(self):
        with self.assertRaises(TemplateSealError) as caught:
            verify_against_pinned_identity(
                _materialized("v3.1"), suite="v9.9", from_suite="v3.1", reason="  "
            )
        self.assertIn("--reason", str(caught.exception))

    def test_a_new_suite_records_the_reports_that_changed(self):
        changed = self._changed_pack("v3.1")
        altered = next(
            rid for rid, meta in json.loads(
                (STORE_ROOT / "v3.1" / "MANIFEST.json").read_text(encoding="utf-8")
            )["reports"].items()
            if meta["filename"] == sorted(changed)[-1]
        )
        manifest = verify_against_pinned_identity(
            changed, suite="v9.9", from_suite="v3.1", reason="teste de linhagem"
        )
        self.assertEqual(manifest["version"], "v9.9")
        self.assertEqual(manifest["lineage"]["descends_from"], "v3.1")
        self.assertIn(altered, manifest["lineage"]["reports_changed"])
        self.assertEqual(manifest["lineage"]["reason"], "teste de linhagem")

    def test_sealing_a_new_suite_leaves_the_base_manifest_untouched(self):
        before = (STORE_ROOT / "v3.1" / "MANIFEST.json").read_bytes()
        verify_against_pinned_identity(
            self._changed_pack("v3.1"), suite="v9.9", from_suite="v3.1", reason="teste"
        )
        self.assertEqual((STORE_ROOT / "v3.1" / "MANIFEST.json").read_bytes(), before)

    def test_the_renderer_reference_is_not_repointed_by_sealing(self):
        """Moving the renderer to another suite is a separate, deliberate act."""
        reference = ROOT / "reporting" / "reference_v3_manifest.json"
        before = reference.read_bytes()
        verify_against_pinned_identity(
            self._changed_pack("v3.1"), suite="v9.9", from_suite="v3.1", reason="teste"
        )
        self.assertEqual(reference.read_bytes(), before)


class TheStoreRecordsWhatActuallyHappenedTest(unittest.TestCase):
    def setUp(self):
        self.v30 = json.loads((STORE_ROOT / "v3.0" / "MANIFEST.json").read_text(encoding="utf-8"))
        self.v31 = json.loads((STORE_ROOT / "v3.1" / "MANIFEST.json").read_text(encoding="utf-8"))

    def test_v31_carries_the_amendment_as_its_lineage(self):
        lineage = self.v31["lineage"]
        self.assertEqual(lineage["descends_from"], "v3.0")
        inherited = lineage["inherited_amendments"]
        self.assertTrue(inherited)
        self.assertEqual({e["report"] for e in inherited}, set(lineage["differs_from_base_original"]))

    def test_v31_does_not_keep_a_bare_amendments_list(self):
        """An amendment under a suite is exactly what may no longer exist."""
        self.assertNotIn("amendments", self.v31)

    def test_v30_names_its_successor(self):
        self.assertEqual(self.v30["superseded_by"]["suite"], "v3.1")

    def test_the_v30_readme_records_the_broken_promise_beside_the_promise(self):
        readme = (STORE_ROOT / "v3.0" / "README.md").read_text(encoding="utf-8")
        self.assertIn("Esta regra foi quebrada uma vez", readme)
        self.assertIn("template_store/v3.1/", readme)

    def test_both_suites_verify_independently(self):
        from scripts.verify_template_store import verify

        for suite in ("v3.0", "v3.1"):
            with self.subTest(suite=suite):
                result = verify(suite=suite)
                self.assertEqual(result["operational_status"], "VERIFICADO")
                self.assertEqual(result["reports"], 11)


def tearDownModule() -> None:
    """The tests seal a throwaway suite; it must not survive the run."""
    shutil.rmtree(STORE_ROOT / "v9.9", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
