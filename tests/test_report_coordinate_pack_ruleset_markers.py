from __future__ import annotations

import unittest

from scripts.build_report_coordinate_pack import (
    CANONICAL_RULESET_CONTROL,
    _ruleset_control_sources,
)


class ReportCoordinatePackRulesetMarkerTests(unittest.TestCase):
    def test_canonical_marker_is_accepted(self) -> None:
        self.assertEqual(
            _ruleset_control_sources(f"control={CANONICAL_RULESET_CONTROL}"),
            [CANONICAL_RULESET_CONTROL],
        )

    def test_malformed_marker_is_rejected_even_after_valid_marker(self) -> None:
        text = f"{CANONICAL_RULESET_CONTROL}\nGENOMA-HUDSON-RULESET-v"
        with self.assertRaisesRegex(RuntimeError, "malformed GENOMA ruleset control marker"):
            _ruleset_control_sources(text)

    def test_noncanonical_marker_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "noncanonical GENOMA ruleset control marker"):
            _ruleset_control_sources("GENOMA-HUDSON-RULESET-v3.3")


if __name__ == "__main__":
    unittest.main()
