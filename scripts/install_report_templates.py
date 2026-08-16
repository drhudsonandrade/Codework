#!/usr/bin/env python3
"""Install the externally held GENOMA v3.0 visual template pack only after SHA verification."""
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


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_coordinate_pack(root: Path, manifest: dict) -> dict:
    result = {}
    for key in ("external_coordinate_manifest", "external_coordinate_detail"):
        meta = manifest.get(key) or {}
        name = str(meta.get("filename") or "")
        expected = str(meta.get("sha256") or "")
        path = root / name
        if not name or not expected or not path.is_file():
            raise TemplateV3Error(f"missing external v3 coordinate artifact: {key}")
        actual = _sha256(path)
        if actual != expected:
            raise TemplateV3Error(f"checksum mismatch for external v3 coordinate artifact: {name}")
        result[key] = {"filename": name, "sha256": actual, "status": "VERIFICADO"}
    return result


def install(source: Path, target: Path) -> dict:
    manifest = load_reference_manifest()
    source_verification = verify_template_pack(source, manifest)
    source_coordinates = _verify_coordinate_pack(source, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="genoma-v3-template-stage-", dir=str(target.parent)) as td:
        stage = Path(td) / "pack"
        stage.mkdir()
        for rid in sorted(manifest["reports"]):
            name = manifest["reports"][rid]["filename"]
            shutil.copy2(source / name, stage / name)
        for key in ("external_coordinate_manifest", "external_coordinate_detail"):
            name = manifest[key]["filename"]
            shutil.copy2(source / name, stage / name)
        staged = verify_template_pack(stage, manifest)
        staged_coordinates = _verify_coordinate_pack(stage, manifest)
        target.mkdir(parents=True, exist_ok=True)
        for source_path in stage.iterdir():
            if source_path.is_file():
                shutil.copy2(source_path, target / source_path.name)
    final = verify_template_pack(target, manifest)
    final_coordinates = _verify_coordinate_pack(target, manifest)
    return {
        "schema": "genoma-editorial-v3-template-install-v2",
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
        "note": "No template or coordinate inventory is downloaded blindly; every installed artifact must match its pinned SHA-256 identity.",
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
        path = Path(args.evidence); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
