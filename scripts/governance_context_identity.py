from __future__ import annotations

import hashlib
import re

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def context_digest(value: str) -> str:
    """Return the SHA-256 digest of an exact UTF-8 check context."""
    if not isinstance(value, str) or not value:
        raise ValueError("check context must be a non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint_is_valid(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    return (
        value.get("algorithm") == "sha256"
        and value.get("case_sensitive") is True
        and isinstance(value.get("provider_family"), str)
        and bool(value.get("provider_family"))
        and isinstance(value.get("digest"), str)
        and _SHA256_RE.fullmatch(value["digest"]) is not None
    )


def expected_check_is_well_formed(expected: object) -> bool:
    """Validate either a literal or fingerprinted tracked check identity."""
    if not isinstance(expected, dict):
        return False
    has_context = "context" in expected
    has_fingerprint = "context_fingerprint" in expected
    if has_context == has_fingerprint:
        return False
    if has_context and (
        not isinstance(expected.get("context"), str) or not expected.get("context")
    ):
        return False
    if has_fingerprint and not _fingerprint_is_valid(expected.get("context_fingerprint")):
        return False
    integration_id = expected.get("integration_id")
    return integration_id is None or (isinstance(integration_id, int) and not isinstance(integration_id, bool))


def match_expected_check(live: dict, expected: dict) -> bool:
    """Match live provider state against a tracked neutral check identity."""
    if not expected_check_is_well_formed(expected) or not isinstance(live, dict):
        return False
    live_context = live.get("context")
    if not isinstance(live_context, str):
        return False
    if "context" in expected:
        context_match = live_context == expected["context"]
    else:
        fingerprint = expected["context_fingerprint"]
        context_match = context_digest(live_context) == fingerprint["digest"]
    if not context_match:
        return False
    if "integration_id" in expected:
        return live.get("integration_id") == expected["integration_id"]
    return True
