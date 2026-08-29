#!/usr/bin/env bash
set -euo pipefail

manifest=${1:?sample manifest required}
ref=${2:?reference fasta required}
out=${3:?output BAM required}
input_qc=${4:?verified input-qc.json required}

sample_dir=$(cd "$(dirname "$manifest")" && pwd)

# The gate resolved, contained and hashed the inputs. This script used to ignore all of that
# and re-read the raw manifest with jq, explicitly honouring an absolute path and checking no
# digest — so whatever containment the gate established stopped at its own process boundary
# and alignment consumed a path nobody had verified. Every input below now comes from
# input-qc.json, is re-checked to sit inside the sample directory, and must still hash to
# what the gate recorded.
[[ "$(jq -r '.status' "$input_qc")" == "VERIFICADO" ]] || {
  echo "NÃO DISPONÍVEL: input gate did not verify this sample" >&2; exit 2; }

verified_input() {
  # $1 = key under .inputs; echoes the path, or exits non-zero with a reason.
  local key="$1" path digest observed
  path=$(jq -r --arg k "$key" '.inputs[$k].path // empty' "$input_qc")
  digest=$(jq -r --arg k "$key" '.inputs[$k].sha256 // empty' "$input_qc")
  [[ -n "$path" && -n "$digest" ]] || {
    echo "NÃO DISPONÍVEL: input-qc.json records no verified $key" >&2; return 3; }
  case "$path" in
    "$sample_dir"/*) ;;
    *) echo "NÃO DISPONÍVEL: verified $key is outside the sample directory" >&2; return 3 ;;
  esac
  [[ -s "$path" ]] || { echo "NÃO DISPONÍVEL: verified $key is missing or empty" >&2; return 3; }
  observed=$(sha256sum "$path" | cut -d" " -f1)
  [[ "$observed" == "$digest" ]] || {
    echo "NÃO DISPONÍVEL: $key changed after the gate verified it" >&2; return 3; }
  printf '%s' "$path"
}
input_type=$(jq -r '.input_type | ascii_upcase' "$manifest")
sample=$(jq -r '.sample_id' "$manifest")
rgid=$(jq -r '.read_group.id' "$manifest")
library=$(jq -r '.read_group.library' "$manifest")
platform=$(jq -r '.read_group.platform' "$manifest")
platform_unit=$(jq -r '.read_group.platform_unit // "GENOMA"' "$manifest")

[[ -s "$ref" ]] || { echo "NÃO DISPONÍVEL: reference FASTA missing" >&2; exit 2; }
[[ -n "$sample" && "$sample" != null ]] || { echo "NÃO DISPONÍVEL: sample_id missing" >&2; exit 2; }
mkdir -p "$(dirname "$out")"

case "$input_type" in
  FASTQ)
    r1=$(verified_input r1)
    r2=$(verified_input r2)
    rg=$(printf '@RG\tID:%s\tSM:%s\tLB:%s\tPL:%s\tPU:%s' "$rgid" "$sample" "$library" "$platform" "$platform_unit")
    bwa-mem2 mem -R "$rg" -t "${WGS_THREADS:-8}" "$ref" "$r1" "$r2" \
      | samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" -
    ;;
  BAM)
    source=$(verified_input alignment)
    samtools quickcheck -v "$source"
    samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" "$source"
    ;;
  CRAM)
    source=$(verified_input alignment)
    samtools quickcheck -v "$source"
    samtools view -T "$ref" -b "$source" | samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" -
    ;;
  *)
    echo "NÃO DISPONÍVEL: unsupported input_type=$input_type" >&2
    exit 4
    ;;
esac

samtools index -@ "${WGS_SORT_THREADS:-4}" "$out"
samtools quickcheck -v "$out"
samtools view -H "$out" | grep -q '^@RG' || { echo 'NÃO DISPONÍVEL: output BAM lacks @RG' >&2; exit 5; }
rg_samples=$(samtools view -H "$out" | awk -F '\t' '$1=="@RG" {for(i=1;i<=NF;i++) if($i ~ /^SM:/){sub(/^SM:/,"",$i); print $i}}' | sort -u)
[[ "$rg_samples" = "$sample" ]] || { echo "NÃO DISPONÍVEL: BAM SM does not match declared sample" >&2; exit 6; }
