#!/usr/bin/env bash
set -euo pipefail

failures=0

check_version() {
  local tool="$1"
  local expected="$2"
  shift 2
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf '%s\tMISSING\texpected=%s\n' "$tool" "$expected"
    failures=$((failures + 1))
    return
  fi
  local output
  if ! output=$("$@" 2>&1); then
    printf '%s\tERROR\texpected=%s\n' "$tool" "$expected"
    failures=$((failures + 1))
    return
  fi
  local first_line
  first_line=$(printf '%s\n' "$output" | head -n 1)
  if [[ "$output" != *"$expected"* ]]; then
    printf '%s\tMISMATCH\texpected=%s\tobserved=%s\n' "$tool" "$expected" "$first_line"
    failures=$((failures + 1))
    return
  fi
  printf '%s\tPASS\texpected=%s\tobserved=%s\tpath=%s\n' \
    "$tool" "$expected" "$first_line" "$(command -v "$tool")"
}

check_version java '17.' java -version
check_version samtools '1.24' samtools --version
check_version bcftools '1.24' bcftools --version
check_version bwa-mem2 '2.2.1' bwa-mem2 version
check_version gatk '4.6.2.0' gatk --version
check_version nextflow '26.04.6' nextflow -version
check_version snakemake '7.32.4' snakemake --version

if (( failures > 0 )); then
  printf 'runtime_gate\tFAIL\tfailures=%d\n' "$failures"
  exit 1
fi
printf 'runtime_gate\tPASS\tfailures=0\n'
