from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .models import RulesetSection

EXPECTED_STATUS = "VIGENTE"
EXPECTED_VERSION = "v3.4"
EXPECTED_DATE = "17/08/2026"
EXPECTED_CANONICAL = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"
EXPECTED_SHA256 = "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580"
EXPECTED_SECTIONS = 263
EXPECTED_LAST_SECTION = 262

_HEADER_PATTERNS = {
    "status": re.compile(r"^STATUS NORMATIVO:\s*(.+?)\s*$", re.MULTILINE),
    "version": re.compile(r"^VERSÃO NORMATIVA:\s*(.+?)\s*$", re.MULTILINE),
    "date": re.compile(r"^DATA FORMAL DE EMISSÃO E VIGÊNCIA:\s*(.+?)\s*$", re.MULTILINE),
    "canonical": re.compile(r"^ARQUIVO CANÔNICO:\s*(.+?)\s*$", re.MULTILINE),
}


class RulesetError(RuntimeError):
    pass


@dataclass(frozen=True)
class Ruleset:
    path: Path
    sha256: str
    status: str
    version: str
    effective_date: str
    canonical_filename: str
    sections: tuple[RulesetSection, ...]

    def metadata(self) -> dict[str, object]:
        return {
            "status": self.status,
            "version": self.version,
            "effective_date": self.effective_date,
            "canonical_filename": self.canonical_filename,
            "sha256": self.sha256,
            "section_count": len(self.sections),
            "section_range": [0, self.sections[-1].number if self.sections else None],
        }


def _extract_header(text: str, field: str) -> str:
    match = _HEADER_PATTERNS[field].search(text)
    if not match:
        raise RulesetError(f"missing normative header: {field}")
    return match.group(1).strip()


def _top_level_heading_positions(lines: list[str]) -> list[tuple[int, int, str]]:
    """Extract the first sequential 0..262 headings, ignoring numbered sublists."""
    expected = 0
    positions: list[tuple[int, int, str]] = []
    for index, raw in enumerate(lines):
        match = re.match(r"^(\d+)\.\s+(.+?)\s*$", raw.strip())
        if not match:
            continue
        number = int(match.group(1))
        if number != expected:
            continue
        positions.append((index, number, match.group(2)))
        expected += 1
        if expected == EXPECTED_SECTIONS:
            break
    if len(positions) != EXPECTED_SECTIONS:
        found = [p[1] for p in positions]
        raise RulesetError(
            f"top-level section sequence is incomplete: expected 0..{EXPECTED_LAST_SECTION}, "
            f"found {len(found)} sections ending at {found[-1] if found else 'none'}"
        )
    return positions


def _compile_sections(text: str) -> tuple[RulesetSection, ...]:
    lines = text.splitlines()
    positions = _top_level_heading_positions(lines)
    sections: list[RulesetSection] = []
    for idx, (line_index, number, title) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(lines)
        body = "\n".join(lines[line_index:end]).strip() + "\n"
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        sections.append(RulesetSection(number=number, title=title, body=body, sha256=digest))
    return tuple(sections)


def load_ruleset(path: str | Path) -> Ruleset:
    source = Path(path)
    if not source.is_file():
        raise RulesetError(f"ruleset not found: {source}")
    raw = source.read_bytes()
    text = raw.decode("utf-8")
    ruleset = Ruleset(
        path=source,
        sha256=hashlib.sha256(raw).hexdigest(),
        status=_extract_header(text, "status"),
        version=_extract_header(text, "version"),
        effective_date=_extract_header(text, "date"),
        canonical_filename=_extract_header(text, "canonical"),
        sections=_compile_sections(text),
    )
    validate_normative_identity(ruleset)
    return ruleset


def validate_normative_identity(ruleset: Ruleset) -> None:
    mismatches: list[str] = []
    if ruleset.status != EXPECTED_STATUS:
        mismatches.append(f"status={ruleset.status!r}")
    if ruleset.version != EXPECTED_VERSION:
        mismatches.append(f"version={ruleset.version!r}")
    if ruleset.effective_date != EXPECTED_DATE:
        mismatches.append(f"effective_date={ruleset.effective_date!r}")
    if ruleset.canonical_filename != EXPECTED_CANONICAL:
        mismatches.append(f"canonical_filename={ruleset.canonical_filename!r}")
    if ruleset.path.name != EXPECTED_CANONICAL:
        mismatches.append(f"actual_filename={ruleset.path.name!r}")
    if ruleset.sha256 != EXPECTED_SHA256:
        mismatches.append(f"sha256={ruleset.sha256!r}")
    if len(ruleset.sections) != EXPECTED_SECTIONS:
        mismatches.append(f"section_count={len(ruleset.sections)}")
    if mismatches:
        raise RulesetError("RULESET NÃO DISPONÍVEL/CONFLITANTE: " + "; ".join(mismatches))


def parse_external_manifest(path: str | Path) -> tuple[str, str]:
    manifest = Path(path)
    if not manifest.is_file():
        raise RulesetError(f"external SHA-256 manifest not found: {manifest}")
    fields = manifest.read_text(encoding="ascii").strip().split()
    if len(fields) != 2:
        raise RulesetError("invalid ruleset SHA-256 manifest format")
    return fields[0], fields[1]


def verify_external_manifest(ruleset: Ruleset, manifest_path: str | Path) -> None:
    digest, filename = parse_external_manifest(manifest_path)
    if digest != ruleset.sha256 or filename != ruleset.canonical_filename:
        raise RulesetError("external ruleset SHA-256 manifest does not match canonical ruleset")


def discover_active_rulesets(directory: str | Path) -> list[Path]:
    root = Path(directory)
    active: list[Path] = []
    for candidate in sorted(root.glob("REGRAS_PROJETO_GENOMA*.txt")):
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", text, re.MULTILINE):
            active.append(candidate)
    return active


def enforce_unique_active_ruleset(directory: str | Path, expected_path: str | Path) -> None:
    active = discover_active_rulesets(directory)
    expected = Path(expected_path).resolve()
    if len(active) != 1 or active[0].resolve() != expected:
        names = [p.name for p in active]
        raise RulesetError(
            "RULESET NÃO DISPONÍVEL/CONFLITANTE: expected exactly one active ruleset "
            f"({expected.name}), found {names}"
        )


def compiled_catalog(ruleset: Ruleset) -> dict[str, object]:
    return {
        "ruleset": ruleset.metadata(),
        "rules": [
            {
                "rule_id": section.rule_id,
                "section": section.number,
                "title": section.title,
                "sha256": section.sha256,
                "text": section.body,
                "executor": "attestation_or_specialized_gate",
            }
            for section in ruleset.sections
        ],
    }
