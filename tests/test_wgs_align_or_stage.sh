#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
align_script="$repo_root/scripts/wgs_align_or_stage.sh"

for tool in bash jq sha256sum readlink; do
  command -v "$tool" >/dev/null || { echo "FAIL: $tool unavailable" >&2; exit 1; }
done
bash_bin=$(command -v bash)
[[ "$bash_bin" = /* ]] || { echo 'FAIL: absolute bash path unavailable' >&2; exit 1; }
[[ -r /dev/fd/0 ]] || { echo 'FAIL: /dev/fd unavailable' >&2; exit 1; }

root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_contains() { [[ "$1" == *"$2"* ]] || fail "expected <$2> in <$1>"; }
assert_not_contains() { [[ "$1" != *"$2"* ]] || fail "unexpected <$2> in <$1>"; }
assert_no_tools() { [[ ! -s "$1" ]] || fail "alignment tools ran before refusal: $(cat "$1")"; }

make_stubs() {
  local dir=$1
  mkdir -p "$dir"
  cat >"$dir/samtools" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "samtools $*" >> "$STUB_LOG"
sub=$1; shift
case "$sub" in
  sort)
    out=''; src=''
    while (($#)); do
      case "$1" in -@) shift 2;; -o) out=$2; shift 2;; *) src=$1; shift;; esac
    done
    if [[ -z "$src" || "$src" == '-' ]]; then cat >"$out"; else cat "$src" >"$out"; fi
    ;;
  view)
    if [[ " $* " == *" -H "* ]]; then
      printf '@HD\tVN:1.6\n@RG\tID:RG1\tSM:%s\n' "$STUB_SAMPLE"
    else
      cat "${@: -1}"
    fi
    ;;
  index|quickcheck) : ;;
  *) exit 90;;
esac
SH
  cat >"$dir/bwa-mem2" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "bwa-mem2 $*" >> "$STUB_LOG"
if [[ -n "${STUB_SWAP_TARGET:-}" ]]; then
  rm -f "$STUB_SWAP_TARGET"
  printf 'SWAPPED-BY-THE-ATTACKER\n' >"$STUB_SWAP_TARGET"
fi
cat "${@: -2:1}" >"$STUB_R1_SEEN"
cat "${@: -1}" >"$STUB_R2_SEEN"
printf 'ALIGNED\n'
SH
  chmod 0755 "$dir/samtools" "$dir/bwa-mem2"
}

fixture() {
  local case_root=$1 status=${2:-VERIFICADO}
  local sample_dir="$case_root/sample"
  mkdir -p "$sample_dir" "$case_root/bin"
  printf '@read1\nACGT\n+\nIIII\n' >"$sample_dir/r1.fastq"
  printf '@read1\nTGCA\n+\nIIII\n' >"$sample_dir/r2.fastq"
  printf '>chr1\nACGT\n' >"$case_root/ref.fasta"
  cat >"$sample_dir/sample-manifest.json" <<'JSON'
{"sample_id":"S1","input_type":"FASTQ","r1":"r1.fastq","r2":"r2.fastq","read_group":{"id":"RG1","sample":"S1","library":"L1","platform":"ILLUMINA"}}
JSON
  make_stubs "$case_root/bin"
  local r1_digest r2_digest
  r1_digest=$(sha256sum "$sample_dir/r1.fastq" | cut -d' ' -f1)
  r2_digest=$(sha256sum "$sample_dir/r2.fastq" | cut -d' ' -f1)
  jq -n --arg status "$status" --arg r1 "$sample_dir/r1.fastq" --arg r2 "$sample_dir/r2.fastq" --arg d1 "$r1_digest" --arg d2 "$r2_digest" \
    '{schema:"genoma-wgs-input-gate-v1",status:$status,sample_id:"S1",input_type:"FASTQ",read_group:{id:"RG1",sample:"S1",library:"L1",platform:"ILLUMINA"},inputs:{r1:{path:$r1,sha256:$d1},r2:{path:$r2,sha256:$d2}}}' >"$case_root/input-qc.json"
}

alignment_fixture() {
  local case_root=$1 input_type=$2 status=${3:-VERIFICADO}
  local sample_dir="$case_root/sample" extension alignment digest
  case "$input_type" in
    BAM) extension=bam ;;
    CRAM) extension=cram ;;
    *) fail "unsupported alignment fixture type: $input_type" ;;
  esac
  mkdir -p "$sample_dir" "$case_root/bin"
  alignment="$sample_dir/alignment.$extension"
  printf 'SYNTHETIC-%s-BYTES\n' "$input_type" >"$alignment"
  printf '>chr1\nACGT\n' >"$case_root/ref.fasta"
  jq -n --arg input_type "$input_type" --arg alignment "alignment.$extension" \
    '{sample_id:"S1",input_type:$input_type,alignment:$alignment,read_group:{id:"RG1",sample:"S1",library:"L1",platform:"ILLUMINA"}}' \
    >"$sample_dir/sample-manifest.json"
  make_stubs "$case_root/bin"
  digest=$(sha256sum "$alignment" | cut -d' ' -f1)
  jq -n --arg status "$status" --arg input_type "$input_type" --arg alignment "$alignment" --arg digest "$digest" \
    '{schema:"genoma-wgs-input-gate-v1",status:$status,sample_id:"S1",input_type:$input_type,read_group:{id:"RG1",sample:"S1",library:"L1",platform:"ILLUMINA"},inputs:{alignment:{path:$alignment,sha256:$digest}}}' >"$case_root/input-qc.json"
}

run_case() {
  local case_root=$1
  STUB_LOG="$case_root/tools.log" \
  STUB_SAMPLE=S1 \
  STUB_R1_SEEN="$case_root/r1.seen" \
  STUB_R2_SEEN="$case_root/r2.seen" \
  PATH="$case_root/bin:$PATH" \
    "$bash_bin" "$align_script" \
      "$case_root/sample/sample-manifest.json" \
      "$case_root/ref.fasta" \
      "$case_root/out/sample.bam" \
      "$case_root/input-qc.json"
}

# Refused gate verdict must stop before any alignment tool.
case_root="$root/status"; fixture "$case_root" 'NÃO DISPONÍVEL'
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'non-VERIFICADO gate unexpectedly passed'
fi
assert_contains "$stderr" 'input gate did not verify this sample'
assert_no_tools "$case_root/tools.log"

# A record from another or malformed gate schema must never be treated as this gate's verdict.
case_root="$root/schema"; fixture "$case_root"
jq '.schema="other-input-gate-v9"' "$case_root/input-qc.json" >"$case_root/qc.tmp"
mv "$case_root/qc.tmp" "$case_root/input-qc.json"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'wrong input gate schema unexpectedly passed'
fi
assert_contains "$stderr" 'input gate schema'
assert_no_tools "$case_root/tools.log"

# Recorded path outside the sample directory must be refused before tools.
case_root="$root/outside"; fixture "$case_root"
printf '@evil\nACGT\n+\nIIII\n' >"$case_root/outside.fastq"
digest=$(sha256sum "$case_root/outside.fastq" | cut -d' ' -f1)
jq --arg p "$case_root/outside.fastq" --arg d "$digest" '.inputs.r1.path=$p | .inputs.r1.sha256=$d' "$case_root/input-qc.json" >"$case_root/qc.tmp"
mv "$case_root/qc.tmp" "$case_root/input-qc.json"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'outside path unexpectedly passed'
fi
assert_contains "$stderr" 'outside the sample directory'
assert_no_tools "$case_root/tools.log"

# A textual `..` traversal must not satisfy the sample-directory prefix check.
case_root="$root/dotdot"; fixture "$case_root"
printf '@evil\nACGT\n+\nIIII\n' >"$case_root/outside.fastq"
digest=$(sha256sum "$case_root/outside.fastq" | cut -d' ' -f1)
traversal_path="$case_root/sample/../outside.fastq"
jq --arg p "$traversal_path" --arg d "$digest" '.inputs.r1.path=$p | .inputs.r1.sha256=$d' "$case_root/input-qc.json" >"$case_root/qc.tmp"
mv "$case_root/qc.tmp" "$case_root/input-qc.json"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'dotdot traversal unexpectedly passed'
fi
assert_contains "$stderr" 'outside the sample directory'
assert_no_tools "$case_root/tools.log"

# A symlink whose textual name is inside the sample must not authorize its outside target.
case_root="$root/symlink-outside"; fixture "$case_root"
printf '@evil\nACGT\n+\nIIII\n' >"$case_root/outside.fastq"
ln -s "$case_root/outside.fastq" "$case_root/sample/r1-link.fastq"
digest=$(sha256sum "$case_root/outside.fastq" | cut -d' ' -f1)
link_path="$case_root/sample/r1-link.fastq"
jq --arg p "$link_path" --arg d "$digest" '.inputs.r1.path=$p | .inputs.r1.sha256=$d' "$case_root/input-qc.json" >"$case_root/qc.tmp"
mv "$case_root/qc.tmp" "$case_root/input-qc.json"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'outside symlink unexpectedly passed'
fi
assert_contains "$stderr" 'outside the sample directory'
assert_no_tools "$case_root/tools.log"

# Digest drift must be caught before tools.
case_root="$root/digest"; fixture "$case_root"
printf '@read1\nTTTT\n+\nIIII\n' >"$case_root/sample/r1.fastq"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'digest mismatch unexpectedly passed'
fi
assert_contains "$stderr" 'changed after the gate verified it'
assert_no_tools "$case_root/tools.log"

# Missing digest means the record does not cover the input.
case_root="$root/missing-digest"; fixture "$case_root"
jq 'del(.inputs.r1.sha256)' "$case_root/input-qc.json" >"$case_root/qc.tmp"
mv "$case_root/qc.tmp" "$case_root/input-qc.json"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'missing digest unexpectedly passed'
fi
assert_contains "$stderr" 'records no verified r1'
assert_no_tools "$case_root/tools.log"

# The harness must not allow its stub-first PATH to replace the interpreter itself.
case_root="$root/bash-hijack"; fixture "$case_root" 'NÃO DISPONÍVEL'
cat >"$case_root/bin/bash" <<'SH'
#!/bin/sh
exit 99
SH
chmod 0755 "$case_root/bin/bash"
if stderr=$(run_case "$case_root" 2>&1); then
  fail 'non-VERIFICADO gate unexpectedly passed'
else
  rc=$?
fi
((rc != 99)) || fail 'stub-first PATH replaced the trusted bash interpreter'
assert_contains "$stderr" 'input gate did not verify this sample'
assert_no_tools "$case_root/tools.log"

# Positive FASTQ path: verified bytes reach the aligner.
case_root="$root/happy"; fixture "$case_root"
run_case "$case_root" >/dev/null
cmp -s "$case_root/r1.seen" "$case_root/sample/r1.fastq" || fail 'R1 bytes did not reach aligner'
cmp -s "$case_root/r2.seen" "$case_root/sample/r2.fastq" || fail 'R2 bytes did not reach aligner'

# Metadata verified by the input gate must not be re-read from a later-mutated manifest.
case_root="$root/metadata-drift"; fixture "$case_root"
jq '.read_group.library="ATTACKER-LIB" | .read_group.platform="ATTACKER-PLATFORM"' \
  "$case_root/sample/sample-manifest.json" >"$case_root/manifest.tmp"
mv "$case_root/manifest.tmp" "$case_root/sample/sample-manifest.json"
run_case "$case_root" >/dev/null
tool_log=$(cat "$case_root/tools.log")
assert_contains "$tool_log" 'LB:L1'
assert_contains "$tool_log" 'PL:ILLUMINA'
assert_not_contains "$tool_log" 'ATTACKER-LIB'
assert_not_contains "$tool_log" 'ATTACKER-PLATFORM'

# TOCTOU regression: repointing the name after digest must not alter bytes read.
case_root="$root/toctou"; fixture "$case_root"
original="$case_root/original-r1"
cp "$case_root/sample/r1.fastq" "$original"
STUB_SWAP_TARGET="$case_root/sample/r1.fastq" \
STUB_LOG="$case_root/tools.log" STUB_SAMPLE=S1 \
STUB_R1_SEEN="$case_root/r1.seen" STUB_R2_SEEN="$case_root/r2.seen" \
PATH="$case_root/bin:$PATH" \
  "$bash_bin" "$align_script" "$case_root/sample/sample-manifest.json" "$case_root/ref.fasta" "$case_root/out/sample.bam" "$case_root/input-qc.json" >/dev/null
assert_contains "$(cat "$case_root/sample/r1.fastq")" 'SWAPPED-BY-THE-ATTACKER'
cmp -s "$case_root/r1.seen" "$original" || fail 'aligner reopened the repointed filename'

# A symlinked sample directory must canonicalize to the physical root.
case_root="$root/symlink"; fixture "$case_root"
ln -s "$case_root/sample" "$case_root/sample-link"
STUB_LOG="$case_root/tools.log" STUB_SAMPLE=S1 \
STUB_R1_SEEN="$case_root/r1.seen" STUB_R2_SEEN="$case_root/r2.seen" \
PATH="$case_root/bin:$PATH" \
  "$bash_bin" "$align_script" "$case_root/sample-link/sample-manifest.json" "$case_root/ref.fasta" "$case_root/out/sample.bam" "$case_root/input-qc.json" >/dev/null
cmp -s "$case_root/r1.seen" "$case_root/sample/r1.fastq" || fail 'physical sample root containment failed'

# BAM and CRAM must consume the verified alignment descriptor, never the recorded filename.
for input_type in BAM CRAM; do
  case "$input_type" in BAM) extension=bam ;; CRAM) extension=cram ;; esac
  case_root="$root/${input_type,,}-happy"; alignment_fixture "$case_root" "$input_type"
  run_case "$case_root" >/dev/null
  tool_log=$(cat "$case_root/tools.log")
  assert_contains "$tool_log" 'samtools quickcheck -v /dev/fd/'
  assert_not_contains "$tool_log" "$case_root/sample/alignment.$extension"

  # A changed BAM/CRAM must fail before the first samtools invocation.
  case_root="$root/${input_type,,}-digest"; alignment_fixture "$case_root" "$input_type"
  printf 'CHANGED-AFTER-GATE\n' >>"$case_root/sample/alignment.$extension"
  if stderr=$(run_case "$case_root" 2>&1); then
    fail "$input_type digest mismatch unexpectedly passed"
  fi
  assert_contains "$stderr" 'alignment changed after the gate verified it'
  assert_no_tools "$case_root/tools.log"
done

echo 'WGS alignment boundary regressions: PASS'
