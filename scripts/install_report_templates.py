#!/usr/bin/env python3
"""Install the externally held GENOMA v3.0 visual template pack after SHA verification.

Coordinate inventories may be supplied as the previously approved external pack or rebuilt
locally from the exact hash-pinned PDFs with the pinned deterministic compiler.  In either
case, the resulting coordinate artifacts must match a pinned SHA-256 before installation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.template_v3 import load_reference_manifest, verify_template_pack, TemplateV3Error
from scripts.build_report_coordinate_pack import compile_pack, write_pack, COMPILER_ID


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pair(root: Path, manifest: dict, prefix: str) -> tuple[dict, dict] | None:
    manifest_meta = manifest.get(f"{prefix}_coordinate_manifest") or {}
    detail_meta = manifest.get(f"{prefix}_coordinate_detail") or {}
    mname = str(manifest_meta.get("filename") or "")
    dname = str(detail_meta.get("filename") or "")
    if not mname or not dname:
        return None
    mp = root / mname
    dp = root / dname
    if not mp.is_file() or not dp.is_file():
        return None
    ma = _sha256(mp)
    da = _sha256(dp)
    if ma != manifest_meta.get("sha256") or da != detail_meta.get("sha256"):
        raise TemplateV3Error(f"checksum mismatch for {prefix} v3 coordinate artifacts")
    return (
        {"filename": mname, "sha256": ma, "status": "VERIFICADO"},
        {"filename": dname, "sha256": da, "status": "VERIFICADO"},
    )


def _ensure_coordinates(root: Path, manifest: dict) -> dict:
    # Prefer the historical approved external pair when explicitly supplied.
    external = _pair(root, manifest, "external")
    if external:
        return {"mode": "external-pinned", "manifest": external[0], "detail": external[1]}

    compiler = manifest.get("coordinate_compiler") or {}
    if compiler.get("id") != COMPILER_ID:
        raise TemplateV3Error("coordinate compiler identity does not match pinned reference index")
    generated_meta = manifest.get("generated_coordinate_manifest") or {}
    detail_meta = manifest.get("generated_coordinate_detail") or {}
    if not generated_meta or not detail_meta:
        raise TemplateV3Error("pinned generated v3 coordinate hashes are missing")

    payload = compile_pack(root, ROOT / "reporting" / "reference_v3_manifest.json")
    build = write_pack(payload, root)
    generated = _pair(root, manifest, "generated")
    if not generated:
        raise TemplateV3Error("deterministic coordinate compilation did not produce required artifacts")
    return {
        "mode": "generated-from-pinned-pdfs",
        "compiler": COMPILER_ID,
        "manifest": generated[0],
        "detail": generated[1],
        "build": build,
    }


def install(source: Path, target: Path) -> dict:
    manifest = load_reference_manifest()
    source_verification = verify_template_pack(source, manifest)
    source_coordinates = _ensure_coordinates(source, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="genoma-v3-template-stage-", dir=str(target.parent)) as td:
        stage = Path(td) / "pack"
        stage.mkdir()
        for rid in sorted(manifest["reports"]):
            name = manifest["reports"][rid]["filename"]
            shutil.copy2(source / name, stage / name)
        pair = source_coordinates
        for key in ("manifest", "detail"):
            name = pair[key]["filename"]
            shutil.copy2(source / name, stage / name)
        staged = verify_template_pack(stage, manifest)
        staged_coordinates = _ensure_coordinates(stage, manifest)
        target.mkdir(parents=True, exist_ok=True)
        for source_path in stage.iterdir():
            if source_path.is_file():
                shutil.copy2(source_path, target / source_path.name)
    final = verify_template_pack(target, manifest)
    final_coordinates = _ensure_coordinates(target, manifest)
    return {
        "schema": "genoma-editorial-v3-template-install-v3",
        "status": "VERIFICADO",
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": str(source),
        "target": str(target),
        "source_verification": source_verification,
        "source_coordinates": source_coordinates,
        "staged_verification": staged,
        "staged_coordinates": staged_coordinates,
        "final_verification": final,
        "final_coordinates": final_coordinates,
        "note": "Coordinates are accepted only when either an approved external pair or deterministic recompilation from exact hash-pinned PDFs matches pinned SHA-256 identities.",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", required=True)
    p.add_argument("--target-dir", required=True)
    p.add_argument("--evidence")
    args = p.parse_args()
    result = install(Path(args.source_dir), Path(args.target_dir))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.evidence:
        path = Path(args.evidence)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
