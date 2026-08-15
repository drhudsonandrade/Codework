#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly MANIFEST=${GRCH38_MANIFEST:-"$PROJECT_ROOT/manifests/GRCh38.sources.tsv"}
: "${REF_ROOT:?Set REF_ROOT to the persistent GRCh38 directory, for example /srv/genome/refs}"

mkdir -p "$REF_ROOT"
if [[ ! -f "$MANIFEST" ]]; then
  printf 'manifest not found: %s\n' "$MANIFEST" >&2
  exit 2
fi

download_direct() {
  local url="$1"
  local target="$2"
  local partial="${target}.partial"
  if [[ -s "$target" ]]; then
    return
  fi
  curl --fail --location --retry 5 --retry-all-errors --continue-at - \
    --output "$partial" "$url"
  if [[ ! -s "$partial" ]]; then
    printf 'download produced an empty file: %s\n' "$url" >&2
    exit 3
  fi
  mv "$partial" "$target"
}

verify_existing_against_approved_lock() {
  local target_name="$1"
  local target_path="$REF_ROOT/$target_name"
  local approved="$REF_ROOT/GRCh38.lock.sha256.approved"
  if [[ ! -e "$target_path" || ! -f "$approved" ]]; then
    return
  fi
  local expected
  expected=$(awk -v name="$target_name" '$2 == name {print $1}' "$approved")
  if [[ -z "$expected" ]]; then
    printf 'approved lock has no entry for %s\n' "$target_name" >&2
    exit 4
  fi
  local observed
  observed=$(sha256sum "$target_path" | awk '{print $1}')
  if [[ "$expected" != "$observed" ]]; then
    printf 'existing artifact does not match approved lock: %s\n' "$target_name" >&2
    exit 5
  fi
}

while IFS=$'\t' read -r artifact_id target url transform provider build; do
  [[ "$artifact_id" == "artifact_id" ]] && continue
  [[ -z "$artifact_id" ]] && continue
  verify_existing_against_approved_lock "$target"
  case "$transform" in
    direct)
      printf 'acquire\t%s\t%s\t%s\t%s\n' "$artifact_id" "$provider" "$build" "$target"
      download_direct "$url" "$REF_ROOT/$target"
      ;;
    bgzip_tabix)
      printf 'acquire-transform\t%s\t%s\t%s\t%s\n' "$artifact_id" "$provider" "$build" "$target"
      if [[ ! -s "$REF_ROOT/$target" ]]; then
        source_vcf="$REF_ROOT/${target%.gz}.source"
        download_direct "$url" "$source_vcf"
        bgzip --threads "${BGZIP_THREADS:-4}" --stdout "$source_vcf" > "$REF_ROOT/${target}.partial"
        mv "$REF_ROOT/${target}.partial" "$REF_ROOT/$target"
        rm -f "$source_vcf"
      fi
      tabix --force --preset vcf "$REF_ROOT/$target"
      ;;
    generated_tbi)
      if [[ ! -s "$REF_ROOT/$target" ]]; then
        printf 'generated index missing after parent VCF transform: %s\n' "$target" >&2
        exit 6
      fi
      ;;
    *)
      printf 'unsupported manifest transform: %s\n' "$transform" >&2
      exit 7
      ;;
  esac
done < "$MANIFEST"

mapfile -t targets < <(awk -F '\t' 'NR > 1 && NF {print $2}' "$MANIFEST")
for target in "${targets[@]}"; do
  [[ -s "$REF_ROOT/$target" ]] || { printf 'required artifact missing: %s\n' "$target" >&2; exit 8; }
done

(
  cd "$REF_ROOT"
  sha256sum "${targets[@]}" > GRCh38.lock.sha256.pending
)
printf 'resource_acquisition\tPASS\tartifacts=%d\n' "${#targets[@]}"
printf 'approval_gate\tPENDING\tlock=%s\n' "$REF_ROOT/GRCh38.lock.sha256.pending"
