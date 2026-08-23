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
        self.assertIn('.marketplaces[]?', script)
        self.assertIn('.name == "codework-codex"', script)
        self.assertIn('.root == $expected_marketplace_source', script)
        self.assertIn('.marketplaceSource.sourceType == "local"', script)
        self.assertIn('.marketplaceSource.source == $expected_marketplace_source', script)
        self.assertIn('.installed[]?', script)
        self.assertIn('.installed == true', script)
        self.assertIn('.enabled == true', script)
        self.assertIn('.source.sha == $expected_sha', script)
        self.assertIn('.marketplaceName == "codework-codex"', script)
        self.assertGreaterEqual(script.count('marketplace_present <<<"$marketplaces_json"'), 2)
        self.assertGreaterEqual(script.count('plugin_installed <<<"$plugins_json"'), 2)
        self.assertLess(script.rindex('marketplace_present <<<"$marketplaces_json"'), success)
        self.assertLess(script.rindex('plugin_installed <<<"$plugins_json"'), success)

    def _run_setup_with_fake_codex(
        self,
        *,
        adulterated_marketplace: bool,
        coderabbit_version_output: str = "coderabbit 0.7.5",
    ) -> tuple[subprocess.CompletedProcess[str], bool]:
        self.assertIsNotNone(shutil.which("jq"), "jq is required by the live setup contract")
        setup_script = ROOT / "scripts" / "codex" / "setup-coderabbit.sh"
        marketplace_manifest = ROOT / ".agents" / "plugins" / "marketplace.json"

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        sandbox = Path(td.name)
        repo = sandbox / "repo"
        fake_bin = sandbox / "bin"
        marker = sandbox / "plugin-installed"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        fake_bin.mkdir()
        shutil.copy2(marketplace_manifest, repo / ".agents" / "plugins" / "marketplace.json")
        marketplace_source = str(sandbox / "unreviewed-marketplace") if adulterated_marketplace else str(repo)

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

        plugin_common = (
            '"pluginId":"coderabbit@codework-codex","name":"coderabbit",'
            '"marketplaceName":"codework-codex","version":"1.0.0",'
            '"source":{"source":"git-subdir","url":"openai/plugins","path":"plugins/coderabbit","ref":"main",'
            f'"sha":"{PLUGIN_SOURCE_SHA}"}},'
            f'"marketplaceSource":{{"sourceType":"local","source":"{marketplace_source}"}},'
            '"installPolicy":"AVAILABLE","authPolicy":"ON_INSTALL"'
        )
        installed = "{" + plugin_common + ',"installed":true,"enabled":true}'
        available = "{" + plugin_common + ',"installed":false,"enabled":false}'
        marketplace_entry = (
            '{"name":"codework-codex",'
            f'"root":"{marketplace_source}",'
            f'"marketplaceSource":{{"sourceType":"local","source":"{marketplace_source}"}}}}'
        )

        fake_codex = fake_bin / "codex"
        fake_codex.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                set -euo pipefail
                case "$*" in
                  "plugin marketplace list --json")
                    printf '%s\\n' '{{"marketplaces":[{marketplace_entry}]}}'
                    ;;
                  "plugin marketplace add"*)
                    printf '%s\\n' '{{}}'
                    ;;
                  "plugin list --marketplace codework-codex --json --available")
                    if [[ -f "$FAKE_CODEX_STATE" ]]; then
                      printf '%s\\n' '{{"installed":[{installed}],"available":[]}}'
                    else
                      printf '%s\\n' '{{"installed":[],"available":[{available}]}}'
                    fi
                    ;;
                  "plugin list --marketplace codework-codex --json")
                    if [[ -f "$FAKE_CODEX_STATE" ]]; then
                      printf '%s\\n' '{{"installed":[{installed}],"available":[]}}'
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
            f"if [[ \"${{1:-}}\" == \"--version\" ]]; then echo {coderabbit_version_output!r}; exit 0; fi\n"
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
        return result, marker.is_file()

    def test_available_plugin_is_installed_before_success(self) -> None:
        result, marker_created = self._run_setup_with_fake_codex(adulterated_marketplace=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker_created, "available-only plugin must be installed before success")
        self.assertIn("CodeRabbit Codex plugin + CLI configurados", result.stdout)

    def test_adulterated_marketplace_source_is_rejected(self) -> None:
        result, marker_created = self._run_setup_with_fake_codex(adulterated_marketplace=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker_created)
        self.assertNotIn("CodeRabbit Codex plugin + CLI configurados", result.stdout)

    def test_version_prefix_does_not_satisfy_exact_cli_pin(self) -> None:
        result, _ = self._run_setup_with_fake_codex(
            adulterated_marketplace=False,
            coderabbit_version_output="coderabbit 0.7.50",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertNotIn("CodeRabbit Codex plugin + CLI configurados", result.stdout)


if __name__ == "__main__":
    unittest.main()
