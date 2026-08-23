from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import bootstrap_attestation


class BootstrapAttestationCliTests(unittest.TestCase):
    def test_write_requires_fresh_verified_at_even_when_prior_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "bootstrap.json"
            output.write_text('{"verified_at":"2026-01-01T00:00:00Z"}', encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                bootstrap_attestation.main(["--write", "--output", str(output)])
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                '{"verified_at":"2026-01-01T00:00:00Z"}',
            )

    def test_explicit_verified_at_recovers_from_corrupt_prior_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "bootstrap.json"
            output.write_text("not-json", encoding="utf-8")
            payload = {
                "attestation_type": "GENOMA_PROJECT_BOOTSTRAP",
                "verified_at": "2026-08-23T22:15:00Z",
            }
            with patch.object(bootstrap_attestation, "build_attestation", return_value=payload):
                rc = bootstrap_attestation.main(
                    [
                        "--write",
                        "--verified-at",
                        payload["verified_at"],
                        "--output",
                        str(output),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)


if __name__ == "__main__":
    unittest.main()
