#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly MANIFEST=${RULESET_MANIFEST:-"$PROJECT_ROOT/manifests/RULESET_V3.3.sha256"}
readonly CANONICAL_NAME=REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt
readonly RULESET_PATH=${1:?Usage: verify_ruleset.sh /secure/path/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt}

[[ "$(basename "$RULESET_PATH")" == "$CANONICAL_NAME" ]] || {
  printf 'ruleset_identity\tFAIL\treason=unexpected_filename\n' >&2
  exit 2
}
[[ -s "$RULESET_PATH" ]] || {
  printf 'ruleset_identity\tFAIL\treason=missing_or_empty\n' >&2
  exit 3
}

expected=$(awk -v name="$CANONICAL_NAME" '$2 == name {print $1}' "$MANIFEST")
[[ "$expected" =~ ^[0-9a-f]{64}$ ]] || {
  printf 'ruleset_hash\tFAIL\treason=invalid_external_manifest\n' >&2
  exit 4
}
observed=$(sha256sum "$RULESET_PATH" | awk '{print $1}')
[[ "$observed" == "$expected" ]] || {
  printf 'ruleset_hash\tFAIL\texpected=%s\tobserved=%s\n' "$expected" "$observed" >&2
  exit 5
}

grep -Fxq 'STATUS NORMATIVO: VIGENTE' "$RULESET_PATH"
grep -Fxq 'VERSÃO NORMATIVA: v3.3' "$RULESET_PATH"
grep -Fxq 'DATA FORMAL DE EMISSÃO E VIGÊNCIA: 14/08/2026' "$RULESET_PATH"
grep -Fxq 'IDENTIFICADOR NORMATIVO: GENOMA-HUDSON-RULESET-v3.3' "$RULESET_PATH"

printf 'ruleset_hash\tPASS\tsha256=%s\n' "$observed"
printf 'ruleset_header\tPASS\tstatus=VIGENTE\tversion=v3.3\tdate=14/08/2026\n'
printf 'deployment_gate\tPENDING\treason=project_source_bootstrap_and_live_smoke_15_of_15_required\n'
