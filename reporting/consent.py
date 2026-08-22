"""The operator's consent record: what was authorised, for whom, over which bytes.

CONSENT_GATE checks three things — `verified` truthy, `version` non-empty,
`authorized_domains` non-empty — and the orchestrator handed it whatever JSON the operator
typed. So

    --consent '{"verified": true, "version": "x", "authorized_domains": ["CLÍNICO"]}'

cleared the gate. Three fields anyone can type are not a consent instrument, and the gate
they clear is the one standing between a genomic file and a published report about a person.

This module makes consent a record instead:

* bound to the **bytes** analysed, so a record captured for one file cannot authorise
  another — the same inheritance section 259 forbids for a PASS;
* bound to the **subject and case**, so a record cannot travel between people;
* **time-bound**, with an explicit grant date and an optional expiry, because a record with
  no date is not a record;
* scoped to a **closed vocabulary** of domains, checked per report — consent for
  ANCESTRALIDADE must not publish a clinical report, which nothing checked before;
* carrying the **affirmations** the operator actually made, so `verified` reflects a set of
  statements rather than a boolean someone wrote;
* hashed, so the manifest and the payload name the exact record that was evaluated.

None of this can prove a person signed a paper. It can prove that the record the system acted
on is the record on disk, that it names this subject and these bytes, that it has not expired,
and that the report about to be published falls inside what it authorises. That is the part a
program can be honest about.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "genoma-consent-record-v1"

#: The artifact name the record is registered under. Reserved, like the policy verdict and
#: the post-deployment witness: it may only arrive as a file.
CONSENT_ARTIFACT = "consent-record"

#: Every domain a report can require. Closed, because an open vocabulary means a typo in the
#: record silently authorises nothing while reading as though it authorised something.
ALLOWED_DOMAINS = (
    "CLÍNICO",
    "REPRODUTIVO",
    "FARMACOGENÔMICO",
    "ANCESTRALIDADE",
    "BEM-ESTAR",
    "TÉCNICO",
)

#: Which domain each report falls in, read from what the catalogue says the report asserts.
#: Kept here rather than passed in by the builder: a builder that declared its own domain
#: could declare the one it happened to have consent for.
#:
#: 03 is REPRODUTIVO rather than CLÍNICO because carrier screening reports on relatives as
#: well as on the subject. 07 is CLÍNICO rather than BEM-ESTAR because its purpose is
#: preventive risk for a clinical team, not wellness content. 08 is BEM-ESTAR because the
#: catalogue defines it as explicitly non-clinical. 05, 09 and 11 are TÉCNICO: methods, QC,
#: coverage and the editorial suite carry no clinical interpretation of the person.
REPORT_DOMAINS = {
    "01": "CLÍNICO",
    "02": "ANCESTRALIDADE",
    "03": "REPRODUTIVO",
    "04": "BEM-ESTAR",
    "05": "TÉCNICO",
    "06": "FARMACOGENÔMICO",
    "07": "CLÍNICO",
    "08": "BEM-ESTAR",
    "09": "TÉCNICO",
    "10": "CLÍNICO",
    "11": "TÉCNICO",
}

#: What the operator must affirm before `verified` may be true. Named individually because
#: `all(...)` over a truncated mapping is True, and this is the set that decides whether a
#: genomic report about a person may exist at all.
REQUIRED_AFFIRMATIONS = (
    "identity_confirmed",
    "purpose_explained",
    "scope_explained",
    "limitations_explained",
    "incidental_findings_addressed",
    "withdrawal_explained",
    "data_retention_explained",
)

#: Fields no record may omit. `basis` is included: a record that cannot say on what footing
#: it was captured is not auditable, and the field is where a paper reference, a signed form
#: identifier or a session note goes.
REQUIRED_FIELDS = (
    "schema",
    "subject_id",
    "case_id",
    "input_sha256",
    "version",
    "authorized_domains",
    "granted_at",
    "instrument",
    "instrument_version",
    "captured_by",
    "affirmations",
    "verified",
    "basis",
)


class ConsentError(Exception):
    """The record cannot authorise this run, and the reason says why."""


def _today() -> date:
    """Seam for tests; production always reads the clock."""
    return datetime.now(timezone.utc).date()


def _parse_date(value: Any, field: str) -> date:
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError) as exc:
        raise ConsentError(f"{field} não é uma data legível: {value!r}") from exc
    return parsed.date()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def domain_for(report_id: str) -> str:
    """The consent domain a report falls in, or a refusal for a report with no entry.

    Deliberately raises rather than defaulting: a report added without deciding what consent
    covers it would otherwise publish under whatever the operator happened to authorise.
    """
    try:
        return REPORT_DOMAINS[str(report_id)]
    except KeyError as exc:
        raise ConsentError(
            f"o relatório {report_id!r} não tem domínio de consentimento atribuído; "
            "nenhum relatório publica sob um escopo que ninguém decidiu"
        ) from exc


def validate_record(
    record: Any,
    *,
    case_id: str | None = None,
    input_sha256: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return the record if it may authorise this run, else raise with the reason.

    `case_id` and `input_sha256` are optional only so the record can be validated at capture
    time, before the case is analysed. Every consuming path passes both — a record validated
    against nothing is a record that authorises everything.
    """
    if not isinstance(record, dict):
        raise ConsentError("o registro de consentimento deve ser um objeto JSON")
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise ConsentError(f"campos ausentes no registro de consentimento: {sorted(missing)}")
    if record.get("schema") != SCHEMA:
        raise ConsentError(f"schema {record.get('schema')!r}; esperado {SCHEMA!r}")

    for field in ("subject_id", "version", "instrument", "instrument_version", "captured_by", "basis"):
        if not str(record.get(field) or "").strip():
            raise ConsentError(f"{field} está vazio")

    domains = record.get("authorized_domains")
    if not isinstance(domains, list) or not domains:
        raise ConsentError("authorized_domains deve listar ao menos um domínio")
    unknown = sorted({str(d) for d in domains} - set(ALLOWED_DOMAINS))
    if unknown:
        # Refused rather than ignored: an unrecognised domain silently authorises nothing
        # while reading, to a human, as though it authorised something.
        raise ConsentError(
            f"domínios desconhecidos {unknown}; o vocabulário fechado é {list(ALLOWED_DOMAINS)}"
        )

    affirmations = record.get("affirmations")
    if not isinstance(affirmations, dict):
        raise ConsentError("affirmations deve ser um objeto")
    unaffirmed = sorted(key for key in REQUIRED_AFFIRMATIONS if affirmations.get(key) is not True)
    if record.get("verified") is True and unaffirmed:
        # This is the whole point of the affirmations block: `verified` may not be a boolean
        # someone wrote, it must be the conclusion of a set of statements each made explicitly.
        raise ConsentError(
            f"verified=true sem as afirmações {unaffirmed}; o consentimento verificado é a "
            "conclusão das afirmações, não um campo independente delas"
        )
    if record.get("verified") is not True:
        raise ConsentError("verified não é true; este registro não autoriza execução alguma")

    granted = _parse_date(record.get("granted_at"), "granted_at")
    reference = today or _today()
    if granted > reference:
        raise ConsentError(f"granted_at está no futuro ({record.get('granted_at')!r})")
    expires = record.get("expires_at")
    if expires not in (None, ""):
        if _parse_date(expires, "expires_at") < reference:
            raise ConsentError(f"o consentimento expirou em {expires!r}")

    if case_id is not None and str(record.get("case_id")) != str(case_id):
        raise ConsentError(
            f"o registro autoriza o caso {record.get('case_id')!r}, e esta execução é "
            f"{case_id!r}; um consentimento não viaja entre casos"
        )
    if input_sha256 is not None and str(record.get("input_sha256")) != str(input_sha256):
        raise ConsentError(
            f"o registro está vinculado aos bytes {str(record.get('input_sha256'))[:16]}…, e "
            f"esta execução analisa {str(input_sha256)[:16]}…; um consentimento não viaja "
            "entre arquivos"
        )
    return record


def load_record(
    path: Path | str,
    *,
    case_id: str | None = None,
    input_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Read and validate a record, returning it with the SHA-256 of the bytes on disk."""
    raw = Path(path).read_bytes()
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsentError(f"registro de consentimento ilegível: {exc}") from exc
    validate_record(record, case_id=case_id, input_sha256=input_sha256)
    return record, hashlib.sha256(raw).hexdigest()


def scope_verdict(record: Any, report_id: str, *, sha256: str | None = None) -> dict[str, Any]:
    """Does this record authorise *this* report? PASS or a refusal that names the gap.

    Separate from `validate_record` because they answer different questions. A record can be
    perfectly valid and still not cover the report being compiled — consent for
    ANCESTRALIDADE is a real consent, and it does not authorise a clinical report. Nothing
    checked this before: `consent_verified` came from CONSENT_GATE, which the engine
    evaluates once for the whole run and which knows nothing about which of the eleven
    reports is being built.
    """
    domain = domain_for(report_id)
    if not isinstance(record, dict):
        return {
            "covers": False,
            "report_domain": domain,
            "basis": (
                "nenhum registro de consentimento foi fornecido; a publicação de qualquer "
                "relatório sobre uma pessoa exige um"
            ),
        }
    domains = [str(d) for d in (record.get("authorized_domains") or [])]
    covers = domain in domains
    return {
        "covers": covers,
        "report_domain": domain,
        "authorized_domains": domains,
        "record_sha256": sha256,
        "subject_id": record.get("subject_id"),
        "version": record.get("version"),
        "expires_at": record.get("expires_at"),
        "basis": (
            f"o domínio {domain!r} deste relatório consta do escopo autorizado {domains}"
            if covers
            else (
                f"o relatório é do domínio {domain!r} e o consentimento autoriza {domains}; "
                "um consentimento real para outro escopo não é consentimento para este"
            )
        ),
    }
