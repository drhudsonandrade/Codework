#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: Codex CLI não encontrado neste ambiente." >&2
  exit 2
fi

# Este marketplace fica dentro do repositório, portanto precisa ser registrado
# explicitamente no Codex antes da instalação do plugin.
codex plugin marketplace add "$REPO_ROOT" --json

codex plugin add coderabbit@codework-codex --json

if ! command -v coderabbit >/dev/null 2>&1; then
  curl -fsSL https://cli.coderabbit.ai/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

coderabbit --version

if ! coderabbit auth status --agent >/dev/null 2>&1; then
  echo "CodeRabbit CLI precisa de autenticação interativa uma única vez." >&2
  coderabbit auth login --agent
fi

coderabbit auth status --agent
codex plugin marketplace list --json
codex plugin list --marketplace codework-codex --json

echo "CodeRabbit Codex plugin + CLI configurados para este workspace. Reinicie/abra nova sessão do Codex antes de usar o plugin."
