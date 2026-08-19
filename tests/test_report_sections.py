"""Every builder's section titles must equal the catalogue's, character for character.

`reporting.engine` prints sections by looking each one up under its catalogue title. A
builder that anchors text under a paraphrase therefore renders an *empty* section while the
anchored content sits unreachable under a key nobody reads — the document silently loses a
page and nothing raises. That has happened twice in this project, and both times it survived
until someone opened the PDF and read it.

This test makes the drift impossible to ship. Builders may keep a literal `SECTIONS` tuple
for readability; they may not disagree with `reporting/catalog.json`.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.catalog import load_catalog, report_ids, section_titles


def _load(module_path: Path):
    spec = importlib.util.spec_from_file_location(f"_builder_{module_path.stem}", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _builders() -> list[tuple[str, Path]]:
    """Every script that declares both a REPORT_ID and a SECTIONS tuple.

    Discovered rather than listed: a hand-kept list would omit the next builder someone adds,
    which is exactly the one most likely to carry a typo.
    """
    found: list[tuple[str, Path]] = []
    for path in sorted((ROOT / "scripts").glob("build_*.py")):
        text = path.read_text(encoding="utf-8")
        if "\nSECTIONS" not in text or "\nREPORT_ID" not in text:
            continue
        found.append((path.stem, path))
    return found


class BuilderSectionTitlesTest(unittest.TestCase):
    def test_builders_were_discovered(self):
        # Negative control for the discovery itself: a test that found nothing to check
        # would pass silently and prove nothing, which is the vacuous pass this project
        # keeps finding elsewhere.
        self.assertGreaterEqual(len(_builders()), 6, _builders())

    def test_every_builder_matches_the_catalogue(self):
        for name, path in _builders():
            with self.subTest(builder=name):
                module = _load(path)
                report_id = getattr(module, "REPORT_ID")
                sections = tuple(getattr(module, "SECTIONS"))
                self.assertEqual(
                    sections,
                    section_titles(report_id),
                    f"{name} declares section titles that differ from reporting/catalog.json "
                    f"for report {report_id}; the engine prints by catalogue title, so the "
                    "mismatched sections would render empty",
                )


class CatalogShapeTest(unittest.TestCase):
    def test_every_report_declares_sections(self):
        for report_id in report_ids():
            with self.subTest(report=report_id):
                self.assertTrue(section_titles(report_id))

    def test_section_titles_are_unique_within_a_report(self):
        # Two sections with the same title collapse into one key in the payload, so the
        # second silently overwrites the first.
        for report_id in report_ids():
            titles = section_titles(report_id)
            with self.subTest(report=report_id):
                self.assertEqual(len(titles), len(set(titles)))

    def test_an_unknown_report_raises_rather_than_returning_empty(self):
        from reporting.catalog import CatalogError

        with self.assertRaises(CatalogError):
            section_titles("99")

    def test_the_catalogue_covers_the_declared_suite(self):
        self.assertEqual(len(load_catalog()), 11)



class AssociationSectionRolesTest(unittest.TestCase):
    """The association reports do not order their sections alike.

    Mapping them by position put report 08's trait matrix under "Sentidos, fisiologia e
    preferências" and its refusal under "Cartões de traços", and nothing errored. The roles
    are now named, and this checks they still name real catalogue sections.
    """

    def test_every_role_names_a_real_middle_section(self):
        module = _load(ROOT / "scripts" / "build_association_report.py")
        for report_id, roles in module.SECTION_ROLES.items():
            with self.subTest(report=report_id):
                middle = section_titles(report_id)[1:-1]
                self.assertEqual(sorted(roles), sorted(middle))

    def test_each_report_maps_exactly_one_section_to_the_association_matrix(self):
        module = _load(ROOT / "scripts" / "build_association_report.py")
        for report_id, roles in module.SECTION_ROLES.items():
            with self.subTest(report=report_id):
                self.assertEqual(
                    sum(1 for role in roles.values() if role == "associations"), 1
                )


if __name__ == "__main__":
    unittest.main()
