#!/usr/bin/env bash
set -euo pipefail

manifest=${1:?sample manifest required}
ref=${2:?reference fasta required}
out=${3:?output BAM required}

sample_dir=$(cd "$(dirname "$manifest")" && pwd)
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
    r1=$(jq -r '.r1' "$manifest")
    r2=$(jq -r '.r2' "$manifest")
    [[ "$r1" = /* ]] || r1="$sample_dir/$r1"
    [[ "$r2" = /* ]] || r2="$sample_dir/$r2"
    [[ -s "$r1" && -s "$r2" ]] || { echo "NÃO DISPONÍVEL: paired FASTQ missing" >&2; exit 3; }
    rg=$(printf '@RG\tID:%s\tSM:%s\tLB:%s\tPL:%s\tPU:%s' "$rgid" "$sample" "$library" "$platform" "$platform_unit")
    bwa-mem2 mem -R "$rg" -t "${WGS_THREADS:-8}" "$ref" "$r1" "$r2" \
      | samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" -
    ;;
  BAM)
    source=$(jq -r '.alignment' "$manifest")
    [[ "$source" = /* ]] || source="$sample_dir/$source"
    samtools quickcheck -v "$source"
    samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" "$source"
    ;;
  CRAM)
    source=$(jq -r '.alignment' "$manifest")
    [[ "$source" = /* ]] || source="$sample_dir/$source"
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
