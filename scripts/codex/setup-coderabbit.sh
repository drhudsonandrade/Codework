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
    fail "sha256sum ou shasum é obrigatório para validar o release do CodeRabbit."
  fi
}

command -v jq >/dev/null 2>&1 || fail "jq é obrigatório para validar o estado do marketplace/plugin."
command -v codex >/dev/null 2>&1 || fail "Codex CLI não encontrado neste ambiente."
command -v curl >/dev/null 2>&1 || fail "curl é obrigatório para baixar o release fixado do CodeRabbit."
command -v unzip >/dev/null 2>&1 || fail "unzip é obrigatório para instalar o release fixado do CodeRabbit."
[[ -f "$MARKETPLACE_MANIFEST" ]] || fail "manifesto local do marketplace não encontrado."
[[ -f "$CLI_LOCK" ]] || fail "lock de checksums do CodeRabbit CLI não encontrado."

lock_version="$(jq -er '.version' "$CLI_LOCK")" || fail "versão ausente no lock do CodeRabbit CLI."
lock_schema="$(jq -er '.schema' "$CLI_LOCK")" || fail "schema ausente no lock do CodeRabbit CLI."
lock_template="$(jq -er '.url_template' "$CLI_LOCK")" || fail "URL template ausente no lock do CodeRabbit CLI."
[[ "$lock_schema" == "codework-coderabbit-cli-release-lock-v1" ]] || fail "schema do lock do CodeRabbit CLI não reconhecido."
[[ "$lock_version" == "$CODERABBIT_VERSION" ]] || fail "versão do lock diverge de CODERABBIT_VERSION."
[[ "$lock_template" == 'https://cli.coderabbit.ai/releases/{version}/coderabbit-{platform}.zip' ]] || fail "URL template do CodeRabbit CLI não é a origem oficial esperada."

case "$(uname -s):$(uname -m)" in
  Linux:x86_64|Linux:amd64) platform="linux-x64" ;;
  Linux:aarch64|Linux:arm64) platform="linux-arm64" ;;
  Darwin:arm64|Darwin:aarch64) platform="darwin-arm64" ;;
  Darwin:x86_64|Darwin:amd64) platform="darwin-x64" ;;
  *) fail "plataforma não suportada para o release fixado do CodeRabbit: $(uname -s)/$(uname -m)" ;;
esac

expected_archive_sha="$(jq -er --arg platform "$platform" '.platforms[$platform].sha256' "$CLI_LOCK")" \
  || fail "checksum do CodeRabbit ausente para $platform."
[[ "$expected_archive_sha" =~ ^[0-9a-f]{64}$ ]] || fail "checksum do release CodeRabbit é inválido para $platform."

TEMP_DIR="$(mktemp -d)"
archive="$TEMP_DIR/coderabbit.zip"
extract_dir="$TEMP_DIR/extracted"
mkdir -p "$extract_dir"
release_url="${lock_template//\{version\}/$CODERABBIT_VERSION}"
release_url="${release_url//\{platform\}/$platform}"
[[ "$release_url" == "https://cli.coderabbit.ai/releases/${CODERABBIT_VERSION}/coderabbit-${platform}.zip" ]] \
  || fail "URL de release derivada do lock não é a origem oficial esperada."
curl --fail --location --silent --show-error --output "$archive" "$release_url"
observed_archive_sha="$(sha256_file "$archive")"
[[ "$observed_archive_sha" == "$expected_archive_sha" ]] || fail "SHA-256 do archive CodeRabbit diverge do lock versionado."
unzip -q "$archive" -d "$extract_dir"
verified_binary="$extract_dir/coderabbit"
[[ -f "$verified_binary" && ! -L "$verified_binary" ]] \
  || fail "archive CodeRabbit verificado não contém o binário regular esperado."
chmod 0755 "$verified_binary"

verified_version_output="$($verified_binary --version 2>&1)"
verified_version_token="$(awk 'NF { token=$NF } END { print token }' <<<"$verified_version_output")"
[[ "$verified_version_token" == "$CODERABBIT_VERSION" ]] || {
  echo "ERROR: release CodeRabbit verificado reporta versão inesperada: ${verified_version_output}" >&2
  exit 5
}
verified_binary_sha="$(sha256_file "$verified_binary")"

install -d -m 0755 "$INSTALL_BIN_DIR"
installed_path="$INSTALL_BIN_DIR/coderabbit"
install -m 0755 "$verified_binary" "$installed_path"
installed_sha="$(sha256_file "$installed_path")"
[[ "$installed_sha" == "$verified_binary_sha" ]] || fail "binário CodeRabbit instalado diverge do binário extraído do archive verificado."
installed_version_output="$($installed_path --version 2>&1)"
installed_version_token="$(awk 'NF { token=$NF } END { print token }' <<<"$installed_version_output")"
[[ "$installed_version_token" == "$CODERABBIT_VERSION" ]] || fail "binário CodeRabbit instalado não preservou a versão fixada."

# Bind plugin installation to the reviewed marketplace source, not to a mutable ref alone.
manifest_source_sha="$(jq -er '
  .plugins[]?
  | select(.name == "coderabbit")
  | select(.source.source == "git-subdir")
  | select(.source.url == "openai/plugins")
  | select(.source.path == "plugins/coderabbit")
  | .source.sha
' "$MARKETPLACE_MANIFEST")" || fail "fonte canônica do plugin coderabbit não encontrada no marketplace."
[[ "$manifest_source_sha" == "$CODERABBIT_PLUGIN_SOURCE_SHA" ]] || fail "SHA do source do plugin coderabbit diverge do pin revisado."
[[ "$manifest_source_sha" =~ ^[0-9a-f]{40}$ ]] || fail "SHA do source do plugin coderabbit é inválido."

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
marketplace_present <<<"$marketplaces_json" || fail "marketplace codework-codex não foi confirmado no root local revisado após registro."

# Availability is discovery only. Success requires an installed+enabled plugin whose
# marketplace provenance and resolved plugin source both match reviewed identities.
plugins_json="$(codex plugin list --marketplace codework-codex --json --available)"
if ! plugin_installed <<<"$plugins_json"; then
  plugin_available <<<"$plugins_json" || fail "plugin coderabbit não está disponível a partir do marketplace/root e source SHA revisados."
  codex plugin add coderabbit@codework-codex --json >/dev/null
fi
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
plugin_installed <<<"$plugins_json" || fail "plugin coderabbit não foi confirmado como instalado, habilitado e preso ao marketplace/root e source SHA revisados."

if ! "$installed_path" auth status --agent >/dev/null 2>&1; then
  if [[ -t 0 && -t 1 ]]; then
    echo "CodeRabbit CLI precisa de autenticação interativa uma única vez." >&2
    "$installed_path" auth login --agent
  else
    echo "ERROR: CodeRabbit CLI não autenticado em ambiente não interativo." >&2
    exit 7
  fi
fi
"$installed_path" auth status --agent >/dev/null

# Final confirmation repeats the installed-only, source-bound predicates.
marketplaces_json="$(codex plugin marketplace list --json)"
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
marketplace_present <<<"$marketplaces_json" || fail "marketplace perdeu o root/proveniência local esperados antes da confirmação final."
plugin_installed <<<"$plugins_json" || fail "plugin perdeu o estado instalado/habilitado, a proveniência do marketplace ou o source SHA esperado antes da confirmação final."

echo "CodeRabbit Codex plugin + CLI ${CODERABBIT_VERSION} configurados a partir de release checksum-locked. Reinicie/abra nova sessão do Codex antes de usar o plugin."
