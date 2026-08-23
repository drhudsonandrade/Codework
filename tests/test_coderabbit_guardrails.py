from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE_SHA = "11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"


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
        self.assertIn(PLUGIN_SOURCE_SHA, script)
        self.assertIn(PLUGIN_SOURCE_SHA, marketplace)
        self.assertIn('.source.url == "openai/plugins"', script)
        self.assertIn('.source.path == "plugins/coderabbit"', script)
        self.assertIn('[[ "$manifest_source_sha" == "$CODERABBIT_PLUGIN_SOURCE_SHA" ]]', script)

    def test_setup_script_verifies_structured_marketplace_and_plugin_identity_before_success(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(encoding="utf-8")
        success = script.index("CodeRabbit Codex plugin + CLI configurados")
        self.assertLess(script.index("marketplace_present()"), success)
        self.assertLess(script.index("plugin_installed()"), success)
        self.assertIn('.marketplaces[]? | select(.name == "codework-codex")', script)
        self.assertIn('.installed[]?', script)
        self.assertIn('.installed == true', script)
        self.assertIn('.enabled == true', script)
        self.assertIn('.source.sha == $expected_sha', script)
        self.assertIn('.marketplaceName == "codework-codex"', script)
        self.assertGreaterEqual(script.count('marketplace_present <<<"$marketplaces_json"'), 2)
        self.assertGreaterEqual(script.count('plugin_installed <<<"$plugins_json"'), 2)
        self.assertLess(script.rindex('marketplace_present <<<"$marketplaces_json"'), success)
        self.assertLess(script.rindex('plugin_installed <<<"$plugins_json"'), success)

    def test_available_plugin_is_installed_before_success(self) -> None:
        self.assertIsNotNone(shutil.which("jq"), "jq is required by the live setup contract")
        setup_script = ROOT / "scripts" / "codex" / "setup-coderabbit.sh"
        marketplace_source = ROOT / ".agents" / "plugins" / "marketplace.json"

        with tempfile.TemporaryDirectory() as td:
            sandbox = Path(td)
            repo = sandbox / "repo"
            fake_bin = sandbox / "bin"
            marker = sandbox / "plugin-installed"
            (repo / ".agents" / "plugins").mkdir(parents=True)
            fake_bin.mkdir()
            shutil.copy2(marketplace_source, repo / ".agents" / "plugins" / "marketplace.json")

            fake_git = fake_bin / "git"
            fake_git.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [[ \"${1:-}\" == \"rev-parse\" && \"${2:-}\" == \"--show-toplevel\" ]]; then\n"
                "  printf '%s\\n' \"$FAKE_REPO_ROOT\"\n"
                "  exit 0\n"
                "fi\n"
                "exit 9\n",
                encoding="utf-8",
            )

            plugin_entry_installed = (
                '{"pluginId":"coderabbit@codework-codex","name":"coderabbit",'
                '"marketplaceName":"codework-codex","version":"1.0.0","installed":true,"enabled":true,'
                f'"source":{{"source":"git-subdir","url":"openai/plugins","path":"plugins/coderabbit","ref":"main","sha":"{PLUGIN_SOURCE_SHA}"}},'
                '"installPolicy":"AVAILABLE","authPolicy":"ON_INSTALL"}'
            )
            plugin_entry_available = plugin_entry_installed.replace('"installed":true,"enabled":true', '"installed":false,"enabled":false')
            fake_codex = fake_bin / "codex"
            fake_codex.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    set -euo pipefail
                    case "$*" in
                      "plugin marketplace list --json")
                        printf '%s\\n' '{{"marketplaces":[{{"name":"codework-codex"}}]}}'
                        ;;
                      plugin\ marketplace\ add*)
                        printf '%s\\n' '{{}}'
                        ;;
                      "plugin list --marketplace codework-codex --json --available")
                        if [[ -f "$FAKE_CODEX_STATE" ]]; then
                          printf '%s\\n' '{{"installed":[{plugin_entry_installed}],"available":[]}}'
                        else
                          printf '%s\\n' '{{"installed":[],"available":[{plugin_entry_available}]}}'
                        fi
                        ;;
                      "plugin list --marketplace codework-codex --json")
                        if [[ -f "$FAKE_CODEX_STATE" ]]; then
                          printf '%s\\n' '{{"installed":[{plugin_entry_installed}],"available":[]}}'
                        else
                          printf '%s\\n' '{{"installed":[],"available":[]}}'
                        fi
                        ;;
                      "plugin add coderabbit@codework-codex --json")
                        : > "$FAKE_CODEX_STATE"
                        printf '%s\\n' '{{"pluginId":"coderabbit@codework-codex","name":"coderabbit","marketplaceName":"codework-codex","version":"1.0.0","installedPath":"/tmp/coderabbit","authPolicy":"ON_INSTALL"}}'
                        ;;
                      *)
                        echo "unexpected codex invocation: $*" >&2
                        exit 10
                        ;;
                    esac
                    """
                ),
                encoding="utf-8",
            )

            fake_coderabbit = fake_bin / "coderabbit"
            fake_coderabbit.write_text(
                "#!/usr/bin/env bash\n"
                "set -euo pipefail\n"
                "if [[ \"${1:-}\" == \"--version\" ]]; then echo 'coderabbit 0.7.5'; exit 0; fi\n"
                "if [[ \"${1:-}\" == \"auth\" && \"${2:-}\" == \"status\" && \"${3:-}\" == \"--agent\" ]]; then exit 0; fi\n"
                "exit 11\n",
                encoding="utf-8",
            )

            for executable in (fake_git, fake_codex, fake_coderabbit):
                executable.chmod(0o755)

            coderabbit_sha = hashlib.sha256(fake_coderabbit.read_bytes()).hexdigest()
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "FAKE_REPO_ROOT": str(repo),
                    "FAKE_CODEX_STATE": str(marker),
                    "CODERABBIT_BINARY_SHA256": coderabbit_sha,
                }
            )
            result = subprocess.run(
                ["bash", str(setup_script)],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(marker.is_file(), "available-only plugin must be installed before success")


if __name__ == "__main__":
    unittest.main()
