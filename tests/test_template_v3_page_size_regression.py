from __future__ import annotations

import unittest

from reporting.template_v3 import TemplateV3Error, _validate_page_size_pt


class TemplateV3PageSizeRegressionTests(unittest.TestCase):
    def test_nonfinite_and_overflowing_dimensions_fail_closed(self) -> None:
        # 1e309 is already inf at parse time, so it is kept only as an explicit
        # record of the literal form; 10**400 is the distinct int-overflow case.
        invalid_values = (float("nan"), float("inf"), float("-inf"), 1e309, 10**400)
        for invalid in invalid_values:
            with self.subTest(value=repr(invalid)):
                with self.assertRaises(TemplateV3Error):
                    _validate_page_size_pt("01", {"page_size_pt": [invalid, 841.889771]})

    def test_zero_and_negative_dimensions_fail_closed(self) -> None:
        """The implementation rejects ``number <= 0``; nothing pinned that boundary."""
        for invalid in (0, 0.0, -0.0, -1.0, -595.303955):
            with self.subTest(value=repr(invalid)):
                with self.assertRaises(TemplateV3Error):
                    _validate_page_size_pt("01", {"page_size_pt": [invalid, 841.889771]})
                with self.assertRaises(TemplateV3Error):
                    _validate_page_size_pt("01", {"page_size_pt": [595.303955, invalid]})

    def test_positive_finite_dimensions_remain_valid(self) -> None:
        _validate_page_size_pt("01", {"page_size_pt": [595.303955, 841.889771]})


if __name__ == "__main__":
    unittest.main()
