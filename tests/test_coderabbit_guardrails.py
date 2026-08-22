from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CodeRabbitGuardrailTests(unittest.TestCase):
    def test_review_cannot_be_skipped_by_title_or_bot_username(self) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        auto_review_match = re.search(
            r"(?ms)^\s{2}auto_review:\s*\n(?P<body>.*?)(?=^\s{2}\S|^reviews:\s*$|\Z)",
            config,
        )
        self.assertIsNotNone(auto_review_match)
        auto_review = auto_review_match.group("body") if auto_review_match else ""
        self.assertNotIn("ignore_title_keywords:", auto_review)
        self.assertNotIn("ignore_usernames:", auto_review)
        for forbidden in ("[skip review]", "dependabot[bot]", "github-actions[bot]", "WIP", "DO NOT MERGE"):
            self.assertNotIn(forbidden, auto_review)
        self.assertNotIn("ignore_title_keywords:", config)
        self.assertNotIn("ignore_usernames:", config)

    def test_title_check_is_blocking_and_evidence_adapters_are_covered(self) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        self.assertRegex(config, r"pre_merge_checks:\s*\n\s*title:\s*\n\s*mode:\s*\"error\"")
        self.assertIn('- path: "evidence_adapters/**"', config)

    def test_setup_script_does_not_execute_unverified_remote_installer(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"curl[^\n]*\|\s*(?:ba)?sh\b")
        self.assertNotRegex(script, r"wget[^\n]*\|\s*(?:ba)?sh\b")
        self.assertIn('readonly CODERABBIT_VERSION="0.7.5"', script)
        self.assertIn("CODERABBIT_PLUGIN_SOURCE_SHA", script)
        self.assertIn("CODERABBIT_BINARY_SHA256 aprovado é obrigatório", script)
        self.assertRegex(script, r"CODERABBIT_BINARY_SHA256.*64")
        self.assertIn('observed_sha256="$(sha256sum', script)
        self.assertIn("não executa instalador remoto", script)

    def test_setup_script_binds_plugin_to_reviewed_source_sha(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        marketplace = (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        pin = "11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"
        self.assertIn(pin, script)
        self.assertIn(pin, marketplace)
        self.assertIn('.source.url == "openai/plugins"', script)
        self.assertIn('.source.path == "plugins/coderabbit"', script)
        self.assertIn('[[ "$manifest_source_sha" == "$CODERABBIT_PLUGIN_SOURCE_SHA" ]]', script)

    def test_setup_script_verifies_structured_marketplace_and_plugin_identity_before_success(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        success = script.index("CodeRabbit Codex plugin + CLI configurados")
        self.assertLess(script.index("marketplace_present()"), success)
        self.assertLess(script.index("plugin_present()"), success)
        self.assertIn('.marketplaces[]? | select(.name == "codework-codex")', script)
        self.assertIn('.installed[]?, .available[]?', script)
        self.assertIn('.marketplaceName == "codework-codex"', script)
        self.assertIn('codex plugin list --marketplace codework-codex --json --available', script)
        self.assertGreaterEqual(script.count('marketplace_present <<<"$marketplaces_json"'), 2)
        self.assertGreaterEqual(script.count('plugin_present <<<"$plugins_json"'), 2)
        self.assertLess(script.rindex('marketplace_present <<<"$marketplaces_json"'), success)
        self.assertLess(script.rindex('plugin_present <<<"$plugins_json"'), success)


if __name__ == "__main__":
    unittest.main()
