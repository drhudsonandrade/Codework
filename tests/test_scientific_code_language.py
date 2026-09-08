"""Guard the known stage-three prose debt without translating scientific wire values."""
from __future__ import annotations

import ast
import gzip
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_trait_targets import _open_associations
from scripts.code_language_guard import LanguagePolicy, load_policy, scan_python_file

ROOT = Path(__file__).resolve().parents[1]
SCOPED_PATHS = (
    "scripts/build_trait_targets.py",
    "tests/test_completeness_regressions.py",
    "tests/test_assessed_allele_presence.py",
)
PROSE_TERMS = frozenset({"termo", "rotulo", "controle", "positivo"})
TEST_NAME_TERMS = frozenset({"observado", "nao", "controle", "positivo"})


def _scientific_policy() -> LanguagePolicy:
    """Extend the existing scanner only within this bounded regression suite."""
    policy = load_policy(ROOT)
    return replace(policy, technical_terms=policy.technical_terms | PROSE_TERMS)


class ScientificCodeLanguageTest(unittest.TestCase):
    """Keep migrated prose English and preserve intentional Portuguese payloads."""

    def test_scoped_scientific_prose_has_no_known_untranslated_debt(self):
        """The three migrated sources must not reintroduce the inventoried prose terms."""
        for relative in SCOPED_PATHS:
            with self.subTest(path=relative):
                findings = scan_python_file(ROOT / relative, ROOT, _scientific_policy())
                prose = [item for item in findings if item.kind in {"comment", "docstring"}]
                self.assertEqual(prose, [])

    def test_scientific_test_method_names_use_english(self):
        """Private test names use English without renaming their imported wire constants."""
        for relative in SCOPED_PATHS[1:]:
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            names = [
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
            ]
            with self.subTest(path=relative):
                self.assertTrue(names)
                forbidden = [name for name in names if TEST_NAME_TERMS & set(name.split("_"))]
                self.assertEqual(forbidden, [])

    def test_scoped_scanner_detects_portuguese_prose(self):
        """A positive fixture proves both comments and docstrings are actually scanned."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixture.py"
            path.write_text('"""Controle positivo."""\n# termo e rótulo\n', encoding="utf-8")
            findings = scan_python_file(path, root, _scientific_policy())
        self.assertEqual({item.kind for item in findings}, {"comment", "docstring"})
        self.assertEqual({item.token for item in findings}, PROSE_TERMS)

    def test_localized_runtime_values_remain_permitted(self):
        """Ordinary runtime strings and normative state quotations are not prose debt."""
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "fixture.py"
            path.write_text(
                '# NÃO DISPONÍVEL\nmessage = "Controle positivo: termo e rótulo"\n',
                encoding="utf-8",
            )
            findings = scan_python_file(path, root, _scientific_policy())
        self.assertEqual(findings, ())


class ScientificStreamCompatibilityTest(unittest.TestCase):
    """Keep the association loader's container behavior during type-only maintenance."""

    def test_plain_gzip_and_zip_associations_preserve_text_and_close(self):
        """Every supported container exposes the same text and releases its stream."""
        text = "SNPS\tDISEASE/TRAIT\nrs1\tsynthetic fixture\n"
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "associations.tsv"
            compressed = root / "associations.tsv.gz"
            archive_path = root / "associations.zip"
            plain.write_text(text, encoding="utf-8")
            compressed.write_bytes(gzip.compress(text.encode("utf-8")))
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("associations.tsv", text)
            for path in (plain, compressed, archive_path):
                with self.subTest(container=path.name):
                    with _open_associations(path) as stream:
                        self.assertEqual(stream.read(), text)
                    self.assertTrue(stream.closed)


if __name__ == "__main__":
    unittest.main()
