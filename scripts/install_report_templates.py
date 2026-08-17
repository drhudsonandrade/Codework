#!/usr/bin/env python3
"""Install the hash-pinned GENOMA v3.1 visual template pack fail-closed."""
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

from reporting.reference_v31 import INDEX_PATH, load_verified_reference
from reporting.template_v3 import verify_template_pack
from scripts.build_report_coordinate_pack import COMPILER_ID, encode_pack


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install(source: Path, target: Path) -> dict:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    source_verification = verify_template_pack(source, index)
    coordinate_manifest = load_verified_reference(source)
    encoded_coordinates = encode_pack(coordinate_manifest)
    coordinate_sha = _sha256_bytes(encoded_coordinates)
    expected_coordinate_sha = str(index.get("compressed_detail_sha256") or "")
    if coordinate_sha != expected_coordinate_sha:
        raise RuntimeError("v3.1 coordinate pack identity mismatch before installation")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="genoma-v31-template-stage-", dir=str(target.parent)) as td:
        stage = Path(td) / "pack"
        stage.mkdir()
        for rid in sorted(index["reports"]):
            name = index["reports"][rid]["filename"]
            shutil.copy2(source / name, stage / name)
        staged = verify_template_pack(stage, coordinate_manifest)
        target.mkdir(parents=True, exist_ok=True)
        for source_path in stage.iterdir():
            if source_path.is_file():
                shutil.copy2(source_path, target / source_path.name)

    final = verify_template_pack(target, coordinate_manifest)
    return {
        "schema": "genoma-editorial-v31-template-install-v1",
        "status": "VERIFICADO",
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": str(source),
        "target": str(target),
        "source_verification": source_verification,
        "staged_verification": staged,
        "final_verification": final,
        "coordinate_compiler": COMPILER_ID,
        "coordinate_sha256": coordinate_sha,
        "coordinate_expected_sha256": expected_coordinate_sha,
        "note": "Installation is accepted only when all 11 PDF identities and the deterministically rebuilt coordinate pack match pinned v3.1 SHA-256 identities.",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", required=True)
    p.add_argument("--target-dir", required=True)
    p.add_argument("--evidence")
    args = p.parse_args()
    result = install(Path(args.source_dir), Path(args.target_dir))
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.evidence:
        path = Path(args.evidence)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
