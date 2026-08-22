#!/usr/bin/env bash
set -euo pipefail

readonly CODERABBIT_VERSION="0.7.5"
readonly CODERABBIT_BINARY_SHA256="${CODERABBIT_BINARY_SHA256:-}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq é obrigatório para validar o estado do marketplace/plugin." >&2
  exit 2
fi
if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: Codex CLI não encontrado neste ambiente." >&2
  exit 2
fi

marketplaces_json="$(codex plugin marketplace list --json)"
if ! jq -e '[.. | strings] | index("codework-codex") != null' >/dev/null <<<"$marketplaces_json"; then
  codex plugin marketplace add "$REPO_ROOT" --json >/dev/null
fi
marketplaces_json="$(codex plugin marketplace list --json)"
jq -e '[.. | strings] | index("codework-codex") != null' >/dev/null <<<"$marketplaces_json" || {
  echo "ERROR: marketplace codework-codex não foi confirmado após registro." >&2
  exit 3
}

plugins_json="$(codex plugin list --marketplace codework-codex --json)"
if ! jq -e '[.. | strings] | index("coderabbit") != null' >/dev/null <<<"$plugins_json"; then
  codex plugin add coderabbit@codework-codex --json >/dev/null
fi
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
jq -e '[.. | strings] | index("coderabbit") != null' >/dev/null <<<"$plugins_json" || {
  echo "ERROR: plugin coderabbit não foi confirmado no marketplace codework-codex." >&2
  exit 3
}

if ! command -v coderabbit >/dev/null 2>&1; then
  cat >&2 <<EOF
ERROR: CodeRabbit CLI não está pré-instalado.
Este script não executa instalador remoto via curl|sh e não aceita artefato sem checksum.
Provisione previamente a versão ${CODERABBIT_VERSION} por um canal verificado e execute novamente.
EOF
  exit 4
fi

observed_version="$(coderabbit --version 2>&1)"
case "$observed_version" in
  *"${CODERABBIT_VERSION}"*) ;;
  *)
    echo "ERROR: CodeRabbit CLI fora da versão fixada ${CODERABBIT_VERSION}: ${observed_version}" >&2
    exit 5
    ;;
esac

if [[ -n "$CODERABBIT_BINARY_SHA256" ]]; then
  coderabbit_path="$(command -v coderabbit)"
  observed_sha256="$(sha256sum "$coderabbit_path" | awk '{print $1}')"
  [[ "$observed_sha256" == "$CODERABBIT_BINARY_SHA256" ]] || {
    echo "ERROR: SHA256 do binário CodeRabbit não corresponde ao valor aprovado." >&2
    exit 6
  }
fi

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

marketplaces_json="$(codex plugin marketplace list --json)"
plugins_json="$(codex plugin list --marketplace codework-codex --json)"
jq -e '[.. | strings] | index("codework-codex") != null' >/dev/null <<<"$marketplaces_json"
jq -e '[.. | strings] | index("coderabbit") != null' >/dev/null <<<"$plugins_json"

echo "CodeRabbit Codex plugin + CLI configurados para este workspace. Reinicie/abra nova sessão do Codex antes de usar o plugin."
