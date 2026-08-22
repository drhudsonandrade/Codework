from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CodeRabbitGuardrailTests(unittest.TestCase):
    def test_review_cannot_be_skipped_by_title_or_bot_username(self) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        self.assertNotIn("[skip review]", config)
        self.assertNotIn('"dependabot[bot]"', config)
        self.assertNotIn('"github-actions[bot]"', config)

    def test_title_check_is_blocking_and_evidence_adapters_are_covered(self) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        self.assertRegex(config, r"pre_merge_checks:\s*\n\s*title:\s*\n\s*mode:\s*\"error\"")
        self.assertIn('- path: "evidence_adapters/**"', config)

    def test_setup_script_does_not_pipe_remote_code_to_shell(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"curl[^\n]*\|\s*(?:ba)?sh\b")
        self.assertIn("CODERABBIT_VERSION", script)
        self.assertIn("SHA256", script)

    def test_setup_script_verifies_marketplace_and_plugin_before_success(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        success = script.index("CodeRabbit Codex plugin + CLI configurados")
        self.assertLess(script.index("codex plugin marketplace list"), success)
        self.assertLess(script.index("codex plugin list --marketplace codework-codex"), success)
        self.assertRegex(script, r"jq\s+-e")


if __name__ == "__main__":
    unittest.main()
