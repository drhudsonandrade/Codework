#!/usr/bin/env python3
from __future__ import annotations

import argparse
import errno
import fcntl
import gzip
import hashlib
import io
import json
import os
import stat
from pathlib import Path


class InputRefused(ValueError):
    """Containment said no: an escape, a symlink, or a platform that cannot refuse one."""


class InputMissing(ValueError):
    """Nothing is at that path. Not a refusal — the sample did not deliver the file."""


class InputUnreadable(ValueError):
    """The path exists and is contained, but the open failed for some other reason."""


def _open_failure(exc: OSError) -> ValueError:
    """Name what actually went wrong, instead of calling everything a refusal.

    `open_contained` reports every failure as a ValueError so callers have one type to
    catch, and flattening all of them into `refused` traded one conflation for its mirror
    image: an absent FASTQ became evidence that something tried to escape the sample
    directory. These are three different operational facts and the Evidence Plane has to
    keep them apart — ELOOP here is the O_NOFOLLOW refusal of a symlinked component, not a
    missing file, and EACCES is neither.
    """
    if exc.errno in (errno.ENOENT, errno.ENOTDIR):
        return InputMissing(f"input is not present: {exc}")
    if exc.errno == errno.ELOOP:
        return InputRefused(f"input could not be opened: {exc}")
    return InputUnreadable(f"input could not be opened: {exc}")


def _sha256_stream(handle) -> str:
    """Hash an already-open handle from its start, leaving it rewound."""
    handle.seek(0)
    h = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        h.update(chunk)
    handle.seek(0)
    return h.hexdigest()


def open_contained(root: Path, path: Path):
    """Open a validated input by walking down from the root, one component at a time.

    Containment is checked against a *path*, and every later step used to reopen that path by
    name — probe it, hash it, size it. Between the check and each of those opens the name can
    be repointed, so the bytes recorded as this sample's input were not provably the bytes
    that passed containment.

    Opening the final component with `O_NOFOLLOW` is not enough on its own: given
    `nested/r1.fastq`, `nested` itself can be swapped for a link to somewhere else after
    `resolve` accepted the path, and the final open then lands on an outside file that is a
    perfectly ordinary regular file. So the walk starts at the trusted root and opens each
    component relative to the previous one with `dir_fd`, refusing a symlink at every step,
    directories included. The descriptor that comes back is the one every consumer uses;
    nothing re-looks-up a name afterwards.
    """
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise InputRefused("input path escapes the sample directory") from exc
    parts = relative.parts
    if not parts:
        raise InputRefused("input path names no file")
    # `relative_to` does not normalise: for root=/s and path=/s/../outside.fastq it returns
    # `../outside.fastq`, and the walk below would then open `..` with dir_fd and step
    # straight out of the root — no symlink anywhere, so O_NOFOLLOW never fires. Today's
    # callers hand over paths `resolve` already normalised, but this function *is* the
    # containment boundary and is called directly, so it has to hold on its own.
    if any(component in ("..", ".", "") for component in parts):
        raise InputRefused("input path escapes the sample directory")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        # Defaulting the flag to 0 would turn a platform that cannot refuse symlinks into
        # one that silently follows them. A gate that quietly weakens itself is worse than
        # one that stops.
        raise InputRefused("input could not be opened: O_NOFOLLOW unavailable")
    open_fds: list[int] = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        open_fds.append(parent)
        for component in parts[:-1]:
            parent = os.open(
                component,
                os.O_RDONLY | os.O_DIRECTORY | nofollow,
                dir_fd=parent,
            )
            open_fds.append(parent)
        # O_NONBLOCK because a FIFO sitting at this path would otherwise park `os.open`
        # until some writer showed up, and the gate would hang instead of answering. A gate
        # that never returns is not fail-closed: nothing downstream ever reads a status, and
        # `input-qc.json` is never written at all.
        descriptor = os.open(
            parts[-1], os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0), dir_fd=parent
        )
    except OSError as exc:
        raise _open_failure(exc) from exc
    finally:
        for fd in open_fds:
            os.close(fd)
    # Having opened it without blocking, refuse anything that is not a plain file — a FIFO,
    # a device, a socket. `fstat` on the descriptor we already hold, not another look at the
    # name. A sample input is a file; the rest are ways to make the gate read something that
    # is not one.
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise InputRefused("input is not a regular file")
        # Regular files ignore O_NONBLOCK on read, but clear it anyway so the descriptor
        # handed to the probe and the hash behaves exactly as an ordinary open would.
        flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
        fcntl.fcntl(descriptor, fcntl.F_SETFL, flags & ~getattr(os, "O_NONBLOCK", 0))
    except BaseException:
        os.close(descriptor)
        raise
    return os.fdopen(descriptor, "rb")


def resolve(root: Path, value: str | None) -> Path | None:
    """Resolve a manifest-declared input without granting ambient filesystem authority.

    The manifest is sample-supplied, so an absolute path or a `../` chain must not let it
    name a file outside the sample directory that the gate would then hash and record as a
    verified input. Symlinks are followed before the containment check, so a link planted
    inside the sample directory cannot reach out either.

    Every refusal is a ValueError, so `validate_manifest` has one exception type to catch and
    the gate always answers with a status rather than a traceback.
    """
    # Type before emptiness, in that order. The manifest is JSON, so a path field can arrive
    # as a number, a bool, a list or an object, and `Path()` raises TypeError on all of them.
    # Testing `not value` first also swallowed every *falsy* non-string — False, 0, 0.0, [],
    # {} — as though the field had been left out, which reports "FASTQ requires r1 and r2"
    # for a manifest that did supply r1, just not as text. A missing field and a wrong type
    # are different facts and the gate now says which one it found.
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"input path must be a string, got {type(value).__name__}")
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError("absolute input paths are not allowed in sample-manifest.json")
    try:
        absolute_root = root.resolve()
        candidate = (absolute_root / raw).resolve()
    except (OSError, RuntimeError) as exc:
        # `Path.resolve()` raises RuntimeError on a symlink loop and OSError on other
        # filesystem failures. Left uncaught, the call added here to *enforce* containment
        # was itself a way to kill the gate before it could report NÃO DISPONÍVEL.
        raise ValueError(f"input path could not be resolved: {exc}") from exc
    try:
        candidate.relative_to(absolute_root)
    except ValueError as exc:
        raise ValueError("input path escapes the sample directory") from exc
    # Version-independent loop detection. `Path.resolve()` raises RuntimeError on a symlink
    # loop up to Python 3.12; from 3.13 the non-strict form raises nothing and returns a
    # partially resolved path instead, so the handler above would never fire and the loop
    # would only surface later, as an ELOOP at open time. `stat` reports ELOOP on every
    # supported version, and a path that simply does not exist yet is not this check's
    # business — the probe reports that separately.
    try:
        candidate.stat()
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"input path could not be resolved: {exc}") from exc
    return candidate


def fastq_probe(root: Path, path: Path) -> tuple[bool, dict]:
    """Probe and hash one FASTQ through a single open handle.

    The probe and the hash used to open the path separately, so the bytes recorded as this
    sample's input were not provably the bytes the probe accepted.
    """
    try:
        raw = open_contained(root, path)
    except InputMissing:
        return False, {"path": str(path), "reason": "missing_or_empty"}
    except InputRefused as exc:
        # Escape, symlink and swapped-parent refusals all used to be flattened into
        # "missing_or_empty", so input-qc.json described a containment breach as a file the
        # sample forgot to upload — and `errors` said only "R1 integrity probe failed".
        return False, {"path": str(path), "reason": f"refused: {exc}"}
    except InputUnreadable as exc:
        return False, {"path": str(path), "reason": f"unreadable: {exc}"}
    try:
        with raw:
            if os.fstat(raw.fileno()).st_size == 0:
                return False, {"path": str(path), "reason": "missing_or_empty"}
            stream = gzip.GzipFile(fileobj=raw) if path.suffix == ".gz" else raw
            handle = io.TextIOWrapper(stream, encoding="utf-8", errors="strict")
            records = []
            for _ in range(128):
                row = [handle.readline() for __ in range(4)]
                if row[0] == "":
                    break
                if any(part == "" for part in row) or not row[0].startswith("@") or not row[2].startswith("+") or len(row[1].strip()) != len(row[3].strip()):
                    return False, {"path": str(path), "reason": "malformed_fastq_probe"}
                records.append(row[0].strip().split()[0])
            if not records:
                return False, {"path": str(path), "reason": "no_records"}
            handle.detach()
            return True, {
                "path": str(path),
                "probe_records": len(records),
                "sha256": _sha256_stream(raw),
            }
    except (OSError, EOFError, UnicodeError, gzip.BadGzipFile) as exc:
        return False, {"path": str(path), "reason": type(exc).__name__}


def validate_manifest(manifest_path: Path) -> dict:
    """Turn one sample manifest into the gate's verdict, never into a traceback.

    Every refusal the helpers raise is caught here and reported as an entry in `errors`, so
    the caller always receives a status document. That matters because `workflows/wgs.nf`
    gates the whole WGS lane on this file reading VERIFICADO: a process that dies without
    writing `input-qc.json` leaves the lane waiting on a verdict that never arrives, which is
    not the same thing as refusing.

    `root` is resolved once. A sample directory reached through a symlink (a `/tmp` staging
    root, say) would otherwise compare against its logical path and refuse every legitimate
    input in it.
    """
    root = manifest_path.parent.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    sample_id = str(manifest.get("sample_id") or "").strip()
    input_type = str(manifest.get("input_type") or "").upper()
    rg = manifest.get("read_group") if isinstance(manifest.get("read_group"), dict) else {}
    if not sample_id:
        errors.append("sample_id missing")
    if input_type not in {"FASTQ", "BAM", "CRAM"}:
        errors.append("input_type must be FASTQ, BAM, or CRAM")
    required_rg = ("id", "sample", "library", "platform")
    for key in required_rg:
        if not str(rg.get(key) or "").strip():
            errors.append(f"read_group.{key} missing")
    if sample_id and str(rg.get("sample") or "") != sample_id:
        errors.append("read_group.sample must equal sample_id")

    inputs: dict[str, dict] = {}
    # A refused path is already a reported error; re-reporting it as "missing" would
    # describe a containment breach as an absent file.
    refused = False
    if input_type == "FASTQ":
        try:
            r1 = resolve(root, manifest.get("r1"))
            r2 = resolve(root, manifest.get("r2"))
        except ValueError as exc:
            r1 = r2 = None
            refused = True
            errors.append(str(exc))
        if r1 is None or r2 is None:
            if not refused:
                errors.append("FASTQ requires r1 and r2")
        else:
            ok1, d1 = fastq_probe(root, r1)
            ok2, d2 = fastq_probe(root, r2)
            inputs["r1"] = d1
            inputs["r2"] = d2
            if not ok1:
                errors.append("R1 integrity probe failed")
            if not ok2:
                errors.append("R2 integrity probe failed")
    elif input_type in {"BAM", "CRAM"}:
        try:
            alignment = resolve(root, manifest.get("alignment"))
        except ValueError as exc:
            alignment = None
            refused = True
            errors.append(str(exc))
        # Size and hash from one handle, for the same reason as the FASTQ path: `stat` then
        # `open` is two lookups of a name that was validated once.
        alignment_size = None
        # Same distinction as the FASTQ path: a refused open is a containment fact, not an
        # absent file, and the Evidence Plane has to be able to tell them apart.
        alignment_refusal = None
        if alignment is not None:
            try:
                with open_contained(root, alignment) as handle:
                    alignment_size = os.fstat(handle.fileno()).st_size
                    alignment_sha = _sha256_stream(handle) if alignment_size else None
            except InputMissing:
                alignment_size = None
            except InputRefused as exc:
                alignment_size = None
                alignment_refusal = f"refused: {exc}"
            except InputUnreadable as exc:
                alignment_size = None
                alignment_refusal = f"unreadable: {exc}"
            except OSError as exc:
                alignment_size = None
                alignment_refusal = f"unreadable: {type(exc).__name__}"
        if alignment is None or not alignment_size:
            if not refused:
                errors.append(f"{input_type} alignment {alignment_refusal or 'missing_or_empty'}")
        else:
            inputs["alignment"] = {
                "path": str(alignment),
                "size_bytes": alignment_size,
                "sha256": alignment_sha,
            }

    return {
        "schema": "genoma-wgs-input-gate-v1",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "sample_id": sample_id or None,
        "input_type": input_type or None,
        "read_group": rg,
        "inputs": inputs,
        "errors": errors,
        "note": "FASTQ is probed here; complete BAM/CRAM/read-group integrity is re-executed after alignment before variant calling.",
    }


def main() -> int:
    """Write `input-qc.json` and exit 0 only when the sample verified.

    The exit status and the file say the same thing on purpose: the workflow reads the file,
    a human reads the stream, and a disagreement between the two would be the gate arguing
    with itself.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = validate_manifest(Path(args.manifest))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "VERIFICADO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
