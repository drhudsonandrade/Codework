#!/usr/bin/env bash
set -euo pipefail

IMAGE_REF="${1:-}"
DEST="${2:-/srv/genoma/refs/materialized}"

[[ "$IMAGE_REF" =~ ^ghcr\.io/.+@sha256:[0-9a-f]{64}$ ]] || { echo 'invalid immutable reference image' >&2; exit 2; }
command -v docker >/dev/null || { echo 'NÃO DISPONÍVEL: docker missing' >&2; exit 2; }

if [[ -s "$DEST/.genoma-reference-image" ]] && [[ "$(tr -d '[:space:]' < "$DEST/.genoma-reference-image")" == "$IMAGE_REF" ]]; then
  echo "$DEST"
  exit 0
fi

parent=$(dirname "$DEST")
mkdir -p "$parent"
tmp=$(mktemp -d "$parent/.genoma-ref.XXXXXX")
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT

docker pull "$IMAGE_REF" >/dev/null
cid=$(docker create "$IMAGE_REF")
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true; cleanup' EXIT
docker cp "$cid:/refs/." "$tmp/"
docker rm -f "$cid" >/dev/null
trap cleanup EXIT

test -s "$tmp/GRCh38.bundle.sha256" || { echo 'reference image lacks bundle lock' >&2; exit 1; }
(
  cd "$tmp"
  sha256sum -c GRCh38.bundle.sha256
)
printf '%s\n' "$IMAGE_REF" > "$tmp/.genoma-reference-image"
chmod -R a-w "$tmp"
rm -rf "$DEST.old"
if [[ -e "$DEST" ]]; then mv "$DEST" "$DEST.old"; fi
mv "$tmp" "$DEST"
trap - EXIT
rm -rf "$DEST.old"
echo "$DEST"
