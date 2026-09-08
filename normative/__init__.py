"""Single source of truth for the GENOMA canonical normative identity.

Every plane (policy control, scientific data, evidence, audit) and every gate that
emits a `ruleset` block must take its identity from here instead of restating the
version, date or hash inline. Ruleset v3.4's uniqueness rule allows exactly one
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
LAST_SECTION = SECTION_COUNT - 1
SHA_MANIFEST_RELATIVE = "manifests/RULESET_V3.4.sha256"

IDENTITY_STRING = f"{VERSION}/{STATUS}/{EFFECTIVE_DATE}"

COMPANION_MANIFEST_RELATIVE = "manifests/COMPANION_SOURCES.sha256"

# Companion documents distributed alongside the norm. They are integrity-pinned so a
# swapped copy is detectable and explicitly NOT normative: the companion prompt states that
# in a conflict the active norm prevails and generation must stop. Nothing here may be
# consulted in place of the ruleset, and no gate may take its identity from this table.
COMPANION_SOURCES = {
    "PROMPT_FONTE_GERACAO_RELATORIOS_GENOMICOS_v1.2.txt": {
        "sha256": "1b8a199ce9a94213aa22dedb0476284c2e72f163ab8db0eefc2beb45ab3515e1",
        "version": "1.2",
        "date": "17/08/2026",
        "nature": "COMPLEMENTAR E NÃO NORMATIVA",
        "normative": False,
        "precedence": "a norma vigente prevalece integralmente; em conflito, a geração deve parar",
    },
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


def verify_companion(filename: str, path: Any) -> dict[str, Any]:
    """Check a companion document against its pinned digest.

    Returns a status block; never raises into a caller and never promotes the companion to
    a normative source. An unknown or mismatched file is NÃO DISPONÍVEL, not a fallback
    ruleset.
    """
    import hashlib
    from pathlib import Path

    spec = COMPANION_SOURCES.get(filename)
    if spec is None:
        return {"file": filename, "status": "NÃO DISPONÍVEL", "reason": "not a registered companion source", "normative": False}
    candidate = Path(path)
    if not candidate.is_file():
        return {"file": filename, "status": "NÃO DISPONÍVEL", "reason": "file not present", "normative": False}
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if digest != spec["sha256"]:
        return {
            "file": filename,
            "status": "NÃO DISPONÍVEL",
            "reason": "SHA-256 mismatch",
            "expected": spec["sha256"],
            "observed": digest,
            "normative": False,
        }
    return {
        "file": filename,
        "status": "VERIFICADO",
        "sha256": digest,
        "version": spec["version"],
        "nature": spec["nature"],
        "normative": False,
        "precedence": spec["precedence"],
    }


def rule_id(section: int) -> str:
    """Stable machine-addressable identity for a top-level normative section."""

    if not 0 <= section <= LAST_SECTION:
        raise ValueError(f"section out of normative range 0..{LAST_SECTION}: {section}")
    return f"GENOMA-{VERSION.upper()}-S{section:03d}"
