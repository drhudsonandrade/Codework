#!/usr/bin/env bash
set -euo pipefail

: "${REF_ROOT:?Set REF_ROOT to the approved GRCh38 directory}"
fasta="$REF_ROOT/Homo_sapiens_assembly38.fasta"
[[ -s "$fasta" ]] || { echo 'bwa_functional_gate\tFAIL\treason=fasta_missing'; exit 2; }
for suffix in .0123 .amb .ann .bwt.2bit.64 .pac; do
  [[ -s "${fasta}${suffix}" ]] || { printf 'bwa_functional_gate\tFAIL\tmissing=%s\n' "${fasta}${suffix}"; exit 3; }
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
seq=$(samtools faidx "$fasta" chr1:1000000-1000150 | tail -n +2 | tr -d '\r\n')
[[ ${#seq} -eq 151 ]] || { printf 'bwa_functional_gate\tFAIL\treason=probe_sequence_length\tobserved=%d\n' "${#seq}"; exit 4; }
printf '@grch38-index-probe\n%s\n+\n' "$seq" > "$tmp/probe.fastq"
printf '%*s\n' "${#seq}" '' | tr ' ' 'I' >> "$tmp/probe.fastq"

bwa-mem2 mem -t 1 "$fasta" "$tmp/probe.fastq" > "$tmp/probe.sam" 2> "$tmp/bwa.stderr"
rname=$(awk '$0 !~ /^@/ {print $3; exit}' "$tmp/probe.sam")
flag=$(awk '$0 !~ /^@/ {print $2; exit}' "$tmp/probe.sam")
[[ -n "$rname" && "$rname" != '*' ]] || { echo 'bwa_functional_gate\tFAIL\treason=probe_unmapped'; exit 5; }
if (( flag & 4 )); then
  echo 'bwa_functional_gate\tFAIL\treason=probe_flag_unmapped'
  exit 6
fi
printf 'bwa_functional_gate\tPASS\trname=%s\tprobe_length=%d\n' "$rname" "${#seq}"
