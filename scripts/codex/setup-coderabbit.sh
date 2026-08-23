#!/usr/bin/env bash
set -euo pipefail

readonly CODERABBIT_VERSION="0.7.5"
readonly CODERABBIT_PLUGIN_SOURCE_SHA="11c74d6ba24d3a6d48f54a194cd00ef3beea18f9"
readonly CODERABBIT_BINARY_SHA256="${CODERABBIT_BINARY_SHA256:-}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
MARKETPLACE_MANIFEST="$REPO_ROOT/.agents/plugins/marketplace.json"
expected_marketplace_source="$REPO_ROOT"
cd "$REPO_ROOT"

fail() {
  echo "ERROR: $*" >&2
  exit 2
}

command -v jq >/dev/null 2>&1 || fail "jq é obrigatório para validar o estado do marketplace/plugin."
command -v codex >/dev/null 2>&1 || fail "Codex CLI não encontrado neste ambiente."
[[ -f "$MARKETPLACE_MANIFEST" ]] || fail "manifesto local do marketplace não encontrado."

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

if ! command -v coderabbit >/dev/null 2>&1; then
  cat >&2 <<EOF
ERROR: CodeRabbit CLI não está pré-instalado.
Este script não executa instalador remoto via curl|sh e não aceita artefato sem checksum.
Provisione previamente a versão ${CODERABBIT_VERSION} por um canal verificado e execute novamente.
EOF
  exit 4
fi

[[ -n "$CODERABBIT_BINARY_SHA256" ]] || fail "CODERABBIT_BINARY_SHA256 aprovado é obrigatório; binário sem digest não será aceito."
[[ "$CODERABBIT_BINARY_SHA256" =~ ^[0-9a-fA-F]{64}$ ]] || fail "CODERABBIT_BINARY_SHA256 deve conter exatamente 64 dígitos hexadecimais."

observed_version="$(coderabbit --version 2>&1)"
case "$observed_version" in
  *"${CODERABBIT_VERSION}"*) ;;
  *)
    echo "ERROR: CodeRabbit CLI fora da versão fixada ${CODERABBIT_VERSION}: ${observed_version}" >&2
    exit 5
    ;;
esac

coderabbit_path="$(command -v coderabbit)"
observed_sha256="$(sha256sum "$coderabbit_path" | awk '{print $1}')"
[[ "${observed_sha256,,}" == "${CODERABBIT_BINARY_SHA256,,}" ]] || {
  echo "ERROR: SHA256 do binário CodeRabbit não corresponde ao valor aprovado." >&2
  exit 6
}

if ! coderabbit auth status --agent >/dev/null 2>&1; then
  if [[ -t 0 && -t 1 ]]; then
    echo "CodeRabbit CLI precisa de autenticação interativa uma única vez." >&2
    coderabbit auth login --agent
  else
    echo "ERROR: CodeRabbit CLI não autenticado em ambiente não interativo." >&2
    exit 7
  fi
fi
coderabbit auth status --agent >/dev/null

# Final confirmation repeats the installed-only, source-bound predicates.
marketplaces_json="$(codex plugin marketplace list --json)"
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
marketplace_present <<<"$marketplaces_json" || fail "marketplace perdeu o root/proveniência local esperados antes da confirmação final."
plugin_installed <<<"$plugins_json" || fail "plugin perdeu o estado instalado/habilitado, a proveniência do marketplace ou o source SHA esperado antes da confirmação final."

echo "CodeRabbit Codex plugin + CLI configurados para este workspace. Reinicie/abra nova sessão do Codex antes de usar o plugin."
