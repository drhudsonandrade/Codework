#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly MANIFEST=${GRCH38_MANIFEST:-"$PROJECT_ROOT/manifests/GRCh38.sources.tsv"}
: "${REF_ROOT:?Set REF_ROOT to the persistent GRCh38 directory}"
readonly APPROVED_LOCK="$REF_ROOT/GRCh38.lock.sha256.approved"
readonly REQUIRE_BWA_INDEX=${REQUIRE_BWA_INDEX:-1}

mapfile -t targets < <(awk -F '\t' 'NR > 1 && NF {print $2}' "$MANIFEST")
missing=0
for target in "${targets[@]}"; do
  if [[ ! -s "$REF_ROOT/$target" ]]; then
    printf 'artifact\tFAIL\t%s\n' "$target"
    missing=$((missing + 1))
  else
    printf 'artifact\tPASS\t%s\n' "$target"
  fi
done
(( missing == 0 )) || { printf 'artifact_gate\tFAIL\tmissing=%d\n' "$missing"; exit 2; }

if [[ ! -s "$APPROVED_LOCK" ]]; then
  printf 'checksum_gate\tFAIL\treason=external_approval_missing\tpath=%s\n' "$APPROVED_LOCK"
  exit 3
fi
(
  cd "$REF_ROOT"
  sha256sum --check --strict "$(basename "$APPROVED_LOCK")"
)
printf 'checksum_gate\tPASS\tartifacts=%d\n' "${#targets[@]}"

fasta="$REF_ROOT/Homo_sapiens_assembly38.fasta"
fai="$REF_ROOT/Homo_sapiens_assembly38.fasta.fai"
dict="$REF_ROOT/Homo_sapiens_assembly38.dict"
dbsnp="$REF_ROOT/Homo_sapiens_assembly38.dbsnp138.vcf.gz"
mills="$REF_ROOT/Mills_and_1000G_gold_standard.indels.hg38.vcf.gz"
gtf="$REF_ROOT/gencode.v50.primary_assembly.annotation.gtf.gz"

query_sequence=$(samtools faidx "$fasta" chr1:1000000-1000100 | tail -n +2 | tr -d '\r\n')
[[ ${#query_sequence} -eq 101 ]] || { printf 'samtools_faidx\tFAIL\tlength=%d\n' "${#query_sequence}"; exit 4; }
printf 'samtools_faidx\tPASS\tlength=101\n'

dbsnp_record=$(bcftools query -r chr1:1000000-1100000 -f '%CHROM\t%POS\t%REF\t%ALT\n' "$dbsnp" | head -n 1)
[[ -n "$dbsnp_record" ]] || { printf 'bcftools_query\tFAIL\treason=no_record\n'; exit 5; }
printf 'bcftools_query\tPASS\trecord_present=true\n'

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
cut -f1 "$fai" | sort -u > "$tmp_dir/fasta.contigs"
awk -F '\t' '$1 == "@SQ" {for (i=1; i<=NF; i++) if ($i ~ /^SN:/) {sub(/^SN:/, "", $i); print $i}}' "$dict" | sort -u > "$tmp_dir/dict.contigs"
bcftools view --header-only "$dbsnp" | sed -n 's/^##contig=<ID=\([^,>]*\).*/\1/p' | sort -u > "$tmp_dir/dbsnp.contigs"
bcftools view --header-only "$mills" | sed -n 's/^##contig=<ID=\([^,>]*\).*/\1/p' | sort -u > "$tmp_dir/mills.contigs"
gzip -cd "$gtf" | awk 'BEGIN {FS="\t"} $0 !~ /^#/ {print $1}' | sort -u > "$tmp_dir/gtf.contigs"

for primary in $(seq 1 22) X Y M; do
  contig="chr${primary}"
  for source in fasta dict dbsnp mills; do
    grep -Fxq "$contig" "$tmp_dir/${source}.contigs" || {
      printf 'contig_gate\tFAIL\tcontig=%s\tsource=%s\n' "$contig" "$source"
      exit 6
    }
  done
done
if comm -23 "$tmp_dir/gtf.contigs" "$tmp_dir/fasta.contigs" | grep -q .; then
  printf 'contig_gate\tFAIL\treason=gtf_contig_absent_from_fasta\n'
  exit 7
fi
printf 'contig_gate\tPASS\tprimary_contigs=25\n'

if [[ "$REQUIRE_BWA_INDEX" == "1" ]]; then
  for suffix in .0123 .amb .ann .bwt.2bit.64 .pac; do
    [[ -s "${fasta}${suffix}" ]] || { printf 'bwa_index_gate\tFAIL\tmissing=%s\n' "${fasta}${suffix}"; exit 8; }
  done
  printf 'bwa_index_gate\tPASS\tfiles=5\n'
else
  printf 'bwa_index_gate\tSKIPPED\treason=REQUIRE_BWA_INDEX_0\n'
fi

printf 'grch38_resource_gate\tPASS\tartifacts=9\n'
