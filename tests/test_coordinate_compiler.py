"""A placeholder must never swallow template body text.

PDF extraction splits a placeholder across spans wherever the typesetter broke it, and the
compiler joins spans with a newline. When a closing bracket pair landed on that split
(`...ANCESTRALIDADE]` + newline + `]`), the non-greedy `\\[\\[.*?\\]\\]` failed to close and
ran on to the NEXT token's `]]`, producing one enormous bogus placeholder covering most of
a page.

Two consequences made this worse than a cosmetic bug:

  * the swallowed tokens disappeared from the inventory, so those fields would never be
    filled — 18 placeholders across 6 reports were hidden this way;
  * the bogus rectangle became a MASK, and the static pixel QA excludes masked regions by
    construction, so the QA could never have detected the damage.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz

from scripts.build_report_coordinate_pack import TOKEN_RE, _tokens


class TokenPatternTest(unittest.TestCase):
    def test_plain_placeholder_matches(self):
        self.assertEqual(TOKEN_RE.findall("[[CASE_ID]]"), ["[[CASE_ID]]"])

    def test_placeholder_split_mid_name_still_closes_at_its_own_brackets(self):
        """The historical failure: the closing pair straddles a span boundary."""
        text = "[[CALIBRACAO_A\nNCESTRALIDADE]\n]\nCampos em azul\n[[INDICACAO]]"
        matches = TOKEN_RE.findall(text)
        self.assertEqual(len(matches), 2, f"expected two tokens, got {matches}")
        normalized = [re.sub(r"\s+", "", m) for m in matches]
        self.assertEqual(normalized, ["[[CALIBRACAO_ANCESTRALIDADE]]", "[[INDICACAO]]"])
        self.assertNotIn("Campos", "".join(normalized))

    def test_opening_pair_split_also_closes_correctly(self):
        text = "[\n[CASE_ID]]"
        self.assertEqual([re.sub(r"\s+", "", m) for m in TOKEN_RE.findall(text)], ["[[CASE_ID]]"])

    def test_two_adjacent_tokens_do_not_merge(self):
        text = "[[A]]\n[[B]]"
        self.assertEqual([re.sub(r"\s+", "", m) for m in TOKEN_RE.findall(text)], ["[[A]]", "[[B]]"])


class TokenExtractionGuardTest(unittest.TestCase):
    def _page(self, text: str) -> fitz.Page:
        doc = fitz.open()
        page = doc.new_page(width=400, height=200)
        page.insert_text((20, 40), text, fontsize=9)
        self._doc = doc  # keep alive for the caller
        return page

    def test_a_swallowing_match_raises_instead_of_producing_a_giant_mask(self):
        """Fail loudly: an oversized mask is invisible to the pixel QA."""
        page = self._page("[[OUTER [[INNER]] STILL]]")
        with self.assertRaises(ValueError) as ctx:
            _tokens(page)
        self.assertIn("swallowed template text", str(ctx.exception))

    def test_well_formed_tokens_extract_without_raising(self):
        page = self._page("[[CASE_ID]] e [[DATA]]")
        tokens = [t[0] for t in _tokens(page)]
        self.assertEqual(sorted(tokens), ["[[CASE_ID]]", "[[DATA]]"])


class PinnedInventoryTest(unittest.TestCase):
    """The pinned counts were themselves a symptom; they must reflect the repaired compiler."""

    def test_reference_manifest_carries_the_repaired_placeholder_counts(self):
        import json

        index = json.loads((ROOT / "reporting/reference_v3_manifest.json").read_text(encoding="utf-8"))
        counts = {rid: meta["placeholder_count"] for rid, meta in index["reports"].items()}
        self.assertEqual(sum(counts.values()), 1149)
        # The six reports whose tokens were being swallowed.
        self.assertEqual(counts["01"], 130)
        self.assertEqual(counts["02"], 117)
        self.assertEqual(counts["04"], 113)
        self.assertEqual(counts["05"], 201)
        self.assertEqual(counts["06"], 92)
        self.assertEqual(counts["07"], 91)
        self.assertEqual(counts["09"], 84)


if __name__ == "__main__":
    unittest.main()
