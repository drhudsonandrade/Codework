#!/usr/bin/env bash
set -euo pipefail

manifest=${1:?sample manifest required}
ref=${2:?reference fasta required}
out=${3:?output BAM required}
input_qc=${4:?verified input-qc.json required}

# `pwd -P` because the gate records physically resolved paths: with a symlinked sample
# directory the logical `pwd` prints the link and the containment test below then rejects
# every verified input, or — worse, if the link is repointed — accepts one from elsewhere.
sample_dir=$(cd -P "$(dirname "$manifest")" && pwd -P)

# The gate resolved, contained and hashed the inputs. This script used to ignore all of that
# and re-read the raw manifest with jq, explicitly honouring an absolute path and checking no
# digest — so whatever containment the gate established stopped at its own process boundary
# and alignment consumed a path nobody had verified. Every input below now comes from
# input-qc.json, is re-checked to sit inside the sample directory, and must still hash to
# what the gate recorded.
[[ "$(jq -r '.status' "$input_qc")" == "VERIFICADO" ]] || {
  echo "NÃO DISPONÍVEL: input gate did not verify this sample" >&2; exit 2; }

# `/dev/fd` is how a verified input reaches the aligner as bytes rather than as a name; a
# kernel without it cannot make that binding, and the pipeline refuses rather than falling
# back to the name it just finished proving it cannot trust.
[[ -r /dev/fd/0 ]] || { echo 'NÃO DISPONÍVEL: /dev/fd unavailable, cannot bind verified inputs' >&2; exit 2; }

open_verified() {
  # $1 = key under .inputs, $2 = name of the variable that receives the descriptor path.
  #
  # Hashing the name and then handing the same name to bwa-mem2/samtools proves nothing:
  # sha256sum certifies the bytes at one instant, the tools open the name again later, and
  # anything able to write in the sample directory can repoint the file — or a parent
  # directory — in between. So the file is opened once, here, in the *calling* shell; the
  # digest is taken through that descriptor; and the tools are given `/dev/fd/N`, which on
  # Linux reopens the inode the descriptor already holds instead of walking the name again.
  # The bytes the aligner reads are therefore the bytes that matched the gate's digest.
  # `printf -v` rather than an echoed value because a command substitution runs in a
  # subshell and the descriptor would die with it.
  local key="$1" outvar="$2" path digest observed fd relative
  path=$(jq -r --arg k "$key" '.inputs[$k].path // empty' "$input_qc")
  digest=$(jq -r --arg k "$key" '.inputs[$k].sha256 // empty' "$input_qc")
  [[ -n "$path" && -n "$digest" ]] || {
    echo "NÃO DISPONÍVEL: input-qc.json records no verified $key" >&2; return 3; }
  case "$path" in
    "$sample_dir"/*) ;;
    *) echo "NÃO DISPONÍVEL: verified $key is outside the sample directory" >&2; return 3 ;;
  esac
  relative=${path#"$sample_dir"/}
  case "/$relative/" in
    */../*) echo "NÃO DISPONÍVEL: verified $key is outside the sample directory" >&2; return 3 ;;
  esac
  exec {fd}< "$path" || {
    echo "NÃO DISPONÍVEL: verified $key is missing or unreadable" >&2; return 3; }
  observed=$(sha256sum "/dev/fd/$fd" | cut -d" " -f1)
  [[ "$observed" == "$digest" ]] || {
    exec {fd}<&-
    echo "NÃO DISPONÍVEL: $key changed after the gate verified it" >&2; return 3; }
  printf -v "$outvar" '/dev/fd/%s' "$fd"
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
    open_verified r1 r1
    open_verified r2 r2
    rg=$(printf '@RG\tID:%s\tSM:%s\tLB:%s\tPL:%s\tPU:%s' "$rgid" "$sample" "$library" "$platform" "$platform_unit")
    bwa-mem2 mem -R "$rg" -t "${WGS_THREADS:-8}" "$ref" "$r1" "$r2" \
      | samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" -
    ;;
  BAM)
    open_verified alignment source
    samtools quickcheck -v "$source"
    samtools sort -@ "${WGS_SORT_THREADS:-4}" -o "$out" "$source"
    ;;
  CRAM)
    open_verified alignment source
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
