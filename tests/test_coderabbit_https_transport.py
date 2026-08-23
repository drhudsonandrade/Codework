from __future__ import annotations

import re
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

    def test_tls_verification_cannot_be_disabled(self) -> None:
        """Asserting the safe flags are present does not prove unsafe ones are absent.

        curl happily accepts --insecure alongside --proto '=https': the protocol
        restriction still holds while certificate verification is switched off. A
        presence-only test stays green through exactly that change.
        """
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        for forbidden in ("--insecure", "--proto-default", "--doh-insecure", "--ssl-no-revoke"):
            self.assertNotIn(forbidden, script, f"TLS verification weakened by {forbidden}")
        # -k is curl's short --insecure. Matched as a standalone word so that
        # unrelated tokens ending in "-k" do not trigger a false rejection.
        self.assertIsNone(
            re.search(r"(?<![\w-])-k(?![\w-])", script),
            "TLS verification weakened by curl -k",
        )

    def test_the_pinned_release_is_verified_before_it_is_used(self) -> None:
        """A checksum proven after installation would be proving the wrong thing."""
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        verified = script.index('[[ "$observed_archive_sha" == "$expected_archive_sha" ]]')
        self.assertLess(verified, script.index("unzip -q"), "archive is extracted before its digest is checked")
        self.assertLess(verified, script.index('install -m 0755 "$verified_binary"'))


if __name__ == "__main__":
    unittest.main()
