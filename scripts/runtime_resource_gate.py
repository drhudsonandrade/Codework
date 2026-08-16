#!/usr/bin/env python3
"""Session-specific GENOMA Runtime/Resource Gate.

Produces machine-readable evidence. It never inherits a prior PASS. Missing inputs are
reported as NÃO DISPONÍVEL rather than guessed. Exit 0 means every required check for
`--require-real-calling` was EXECUTADO; exit 2 means at least one required check is
NÃO DISPONÍVEL/failed.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_TOOLS = {
    "java": ("17.", ["java", "-version"]),
    "samtools": ("1.24", ["samtools", "--version"]),
    "bcftools": ("1.24", ["bcftools", "--version"]),
    "bwa-mem2": ("2.2.1", ["bwa-mem2", "version"]),
    "gatk": ("4.6.2.0", ["gatk", "--version"]),
    "nextflow": ("26.04.6", ["nextflow", "-version"]),
    "snakemake": ("7.32.4", ["snakemake", "--version"]),
}
REQUIRED_REFERENCE = (
    "Homo_sapiens_assembly38.fasta",
    "Homo_sapiens_assembly38.fasta.fai",
    "Homo_sapiens_assembly38.dict",
    "gencode.v50.primary_assembly.annotation.gtf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz.tbi",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz.tbi",
    "hg38-blacklist.v2.bed.gz",
)
BWA_SUFFIXES = (".0123", ".amb", ".ann", ".bwt.2bit.64", ".pac")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def item(status: str, evidence_ref: str, **details: Any) -> dict[str, Any]:
    return {"status": status, "evidence_ref": evidence_ref, "details": details}


def check_tools() -> dict[str, Any]:
    observed: dict[str, Any] = {}
    failures: list[str] = []
    for tool, (expected, cmd) in EXPECTED_TOOLS.items():
        path = shutil.which(tool)
        if not path:
            observed[tool] = {"status": "NÃO DISPONÍVEL", "expected": expected}
            failures.append(f"{tool}:missing")
            continue
        code, output = run(cmd)
        first = output.splitlines()[0] if output else ""
        ok = code == 0 and expected in output
        observed[tool] = {"status": "EXECUTADO" if ok else "NÃO DISPONÍVEL", "expected": expected, "observed": first, "path": path, "exit_code": code}
        if not ok:
            failures.append(f"{tool}:version_or_execution")
    return item("EXECUTADO" if not failures else "NÃO DISPONÍVEL", "runtime:tool-versions", tools=observed, failures=failures)


def load_lock(lock: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not lock.is_file():
        return entries
    for raw in lock.read_text(encoding="ascii").splitlines():
        fields = raw.split()
        if len(fields) >= 2 and re.fullmatch(r"[0-9a-f]{64}", fields[0]):
            entries[Path(fields[-1]).name] = fields[0]
    return entries


def check_reference(ref_root: Path) -> dict[str, dict[str, Any]]:
    checks: dict[str, dict[str, Any]] = {}
    fasta = ref_root / REQUIRED_REFERENCE[0]
    fai = ref_root / REQUIRED_REFERENCE[1]
    dictionary = ref_root / REQUIRED_REFERENCE[2]
    missing = [name for name in REQUIRED_REFERENCE if not (ref_root / name).is_file() or (ref_root / name).stat().st_size == 0]
    checks["fasta_fai_dictionary"] = item(
        "EXECUTADO" if all(p.is_file() and p.stat().st_size for p in (fasta, fai, dictionary)) else "NÃO DISPONÍVEL",
        "runtime:fasta-fai-dictionary",
        fasta=str(fasta), fai=str(fai), dictionary=str(dictionary), missing=[p.name for p in (fasta, fai, dictionary) if not p.is_file() or p.stat().st_size == 0],
    )
    checks["required_resources_checksums"] = item("NÃO DISPONÍVEL", "runtime:resource-checksums", missing=missing)
    checks["reference_build_and_contigs"] = item("NÃO DISPONÍVEL", "runtime:contigs", build="GRCh38", reason="reference unavailable")
    checks["aligner_indexes"] = item("NÃO DISPONÍVEL", "runtime:bwa-indexes", missing=[])
    if missing:
        return checks

    approved = ref_root / "GRCh38.lock.sha256.approved"
    lock = load_lock(approved)
    mismatch: list[str] = []
    if len(lock) != len(REQUIRED_REFERENCE):
        mismatch.append(f"approved_lock_entries={len(lock)} expected={len(REQUIRED_REFERENCE)}")
    for name in REQUIRED_REFERENCE:
        expected = lock.get(name)
        if not expected:
            mismatch.append(f"missing-lock:{name}")
            continue
        observed = sha256_file(ref_root / name)
        if observed != expected:
            mismatch.append(f"sha-mismatch:{name}")
    checks["required_resources_checksums"] = item(
        "EXECUTADO" if not mismatch else "NÃO DISPONÍVEL", "runtime:resource-checksums", approved_lock=str(approved), artifacts=len(REQUIRED_REFERENCE), failures=mismatch
    )

    contig_failures: list[str] = []
    fai_contigs: dict[str, int] = {}
    for line in fai.read_text(encoding="utf-8").splitlines():
        f = line.split("\t")
        if len(f) >= 2:
            fai_contigs[f[0]] = int(f[1])
    dict_contigs: dict[str, int] = {}
    for line in dictionary.read_text(encoding="utf-8").splitlines():
        if line.startswith("@SQ"):
            fields = {x.split(":", 1)[0]: x.split(":", 1)[1] for x in line.split("\t")[1:] if ":" in x}
            if "SN" in fields and "LN" in fields:
                dict_contigs[fields["SN"]] = int(fields["LN"])
    for c in [f"chr{x}" for x in range(1, 23)] + ["chrX", "chrY", "chrM"]:
        if c not in fai_contigs or c not in dict_contigs:
            contig_failures.append(f"missing:{c}")
        elif fai_contigs[c] != dict_contigs[c]:
            contig_failures.append(f"length-mismatch:{c}")
    code, out = run(["samtools", "faidx", str(fasta), "chr1:1000000-1000100"], 120)
    seq = "".join(out.splitlines()[1:]) if code == 0 else ""
    if len(seq) != 101:
        contig_failures.append("samtools-faidx-functional-query")
    checks["reference_build_and_contigs"] = item(
        "EXECUTADO" if not contig_failures else "NÃO DISPONÍVEL", "runtime:contigs", build="GRCh38", primary_contigs=25, failures=contig_failures
    )

    missing_indexes = [fasta.name + suffix for suffix in BWA_SUFFIXES if not Path(str(fasta) + suffix).is_file() or Path(str(fasta) + suffix).stat().st_size == 0]
    checks["aligner_indexes"] = item(
        "EXECUTADO" if not missing_indexes else "NÃO DISPONÍVEL", "runtime:bwa-indexes", expected_files=5, missing=missing_indexes
    )
    return checks


def fastq_check(path: Path) -> tuple[bool, dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return False, {"path": str(path), "reason": "missing_or_empty"}
    opener = gzip.open if path.suffix == ".gz" else open
    records = 0
    try:
        with opener(path, "rt", encoding="utf-8", errors="strict") as h:
            while True:
                lines = [h.readline() for _ in range(4)]
                if lines[0] == "":
                    break
                if any(x == "" for x in lines) or not lines[0].startswith("@") or not lines[2].startswith("+") or len(lines[1].strip()) != len(lines[3].strip()):
                    return False, {"path": str(path), "reason": "malformed_fastq", "record": records + 1}
                records += 1
    except (OSError, UnicodeError) as exc:
        return False, {"path": str(path), "reason": type(exc).__name__}
    return records > 0, {"path": str(path), "records": records, "sha256": sha256_file(path)}


def check_sample(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    integrity_details: dict[str, Any] = {}
    rg_details: dict[str, Any] = {}
    any_sample = False
    integrity_ok = True
    rg_ok = True

    if args.fastq_r1 or args.fastq_r2:
        any_sample = True
        if not (args.fastq_r1 and args.fastq_r2):
            integrity_ok = False
            integrity_details["fastq_pair"] = "both R1 and R2 required"
        else:
            ok1, d1 = fastq_check(Path(args.fastq_r1)); ok2, d2 = fastq_check(Path(args.fastq_r2))
            integrity_details["fastq_r1"] = d1; integrity_details["fastq_r2"] = d2
            integrity_ok &= ok1 and ok2
            if ok1 and ok2 and d1.get("records") != d2.get("records"):
                integrity_ok = False; integrity_details["pairing"] = "record_count_mismatch"
        rg_details["fastq"] = "read group is not encoded in FASTQ; must be supplied at alignment"
        rg_ok = False

    alignment = args.bam or args.cram
    if alignment:
        any_sample = True
        path = Path(alignment)
        if not path.is_file() or path.stat().st_size == 0:
            integrity_ok = False; rg_ok = False; integrity_details["alignment"] = {"path": str(path), "reason": "missing_or_empty"}
        else:
            cmd = ["samtools", "quickcheck", "-v", str(path)]
            code, out = run(cmd, 300)
            integrity_details["alignment"] = {"path": str(path), "quickcheck_exit": code, "quickcheck_output": out, "sha256": sha256_file(path)}
            integrity_ok &= code == 0
            code_h, header = run(["samtools", "view", "-H", str(path)], 300)
            rgs = [line for line in header.splitlines() if line.startswith("@RG")]
            sms = set()
            for line in rgs:
                for field in line.split("\t"):
                    if field.startswith("SM:"):
                        sms.add(field[3:])
            rg_details.update({"header_exit": code_h, "read_group_count": len(rgs), "sample_names": sorted(sms)})
            rg_ok &= code_h == 0 and len(rgs) > 0 and len(sms) == 1 and all(sms)

    if not any_sample:
        return {
            "sample_read_group_integrity": item("NÃO DISPONÍVEL", "runtime:sample-read-group", reason="no FASTQ/BAM/CRAM supplied for this session"),
            "fastq_bam_cram_integrity": item("NÃO DISPONÍVEL", "runtime:data-integrity", reason="no FASTQ/BAM/CRAM supplied for this session"),
        }
    return {
        "sample_read_group_integrity": item("EXECUTADO" if rg_ok else "NÃO DISPONÍVEL", "runtime:sample-read-group", **rg_details),
        "fastq_bam_cram_integrity": item("EXECUTADO" if integrity_ok else "NÃO DISPONÍVEL", "runtime:data-integrity", **integrity_details),
    }


def compatibility_check(tools: dict[str, Any], refs: dict[str, dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    reasons: list[str] = []
    caller = args.caller
    if tools.get("status") != "EXECUTADO":
        reasons.append("toolchain not fully verified")
    for k in ("fasta_fai_dictionary", "reference_build_and_contigs", "required_resources_checksums"):
        if refs[k]["status"] != "EXECUTADO":
            reasons.append(f"{k} not executed")
    if caller == "deepvariant":
        if not args.model or not Path(args.model).is_file():
            reasons.append("DeepVariant model not supplied")
    elif caller not in {"gatk-haplotypecaller", "bcftools"}:
        reasons.append(f"unsupported caller profile: {caller}")
    return item(
        "EXECUTADO" if not reasons else "NÃO DISPONÍVEL",
        "runtime:caller-model-reference",
        caller=caller,
        model=args.model or ("not-required-for-profile" if caller in {"gatk-haplotypecaller", "bcftools"} else None),
        reference_build="GRCh38",
        reasons=reasons,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ref-root", default=os.environ.get("REF_ROOT", "/refs"))
    p.add_argument("--fastq-r1")
    p.add_argument("--fastq-r2")
    p.add_argument("--bam")
    p.add_argument("--cram")
    p.add_argument("--caller", default="gatk-haplotypecaller", choices=["gatk-haplotypecaller", "bcftools", "deepvariant"])
    p.add_argument("--model")
    p.add_argument("--session-id")
    p.add_argument("--require-real-calling", action="store_true")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    session_id = args.session_id or str(uuid.uuid4())

    tools = check_tools()
    refs = check_reference(Path(args.ref_root))
    sample = check_sample(args)
    compatibility = compatibility_check(tools, refs, args)
    checks = {
        "executables_and_versions": tools,
        "reference_build_and_contigs": refs["reference_build_and_contigs"],
        "fasta_fai_dictionary": refs["fasta_fai_dictionary"],
        "aligner_indexes": refs["aligner_indexes"],
        "required_resources_checksums": refs["required_resources_checksums"],
        "sample_read_group_integrity": sample["sample_read_group_integrity"],
        "fastq_bam_cram_integrity": sample["fastq_bam_cram_integrity"],
        "caller_model_reference_compatibility": compatibility,
    }
    unavailable = [k for k, v in checks.items() if v["status"] != "EXECUTADO"]
    status = "EXECUTADO" if not unavailable else "NÃO DISPONÍVEL"
    payload = {
        "gate": "RUNTIME_RESOURCE_GATE",
        "status": status,
        "session_id": session_id,
        "inherited_from_previous_session": False,
        "started_at": now(),
        "host": {"hostname": socket.gethostname(), "platform": platform.platform(), "python": sys.version.split()[0]},
        "caller_profile": args.caller,
        "checks": checks,
        "unavailable_checks": unavailable,
        "ready_for_real_calling": not unavailable,
        "classification": "current-session operational evidence; not inherited",
    }
    out = Path(args.output); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.require_real_calling and unavailable:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
