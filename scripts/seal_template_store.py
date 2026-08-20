#!/usr/bin/env python3
"""Seal the approved GENOMA v3.0 report template pack into the private store.

`scripts/verify_template_store.py` is the only reader of that transport; this is the only
writer. The pair mirrors `seal_ruleset.py` / `sealed_ruleset.py`, for the same reason: a
transport nobody can regenerate byte-for-byte cannot be re-verified after the fact.

The authoritative identity of the pack is the SHA-256 of each of the 11 PDFs, pinned in
both `template_store/v3.0/MANIFEST.json` and `reporting/reference_v3_manifest.json`. This
script refuses to seal unless every template matches both, so a wrong, altered or partial
pack can never enter the store. The tar.xz wrapper is a container: it is rebuilt
deterministically here, and only the transport fields of the manifest are rewritten.

    python3 scripts/seal_template_store.py --input /path/to/pack.zip
    python3 scripts/seal_template_store.py --input /path/to/directory
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import lzma
import tarfile
from datetime import datetime, timezone
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "template_store" / "v3.0"
MANIFEST = STORE / "MANIFEST.json"
REFERENCE = ROOT / "reporting" / "reference_v3_manifest.json"
PARTS_DIR = STORE / "sealed" / "parts"
CHUNK_BYTES = 48000
ARCHIVE_NAME = "GENOMA_V3_TEMPLATE_PACK.tar.xz"


class TemplateSealError(RuntimeError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_pack(source: Path) -> dict[str, bytes]:
    """Read the 11 templates from a directory or a zip, ignoring any folder nesting."""
    members: dict[str, bytes] = {}
    if source.is_dir():
        for path in sorted(source.rglob("*.pdf")):
            members[path.name] = path.read_bytes()
    elif zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                    continue
                name = Path(info.filename).name
                if name in members:
                    raise TemplateSealError(f"duplicate template name in pack: {name}")
                members[name] = archive.read(info)
    else:
        raise TemplateSealError(f"input must be a directory or a zip: {source}")
    if not members:
        raise TemplateSealError("no PDF templates found in the supplied pack")
    return members


def verify_against_pinned_identity(
    members: dict[str, bytes],
    *,
    amend: tuple[str, ...] = (),
    reason: str = "",
) -> dict:
    """Refuse any pack that is not the approved one, unless a change is named and justified.

    The guard exists because a template is the page a clinical report is printed on: a
    silently substituted one changes every future document. It stays absolute for anything
    the caller did not name — `--amend 11` permits report 11 to differ and still fails on a
    difference in report 03.

    An amendment is recorded, not just allowed. The previous hash, the new hash, the reason
    and the date go into the manifest, because after this the pack is no longer byte-identical
    to the externally supplied models and a reader has to be able to see that and why.
    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reports = manifest["reports"]

    expected_names = {meta["filename"] for meta in reports.values()}
    if set(members) != expected_names:
        missing = sorted(expected_names - set(members))
        extra = sorted(set(members) - expected_names)
        raise TemplateSealError(f"pack member set mismatch; missing={missing} unexpected={extra}")

    unknown = sorted(set(amend) - set(reports))
    if unknown:
        raise TemplateSealError(f"--amend names reports that do not exist: {unknown}")
    if amend and not reason.strip():
        raise TemplateSealError(
            "--amend requires --reason: an unexplained change to an approved template is "
            "indistinguishable from a substituted one"
        )

    failures: list[str] = []
    amendments: list[dict] = []
    for rid in sorted(reports):
        meta = reports[rid]
        ref = reference["reports"].get(rid, {})
        data = members[meta["filename"]]
        digest = sha256_bytes(data)
        changed = digest != meta["sha256"] or len(data) != meta["size_bytes"]
        if changed and rid in amend:
            amendments.append(
                {
                    "report": rid,
                    "filename": meta["filename"],
                    "previous_sha256": meta["sha256"],
                    "previous_size_bytes": meta["size_bytes"],
                    "sha256": digest,
                    "size_bytes": len(data),
                    "reason": reason.strip(),
                    "amended_at": datetime.now(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                }
            )
            continue
        if changed:
            failures.append(f"{rid}: differs from template_store identity ({digest})")
        if digest != ref.get("sha256") or len(data) != ref.get("size_bytes"):
            failures.append(f"{rid}: differs from reporting reference identity ({digest})")
    if failures:
        raise TemplateSealError("approved template identity mismatch:\n  " + "\n  ".join(failures))

    for entry in amendments:
        rid = entry["report"]
        reports[rid]["sha256"] = entry["sha256"]
        reports[rid]["size_bytes"] = entry["size_bytes"]
        reference["reports"][rid]["sha256"] = entry["sha256"]
        reference["reports"][rid]["size_bytes"] = entry["size_bytes"]
        print(f"  amendment {rid}: {entry['previous_sha256'][:12]} -> {entry['sha256'][:12]}")
    if amendments:
        manifest.setdefault("amendments", []).extend(amendments)
        # The pack no longer *is* the attached models, and the manifest must stop saying so.
        manifest["source"] = (
            "exact user-attached GENOMA v3.0 PDF models, with recorded amendments; "
            "see `amendments`"
        )
        REFERENCE.write_text(
            json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return manifest


def deterministic_archive(members: dict[str, bytes]) -> bytes:
    """tar.xz with every source of nondeterminism pinned, so re-sealing reproduces bytes."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name in sorted(members):
            data = members[name]
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    return lzma.compress(
        buffer.getvalue(),
        format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC64,
        filters=[{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}],
    )


def write_parts(encoded: bytes) -> list[dict]:
    PARTS_DIR.mkdir(parents=True, exist_ok=True)
    for stale in PARTS_DIR.glob("tplpart-*"):
        stale.unlink()
    parts: list[dict] = []
    for index in range(0, len(encoded), CHUNK_BYTES):
        chunk = encoded[index : index + CHUNK_BYTES]
        name = f"tplpart-{index // CHUNK_BYTES:03d}"
        (PARTS_DIR / name).write_bytes(chunk)
        parts.append({"name": name, "size_bytes": len(chunk), "sha256": sha256_bytes(chunk)})
    return parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="directory or zip holding the 11 approved PDFs")
    parser.add_argument(
        "--amend",
        action="append",
        default=[],
        metavar="REPORT_ID",
        help="permit this report to differ from the pinned identity, and repin it. Any "
        "report not named here still fails on any difference.",
    )
    parser.add_argument("--reason", default="", help="why the amended template changed")
    args = parser.parse_args()

    members = load_pack(Path(args.input))
    manifest = verify_against_pinned_identity(
        members, amend=tuple(args.amend), reason=args.reason
    )
    print(f"approved template identity: {len(members)}/11 VERIFICADO")

    archive = deterministic_archive(members)
    encoded = base64.b64encode(archive)
    parts = write_parts(encoded)

    # Only the transport container is rewritten. Report identities stay exactly as pinned.
    manifest["storage"] = {
        **manifest.get("storage", {}),
        "mode": "sealed-tar-xz-base64-chunks",
        "parts_dir": "template_store/v3.0/sealed/parts",
        "part_count": len(parts),
        "decoded_archive": ARCHIVE_NAME,
        "decoded_archive_size_bytes": len(archive),
        "decoded_archive_sha256": sha256_bytes(archive),
        "base64_size_bytes": len(encoded),
        "materialized_dir": "template_store/v3.0/materialized",
        "transport_encoding": "base64(xz(tar(USTAR, sorted, mtime=0, uid/gid=0), preset=9e, check=CRC64))",
        "transport_writer": "scripts/seal_template_store.py",
        "transport_reader": "scripts/verify_template_store.py",
    }
    manifest["parts"] = parts
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  archive sha256 {manifest['storage']['decoded_archive_sha256']}")
    print(f"  archive bytes  {len(archive)}")
    print(f"  base64 bytes   {len(encoded)}")
    print(f"  parts          {len(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
