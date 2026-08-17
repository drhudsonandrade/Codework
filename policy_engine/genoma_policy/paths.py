from __future__ import annotations

import os
from pathlib import Path

CANONICAL_RULESET_NAME = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
CANONICAL_MANIFEST_RELATIVE = Path("manifests") / "RULESET_V3.4.sha256"


class AssetResolutionError(RuntimeError):
    pass


def _unique_existing(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            candidate = path.expanduser().resolve()
        except OSError:
            candidate = path.expanduser().absolute()
        if candidate.is_file() and candidate not in seen:
            seen.add(candidate)
            resolved.append(candidate)
    return resolved


def resolve_ruleset_path(base_dir: str | Path | None = None) -> Path:
    """Resolve exactly one canonical ruleset location, otherwise fail closed."""

    base = Path(base_dir) if base_dir is not None else Path.cwd()
    explicit = os.environ.get("GENOMA_RULESET_PATH")
    if explicit:
        existing = _unique_existing([Path(explicit)])
        if len(existing) != 1:
            raise AssetResolutionError("RULESET NÃO DISPONÍVEL/CONFLITANTE: explicit GENOMA_RULESET_PATH is not a file")
        return existing[0]
    candidates: list[Path] = [
        base / CANONICAL_RULESET_NAME,
        base.parent / CANONICAL_RULESET_NAME,
    ]
    existing = _unique_existing(candidates)
    if len(existing) != 1:
        raise AssetResolutionError(
            "RULESET NÃO DISPONÍVEL/CONFLITANTE: expected exactly one canonical ruleset path, "
            f"found {len(existing)}"
        )
    return existing[0]


def resolve_manifest_path(ruleset_path: str | Path, base_dir: str | Path | None = None) -> Path:
    """Resolve the external SHA manifest adjacent to the ruleset root or engine root."""

    ruleset = Path(ruleset_path).resolve()
    base = Path(base_dir) if base_dir is not None else Path.cwd()
    explicit = os.environ.get("GENOMA_RULESET_SHA_MANIFEST")
    if explicit:
        existing = _unique_existing([Path(explicit)])
        if len(existing) != 1:
            raise AssetResolutionError("explicit GENOMA_RULESET_SHA_MANIFEST is not a file")
        return existing[0]
    candidates: list[Path] = [
        ruleset.parent / CANONICAL_MANIFEST_RELATIVE,
        base / CANONICAL_MANIFEST_RELATIVE,
        base.parent / CANONICAL_MANIFEST_RELATIVE,
    ]
    existing = _unique_existing(candidates)
    if not existing:
        raise AssetResolutionError("RULESET SHA manifest not available")
    if len(existing) > 1:
        raise AssetResolutionError(f"conflicting ruleset SHA manifests found: {existing}")
    return existing[0]
