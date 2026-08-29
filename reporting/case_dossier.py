"""Load the case identification, consent and custody data the templates ask for.

Roughly 60% of every v3.0 template is administrative: who the person is, who requested the
analysis, when the sample was taken, under which consent, signed by whom. None of it is
derivable from a genotype file and none of it can be fetched from a public source — it is
the operator's own record.

So this module supplies the *intake*, not the content. It validates a dossier the operator
writes, and it is deliberately strict in one direction only: a field that is absent stays
absent, and the report prints NÃO DISPONÍVEL. Nothing here invents a plausible value, and
nothing marks a dossier complete because it parsed.

Two rules the validation does enforce, because both are ways a dossier can be worse than
empty:

* **A consent block must be complete or absent.** A half-filled consent — a purpose with no
  identifier, an identifier with no date — reads on the page as though consent were
  documented. Partial consent is rejected rather than printed.
* **The dossier must name the case it belongs to**, and the caller must match it against the
  case the pipeline analysed, so an identity block cannot be attached to someone else's data.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCHEMA = "genoma-case-dossier-v1"
UNAVAILABLE = "NÃO DISPONÍVEL"

#: Every field the dossier may carry, grouped as the templates group them. A field not
#: listed here is rejected: a typo that silently did nothing would be indistinguishable
#: from a field the operator forgot.
SECTIONS: dict[str, tuple[str, ...]] = {
    "identification": (
        "pseudonymised_id",
        "date_of_birth",
        "sex_recorded_at_birth",
        "requesting_professional",
        "requesting_service",
    ),
    "sample": (
        "sample_type",
        "sample_identifier",
        "collection_date",
        "laboratory",
        "platform",
        "chain_of_custody_reference",
    ),
    "consent": (
        "consent_id",
        "consent_version",
        "consent_date",
        "authorised_purposes",
        "authorised_reports",
        "secondary_findings",
        "granular_preferences",
        "delivery_preference",
        "authorised_recipients",
        "retention_policy",
    ),
    "release": (
        "responsible_professional",
        "responsible_registration",
        "signature_reference",
        "issue_date",
    ),
}

#: A consent block is all-or-nothing: these must appear together or not at all.
CONSENT_REQUIRED_TOGETHER = ("consent_id", "consent_version", "consent_date", "authorised_purposes")

#: Fields parsed as calendar dates, so a malformed one is caught at intake rather than
#: printed as-is on a clinical document.
DATE_FIELDS = frozenset({"date_of_birth", "collection_date", "consent_date", "issue_date"})

#: Sex recorded at birth, as a controlled vocabulary rather than free text.
#:
#: This field is not administrative decoration: it is what separates a hemizygous male, who
#: is affected by an X-linked pathogenic variant, from a heterozygous female, who is usually
#: a carrier. A typo would silently fall through to "unknown" and the X-linked interpretation
#: would be refused for a reason the operator never sees, so an unrecognised value is
#: rejected at intake instead.
#:
#: It is recorded sex at birth, which is what the genotype interpretation needs; it is not a
#: statement about the person's gender, and it is not inferred from the genotype — this
#: system never calls sex chromosomes.
SEX_FEMALE = "feminino"
SEX_MALE = "masculino"
SEX_INTERSEX = "intersexo"
SEX_NOT_RECORDED = "não registrado"

SEX_VOCABULARY: dict[str, str] = {
    "f": SEX_FEMALE,
    "feminino": SEX_FEMALE,
    "female": SEX_FEMALE,
    "m": SEX_MALE,
    "masculino": SEX_MALE,
    "male": SEX_MALE,
    "i": SEX_INTERSEX,
    "intersexo": SEX_INTERSEX,
    "intersex": SEX_INTERSEX,
    "nao registrado": SEX_NOT_RECORDED,
    "não registrado": SEX_NOT_RECORDED,
    "not recorded": SEX_NOT_RECORDED,
}


def normalised_sex(value: Any) -> str | None:
    """Map an operator-written sex onto the controlled vocabulary, or None if absent."""
    text = str(value or "").strip().lower()
    if not text:
        return None
    return SEX_VOCABULARY.get(text)


class CaseDossierError(ValueError):
    """The dossier is malformed. An absent dossier is not an error."""


def _parse_date(section: str, field: str, value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    raise CaseDossierError(
        f"{section}.{field}: {text!r} is not a date in YYYY-MM-DD or DD/MM/YYYY"
    )


def load_dossier(path: Path, *, expected_case_id: str | None = None) -> dict[str, Any]:
    """Validate an operator-written dossier and normalise its dates."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    # A dossier whose root is a list, a string, a number or null reached `.get` and died with
    # AttributeError, which is not this module's error type: callers catching CaseDossierError
    # to fail closed saw an unhandled traceback instead.
    if not isinstance(payload, dict):
        raise CaseDossierError(
            f"dossier root must be a JSON object, got {type(payload).__name__}"
        )
    if payload.get("schema") != SCHEMA:
        raise CaseDossierError(f"unsupported dossier schema: {payload.get('schema')!r}")

    case_id = str(payload.get("case_id") or "").strip()
    if not case_id:
        raise CaseDossierError("the dossier must name the case it belongs to")
    if expected_case_id is not None and case_id != expected_case_id:
        # An identity block attached to another person's data is the worst failure this
        # file can cause, so the binding is checked rather than assumed.
        raise CaseDossierError(
            f"dossier case_id {case_id!r} does not match the analysed case {expected_case_id!r}"
        )

    unknown_sections = sorted(set(payload) - set(SECTIONS) - {"schema", "case_id", "notes"})
    if unknown_sections:
        raise CaseDossierError(f"unknown dossier sections: {unknown_sections}")

    cleaned: dict[str, dict[str, Any]] = {}
    for section, allowed in SECTIONS.items():
        block = payload.get(section) or {}
        if not isinstance(block, dict):
            raise CaseDossierError(f"{section} must be an object")
        unknown = sorted(set(block) - set(allowed))
        if unknown:
            raise CaseDossierError(f"{section}: unknown fields {unknown}")
        out: dict[str, Any] = {}
        for field, value in block.items():
            if value in (None, "", [], {}):
                continue
            if field in DATE_FIELDS:
                out[field] = _parse_date(section, field, value)
            elif field == "sex_recorded_at_birth":
                normalised = normalised_sex(value)
                if normalised is None:
                    raise CaseDossierError(
                        f"{section}.{field}: {str(value)!r} is not one of "
                        f"{sorted(set(SEX_VOCABULARY.values()))}. This field decides whether "
                        "a hemizygous male is read as affected or a heterozygous female as a "
                        "carrier, so an unrecognised value is refused rather than silently "
                        "treated as unknown."
                    )
                out[field] = normalised
            else:
                out[field] = value
        cleaned[section] = out

    consent = cleaned.get("consent", {})
    present = [f for f in CONSENT_REQUIRED_TOGETHER if f in consent]
    if present and len(present) != len(CONSENT_REQUIRED_TOGETHER):
        missing = sorted(set(CONSENT_REQUIRED_TOGETHER) - set(present))
        raise CaseDossierError(
            "a partial consent block reads as documented consent on the page; "
            f"supply all of {list(CONSENT_REQUIRED_TOGETHER)} or none — missing {missing}"
        )

    supplied = sum(len(block) for block in cleaned.values())
    total = sum(len(fields) for fields in SECTIONS.values())
    return {
        "schema": SCHEMA,
        "case_id": case_id,
        # Documented means the consent instrument is *identified* — id, version, date and
        # purposes. A block carrying only downstream preferences (which reports, which
        # recipients, how long to retain) is a delivery policy, not a consent record, and
        # reading it as one would print "consentimento documentado" over a case where no
        # consent instrument was ever named.
        "consent_documented": all(field in consent for field in CONSENT_REQUIRED_TOGETHER),
        "consent_preferences_only": bool(consent)
        and not all(field in consent for field in CONSENT_REQUIRED_TOGETHER),
        "fields_supplied": supplied,
        "fields_possible": total,
        # Reported so a reader can see how much of the administrative record exists, rather
        # than inferring completeness from a document that renders without error.
        "fields_absent": sorted(
            f"{section}.{field}"
            for section, fields in SECTIONS.items()
            for field in fields
            if field not in cleaned.get(section, {})
        ),
        **cleaned,
    }


#: Every template token a dossier is capable of answering. Closed and derived from this
#: module, never from a payload: the PDF stamp check exempts dossier-supplied fields from
#: re-derivation, and a payload that could nominate its own exempt tokens would exempt
#: exactly the ones it forged. Kept in sync with `dossier_values` by a test.
DOSSIER_TOKENS = frozenset({
    "NOME_OU_ID_PSEUDONIMIZADO",
    "DATA_NASCIMENTO_OU_NAO_INFORMADA",
    "SEXO_REGISTRADO_AO_NASCER",
    "PROFISSIONAL_OU_SERVICO_SOLICITANTE",
    "TIPO_AMOSTRA_E_IDENTIFICADOR",
    "LABORATORIO_E_PLATAFORMA",
    "DATA_COLETA",
    "ID_VERSAO_DATA_CONSENTIMENTO",
    "FINALIDADE_E_RELATORIOS_AUTORIZADOS",
    "PREFERENCIA_GRANULAR",
    "PREFERENCIA_CANAL_PRAZO",
    "PESSOAS_SERVICOS_AUTORIZADOS",
    "POLITICA_E_PRAZO",
    "RESPONSAVEL",
    "ASSINATURAS",
    "DATA_EMISSAO",
    "NOME_OU_ID_E_DATA_NASCIMENTO",
})


def dossier_values(dossier: dict[str, Any] | None) -> dict[str, Any]:
    """Flatten a dossier into the template tokens it answers.

    Returns only what the dossier actually carries; every other token is left for
    `template_fill` to mark NÃO DISPONÍVEL.
    """
    if not dossier:
        return {}
    identification = dossier.get("identification", {})
    sample = dossier.get("sample", {})
    consent = dossier.get("consent", {})
    release = dossier.get("release", {})

    def joined(value: Any) -> Any:
        return ", ".join(str(v) for v in value) if isinstance(value, list) else value

    values: dict[str, Any] = {
        "NOME_OU_ID_PSEUDONIMIZADO": identification.get("pseudonymised_id"),
        "DATA_NASCIMENTO_OU_NAO_INFORMADA": identification.get("date_of_birth"),
        # Surfaced on the page as well as consumed by the interpretation. A field the
        # operator was asked to supply and that then appears nowhere reads as a field that
        # did not matter, and this one changes what an X-linked variant means.
        "SEXO_REGISTRADO_AO_NASCER": identification.get("sex_recorded_at_birth"),
        "PROFISSIONAL_OU_SERVICO_SOLICITANTE": " / ".join(
            str(v)
            for v in (
                identification.get("requesting_professional"),
                identification.get("requesting_service"),
            )
            if v
        )
        or None,
        "TIPO_AMOSTRA_E_IDENTIFICADOR": " / ".join(
            str(v) for v in (sample.get("sample_type"), sample.get("sample_identifier")) if v
        )
        or None,
        "LABORATORIO_E_PLATAFORMA": " / ".join(
            str(v) for v in (sample.get("laboratory"), sample.get("platform")) if v
        )
        or None,
        "DATA_COLETA": sample.get("collection_date"),
        "ID_VERSAO_DATA_CONSENTIMENTO": " / ".join(
            str(v)
            for v in (
                consent.get("consent_id"),
                consent.get("consent_version"),
                consent.get("consent_date"),
            )
            if v
        )
        or None,
        "FINALIDADE_E_RELATORIOS_AUTORIZADOS": " | ".join(
            str(v)
            for v in (joined(consent.get("authorised_purposes")), joined(consent.get("authorised_reports")))
            if v
        )
        or None,
        "PREFERENCIA_GRANULAR": joined(consent.get("granular_preferences")),
        "PREFERENCIA_CANAL_PRAZO": consent.get("delivery_preference"),
        "PESSOAS_SERVICOS_AUTORIZADOS": joined(consent.get("authorised_recipients")),
        "POLITICA_E_PRAZO": consent.get("retention_policy"),
        "RESPONSAVEL": " / ".join(
            str(v)
            for v in (
                release.get("responsible_professional"),
                release.get("responsible_registration"),
            )
            if v
        )
        or None,
        "ASSINATURAS": release.get("signature_reference"),
        "DATA_EMISSAO": release.get("issue_date"),
        "NOME_OU_ID_E_DATA_NASCIMENTO": " / ".join(
            str(v)
            for v in (identification.get("pseudonymised_id"), identification.get("date_of_birth"))
            if v
        )
        or None,
    }
    return {k: v for k, v in values.items() if v not in (None, "", [], {})}
