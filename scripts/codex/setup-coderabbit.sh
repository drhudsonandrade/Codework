#!/usr/bin/env bash
set -euo pipefail

readonly CODERABBIT_VERSION="0.7.5"
readonly CODERABBIT_PLUGIN_SOURCE_SHA="11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"
REPO_ROOT="$(git rev-parse --show-toplevel)"
MARKETPLACE_MANIFEST="$REPO_ROOT/.agents/plugins/marketplace.json"
CLI_LOCK="$REPO_ROOT/.agents/plugins/coderabbit-cli-checksums.json"
INSTALL_BIN_DIR="${CODEWORK_CODERABBIT_BIN_DIR:-$HOME/.local/bin}"
expected_marketplace_source="$REPO_ROOT"
TEMP_DIR=""
cd "$REPO_ROOT"

fail() {
  echo "ERROR: $*" >&2
  exit 2
}

cleanup() {
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    rm -rf "$TEMP_DIR"
  fi
}
trap cleanup EXIT

sha256_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    fail "sha256sum or shasum is required to verify the CodeRabbit release."
  fi
}

command -v jq >/dev/null 2>&1 || fail "jq is required to validate marketplace/plugin state."
command -v codex >/dev/null 2>&1 || fail "Codex CLI was not found in this environment."
command -v curl >/dev/null 2>&1 || fail "curl is required to download the pinned CodeRabbit release."
command -v unzip >/dev/null 2>&1 || fail "unzip is required to install the pinned CodeRabbit release."
[[ -f "$MARKETPLACE_MANIFEST" ]] || fail "local marketplace manifest was not found."
[[ -f "$CLI_LOCK" ]] || fail "CodeRabbit CLI checksum lock was not found."

lock_version="$(jq -er '.version' "$CLI_LOCK")" || fail "version is missing from the CodeRabbit CLI lock."
lock_schema="$(jq -er '.schema' "$CLI_LOCK")" || fail "schema is missing from the CodeRabbit CLI lock."
lock_template="$(jq -er '.url_template' "$CLI_LOCK")" || fail "URL template is missing from the CodeRabbit CLI lock."
[[ "$lock_schema" == "codework-coderabbit-cli-release-lock-v1" ]] || fail "CodeRabbit CLI lock schema is not recognized."
[[ "$lock_version" == "$CODERABBIT_VERSION" ]] || fail "lock version does not match CODERABBIT_VERSION."
[[ "$lock_template" == 'https://cli.coderabbit.ai/releases/{version}/coderabbit-{platform}.zip' ]] || fail "CodeRabbit CLI URL template is not the expected official source."

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:amd64) platform="linux-x64" ;;
  Linux:aarch64|Linux:arm64) platform="linux-arm64" ;;
  Darwin:arm64|Darwin:aarch64) platform="darwin-arm64" ;;
  Darwin:x86_64|Darwin:amd64) platform="darwin-x64" ;;
  *) fail "unsupported platform for the pinned CodeRabbit release: $(uname -s)/$(uname -m)" ;;
esac

expected_archive_sha="$(jq -er --arg platform "$platform" '.platforms[$platform].sha256' "$CLI_LOCK")" \
  || fail "CodeRabbit checksum is missing for $platform."
[[ "$expected_archive_sha" =~ ^[0-9a-f]{64}$ ]] || fail "CodeRabbit release checksum is invalid for $platform."

TEMP_DIR="$(mktemp -d)"
archive="$TEMP_DIR/coderabbit.zip"
extract_dir="$TEMP_DIR/extracted"
mkdir -p "$extract_dir"
release_url="${lock_template//\{version\}/$CODERABBIT_VERSION}"
release_url="${release_url//\{platform\}/$platform}"
[[ "$release_url" == "https://cli.coderabbit.ai/releases/${CODERABBIT_VERSION}/coderabbit-${platform}.zip" ]] \
  || fail "release URL derived from the lock is not the expected official source."
curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --connect-timeout 15 --max-time 300 \
  --retry 3 --retry-connrefused --retry-delay 2 \
  --output "$archive" "$release_url"
observed_archive_sha="$(sha256_file "$archive")"
[[ "$observed_archive_sha" == "$expected_archive_sha" ]] || fail "CodeRabbit archive SHA-256 does not match the versioned lock."
unzip -q "$archive" -d "$extract_dir"
verified_binary="$extract_dir/coderabbit"
[[ -f "$verified_binary" && ! -L "$verified_binary" ]] \
  || fail "verified CodeRabbit archive does not contain the expected regular binary."
chmod 0755 "$verified_binary"

verified_version_output="$("$verified_binary" --version 2>&1)"
verified_version_token="$(awk 'NF { token=$NF } END { print token }' <<<"$verified_version_output")"
[[ "$verified_version_token" == "$CODERABBIT_VERSION" ]] || {
  echo "ERROR: verified CodeRabbit release reports an unexpected version: ${verified_version_output}" >&2
  exit 5
}
verified_binary_sha="$(sha256_file "$verified_binary")"

install -d -m 0755 "$INSTALL_BIN_DIR"
installed_path="$INSTALL_BIN_DIR/coderabbit"
install -m 0755 "$verified_binary" "$installed_path"
installed_sha="$(sha256_file "$installed_path")"
[[ "$installed_sha" == "$verified_binary_sha" ]] || fail "installed CodeRabbit binary differs from the verified extracted binary."
installed_version_output="$("$installed_path" --version 2>&1)"
installed_version_token="$(awk 'NF { token=$NF } END { print token }' <<<"$installed_version_output")"
[[ "$installed_version_token" == "$CODERABBIT_VERSION" ]] || fail "installed CodeRabbit binary did not preserve the pinned version."

# Bind plugin installation to the reviewed marketplace source, not to a mutable ref alone.
manifest_source_sha="$(jq -er '
  .plugins[]?
  | select(.name == "coderabbit")
  | select(.source.source == "git-subdir")
  | select(.source.url == "openai/plugins")
  | select(.source.path == "plugins/coderabbit")
  | .source.sha
' "$MARKETPLACE_MANIFEST")" || fail "canonical coderabbit plugin source was not found in the marketplace."
[[ "$manifest_source_sha" == "$CODERABBIT_PLUGIN_SOURCE_SHA" ]] || fail "coderabbit plugin source SHA does not match the reviewed pin."
[[ "$manifest_source_sha" =~ ^[0-9a-f]{40}$ ]] || fail "coderabbit plugin source SHA is invalid."

marketplace_present() {
  jq -e --arg expected_marketplace_source "$expected_marketplace_source" '[
    .marketplaces[]?
    | select(
        .name == "codework-codex"
        and .root == $expected_marketplace_source
        and .marketplaceSource.sourceType == "local"
        and .marketplaceSource.source == $expected_marketplace_source
      )
  ] | length == 1' >/dev/null
}

plugin_available() {
  jq -e --arg expected_sha "$CODERABBIT_PLUGIN_SOURCE_SHA" --arg expected_marketplace_source "$expected_marketplace_source" '[
    .available[]?
    | select(
        .pluginId == "coderabbit@codework-codex"
        and .name == "coderabbit"
        and .marketplaceName == "codework-codex"
        and .installed == false
        and .marketplaceSource.sourceType == "local"
        and .marketplaceSource.source == $expected_marketplace_source
        and .source.source == "git-subdir"
        and .source.url == "openai/plugins"
        and .source.path == "plugins/coderabbit"
        and .source.sha == $expected_sha
      )
  ] | length == 1' >/dev/null
}

plugin_present() {
  jq -e --arg expected_sha "$CODERABBIT_PLUGIN_SOURCE_SHA" --arg expected_marketplace_source "$expected_marketplace_source" '[
    .installed[]?
    | select(
        .pluginId == "coderabbit@codework-codex"
        and .name == "coderabbit"
        and .marketplaceName == "codework-codex"
        and .installed == true
        and .marketplaceSource.sourceType == "local"
        and .marketplaceSource.source == $expected_marketplace_source
        and .source.source == "git-subdir"
        and .source.url == "openai/plugins"
        and .source.path == "plugins/coderabbit"
        and .source.sha == $expected_sha
      )
  ] | length == 1' >/dev/null
}

plugin_installed() {
  jq -e --arg expected_sha "$CODERABBIT_PLUGIN_SOURCE_SHA" --arg expected_marketplace_source "$expected_marketplace_source" '[
    .installed[]?
    | select(
        .pluginId == "coderabbit@codework-codex"
        and .name == "coderabbit"
        and .marketplaceName == "codework-codex"
        and .installed == true
        and .enabled == true
        and .marketplaceSource.sourceType == "local"
        and .marketplaceSource.source == $expected_marketplace_source
        and .source.source == "git-subdir"
        and .source.url == "openai/plugins"
        and .source.path == "plugins/coderabbit"
        and .source.sha == $expected_sha
      )
  ] | length == 1' >/dev/null
}

marketplaces_json="$(codex plugin marketplace list --json)"
if ! marketplace_present <<<"$marketplaces_json"; then
  codex plugin marketplace add "$REPO_ROOT" --json >/dev/null
fi
marketplaces_json="$(codex plugin marketplace list --json)"
marketplace_present <<<"$marketplaces_json" || fail "codework-codex marketplace was not confirmed against the reviewed local root after registration."

# Availability is discovery only. An already-installed plugin is never re-added;
# success still requires that exact installed plugin to be enabled and provenance-bound.
plugins_json="$(codex plugin list --marketplace codework-codex --json --available)"
if plugin_present <<<"$plugins_json"; then
  plugin_installed <<<"$plugins_json" || fail "coderabbit plugin was not confirmed as installed, enabled, and bound to the reviewed marketplace/root and source SHA."
elif ! plugin_installed <<<"$plugins_json"; then
  plugin_available <<<"$plugins_json" || fail "coderabbit plugin is not available from the reviewed marketplace/root and source SHA."
  codex plugin add coderabbit@codework-codex --json >/dev/null
fi
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
plugin_installed <<<"$plugins_json" || fail "coderabbit plugin was not confirmed as installed, enabled, and bound to the reviewed marketplace/root and source SHA."

if ! "$installed_path" auth status --agent >/dev/null 2>&1; then
  if [[ -t 0 && -t 1 ]]; then
    echo "CodeRabbit CLI requires one-time interactive authentication." >&2
    "$installed_path" auth login --agent
  else
    echo "ERROR: CodeRabbit CLI is not authenticated in a non-interactive environment." >&2
    exit 7
  fi
fi
"$installed_path" auth status --agent >/dev/null

# Final confirmation repeats the installed-only, source-bound predicates.
marketplaces_json="$(codex plugin marketplace list --json)"
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
marketplace_present <<<"$marketplaces_json" || fail "marketplace lost the expected local root/provenance before final confirmation."
plugin_installed <<<"$plugins_json" || fail "plugin lost installed/enabled state, marketplace provenance, or the expected source SHA before final confirmation."

echo "CodeRabbit Codex plugin + CLI ${CODERABBIT_VERSION} configured from a checksum-locked release. Restart or open a new Codex session before using the plugin."
