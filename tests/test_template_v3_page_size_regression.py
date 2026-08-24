"""Every rejection branch of `_validate_page_size_pt` is pinned separately.

A page size feeds the renderer's geometry, so each branch has to fail closed on its own:
if one of them is deleted these tests must go red rather than silently keep passing on a
neighbouring branch.
"""
from __future__ import annotations

import unittest

from reporting.template_v3 import TemplateV3Error, _validate_page_size_pt

VALID_HEIGHT = 841.889771


class TemplateV3PageSizeRegressionTests(unittest.TestCase):
    def _assert_rejected(self, page_size: object) -> None:
        with self.assertRaises(TemplateV3Error):
            _validate_page_size_pt("01", {"page_size_pt": page_size})

    def test_missing_or_malformed_container_is_rejected(self) -> None:
        for page_size in (None, "595x841", 595.3, [], [595.303955], [595.303955, VALID_HEIGHT, 3.0]):
            with self.subTest(page_size=repr(page_size)):
                self._assert_rejected(page_size)

    def test_nonfinite_and_overflowing_dimensions_fail_closed(self) -> None:
        for invalid in (float("nan"), float("inf"), float("-inf"), 1e309, 10**400):
            with self.subTest(value=repr(invalid)):
                self._assert_rejected([invalid, VALID_HEIGHT])

    def test_boolean_dimensions_are_rejected(self) -> None:
        # bool is a subclass of int; without the explicit guard True would read as 1pt.
        for invalid in (True, False):
            with self.subTest(value=repr(invalid)):
                self._assert_rejected([invalid, VALID_HEIGHT])
                self._assert_rejected([VALID_HEIGHT, invalid])

    def test_non_numeric_dimensions_are_rejected(self) -> None:
        for invalid in ("595.303955", None, [595.303955], {"pt": 595.303955}):
            with self.subTest(value=repr(invalid)):
                self._assert_rejected([invalid, VALID_HEIGHT])

    def test_non_positive_dimensions_are_rejected(self) -> None:
        for invalid in (0, 0.0, -1, -595.303955):
            with self.subTest(value=repr(invalid)):
                self._assert_rejected([invalid, VALID_HEIGHT])
                self._assert_rejected([VALID_HEIGHT, invalid])

    def test_positive_finite_dimensions_remain_valid(self) -> None:
        _validate_page_size_pt("01", {"page_size_pt": [595.303955, VALID_HEIGHT]})
        _validate_page_size_pt("01", {"page_size_pt": [595, 842]})


if __name__ == "__main__":
    unittest.main()
