from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE_SHA = "11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"
CLI_VERSION = "0.7.5"
EXPECTED_RELEASE_HASHES = {
    "darwin-arm64": "5add1edd7269ceda01303bfd6cd9ce6b1fa204d7dd9c89bed412c36680caf020",
    "darwin-x64": "493c9908405eaccede9f373ee835e7fa68f1171caa5a784ce52c07585e37223f",
    "linux-arm64": "596f957f67b7ba07925127c52530e291631177d8dcba0f3a66deb55a9a5b06e9",
    "linux-x64": "0b47cb4de75188c0184f290d8d6818a793a9528e8f79cf660c6a65f225b045c1",
}


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
        for forbidden in (
            "[skip review]",
            "dependabot[bot]",
            "github-actions[bot]",
            "WIP",
            "DO NOT MERGE",
        ):
            self.assertNotIn(forbidden, auto_review)
        self.assertNotIn("ignore_title_keywords:", config)
        self.assertNotIn("ignore_usernames:", config)

    def test_title_check_is_blocking_and_evidence_adapters_are_covered(self) -> None:
        config = (ROOT / ".coderabbit.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            config,
            r"pre_merge_checks:\s*\n\s*title:\s*\n\s*mode:\s*\"error\"",
        )
        self.assertIn('- path: "evidence_adapters/**"', config)

    def test_release_lock_is_versioned_and_contains_reviewed_platform_hashes(self) -> None:
        lock = json.loads(
            (ROOT / ".agents" / "plugins" / "coderabbit-cli-checksums.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(lock["schema"], "codework-coderabbit-cli-release-lock-v1")
        self.assertEqual(lock["version"], CLI_VERSION)
        self.assertEqual(
            lock["url_template"],
            "https://cli.coderabbit.ai/releases/{version}/coderabbit-{platform}.zip",
        )
        self.assertEqual(
            {platform: item["sha256"] for platform, item in lock["platforms"].items()},
            EXPECTED_RELEASE_HASHES,
        )

    def test_setup_script_uses_repository_lock_not_environment_digest(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotRegex(script, r"curl[^\n]*\|\s*(?:ba)?sh\b")
        self.assertNotRegex(script, r"wget[^\n]*\|\s*(?:ba)?sh\b")
        self.assertIn(f'readonly CODERABBIT_VERSION="{CLI_VERSION}"', script)
        self.assertIn("coderabbit-cli-checksums.json", script)
        self.assertNotIn("CODERABBIT_BINARY_SHA256", script)
        self.assertIn('expected_archive_sha="$(jq -er', script)
        self.assertIn('observed_archive_sha="$(sha256_file "$archive")"', script)
        self.assertIn('[[ "$observed_archive_sha" == "$expected_archive_sha" ]]', script)
        self.assertLess(
            script.index('[[ "$observed_archive_sha" == "$expected_archive_sha" ]]'),
            script.index('unzip -q "$archive"'),
        )
        self.assertIn('release_url="${lock_template//\\{version\\}/$CODERABBIT_VERSION}"', script)
        self.assertIn('release_url="${release_url//\\{platform\\}/$platform}"', script)
        self.assertNotIn(
            'release_url="https://cli.coderabbit.ai/releases/${CODERABBIT_VERSION}/coderabbit-${platform}.zip"',
            script,
        )
        self.assertIn("--connect-timeout 15", script)
        self.assertIn("--max-time 300", script)
        self.assertIn("--retry 3", script)
        self.assertIn("--retry-connrefused", script)
        self.assertIn('[[ -f "$verified_binary" && ! -L "$verified_binary" ]]', script)

    def test_setup_script_binds_plugin_to_reviewed_source_sha(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(
            encoding="utf-8"
        )
        marketplace = (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(
            encoding="utf-8"
        )
        self.assertIn(PLUGIN_SOURCE_SHA, script)
        self.assertIn(PLUGIN_SOURCE_SHA, marketplace)
        self.assertIn('.source.url == "openai/plugins"', script)
        self.assertIn('.source.path == "plugins/coderabbit"', script)
        self.assertIn(
            '[[ "$manifest_source_sha" == "$CODERABBIT_PLUGIN_SOURCE_SHA" ]]',
            script,
        )

    def test_setup_script_requires_installed_enabled_plugin_before_success(self) -> None:
        script = (ROOT / "scripts" / "codex" / "setup-coderabbit.sh").read_text(
            encoding="utf-8"
        )
        success = script.index("configurados a partir de release checksum-locked")
        self.assertLess(script.index("marketplace_present()"), success)
        self.assertLess(script.index("plugin_installed()"), success)
        self.assertIn('.marketplaces[]?', script)
        self.assertIn('.installed[]?', script)
        self.assertIn('.installed == true', script)
        self.assertIn('.enabled == true', script)
        self.assertIn('.source.sha == $expected_sha', script)
        self.assertGreaterEqual(script.count('marketplace_present <<<"$marketplaces_json"'), 2)
        self.assertGreaterEqual(script.count('plugin_installed <<<"$plugins_json"'), 2)
        self.assertLess(script.rindex('plugin_installed <<<"$plugins_json"'), success)

    def _make_release_archive(self, path: Path, version_output: str) -> str:
        binary = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f"if [[ \"${{1:-}}\" == \"--version\" ]]; then echo {version_output!r}; exit 0; fi\n"
            "if [[ \"${1:-}\" == \"auth\" && \"${2:-}\" == \"status\" "
            "&& \"${3:-}\" == \"--agent\" ]]; then exit 0; fi\n"
            "exit 11\n"
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("coderabbit", binary)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _run_setup_with_fakes(
        self,
        *,
        adulterated_marketplace: bool = False,
        version_output: str = "coderabbit 0.7.5",
        tamper_archive: bool = False,
        installed_enabled: bool = True,
        already_installed: bool = False,
    ) -> tuple[subprocess.CompletedProcess[str], bool, str]:
        self.assertIsNotNone(shutil.which("jq"), "jq is required by the setup contract")
        self.assertIsNotNone(shutil.which("unzip"), "unzip is required by the setup contract")
        setup_script = ROOT / "scripts" / "codex" / "setup-coderabbit.sh"
        marketplace_manifest = ROOT / ".agents" / "plugins" / "marketplace.json"
        cli_lock = ROOT / ".agents" / "plugins" / "coderabbit-cli-checksums.json"

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        sandbox = Path(td.name)
        repo = sandbox / "repo"
        fake_bin = sandbox / "bin"
        install_bin = sandbox / "installed-bin"
        marker = sandbox / "plugin-installed"
        codex_log = sandbox / "codex-calls.log"
        (repo / ".agents" / "plugins").mkdir(parents=True)
        fake_bin.mkdir()
        shutil.copy2(marketplace_manifest, repo / ".agents" / "plugins" / "marketplace.json")
        if already_installed:
            marker.touch()

        release = sandbox / "release.zip"
        good_archive_sha = self._make_release_archive(release, version_output)
        copied_lock = json.loads(cli_lock.read_text(encoding="utf-8"))
        copied_lock["platforms"]["linux-x64"]["sha256"] = good_archive_sha
        (repo / ".agents" / "plugins" / "coderabbit-cli-checksums.json").write_text(
            json.dumps(copied_lock, indent=2) + "\n",
            encoding="utf-8",
        )
        archive_to_serve = release
        if tamper_archive:
            archive_to_serve = sandbox / "tampered.zip"
            archive_to_serve.write_bytes(release.read_bytes() + b"tamper")

        marketplace_source = (
            str(sandbox / "unreviewed-marketplace")
            if adulterated_marketplace
            else str(repo)
        )
        expected_release_url = (
            f"https://cli.coderabbit.ai/releases/{CLI_VERSION}/coderabbit-linux-x64.zip"
        )

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

        fake_uname = fake_bin / "uname"
        fake_uname.write_text(
            "#!/usr/bin/env bash\n"
            "case \"${1:-}\" in\n"
            "  -s) echo Linux ;;\n"
            "  -m) echo x86_64 ;;\n"
            "  *) echo Linux ;;\n"
            "esac\n",
            encoding="utf-8",
        )

        fake_curl = fake_bin / "curl"
        fake_curl.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "out=''\n"
            "url=''\n"
            "proto=''\n"
            "proto_redir=''\n"
            "connect_timeout=''\n"
            "max_time=''\n"
            "retry=''\n"
            "retry_delay=''\n"
            "retry_connrefused=0\n"
            "while (($#)); do\n"
            "  case \"$1\" in\n"
            "    --output) out=\"$2\"; shift 2 ;;\n"
            "    --proto) proto=\"$2\"; shift 2 ;;\n"
            "    --proto-redir) proto_redir=\"$2\"; shift 2 ;;\n"
            "    --connect-timeout) connect_timeout=\"$2\"; shift 2 ;;\n"
            "    --max-time) max_time=\"$2\"; shift 2 ;;\n"
            "    --retry) retry=\"$2\"; shift 2 ;;\n"
            "    --retry-delay) retry_delay=\"$2\"; shift 2 ;;\n"
            "    --retry-connrefused) retry_connrefused=1; shift ;;\n"
            "    --fail|--location|--silent|--show-error|--tlsv1.2) shift ;;\n"
            "    https://*) url=\"$1\"; shift ;;\n"
            "    *) echo \"unexpected curl argument: $1\" >&2; exit 12 ;;\n"
            "  esac\n"
            "done\n"
            "test -n \"$out\"\n"
            "test \"$proto\" = '=https'\n"
            "test \"$proto_redir\" = '=https'\n"
            "test \"$connect_timeout\" = '15'\n"
            "test \"$max_time\" = '300'\n"
            "test \"$retry\" = '3'\n"
            "test \"$retry_delay\" = '2'\n"
            "test \"$retry_connrefused\" = '1'\n"
            "test \"$url\" = \"$FAKE_CODERABBIT_URL\"\n"
            "cp \"$FAKE_CODERABBIT_ARCHIVE\" \"$out\"\n",
            encoding="utf-8",
        )

        plugin_common = (
            '"pluginId":"coderabbit@codework-codex","name":"coderabbit",'
            '"marketplaceName":"codework-codex","version":"1.0.0",'
            '"source":{"source":"git-subdir","url":"openai/plugins",'
            '"path":"plugins/coderabbit","ref":"main",'
            f'"sha":"{PLUGIN_SOURCE_SHA}"}},'
            f'"marketplaceSource":{{"sourceType":"local","source":"{marketplace_source}"}},'
            '"installPolicy":"AVAILABLE","authPolicy":"ON_INSTALL"'
        )
        enabled_json = "true" if installed_enabled else "false"
        installed = "{" + plugin_common + f',"installed":true,"enabled":{enabled_json}' + "}"
        available = "{" + plugin_common + ',"installed":false,"enabled":false' + "}"
        json.loads(installed)
        json.loads(available)
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
                printf '%s\\n' "$*" >> "$FAKE_CODEX_LOG"
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
                    printf '%s\\n' '{{"pluginId":"coderabbit@codework-codex"}}'
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

        for executable in (fake_git, fake_uname, fake_curl, fake_codex):
            executable.chmod(0o755)

        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{fake_bin}:{env['PATH']}",
                "FAKE_REPO_ROOT": str(repo),
                "FAKE_CODEX_STATE": str(marker),
                "FAKE_CODEX_LOG": str(codex_log),
                "FAKE_CODERABBIT_ARCHIVE": str(archive_to_serve),
                "FAKE_CODERABBIT_URL": expected_release_url,
                "CODEWORK_CODERABBIT_BIN_DIR": str(install_bin),
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
        calls = codex_log.read_text(encoding="utf-8") if codex_log.is_file() else ""
        return result, marker.is_file(), calls

    def test_available_plugin_is_installed_before_success(self) -> None:
        result, marker_created, calls = self._run_setup_with_fakes()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(marker_created, "available-only plugin must be installed before success")
        self.assertIn("plugin add coderabbit@codework-codex --json", calls)
        self.assertIn("configurados a partir de release checksum-locked", result.stdout)

    def test_already_installed_plugin_is_not_added_again(self) -> None:
        result, _marker_created, calls = self._run_setup_with_fakes(already_installed=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("plugin marketplace list --json", calls)
        self.assertIn("plugin list --marketplace codework-codex --json --available", calls)
        self.assertIn("plugin list --marketplace codework-codex --json", calls)
        self.assertNotIn("plugin add coderabbit@codework-codex --json", calls)
        self.assertIn("configurados a partir de release checksum-locked", result.stdout)

    def test_tampered_release_archive_fails_before_plugin_installation(self) -> None:
        result, marker_created, calls = self._run_setup_with_fakes(tamper_archive=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker_created)
        self.assertNotIn("plugin add coderabbit@codework-codex --json", calls)
        self.assertIn("archive CodeRabbit diverge do lock", result.stderr)
        self.assertNotIn("configurados a partir de release checksum-locked", result.stdout)

    def test_adulterated_marketplace_source_is_rejected(self) -> None:
        result, marker_created, calls = self._run_setup_with_fakes(adulterated_marketplace=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker_created)
        self.assertNotIn("plugin add coderabbit@codework-codex --json", calls)
        self.assertIn(
            "marketplace codework-codex não foi confirmado no root local revisado",
            result.stderr,
            result.stdout + result.stderr,
        )
        self.assertNotIn("configurados a partir de release checksum-locked", result.stdout)

    def test_disabled_installed_plugin_is_rejected(self) -> None:
        result, _marker_created, calls = self._run_setup_with_fakes(
            already_installed=True,
            installed_enabled=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("plugin add coderabbit@codework-codex --json", calls)
        self.assertIn("não foi confirmado como instalado, habilitado", result.stderr)
        self.assertNotIn("configurados a partir de release checksum-locked", result.stdout)

    def test_version_prefix_does_not_satisfy_exact_cli_pin(self) -> None:
        result, marker_created, _calls = self._run_setup_with_fakes(
            version_output="coderabbit 0.7.50",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertFalse(marker_created)
        self.assertNotIn("configurados a partir de release checksum-locked", result.stdout)


if __name__ == "__main__":
    unittest.main()
