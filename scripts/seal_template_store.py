#!/usr/bin/env python3
"""Seal an approved GENOMA report template pack into the private store.

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
    python3 scripts/seal_template_store.py --input pack.zip --suite v3.1 --from-suite v3.0 \
        --reason "..."

**Why `--suite` exists.** The store's contract says a report may not change its SHA-256
under a given suite version, and that any byte-level change requires a *new suite version
and a new immutable manifest*. This script hardcoded `v3.0`, so the only way it could accept
a changed template was `--amend`, which repins the hash in place — under the same version
label. That is the one thing the contract forbids, and it had already happened: report 11's
identity was repinned under v3.0 on 2026-08-20, leaving two different byte-sets both called
"GENOMA v3.0" with nothing to tell them apart.

`--amend` is therefore refused against a suite that is already sealed. A changed pack is
sealed as a new suite, which is what the contract asked for in the first place.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import lzma
import re
import tarfile
from datetime import datetime, timezone
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE_ROOT = ROOT / "template_store"
DEFAULT_SUITE = "v3.0"
REFERENCE = ROOT / "reporting" / "reference_v3_manifest.json"
CHUNK_BYTES = 48000

#: A suite label names a directory under the store, so it must not be able to escape it.
SUITE_NAME = re.compile(r"^v\d+\.\d+$")


def suite_paths(suite: str) -> tuple[Path, Path, Path]:
    """(store, manifest, parts) for one suite version."""
    if not SUITE_NAME.fullmatch(suite):
        raise TemplateSealError(f"suite must look like v3.1, got {suite!r}")
    store = STORE_ROOT / suite
    return store, store / "MANIFEST.json", store / "sealed" / "parts"
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
    suite: str = DEFAULT_SUITE,
    from_suite: str | None = None,
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
    store, manifest_path, _parts = suite_paths(suite)
    new_suite = not manifest_path.is_file()
    if new_suite:
        if from_suite is None:
            raise TemplateSealError(
                f"suite {suite} does not exist yet; name the suite it descends from with "
                "--from-suite so the new manifest records its lineage instead of appearing "
                "from nowhere"
            )
        _base_store, base_manifest_path, _base_parts = suite_paths(from_suite)
        if not base_manifest_path.is_file():
            raise TemplateSealError(f"--from-suite {from_suite} has no manifest to descend from")
        if not reason.strip():
            raise TemplateSealError(
                "a new suite version requires --reason: an unexplained new suite is "
                "indistinguishable from a substituted pack"
            )
        manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    reports = manifest["reports"]

    expected_names = {meta["filename"] for meta in reports.values()}
    if set(members) != expected_names:
        missing = sorted(expected_names - set(members))
        extra = sorted(set(members) - expected_names)
        raise TemplateSealError(f"pack member set mismatch; missing={missing} unexpected={extra}")

    failures: list[str] = []
    changes: list[dict] = []
    for rid in sorted(reports):
        meta = reports[rid]
        ref = reference["reports"].get(rid, {})
        data = members[meta["filename"]]
        digest = sha256_bytes(data)
        changed = digest != meta["sha256"] or len(data) != meta["size_bytes"]
        if not changed:
            # Unchanged reports must also still match the renderer's reference identity, or
            # the two pins have drifted apart and the renderer would refuse the pack anyway.
            if digest != ref.get("sha256") or len(data) != ref.get("size_bytes"):
                failures.append(f"{rid}: differs from reporting reference identity ({digest})")
            continue
        if not new_suite:
            # The contract in template_store/<suite>/README.md: a report may not change its
            # identity under a suite that is already sealed. Repinning it in place is what
            # produced two different byte-sets both calling themselves v3.0.
            failures.append(
                f"{rid}: differs from the sealed {suite} identity ({meta['sha256'][:12]} -> "
                f"{digest[:12]}). A byte-level change requires a new suite version: re-run "
                f"with --suite <next> --from-suite {suite} --reason '...'"
            )
            continue
        changes.append(
            {
                "report": rid,
                "filename": meta["filename"],
                "previous_sha256": meta["sha256"],
                "previous_size_bytes": meta["size_bytes"],
                "sha256": digest,
                "size_bytes": len(data),
            }
        )
    if failures:
        raise TemplateSealError("approved template identity mismatch:\n  " + "\n  ".join(failures))

    if new_suite:
        for entry in changes:
            rid = entry["report"]
            reports[rid]["sha256"] = entry["sha256"]
            reports[rid]["size_bytes"] = entry["size_bytes"]
            print(f"  {suite} {rid}: {entry['previous_sha256'][:12]} -> {entry['sha256'][:12]}")
        manifest["version"] = suite
        # Amendments recorded against the base suite are carried here, not left behind. They
        # are the history that *should* have produced a new suite in the first place: a repin
        # under the old label is what this tool now refuses, so when such a repin is found on
        # the baseline it becomes this suite's lineage rather than a footnote on the old one.
        inherited = manifest.pop("amendments", [])
        manifest["lineage"] = {
            "descends_from": from_suite,
            "reason": reason.strip(),
            "sealed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "reports_changed": [entry["report"] for entry in changes],
            "reports_unchanged": sorted(set(reports) - {entry["report"] for entry in changes}),
            "changes": changes,
            "inherited_amendments": inherited,
            "differs_from_base_original": sorted(
                {str(entry.get("report")) for entry in inherited}
                | {entry["report"] for entry in changes}
            ),
        }
        differing = manifest["lineage"]["differs_from_base_original"]
        manifest["source"] = (
            f"GENOMA {suite} template pack, descended from {from_suite}: "
            f"{len(differing)} of {len(reports)} reports differ from the originally approved "
            f"{from_suite} models ({', '.join(differing) or 'none'}). See `lineage`."
        )
        # The reference manifest is *not* rewritten here. It pins what the renderer consumes,
        # and moving the renderer to a new suite is a separate, deliberate act — silently
        # repointing it was how an amended pack came to be rendered under the old label.
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


def write_parts(encoded: bytes, parts_dir: Path) -> list[dict]:
    parts_dir.mkdir(parents=True, exist_ok=True)
    PARTS_DIR = parts_dir
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
        "--suite",
        default=DEFAULT_SUITE,
        help="suite version to seal into, e.g. v3.1. A suite that does not exist yet is "
        "created and requires --from-suite and --reason.",
    )
    parser.add_argument(
        "--from-suite",
        help="the sealed suite this new one descends from; its manifest is the baseline and "
        "the differences are recorded as lineage",
    )
    parser.add_argument("--reason", default="", help="why this suite version exists")
    args = parser.parse_args()

    store, manifest_path, parts_dir = suite_paths(args.suite)
    members = load_pack(Path(args.input))
    manifest = verify_against_pinned_identity(
        members, suite=args.suite, from_suite=args.from_suite, reason=args.reason
    )
    print(f"approved template identity: {len(members)}/{len(manifest['reports'])} VERIFICADO")

    archive = deterministic_archive(members)
    encoded = base64.b64encode(archive)
    parts = write_parts(encoded, parts_dir)

    # Only the transport container is rewritten. Report identities stay exactly as pinned.
    manifest["storage"] = {
        **manifest.get("storage", {}),
        "mode": "sealed-tar-xz-base64-chunks",
        "parts_dir": f"template_store/{args.suite}/sealed/parts",
        "part_count": len(parts),
        "decoded_archive": ARCHIVE_NAME,
        "decoded_archive_size_bytes": len(archive),
        "decoded_archive_sha256": sha256_bytes(archive),
        "base64_size_bytes": len(encoded),
        "materialized_dir": f"template_store/{args.suite}/materialized",
        "transport_encoding": "base64(xz(tar(USTAR, sorted, mtime=0, uid/gid=0), preset=9e, check=CRC64))",
        "transport_writer": "scripts/seal_template_store.py",
        "transport_reader": "scripts/verify_template_store.py",
    }
    manifest["parts"] = parts
    store.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"  archive sha256 {manifest['storage']['decoded_archive_sha256']}")
    print(f"  archive bytes  {len(archive)}")
    print(f"  base64 bytes   {len(encoded)}")
    print(f"  parts          {len(parts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
