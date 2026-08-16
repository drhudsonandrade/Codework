#!/usr/bin/env python3
"""Install the externally held GENOMA v3.0 visual template pack only after SHA verification."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.template_v3 import load_reference_manifest, verify_template_pack


def install(source: Path, target: Path) -> dict:
    manifest = load_reference_manifest()
    source_verification = verify_template_pack(source, manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="genoma-v3-template-stage-", dir=str(target.parent)) as td:
        stage = Path(td) / "pack"
        stage.mkdir()
        for rid in sorted(manifest["reports"]):
            name = manifest["reports"][rid]["filename"]
            shutil.copy2(source / name, stage / name)
        staged = verify_template_pack(stage, manifest)
        target.mkdir(parents=True, exist_ok=True)
        for rid in sorted(manifest["reports"]):
            name = manifest["reports"][rid]["filename"]
            shutil.copy2(stage / name, target / name)
    final = verify_template_pack(target, manifest)
    return {
        "schema": "genoma-editorial-v3-template-install-v1",
        "status": "VERIFICADO",
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": str(source),
        "target": str(target),
        "source_verification": source_verification,
        "staged_verification": staged,
        "final_verification": final,
        "note": "No template is downloaded blindly; every installed PDF must match the pre-approved SHA-256 manifest.",
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
