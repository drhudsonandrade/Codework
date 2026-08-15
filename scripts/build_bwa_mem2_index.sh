#!/usr/bin/env bash
set -euo pipefail

: "${REF_ROOT:?Set REF_ROOT to the persistent GRCh38 directory}"
readonly FASTA="$REF_ROOT/Homo_sapiens_assembly38.fasta"
readonly APPROVED_LOCK="$REF_ROOT/GRCh38.lock.sha256.approved"
readonly MIN_RAM_GIB=${BWA_INDEX_MIN_RAM_GIB:-96}
readonly MIN_DISK_GIB=${BWA_INDEX_MIN_DISK_GIB:-100}

[[ -s "$FASTA" ]] || { printf 'reference FASTA missing: %s\n' "$FASTA" >&2; exit 2; }
[[ -s "$APPROVED_LOCK" ]] || { printf 'externally approved lock missing: %s\n' "$APPROVED_LOCK" >&2; exit 3; }
(
  cd "$REF_ROOT"
  sha256sum --check --strict "$(basename "$APPROVED_LOCK")"
)

available_kib=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
required_kib=$((MIN_RAM_GIB * 1024 * 1024))
if (( available_kib < required_kib )); then
  printf 'resource_gate\tFAIL\treason=ram\tavailable_kib=%d\trequired_kib=%d\n' "$available_kib" "$required_kib" >&2
  exit 4
fi

available_disk_kib=$(df -Pk "$REF_ROOT" | awk 'NR == 2 {print $4}')
required_disk_kib=$((MIN_DISK_GIB * 1024 * 1024))
if (( available_disk_kib < required_disk_kib )); then
  printf 'resource_gate\tFAIL\treason=disk\tavailable_kib=%d\trequired_kib=%d\n' "$available_disk_kib" "$required_disk_kib" >&2
  exit 5
fi

printf 'resource_gate\tPASS\tram_gib=%s\tdisk_gib=%s\n' "$MIN_RAM_GIB" "$MIN_DISK_GIB"
bwa-mem2 index "$FASTA"

indexes=(
  "${FASTA}.0123"
  "${FASTA}.amb"
  "${FASTA}.ann"
  "${FASTA}.bwt.2bit.64"
  "${FASTA}.pac"
)
for index in "${indexes[@]}"; do
  [[ -s "$index" ]] || { printf 'expected bwa-mem2 index missing: %s\n' "$index" >&2; exit 6; }
done
sha256sum "${indexes[@]}" > "$REF_ROOT/bwa_mem2_indexes.sha256"
printf 'bwa_mem2_index\tPASS\tfiles=%d\n' "${#indexes[@]}"
