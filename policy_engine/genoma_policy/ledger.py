from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _entry_hash(record_without_hash: dict[str, Any]) -> str:
    return _sha256_text(_canonical_json(record_without_hash))


class LedgerError(RuntimeError):
    """The chain on disk is not the chain this ledger wrote."""


def append_event(path: str | Path, event_type: str, payload: Any) -> dict[str, Any]:
    """Append one event, refusing to extend a chain that no longer verifies.

    This used to read only the last line and continue from it. A tampered entry anywhere
    earlier stayed invisible: the new record chained onto a hash that was still internally
    consistent with a rewritten history, and every later append signed off on it. The chain
    was verifiable after the fact and never verified before being extended, which is the one
    moment the check is worth anything.
    """
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    previous_hash = GENESIS_HASH
    sequence = 1
    if ledger_path.exists() and ledger_path.stat().st_size:
        ok, errors = verify_ledger(ledger_path)
        if not ok:
            raise LedgerError(
                f"refusing to append to {ledger_path.name}: the existing chain does not "
                f"verify ({'; '.join(errors[:5])}). An append onto a broken chain endorses "
                "the break as history."
            )
        lines = [line for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            previous = json.loads(lines[-1])
            previous_hash = str(previous.get("entry_sha256", ""))
            sequence = int(previous.get("sequence", 0)) + 1

    record: dict[str, Any] = {
        "sequence": sequence,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "payload_sha256": _sha256_text(_canonical_json(payload)),
        "previous_entry_sha256": previous_hash,
    }
    record["entry_sha256"] = _entry_hash(record)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json(record) + "\n")
    return record


def verify_ledger(path: str | Path) -> tuple[bool, list[str]]:
    ledger_path = Path(path)
    errors: list[str] = []
    if not ledger_path.exists():
        return False, ["ledger file does not exist"]

    expected_previous = GENESIS_HASH
    expected_sequence = 1
    for line_number, raw in enumerate(ledger_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_number} invalid JSON: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"line {line_number} is not an object")
            continue
        if record.get("sequence") != expected_sequence:
            errors.append(f"line {line_number} sequence mismatch")
        if record.get("previous_entry_sha256") != expected_previous:
            errors.append(f"line {line_number} previous hash mismatch")
        declared = record.get("entry_sha256")
        unsigned = {key: value for key, value in record.items() if key != "entry_sha256"}
        calculated = _entry_hash(unsigned)
        if declared != calculated:
            errors.append(f"line {line_number} entry hash mismatch")
        if isinstance(declared, str):
            expected_previous = declared
        expected_sequence += 1
    return not errors, errors
