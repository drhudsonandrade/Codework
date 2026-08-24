#!/usr/bin/env bash
set -euo pipefail

readonly PROJECT_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
readonly OUTPUT_DIR=${1:-"$PROJECT_ROOT/results/canary"}
readonly WORK_DIR="$OUTPUT_DIR/work"

if [[ -s "$OUTPUT_DIR/report.json" ]] && jq -e '.status == "PASS"' "$OUTPUT_DIR/report.json" >/dev/null; then
  cat "$OUTPUT_DIR/report.json"
  exit 0
fi

mkdir -p "$OUTPUT_DIR" "$WORK_DIR"
if [[ "${CANARY_VERSION_POLICY:-PINNED}" == "PINNED" ]]; then
  "$PROJECT_ROOT/scripts/check_versions.sh" > "$OUTPUT_DIR/tool_versions.tsv"
else
  {
    printf 'tool\tversion\n'
    printf 'java\t%s\n' "$(java -version 2>&1 | head -1)"
    printf 'samtools\t%s\n' "$(samtools --version | head -1)"
    printf 'bcftools\t%s\n' "$(bcftools --version | head -1)"
    printf 'bwa-mem2\t%s\n' "$(bwa-mem2 version 2>&1 | head -1 || true)"
    printf 'gatk\t%s\n' "$(gatk --version 2>&1 | tail -1)"
    printf 'nextflow\t%s\n' "$(nextflow -version 2>&1 | grep -m1 version || true)"
    printf 'snakemake\t%s\n' "$(snakemake --version 2>&1 | head -1)"
    printf 'pdftoppm\t%s\n' "$(pdftoppm -v 2>&1 | head -1)"
    printf 'pdftocairo\t%s\n' "$(pdftocairo -v 2>&1 | head -1)"
  } > "$OUTPUT_DIR/tool_versions.tsv"
fi
if command -v micromamba >/dev/null 2>&1; then
  micromamba list --name base --explicit > "$OUTPUT_DIR/conda-explicit.lock.txt"
  micromamba list --name base --json > "$OUTPUT_DIR/conda-inventory.json"
fi
# Functional editorial runtime canary is part of the same candidate witness.
# This makes session promotion contingent on the PDF/DOCX renderer stack, not only NGS executables.
python3 - <<'PY' "$WORK_DIR/editorial-canary.pdf" "$OUTPUT_DIR/editorial-runtime.json"
import importlib.metadata as md
import json, sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
pdf, out = sys.argv[1], sys.argv[2]
c = canvas.Canvas(pdf, pagesize=A4)
c.drawString(72, 760, "GENOMA editorial runtime canary")
c.save()
payload = {
    "status": "PENDING",
    "python_packages": {
        "reportlab": md.version("reportlab"),
        "python-docx": md.version("python-docx"),
        "pypdf": md.version("pypdf"),
        "Pillow": md.version("Pillow"),
    },
}
open(out, "w", encoding="utf-8").write(json.dumps(payload, indent=2) + "\n")
PY
# Fail at the failing step with its reason, not later on a missing artifact: the
# renderer's stderr is what tells an operator which part of the stack is broken.
if ! pdftoppm -singlefile -r 72 -png "$WORK_DIR/editorial-canary.pdf" "$WORK_DIR/editorial-canary"; then
  printf 'FAIL\teditor_runtime\treason=pdftoppm_failed\n' >&2
  exit 7
fi
if ! pdftocairo -svg "$WORK_DIR/editorial-canary.pdf" "$WORK_DIR/editorial-canary.svg"; then
  printf 'FAIL\teditor_runtime\treason=pdftocairo_failed\n' >&2
  exit 8
fi
if [[ ! -s "$WORK_DIR/editorial-canary.png" ]]; then
  printf 'FAIL\teditor_runtime\treason=empty_png_raster\n' >&2
  exit 7
fi
if [[ ! -s "$WORK_DIR/editorial-canary.svg" ]]; then
  printf 'FAIL\teditor_runtime\treason=empty_svg_vector\n' >&2
  exit 8
fi
python3 - <<'PY' "$OUTPUT_DIR/editorial-runtime.json"
import json, subprocess, sys
p=sys.argv[1]; d=json.load(open(p, encoding="utf-8"))
d.update({
    "status":"PASS",
    "pdftoppm":subprocess.run(["pdftoppm","-v"],capture_output=True,text=True,check=True).stderr.splitlines()[0],
    "pdftocairo":subprocess.run(["pdftocairo","-v"],capture_output=True,text=True,check=True).stderr.splitlines()[0],
    "functional_outputs":["PNG","SVG"],
})
open(p,"w",encoding="utf-8").write(json.dumps(d,indent=2)+"\n")
PY

python3 "$PROJECT_ROOT/scripts/generate_canary.py" "$WORK_DIR/input"

reference="$WORK_DIR/input/reference.fa"
r1="$WORK_DIR/input/reads_R1.fastq.gz"
r2="$WORK_DIR/input/reads_R2.fastq.gz"
truth="$WORK_DIR/input/truth.vcf"
bam="$WORK_DIR/CANARY.sorted.bam"

samtools faidx "$reference"
gatk --java-options "-Xmx2g" CreateSequenceDictionary \
  --REFERENCE "$reference" \
  --OUTPUT "$WORK_DIR/input/reference.dict"
bwa-mem2 index "$reference"

read_group=$'@RG\tID:CANARY\tSM:CANARY\tPL:ILLUMINA\tLB:SYNTHETIC\tPU:UNIT1'
bwa-mem2 mem -t "${CANARY_THREADS:-2}" -R "$read_group" "$reference" "$r1" "$r2" \
  | samtools sort --threads "${CANARY_THREADS:-2}" --output-fmt BAM -o "$bam" -
samtools index "$bam"
samtools quickcheck -v "$bam"
samtools flagstat "$bam" > "$OUTPUT_DIR/flagstat.txt"

bgzip --stdout "$truth" > "$WORK_DIR/truth.vcf.gz"
tabix --preset vcf "$WORK_DIR/truth.vcf.gz"
bcftools norm --fasta-ref "$reference" --multiallelics -any --output-type z \
  --output "$WORK_DIR/truth.norm.vcf.gz" "$WORK_DIR/truth.vcf.gz"
tabix --preset vcf "$WORK_DIR/truth.norm.vcf.gz"

bcftools mpileup --threads "${CANARY_THREADS:-2}" --output-type u \
  --fasta-ref "$reference" --annotate FORMAT/DP,FORMAT/AD "$bam" \
  | bcftools call --multiallelic-caller --variants-only --output-type z \
      --output "$WORK_DIR/bcftools.raw.vcf.gz"
tabix --preset vcf "$WORK_DIR/bcftools.raw.vcf.gz"
bcftools norm --fasta-ref "$reference" --multiallelics -any --output-type z \
  --output "$WORK_DIR/bcftools.norm.vcf.gz" "$WORK_DIR/bcftools.raw.vcf.gz"
tabix --preset vcf "$WORK_DIR/bcftools.norm.vcf.gz"

gatk --java-options "-Xmx2g" HaplotypeCaller \
  --reference "$reference" \
  --input "$bam" \
  --output "$WORK_DIR/gatk.raw.vcf.gz" \
  --intervals chrSynthetic \
  --native-pair-hmm-threads "${CANARY_THREADS:-2}"
bcftools norm --fasta-ref "$reference" --multiallelics -any --output-type z \
  --output "$WORK_DIR/gatk.norm.vcf.gz" "$WORK_DIR/gatk.raw.vcf.gz"
tabix --force --preset vcf "$WORK_DIR/gatk.norm.vcf.gz"

python3 "$PROJECT_ROOT/scripts/score_variants.py" \
  "$WORK_DIR/truth.norm.vcf.gz" "$WORK_DIR/bcftools.norm.vcf.gz" \
  --output "$OUTPUT_DIR/bcftools.score.json" --require-perfect
python3 "$PROJECT_ROOT/scripts/score_variants.py" \
  "$WORK_DIR/truth.norm.vcf.gz" "$WORK_DIR/gatk.norm.vcf.gz" \
  --output "$OUTPUT_DIR/gatk.score.json" --require-perfect

jq --null-input \
  --slurpfile fixture "$WORK_DIR/input/fixture.json" \
  --slurpfile bcftools "$OUTPUT_DIR/bcftools.score.json" \
  --slurpfile gatk "$OUTPUT_DIR/gatk.score.json" \
  --slurpfile editorial "$OUTPUT_DIR/editorial-runtime.json" \
  --arg version_policy "${CANARY_VERSION_POLICY:-PINNED}" \
  '{
    status: "PASS",
    classification: "synthetic functional canary; not clinical validation",
    sensitive_data: false,
    version_policy: $version_policy,
    fixture: $fixture[0],
    callers: {bcftools: $bcftools[0], gatk_haplotypecaller: $gatk[0]},
    editorial_runtime: $editorial[0],
    limitations: [
      "three synthetic SNPs only",
      "no difficult regions, indels, CNV, SV, repeats, contamination, BQSR or WGS benchmark",
      "does not replace GIAB or laboratory analytical validation"
    ]
  }' > "$OUTPUT_DIR/report.json"

cat "$OUTPUT_DIR/report.json"
