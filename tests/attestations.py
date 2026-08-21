"""One place to build the provenance attestations the array fixtures feed to QC.

Every fixture used to hand `inspect_array` a single attestation for *both* the build and
the strand — one object standing in for two different assertions, naming neither. That is
the shape of the defect it hid: `BUILD_STRAND_GATE` checked that an attestation existed,
was VERIFICADO/SATISFIED, and was bound to the input SHA-256, but never that it agreed with
the value being declared. `array_pipeline.provenance_probe` will honestly determine that a
file is on the reverse strand and emit exactly such an attestation saying so; paired with
`--strand forward` it passed every check and certified the file as forward.

`asserted_value` is now required, so a fixture has to say which assertion it is making, and
this helper exists so saying it costs one argument.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def attestation(
    input_sha: str,
    asserted_value: str,
    *,
    actor_id: str = "tests",
    attestation_id: str = "synthetic-fixture-provenance",
    justification: str = "Fixture determinístico declara explicitamente esta asserção.",
    evidence_ref: str = "synthetic-test-fixture",
    created_at: str = "2026-08-17T00:00:00Z",
) -> dict[str, Any]:
    """A structurally valid attestation for exactly one assertion."""
    return {
        "status": "VERIFICADO",
        "decision": "SATISFIED",
        "asserted_value": asserted_value,
        "justification": justification,
        "evidence_refs": [evidence_ref],
        "trace": {
            "attestation_id": attestation_id,
            "created_at": created_at,
            "actor_type": "SOFTWARE",
            "actor_id": actor_id,
            "method": "deterministic fixture",
            "run_id": "unit-test",
            "input_sha256": [input_sha],
            "output_sha256": [],
            "tool_versions": {"test": "1"},
        },
    }


def provenance_for(path: Path, *, build: str = "GRCh37", strand: str = "forward", **kwargs: Any) -> dict[str, str]:
    """The `inspect_array` provenance keyword arguments for a fixture array."""
    sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return {
        "build": build,
        "strand": strand,
        "build_evidence": json.dumps(attestation(sha, build, **kwargs), ensure_ascii=False),
        "strand_evidence": json.dumps(attestation(sha, strand, **kwargs), ensure_ascii=False),
    }
