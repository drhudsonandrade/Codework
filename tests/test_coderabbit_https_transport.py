from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CodeRabbitHttpsTransportTests(unittest.TestCase):
    def test_release_download_restricts_initial_and_redirect_protocols_to_https(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        self.assertIn("--proto '=https'", script)
        self.assertIn("--proto-redir '=https'", script)
        self.assertIn("--tlsv1.2", script)
        self.assertLess(script.index("--proto '=https'"), script.index('observed_archive_sha="$(sha256_file "$archive")"'))


if __name__ == "__main__":
    unittest.main()
