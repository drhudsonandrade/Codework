#!/usr/bin/env bash
set -euo pipefail

manifest=${1:?sample manifest required}
ref=${2:?reference fasta required}
out=${3:?output BAM required}
input_qc=${4:?verified input-qc.json required}

script_dir=$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
materializer="$script_dir/wgs_materialize_verified_input.py"

# `pwd -P` because the gate records physically resolved paths: with a symlinked sample
# directory the logical `pwd` prints the link and the containment test below then rejects
# every verified input, or — worse, if the link is repointed — accepts one from elsewhere.
sample_dir=$(cd -P "$(dirname "$manifest")" && pwd -P)

# The alignment boundary consumes only this gate schema. A foreign or malformed JSON record
# must not be able to become authority merely by carrying a VERIFICADO status string.
[[ "$(jq -r '.schema // empty' "$input_qc")" == "genoma-wgs-input-gate-v1" ]] || {
  echo "NÃO DISPONÍVEL: unexpected input gate schema" >&2; exit 2; }

# The gate resolved, contained and hashed the inputs. This script used to ignore all of that
# and re-read the raw manifest with jq, explicitly honouring an absolute path and checking no
# digest — so whatever containment the gate established stopped at its own process boundary
# and alignment consumed a path nobody had verified. Every input below now comes from
# input-qc.json, is re-checked to sit inside the sample directory, and must still hash to
# what the gate recorded.
[[ "$(jq -r '.status' "$input_qc")" == "VERIFICADO" ]] || {
  echo "NÃO DISPONÍVEL: input gate did not verify this sample" >&2; exit 2; }

# The secure materializer reuses the gate's component-by-component opener, which applies
# O_NOFOLLOW to every component, O_NONBLOCK to the final open, and S_ISREG to that same
# descriptor. That prevents a post-gate FIFO/device/symlink replacement from either blocking
# this process or becoming an authorized WGS input. The verified bytes are copied into a
# private task directory; only that controlled regular file is opened by Bash afterwards.
command -v python3 >/dev/null || {
  echo 'NÃO DISPONÍVEL: python3 unavailable for verified input staging' >&2; exit 2; }
[[ -f "$materializer" ]] || {
  echo 'NÃO DISPONÍVEL: verified input materializer unavailable' >&2; exit 2; }
[[ -r /dev/fd/0 ]] || {
  echo 'NÃO DISPONÍVEL: /dev/fd unavailable, cannot bind verified inputs' >&2; exit 2; }

open_verified() {
  # $1 = key under .inputs, $2 = name of the variable that receives the descriptor path.
  #
  # The sample pathname is never opened with a blocking Bash redirection. Python opens it
  # through `open_contained`, materializes the already-open regular file to a private task
  # file while hashing the same source descriptor, and only publishes that stage file when
  # the digest equals the gate record. Bash then opens the private file and tools receive
  # `/dev/fd/N`, so downstream still consumes an inode-bound descriptor rather than a mutable
  # sample pathname.
  local key="$1" outvar="$2" path digest fd relative staged rc
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

  staged="$verified_stage/$key"
  if python3 "$materializer" \
      --root "$sample_dir" \
      --source "$path" \
      --expected-sha256 "$digest" \
      --output "$staged"; then
    :
  else
    rc=$?
    if [[ "$rc" -eq 4 ]]; then
      echo "NÃO DISPONÍVEL: $key changed after the gate verified it" >&2
    else
      echo "NÃO DISPONÍVEL: verified $key is missing, unreadable, or unsafe" >&2
    fi
    return 3
  fi

  exec {fd}< "$staged" || {
    echo "NÃO DISPONÍVEL: verified $key staging could not be opened" >&2; return 3; }
  printf -v "$outvar" '/dev/fd/%s' "$fd"
}

# The gate already validated and snapshotted this identity. Re-reading the mutable raw
# manifest here would let post-gate edits change the read group actually handed to the
# aligner while the pipeline still claimed to be consuming the VERIFICADO record.
input_type=$(jq -r '.input_type | ascii_upcase' "$input_qc")
sample=$(jq -r '.sample_id' "$input_qc")
rgid=$(jq -r '.read_group.id' "$input_qc")
library=$(jq -r '.read_group.library' "$input_qc")
platform=$(jq -r '.read_group.platform' "$input_qc")
platform_unit=$(jq -r '.read_group.platform_unit // "GENOMA"' "$input_qc")

[[ -s "$ref" ]] || { echo "NÃO DISPONÍVEL: reference FASTA missing" >&2; exit 2; }
[[ -n "$sample" && "$sample" != null ]] || { echo "NÃO DISPONÍVEL: sample_id missing" >&2; exit 2; }
mkdir -p "$(dirname "$out")"
verified_stage=$(mktemp -d "$(dirname "$out")/.verified-inputs.XXXXXX")
chmod 0700 "$verified_stage"
cleanup_verified_stage() {
  rm -rf -- "$verified_stage"
}
trap cleanup_verified_stage EXIT

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
