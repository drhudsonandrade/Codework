#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

INDEX_SUFFIXES = [".0123", ".amb", ".ann", ".bwt.2bit.64", ".pac"]
FASTA = "Homo_sapiens_assembly38.fasta"
LOCK = "BWA_MEM2.index.sha256.approved"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_lock(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or len(parts[0]) != 64:
            raise ValueError(f"invalid lock line: {raw!r}")
        digest, name = parts
        if Path(name).name != name:
            raise ValueError(f"lock path must be a basename: {name}")
        if name in entries:
            raise ValueError(f"duplicate lock entry: {name}")
        entries[name] = digest.lower()
    return entries


def mem_total_gib() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1024 / 1024
    except Exception:
        return None
    return None


def verify(ref_root: Path, *, run_functional: bool = False, min_functional_memory_gib: float = 16.0) -> dict:
    ref_root = ref_root.resolve()
    lock_path = ref_root / LOCK
    if not lock_path.is_file():
        raise ValueError(f"externally approved index lock missing: {lock_path}")
    expected_names = {FASTA, *(FASTA + suffix for suffix in INDEX_SUFFIXES)}
    entries = parse_lock(lock_path)
    if set(entries) != expected_names:
        raise ValueError(f"index lock must contain exactly FASTA + five BWA-MEM2 index files; got {sorted(entries)}")

    verified = []
    for name in sorted(expected_names):
        path = ref_root / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing/empty prebuilt bundle member: {name}")
        actual = sha256_file(path)
        if actual != entries[name]:
            raise ValueError(f"checksum mismatch for {name}: {actual} != {entries[name]}")
        verified.append({"name": name, "sha256": actual, "size_bytes": path.stat().st_size})

    functional = {"status": "PROPOSTO", "reason": "functional canary not requested"}
    if run_functional:
        memory = mem_total_gib()
        if memory is not None and memory < min_functional_memory_gib:
            raise ValueError(f"functional BWA-MEM2 validation requires >= {min_functional_memory_gib:.1f} GiB host memory by project gate; detected {memory:.1f}")
        script = Path(__file__).resolve().with_name("validate_bwa_mem2_functional.sh")
        env = os.environ.copy()
        env["REF_ROOT"] = str(ref_root)
        result = subprocess.run([str(script)], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        if result.returncode != 0:
            raise ValueError(f"BWA-MEM2 functional validation failed ({result.returncode}): {result.stdout[-2000:]}")
        functional = {"status": "VERIFICADO", "stdout": result.stdout[-4000:]}

    return {
        "schema": "genoma-prebuilt-bwa-mem2-verification-v1",
        "status": "VERIFICADO" if (not run_functional or functional["status"] == "VERIFICADO") else "NÃO DISPONÍVEL",
        "reference_root": str(ref_root),
        "lock": {"path": LOCK, "sha256": sha256_file(lock_path)},
        "files": verified,
        "functional_validation": functional,
        "limitations": [
            "A prebuilt index is accepted only when its FASTA and all five index files are bound by an independently approved SHA-256 lock.",
            "This verifier does not create indexes and therefore does not require the ~80-90 GiB indexing peak; functional mapping still needs enough RAM to load the human index.",
            "The regular GRCh38 9/9 resource gate and per-sample Runtime/Resource Gate remain mandatory.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ref-root", required=True)
    p.add_argument("--run-functional", action="store_true")
    p.add_argument("--min-functional-memory-gib", type=float, default=16.0)
    p.add_argument("--output")
    args = p.parse_args()
    try:
        payload = verify(Path(args.ref_root), run_functional=args.run_functional, min_functional_memory_gib=args.min_functional_memory_gib)
    except (ValueError, OSError) as exc:
        print(f"NÃO DISPONÍVEL: {exc}")
        return 2
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
