#!/usr/bin/env python3
"""Create an isolated latest-resolvable Conda candidate environment.

This never mutates the production environment.yml. Version pins are removed only in a
candidate copy so the configured channels resolve their newest mutually compatible
packages. The candidate must pass the synthetic functional canary before it can be used
for real DNA in the same execution.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DEFAULT_MANAGED = {
    "python", "openjdk", "nodejs", "samtools", "bcftools", "htslib",
    "bwa-mem2", "gatk4", "nextflow", "snakemake-minimal", "curl", "jq", "pigz",
}

_DEP = re.compile(r"^(\s*-\s*)([A-Za-z0-9_.+-]+)(?:=[^\s#]+)?(\s*(?:#.*)?)$")


def prepare_candidate(source: Path, destination: Path, *, managed: set[str] | None = None) -> dict[str, object]:
    managed = managed or set(DEFAULT_MANAGED)
    original = source.read_text(encoding="utf-8")
    unpinned: list[str] = []
    output: list[str] = []
    for line in original.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        body = line[:-1] if ending else line
        match = _DEP.match(body)
        if match and match.group(2) in managed and "=" in body.split("#", 1)[0]:
            prefix, package, suffix = match.groups()
            output.append(f"{prefix}{package}{suffix}{ending}")
            unpinned.append(package)
        else:
            output.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(output), encoding="utf-8")
    ordered = [name for name in DEFAULT_MANAGED if name in unpinned]
    # Stable human-oriented order follows source occurrence when custom sets are used.
    ordered = [name for name in unpinned if name in managed]
    return {
        "schema": "genoma-latest-candidate-v1",
        "source": str(source),
        "destination": str(destination),
        "managed": sorted(managed),
        "unpinned": ordered,
        "production_source_mutated": False,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="environment.yml")
    p.add_argument("--output", required=True)
    p.add_argument("--evidence")
    args = p.parse_args()
    result = prepare_candidate(Path(args.source), Path(args.output))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.evidence:
        path = Path(args.evidence)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
