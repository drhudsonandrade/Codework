from __future__ import annotations

import unittest

from scripts import bootstrap_attestation


class BootstrapVerifiedAtRfc3339Tests(unittest.TestCase):
    def test_rejects_non_rfc3339_datetime_separators(self) -> None:
        for value in (
            "2026-08-23 20:26:00-03:00",
            "2026-08-23X20:26:00-03:00",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    bootstrap_attestation.BootstrapAttestationError,
                    "strict RFC 3339",
                ):
                    bootstrap_attestation._require_verified_at(value)

    def test_accepts_rfc3339_z_and_offset_forms(self) -> None:
        for value in (
            "2026-08-23T23:26:00Z",
            "2026-08-23T20:26:00-03:00",
            "2026-08-23T20:26:00.123456-03:00",
        ):
            with self.subTest(value=value):
                self.assertEqual(bootstrap_attestation._require_verified_at(value), value)


if __name__ == "__main__":
    unittest.main()
