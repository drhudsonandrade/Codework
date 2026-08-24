"""The 263 section attestations RULE_COVERAGE_GATE requires, and the curation behind them.

The gate asks one question of every section of the vigente ruleset: does this rule apply to
the operation being performed, and if it does, how was it satisfied? A run that cannot answer
for all 263 does not publish. That is the correct design, and it is why the gate has been the
last one open — the answers are judgements about rule text, and there is no way to compute
them.

So they are curated, in `config/section_attestations_array.json`, one entry per section,
written against the section's text and **pinned to that text by SHA-256**. When the ruleset
changes, a curated judgement whose `rule_sha256` no longer matches is refused by the gate
rather than carried forward: a judgement made about different words is not a judgement about
these words.

What this module does *not* do is fabricate the missing ones. An external audit reached
`ready_for_requested_operation: true` by attesting all 263 rules NOT_APPLICABLE with one
boilerplate justification; the engine now refuses that shape outright, and the point survives
independently of the check. A section with no curated entry is reported as pending, by number
and title, and the gate refuses — which is the honest state of a partially curated ruleset.

The trace is bound at run time, never stored: `input_sha256` is the file actually analysed and
`output_sha256` the artifacts actually produced. A stored hash would certify a run that did
not happen.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import normative

SCHEMA = "genoma-section-attestations-v1"

ROOT = Path(__file__).resolve().parents[1]

#: The curation for the SNP-array curated-interpretation lane. Other operations (a WGS run,
#: for instance) need their own file: the same rule can apply to one and not to the other, and
#: reusing one lane's judgements for another is exactly the inheritance this gate exists to
#: prevent.
ARRAY_CURATION_PATH = ROOT / "config/section_attestations_array.json"

#: The curation for the projected-VCF lane. Fifteen sections answer differently there — the
#: source hierarchy puts a VCF at Nível 1, the mandatory WGS audit of §6 applies, variant
#: normalisation and the Master Variant Database stop being array concerns, and the meaning of
#: a locus's absence changes from "not on the chip" to "no record and no callability evidence".
VCF_CURATION_PATH = ROOT / "config/section_attestations_wgs_vcf.json"

#: Which genotype-table schemas each curation file was written against. A curation declares
#: this itself, in `applies_to_schemas`, and `curation_for_schema` refuses outside it.
#:
#: This is not hypothetical tidiness. When the VCF projection landed, the array lane's manifest
#: builder attached these 263 judgements to a WGS run without noticing: §3 said "o arquivo
#: analisado é o banco harmonizado, Nível 2 da hierarquia. Nenhum WGS foi enviado", §7 and §55
#: were attested NOT_APPLICABLE because "nenhum WGS existe nesta execução", and §8 —
#: normalisation of sequencing calls — was dismissed as inapplicable to an array export. Six
#: judgements were outright false about the run they were certifying, and RULE_COVERAGE_GATE
#: would have passed on them. Judgements made about one operation certifying another is the
#: inheritance this gate exists to prevent.
CURATIONS = (ARRAY_CURATION_PATH, VCF_CURATION_PATH)

ALLOWED_APPLICABILITY = ("APPLICABLE", "NOT_APPLICABLE", "UNRESOLVED")
ALLOWED_DECISIONS = ("SATISFIED", "BLOCKED", "NOT_APPLICABLE", "UNRESOLVED")
ALLOWED_STATUSES = ("EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL")

#: `validate_section_attestation` accepts SATISFIED only from these; kept here so the curation
#: is checked at authoring time rather than discovered at gate time.
SATISFYING_STATUSES = ("EXECUTADO", "VERIFICADO", "INFERIDO")


class CurationError(Exception):
    """The curation file cannot produce attestations, and the reason says why."""


def rule_id_for(number: int) -> str:
    """The canonical rule id, derived the way `RulesetSection.rule_id` derives it."""
    return f"GENOMA-{normative.VERSION.upper()}-S{number:03d}"


def curation_for_schema(schema: str | None) -> Path | None:
    """The curation written for this assay, or None when nobody has written one.

    None is the honest answer for an operation nobody has judged the ruleset against, and it
    makes RULE_COVERAGE_GATE report 263 rules not considered — which is true. Borrowing
    another lane's file would make the gate pass on judgements about a different run.
    """
    for candidate in CURATIONS:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(schema) in (payload.get("applies_to_schemas") or []):
            return candidate
    return None


def load_curation(path: Path | str | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else ARRAY_CURATION_PATH
    try:
        curation = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CurationError(f"curadoria ilegível em {source}: {exc}") from exc
    if not isinstance(curation, dict) or curation.get("schema") != SCHEMA:
        raise CurationError(f"curadoria em {source} não declara o schema {SCHEMA!r}")
    ruleset = curation.get("ruleset") if isinstance(curation.get("ruleset"), dict) else {}
    if ruleset.get("sha256") != normative.RAW_SHA256:
        # The whole file was written against one ruleset. If that is not the vigente one, every
        # judgement in it is about text this run is not governed by.
        raise CurationError(
            f"a curadoria foi escrita contra o ruleset {ruleset.get('sha256')!r} e o vigente é "
            f"{normative.RAW_SHA256!r}; recurar contra o texto em vigor"
        )
    if not isinstance(curation.get("sections"), dict):
        raise CurationError("a curadoria não traz um objeto 'sections'")
    if not curation.get("applies_to_schemas"):
        raise CurationError(
            f"a curadoria em {source} não declara `applies_to_schemas`; sem isso nada impede "
            "que os juízos de uma via sejam anexados a outra"
        )
    return curation


def validate_curation(curation: dict[str, Any]) -> list[str]:
    """Every problem with the curation itself, before any run consumes it.

    Checked here as well as at the gate because a curator needs the whole list at once, and
    because a malformed entry discovered at gate time reads as a failed analysis rather than
    as an authoring mistake.
    """
    problems: list[str] = []
    for key, entry in sorted(curation.get("sections", {}).items(), key=lambda kv: int(kv[0])):
        prefix = f"section {key}"
        if not isinstance(entry, dict):
            problems.append(f"{prefix}: entry is not an object")
            continue
        applicability = entry.get("applicability")
        decision = entry.get("decision")
        status = entry.get("status")
        if applicability not in ALLOWED_APPLICABILITY:
            problems.append(f"{prefix}: applicability {applicability!r} invalid")
        if decision not in ALLOWED_DECISIONS:
            problems.append(f"{prefix}: decision {decision!r} invalid")
        if status not in ALLOWED_STATUSES:
            problems.append(f"{prefix}: status {status!r} invalid")
        if not str(entry.get("justification") or "").strip():
            problems.append(f"{prefix}: justification is required")
        if not isinstance(entry.get("rule_sha256"), str) or len(entry["rule_sha256"]) != 64:
            problems.append(f"{prefix}: rule_sha256 must be the section's SHA-256")
        refs = entry.get("evidence_refs")
        if not isinstance(refs, list) or any(not isinstance(r, str) or not r for r in refs):
            problems.append(f"{prefix}: evidence_refs must be a list of ids")
            refs = []
        if applicability == "NOT_APPLICABLE" and decision != "NOT_APPLICABLE":
            problems.append(f"{prefix}: NOT_APPLICABLE applicability needs NOT_APPLICABLE decision")
        if applicability == "APPLICABLE" and decision == "NOT_APPLICABLE":
            problems.append(f"{prefix}: APPLICABLE rule cannot decide NOT_APPLICABLE")
        if decision == "SATISFIED":
            if status not in SATISFYING_STATUSES:
                problems.append(f"{prefix}: status {status!r} cannot claim SATISFIED")
            if not refs:
                problems.append(f"{prefix}: SATISFIED needs explicit evidence_refs")
    # The set-level check the engine makes, made here too so a curator sees it while curating.
    not_applicable = [
        e for e in curation.get("sections", {}).values()
        if isinstance(e, dict) and e.get("applicability") == "NOT_APPLICABLE"
    ]
    justifications = {str(e.get("justification") or "").strip() for e in not_applicable}
    if len(not_applicable) > 1 and len(justifications) == 1:
        problems.append(
            "every NOT_APPLICABLE entry shares one justification; one text cannot be the "
            "reason each distinct rule does not apply"
        )
    return problems


def pending(curation: dict[str, Any], *, total: int = normative.SECTION_COUNT) -> list[int]:
    """Sections with no curated judgement, by number. The honest gap, not a default."""
    curated = {int(key) for key in curation.get("sections", {})}
    return [number for number in range(total) if number not in curated]


def build_attestations(
    curation: dict[str, Any],
    *,
    artifact_sha256: dict[str, str],
    input_sha256: str,
    run_id: str,
    created_at: str | None = None,
) -> list[dict[str, Any]]:
    """Bind each curated judgement to this run's real artifacts.

    `artifact_sha256` maps the evidence ids the curation cites to the digests this run
    produced. A cited id with no digest is refused rather than dropped: an attestation whose
    evidence does not exist in the run is the shape of the defect this gate is for.
    """
    stamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    attestations: list[dict[str, Any]] = []
    for key, entry in sorted(curation.get("sections", {}).items(), key=lambda kv: int(kv[0])):
        number = int(key)
        refs = list(entry.get("evidence_refs") or [])
        unknown = sorted(ref for ref in refs if ref not in artifact_sha256)
        if unknown:
            raise CurationError(
                f"section {number} cites evidence {unknown} that this run does not produce; "
                "an attestation may not reference evidence that does not exist"
            )
        outputs = [artifact_sha256[ref] for ref in refs]
        trace: dict[str, Any] = {
            "attestation_id": f"{rule_id_for(number)}-{run_id}",
            "actor_type": entry.get("actor_type", "HUMAN"),
            "actor_id": curation.get("curated_by") or "curadoria do projeto",
            "method": entry.get("method")
            or "leitura da seção do ruleset vigente e comparação com o que esta execução faz",
            "run_id": run_id,
            "created_at": stamp,
            "tool_versions": {
                "reporting.section_attestations": "v1",
                "ruleset": normative.VERSION,
            },
            # Bound to the run, never stored: a curated hash would certify an execution that
            # did not happen. Only SATISFIED applicable rules are required to carry them, and
            # only they get them — an empty list on a NOT_APPLICABLE rule is the honest shape.
            "input_sha256": [input_sha256] if outputs else [],
            "output_sha256": outputs,
        }
        attestations.append(
            {
                "section": number,
                "rule_id": rule_id_for(number),
                "rule_sha256": entry["rule_sha256"],
                "applicability": entry["applicability"],
                "status": entry["status"],
                "decision": entry["decision"],
                "justification": entry["justification"],
                "evidence_refs": refs,
                "trace": trace,
            }
        )
    return attestations


def coverage_report(curation: dict[str, Any]) -> dict[str, Any]:
    """What the curation covers and what it does not, for a human to read."""
    sections = curation.get("sections", {})
    by_applicability: dict[str, int] = {}
    for entry in sections.values():
        if isinstance(entry, dict):
            key = str(entry.get("applicability"))
            by_applicability[key] = by_applicability.get(key, 0) + 1
    missing = pending(curation)
    return {
        "total_rules": normative.SECTION_COUNT,
        "curated": len(sections),
        "pending": len(missing),
        "pending_sections": missing[:20],
        "by_applicability": by_applicability,
        "problems": validate_curation(curation),
        "status": "COMPLETA" if not missing and not validate_curation(curation) else "PENDENTE",
    }
