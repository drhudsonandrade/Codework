#!/usr/bin/env python3
"""Generate a small deterministic diploid sequencing fixture with three SNPs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import random
from pathlib import Path


SEED = 260
REFERENCE_LENGTH = 30_000
READ_PAIRS = 2_966
READ_LENGTH = 151
FRAGMENT_LENGTH = 350
VARIANT_POSITIONS = (5_000, 15_000, 25_000)
BASES = "ACGT"
COMPLEMENT = str.maketrans("ACGT", "TGCA")


def reverse_complement(sequence: str) -> str:
    return sequence.translate(COMPLEMENT)[::-1]


def alternate_base(reference: str) -> str:
    return BASES[(BASES.index(reference) + 1) % len(BASES)]


def write_fasta(path: Path, sequence: str) -> None:
    with path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write(">chrSynthetic\n")
        for offset in range(0, len(sequence), 60):
            handle.write(f"{sequence[offset:offset + 60]}\n")


def write_fastq_gzip(path: Path, records: list[tuple[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="ascii", newline="\n") as handle:
                for name, sequence in records:
                    handle.write(f"@{name}\n{sequence}\n+\n{'I' * len(sequence)}\n")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    reference = "".join(rng.choice(BASES) for _ in range(REFERENCE_LENGTH))
    variants = [
        (position, reference[position - 1], alternate_base(reference[position - 1]))
        for position in VARIANT_POSITIONS
    ]
    alternate_haplotype = list(reference)
    for position, _ref, alt in variants:
        alternate_haplotype[position - 1] = alt
    alternate_haplotype_text = "".join(alternate_haplotype)

    reference_path = output_dir / "reference.fa"
    r1_path = output_dir / "reads_R1.fastq.gz"
    r2_path = output_dir / "reads_R2.fastq.gz"
    truth_path = output_dir / "truth.vcf"
    fixture_path = output_dir / "fixture.json"
    write_fasta(reference_path, reference)

    reads_r1: list[tuple[str, str]] = []
    reads_r2: list[tuple[str, str]] = []
    max_start = REFERENCE_LENGTH - FRAGMENT_LENGTH
    for index in range(READ_PAIRS):
        start = rng.randint(0, max_start)
        haplotype = alternate_haplotype_text if index % 2 else reference
        fragment = haplotype[start : start + FRAGMENT_LENGTH]
        name = f"CANARY:{index + 1}:start:{start + 1}:hap:{index % 2}"
        reads_r1.append((f"{name}/1", fragment[:READ_LENGTH]))
        reads_r2.append((f"{name}/2", reverse_complement(fragment[-READ_LENGTH:])))
    write_fastq_gzip(r1_path, reads_r1)
    write_fastq_gzip(r2_path, reads_r2)

    with truth_path.open("w", encoding="ascii", newline="\n") as handle:
        handle.write("##fileformat=VCFv4.2\n")
        handle.write(f"##contig=<ID=chrSynthetic,length={REFERENCE_LENGTH}>\n")
        handle.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        handle.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tCANARY\n")
        for position, ref, alt in variants:
            handle.write(f"chrSynthetic\t{position}\t.\t{ref}\t{alt}\t100\tPASS\t.\tGT\t0/1\n")

    fixture = {
        "fixture": "omnigenis-synthetic-germline-v2",
        "fragment_length": FRAGMENT_LENGTH,
        "nominal_fragment_coverage": round(READ_PAIRS * FRAGMENT_LENGTH / REFERENCE_LENGTH, 6),
        "read_length": READ_LENGTH,
        "read_pairs": READ_PAIRS,
        "reference_length": REFERENCE_LENGTH,
        "seed": SEED,
        "variants": [
            {"alt": alt, "chrom": "chrSynthetic", "genotype": "0/1", "position": position, "ref": ref}
            for position, ref, alt in variants
        ],
    }
    fixture_path.write_text(json.dumps(fixture, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    central_files = (reference_path, r1_path, r2_path, truth_path, fixture_path)
    checksum_text = "".join(f"{sha256(path)}  {path.name}\n" for path in central_files)
    (output_dir / "checksums.sha256").write_text(checksum_text, encoding="ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    generate(args.output_dir)


if __name__ == "__main__":
    main()
