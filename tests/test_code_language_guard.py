from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.code_language_guard import LanguagePolicyError, load_baseline, load_policy


def _write_json(root: Path, relative: str, payload: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")


class LanguagePolicyLoadingTest(unittest.TestCase):
    def test_policy_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_policy.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language policy schema"):
                load_policy(root)

    def test_baseline_requires_exact_schema(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_json(root, "config/code_language_legacy_baseline.json", {"schema": "wrong"})
            with self.assertRaisesRegex(LanguagePolicyError, "invalid language baseline schema"):
                load_baseline(root)


if __name__ == "__main__":
    unittest.main()
