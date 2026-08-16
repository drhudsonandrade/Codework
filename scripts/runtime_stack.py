from __future__ import annotations

# Single source of truth shared by candidate resolution and session promotion.
# If a component is added here, the latest-tested candidate must carry it and
# promotion must be able to prove its resolved version from the Conda inventory.
MANAGED_RUNTIME_PACKAGES = (
    "python",
    "openjdk",
    "nodejs",
    "samtools",
    "bcftools",
    "htslib",
    "bwa-mem2",
    "gatk4",
    "nextflow",
    "snakemake-minimal",
    "curl",
    "procps-ng",
    "jq",
    "pigz",
)

MANAGED_RUNTIME_SET = frozenset(MANAGED_RUNTIME_PACKAGES)
