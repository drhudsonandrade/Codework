#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HELPER="$ROOT/scripts/ci_changed_paths.sh"
test -f "$HELPER"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git -C "$tmp" init -q
git -C "$tmp" config user.email test@example.invalid
git -C "$tmp" config user.name "CI Contract"
mkdir -p "$tmp/docs"
printf 'one\n' > "$tmp/docs/note.md"
printf 'stable\n' > "$tmp/unchanged.txt"
git -C "$tmp" add .
git -C "$tmp" commit -qm base
base=$(git -C "$tmp" rev-parse HEAD)
printf 'two\n' >> "$tmp/docs/note.md"
printf 'code\n' > "$tmp/runtime.py"
git -C "$tmp" add .
git -C "$tmp" commit -qm change
head=$(git -C "$tmp" rev-parse HEAD)
changed="$tmp/changed.zlist"
deleted="$tmp/deleted.zlist"
(cd "$tmp" && bash "$HELPER" "$base" "$head" "$changed" "$deleted")
mapfile -d '' -t changed_paths < "$changed"
mapfile -d '' -t deleted_paths < "$deleted"
printf '%s\n' "${changed_paths[@]}" | grep -Fx 'docs/note.md' >/dev/null
printf '%s\n' "${changed_paths[@]}" | grep -Fx 'runtime.py' >/dev/null
test "${#changed_paths[@]}" -eq 2
if printf '%s\n' "${changed_paths[@]}" | grep -Fx 'unchanged.txt' >/dev/null; then
  echo 'unchanged file incorrectly reported by non-null diff' >&2
  exit 1
fi
test "${#deleted_paths[@]}" -eq 0

null_sha=0000000000000000000000000000000000000000
(cd "$tmp" && bash "$HELPER" "$null_sha" "$head" "$changed" "$deleted")
mapfile -d '' -t changed_paths < "$changed"
mapfile -d '' -t deleted_paths < "$deleted"
printf '%s\n' "${changed_paths[@]}" | grep -Fx 'docs/note.md' >/dev/null
printf '%s\n' "${changed_paths[@]}" | grep -Fx 'runtime.py' >/dev/null
printf '%s\n' "${changed_paths[@]}" | grep -Fx 'unchanged.txt' >/dev/null
test "${#changed_paths[@]}" -eq 3
test "${#deleted_paths[@]}" -eq 0

git -C "$tmp" rm -q runtime.py
git -C "$tmp" commit -qm deletion
next=$(git -C "$tmp" rev-parse HEAD)
(cd "$tmp" && bash "$HELPER" "$head" "$next" "$changed" "$deleted")
mapfile -d '' -t deleted_paths < "$deleted"
printf '%s\n' "${deleted_paths[@]}" | grep -Fx 'runtime.py' >/dev/null

echo 'ci changed-path helper: PASS'
