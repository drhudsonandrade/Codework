from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "codex" / "setup-coderabbit.sh"
# Flags that would let the release download proceed without a verified TLS peer, or
# silently fall back to a non-HTTPS protocol.
TLS_DEFEATING_FLAGS = (
    r"--insecure\b",
    r"(?<![\w-])-k(?![\w-])",
    r"--proto-default\b",
    r"--ssl-no-revoke\b",
    r"--tlsv1\.0\b",
    r"--tlsv1\.1\b",
)


class CodeRabbitHttpsTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = SETUP_SCRIPT.read_text(encoding="utf-8")

    def test_release_download_restricts_initial_and_redirect_protocols_to_https(self) -> None:
        self.assertIn("--proto '=https'", self.script)
        self.assertIn("--proto-redir '=https'", self.script)
        self.assertIn("--tlsv1.2", self.script)
        self.assertLess(
            self.script.index("--proto '=https'"),
            self.script.index('observed_archive_sha="$(sha256_file "$archive")"'),
        )

    def test_tls_verification_cannot_be_disabled(self) -> None:
        """Pinning the protocol is pointless if verification can still be turned off.

        Asserting only that the HTTPS flags are present would keep passing after someone
        adds --insecure next to them, so each defeating flag is rejected by name.
        """
        for pattern in TLS_DEFEATING_FLAGS:
            with self.subTest(flag=pattern):
                self.assertIsNone(
                    re.search(pattern, self.script),
                    f"TLS verification can be disabled via {pattern}",
                )

    def test_every_curl_invocation_pins_https(self) -> None:
        # Backslash-continued invocations are matched whole, so flags on later lines count.
        matches = list(
            re.finditer(r"^[ \t]*curl\b(?:[^\n]*\\\n)*[^\n]*", self.script, re.MULTILINE)
        )
        self.assertTrue(matches, "setup script must contain at least one curl invocation")
        for match in matches:
            invocation = match.group(0)
            with self.subTest(invocation=invocation.strip()[:80]):
                self.assertIn("--proto '=https'", invocation)
                self.assertIn("--proto-redir '=https'", invocation)


if __name__ == "__main__":
    unittest.main()
