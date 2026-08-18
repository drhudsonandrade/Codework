"""Single source of truth for the GENOMA canonical normative identity.

Every plane (policy control, scientific data, evidence, audit) and every gate that
emits a `ruleset` block must take its identity from here instead of restating the
version, date or hash inline. Ruleset v3.4 REGRA DE UNICIDADE allows exactly one
source marked VIGENTE; duplicating the identity as literals across dozens of modules
is how a repository silently keeps attesting to a superseded version.

`policy_engine/` is a standalone installable package with no dependency on the
repository root, so it carries its own copy of these constants. The two are held
together by `tests/test_normative_identity.py`, which fails closed on any drift.
"""
from __future__ import annotations

from typing import Any

STATUS = "VIGENTE"
VERSION = "v3.4"
EFFECTIVE_DATE = "17/08/2026"
CANONICAL_FILENAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
NORMATIVE_IDENTIFIER = "GENOMA-RULESET-v3.4"
RAW_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
RAW_SIZE_BYTES = 195733
SECTION_COUNT = 263
LAST_SECTION = 262
SHA_MANIFEST_RELATIVE = "manifests/RULESET_V3.4.sha256"

IDENTITY_STRING = f"{VERSION}/{STATUS}/{EFFECTIVE_DATE}"

# Retained so provenance of the superseded source is never erased (principles 2 and 10).
SUPERSEDED = {
    "version": "v3.3",
    "effective_date": "14/08/2026",
    "canonical_filename": "REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt",
    "raw_sha256": "187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a",
    "status": "OBSOLETA",
    "archived_manifest": "manifests/archive/RULESET_V3.3.sha256.obsolete",
}

# Header lines that must appear verbatim in the canonical artifact.
REQUIRED_HEADER_LINES = (
    f"STATUS NORMATIVO: {STATUS}",
    f"VERSÃO NORMATIVA: {VERSION}",
    f"DATA FORMAL DE EMISSÃO E VIGÊNCIA: {EFFECTIVE_DATE}",
    f"IDENTIFICADOR NORMATIVO: {NORMATIVE_IDENTIFIER}",
    f"ARQUIVO CANÔNICO: {CANONICAL_FILENAME}",
)


def ruleset_block(*, include_sha256: bool = True) -> dict[str, Any]:
    """The `ruleset` block embedded in gate artifacts and report payloads."""

    block: dict[str, Any] = {
        "status": STATUS,
        "version": VERSION,
        "effective_date": EFFECTIVE_DATE,
    }
    if include_sha256:
        block["sha256"] = RAW_SHA256
    return block


def attested_ruleset_block(sealed_dir: Any = None) -> dict[str, Any]:
    """A `ruleset` block whose status reflects what was actually proven in this run.

    A gate artifact that always prints `status: VIGENTE` is a claim, not evidence, and
    CAPABILITY HONESTY (principle 8) forbids it. When the sealed transport is reachable
    this decodes and hashes it, so the block is `VERIFICADO`. When it is not reachable the
    block degrades to `NÃO DISPONÍVEL` with a reason rather than asserting compliance.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent
    target = Path(sealed_dir) if sealed_dir is not None else root / "sealed"

    try:
        # Imported lazily: the reader imports this module for its expected identity.
        from scripts.sealed_ruleset import verify_transport

        evidence = verify_transport(target)
    except Exception as exc:  # noqa: BLE001 - any failure must degrade, never raise into a gate
        return {
            "status": "NÃO DISPONÍVEL",
            "version": VERSION,
            "effective_date": EFFECTIVE_DATE,
            "attestation": "NÃO DISPONÍVEL",
            "reason": f"sealed normative transport not verifiable: {type(exc).__name__}: {exc}",
        }

    return {
        "status": evidence["status"],
        "version": evidence["version"],
        "effective_date": evidence["effective_date"],
        "normative_identifier": evidence["normative_identifier"],
        "canonical_filename": evidence["canonical_filename"],
        "sha256": evidence["raw_sha256"],
        "section_count": evidence["section_count"],
        "attestation": "VERIFICADO",
        "verification": "sealed transport decoded and hashed in this run",
    }


def rule_id(section: int) -> str:
    """Stable machine-addressable identity for a top-level normative section."""

    if not 0 <= section <= LAST_SECTION:
        raise ValueError(f"section out of normative range 0..{LAST_SECTION}: {section}")
    return f"GENOMA-V3.4-S{section:03d}"
