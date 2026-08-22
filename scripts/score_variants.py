#!/usr/bin/env python3
"""Score one normalized single-sample VCF against a normalized truth VCF."""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import TextIO


VariantKey = tuple[str, int, str, str]


def open_text(path: Path) -> TextIO:
    """Open by content, not by extension.

    `path.suffix == ".gz"` meant a bgzipped VCF named `.vcf` was read as its own compressed
    bytes: no line parsed, no error raised, zero variants scored. Zero variants against a
    truth set reads as "the caller found nothing", which is a very different statement.
    """
    with path.open("rb") as probe:
        compressed = probe.read(2) == b"\x1f\x8b"
    if compressed:
        return gzip.open(path, "rt", encoding="ascii")
    return path.open("r", encoding="ascii")


def normalize_genotype(value: str) -> str:
    alleles = value.replace("|", "/").split("/")
    if any(allele == "." for allele in alleles):
        return "./."
    return "/".join(sorted(alleles, key=int))


def read_variants(path: Path) -> dict[VariantKey, str]:
    """Read a VCF's calls, refusing a file that is not a VCF.

    Every non-`#` line was parsed as a record and anything that did not fit was skipped, so a
    file that is not a VCF at all produced an empty call set in silence. Against a truth set
    that scores as recall 0 — indistinguishable from a caller that genuinely found nothing,
    and the two demand opposite responses.
    """
    variants: dict[VariantKey, str] = {}
    header_seen = False
    with open_text(path) as handle:
        for index, line in enumerate(handle):
            if index == 0 and not line.startswith("##fileformat=VCF"):
                raise SystemExit(
                    f"NÃO DISPONÍVEL: {path.name} não começa com `##fileformat=VCF`; "
                    "pontuar um arquivo que não é VCF produziria zero variantes em silêncio"
                )
            if line.startswith("#CHROM"):
                header_seen = True
                continue
            if not line or line.startswith("#"):
                continue
            if not header_seen:
                raise SystemExit(
                    f"NÃO DISPONÍVEL: {path.name} traz registros antes da linha #CHROM"
                )
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 10 or fields[6] not in {"PASS", "."}:
                continue
            chrom, position, _identifier, ref, alt = fields[:5]
            format_keys = fields[8].split(":")
            sample_values = fields[9].split(":")
            sample = dict(zip(format_keys, sample_values, strict=False))
            genotype = normalize_genotype(sample.get("GT", "./."))
            for alternate in alt.split(","):
                variants[(chrom, int(position), ref, alternate)] = genotype
    return variants


def score(truth_path: Path, called_path: Path) -> dict[str, float | int]:
    truth = read_variants(truth_path)
    called = read_variants(called_path)
    truth_keys = set(truth)
    called_keys = set(called)
    shared = truth_keys & called_keys
    tp = len(shared)
    fp = len(called_keys - truth_keys)
    fn = len(truth_keys - called_keys)
    compared = sum(1 for key in shared if truth[key] != "./." and called[key] != "./.")
    concordant = sum(
        1
        for key in shared
        if truth[key] != "./." and called[key] != "./." and truth[key] == called[key]
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "f1": round(f1, 12),
        "fn": fn,
        "fp": fp,
        "genotype_compared": compared,
        "genotype_concordant": concordant,
        "precision": round(precision, 12),
        "recall": round(recall, 12),
        "tp": tp,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("truth", type=Path)
    parser.add_argument("called", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-perfect", action="store_true")
    args = parser.parse_args()
    result = score(args.truth, args.called)
    payload = json.dumps(result, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.require_perfect:
        perfect = (
            result["tp"] > 0
            and result["fp"] == 0
            and result["fn"] == 0
            and result["genotype_compared"] == result["genotype_concordant"]
        )
        if not perfect:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
