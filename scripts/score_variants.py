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
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="ascii")
    return path.open("r", encoding="ascii")


def normalize_genotype(value: str) -> str:
    alleles = value.replace("|", "/").split("/")
    if any(allele == "." for allele in alleles):
        return "./."
    return "/".join(sorted(alleles, key=int))


def read_variants(path: Path) -> dict[VariantKey, str]:
    variants: dict[VariantKey, str] = {}
    with open_text(path) as handle:
        for line in handle:
            if not line or line.startswith("#"):
                continue
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
