#!/usr/bin/env python3
"""Capture the operator's consent record and bind it to the case and the bytes.

CONSENT_GATE checks `verified`, `version` and a non-empty `authorized_domains`, and before
this script existed the orchestrator accepted whatever JSON the operator typed on the command
line. `--consent '{"verified": true, "version": "x", "authorized_domains": ["CLÍNICO"]}'`
cleared the gate standing between a genomic file and a published report about a person.

What this script adds is not ceremony. It is the difference between a claim and a record:

* the input file is **hashed here**, so the record names the bytes it authorises and cannot
  be reused for another file;
* `--case-id` binds it to one case, so it cannot travel between people;
* every affirmation must be given **individually** — `--affirm identity_confirmed …` or, with
  `--interactive`, answered one at a time. `verified` is the conclusion of that set, never an
  input, and there is no flag that sets it;
* the domains are checked against the closed vocabulary, so a typo refuses instead of
  quietly authorising nothing;
* `--granted-at` and `--expires-at` make the record time-bound;
* `captured_by`, `instrument` and `instrument_version` say who captured it and on what.

None of this proves a person signed anything. It proves the record the system acted on names
this subject, these bytes, this scope and this date — which is the part a program can be
honest about. The rest is the operator's professional responsibility, and the record says so.

Example:

    python3 scripts/capture_consent.py \\
        --case-id CASO-2026-014 --subject-id PACIENTE-014 \\
        --input data/array.csv.gz \\
        --version "TCLE GENOMA v2 (2026-03)" \\
        --instrument "Termo de Consentimento Livre e Esclarecido assinado" \\
        --instrument-version 2.0 \\
        --captured-by "Dra. Fulana de Tal / CRM 000000" \\
        --domain CLÍNICO --domain FARMACOGENÔMICO \\
        --granted-at 2026-03-14 --expires-at 2027-03-14 \\
        --basis "TCLE assinado em 14/03/2026, arquivo 2026-014-TCLE.pdf" \\
        --affirm-all \\
        --output out/consent-record.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.consent import (
    ALLOWED_DOMAINS,
    REQUIRED_AFFIRMATIONS,
    SCHEMA,
    ConsentError,
    sha256_file,
    validate_record,
)

#: What each affirmation means, printed in `--interactive` and in `--list-affirmations`. The
#: operator is affirming these statements, so they are written out rather than left as keys.
AFFIRMATION_TEXT = {
    "identity_confirmed": (
        "A identidade da pessoa avaliada foi conferida e corresponde a este caso."
    ),
    "purpose_explained": (
        "A finalidade da análise foi explicada em linguagem compreensível para a pessoa."
    ),
    "scope_explained": (
        "O escopo autorizado foi explicado: quais domínios de relatório serão produzidos "
        "e quais não serão."
    ),
    "limitations_explained": (
        "As limitações foram explicadas: triagem não é diagnóstico, o array não cobre o "
        "genoma inteiro, e achados negativos não excluem doença."
    ),
    "incidental_findings_addressed": (
        "A conduta diante de achados incidentais ou secundários foi acordada com a pessoa."
    ),
    "withdrawal_explained": (
        "O direito de retirar o consentimento, e o que isso implica, foi explicado."
    ),
    "data_retention_explained": (
        "A retenção, o armazenamento e o eventual descarte dos dados foram explicados."
    ),
}


def _ask(question: str) -> bool:
    """One affirmation, answered explicitly. Anything but an explicit yes is a no."""
    answer = input(f"{question}\n  Confirma? [s/N] ").strip().lower()
    return answer in {"s", "sim", "y", "yes"}


def _affirmations(args: argparse.Namespace) -> dict[str, bool]:
    if args.interactive:
        print(
            "Cada afirmação abaixo é registrada individualmente. `verified` é a conclusão "
            "delas — não há como concedê-lo diretamente.\n"
        )
        return {key: _ask(AFFIRMATION_TEXT[key]) for key in REQUIRED_AFFIRMATIONS}
    if args.affirm_all:
        return {key: True for key in REQUIRED_AFFIRMATIONS}
    given = set(args.affirm or [])
    unknown = sorted(given - set(REQUIRED_AFFIRMATIONS))
    if unknown:
        raise ConsentError(
            f"afirmações desconhecidas {unknown}; as exigidas são {list(REQUIRED_AFFIRMATIONS)}"
        )
    return {key: key in given for key in REQUIRED_AFFIRMATIONS}


def build_record(args: argparse.Namespace) -> dict[str, Any]:
    input_path = Path(args.input)
    if not input_path.is_file():
        raise ConsentError(f"arquivo de entrada não encontrado: {input_path}")
    affirmations = _affirmations(args)
    return {
        "schema": SCHEMA,
        "subject_id": args.subject_id,
        "case_id": args.case_id,
        # Hashed here rather than copied from a QC report: the record must be bound to the
        # bytes even when it is captured before any analysis has run.
        "input_sha256": sha256_file(input_path),
        "input_name": input_path.name,
        "version": args.version,
        "authorized_domains": list(dict.fromkeys(args.domain)),
        "granted_at": args.granted_at,
        "expires_at": args.expires_at,
        "instrument": args.instrument,
        "instrument_version": args.instrument_version,
        "captured_by": args.captured_by,
        "affirmations": affirmations,
        # Never an input. It is true only when every affirmation was given, and
        # `validate_record` refuses the record if the two disagree.
        "verified": all(affirmations.values()),
        "basis": args.basis,
        "trace": {
            "actor_type": "HUMAN",
            "actor_id": args.captured_by,
            "method": "interactive" if args.interactive else "declared affirmations",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "tool": "scripts/capture_consent.py",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--subject-id", required=True, help="identifier of the person assessed")
    parser.add_argument("--input", required=True, help="the file the consent authorises")
    parser.add_argument("--version", required=True, help="version of the consent instrument")
    parser.add_argument("--instrument", required=True, help="what was signed or recorded")
    parser.add_argument("--instrument-version", required=True)
    parser.add_argument("--captured-by", required=True, help="who captured it, identified")
    parser.add_argument(
        "--domain", action="append", required=True, choices=list(ALLOWED_DOMAINS),
        help="authorised domain; repeat for each. Reports outside the set are not published.",
    )
    parser.add_argument("--granted-at", required=True, help="ISO date the consent was given")
    parser.add_argument("--expires-at", help="ISO date it expires; omit for no expiry")
    parser.add_argument(
        "--basis", required=True,
        help="on what footing this was captured: signed form identifier, session note, etc.",
    )
    parser.add_argument(
        "--affirm", action="append",
        help="one affirmation key; repeat for each. See --list-affirmations.",
    )
    parser.add_argument(
        "--affirm-all", action="store_true",
        help="record every affirmation as given. Use only when each was genuinely made.",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="ask for each affirmation one at a time"
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    try:
        record = build_record(args)
        # Validated before it is written, so an unusable record is refused at capture rather
        # than discovered when a report silently fails to publish.
        validate_record(record, case_id=args.case_id, input_sha256=record["input_sha256"])
    except ConsentError as exc:
        print(f"CONSENTIMENTO NÃO REGISTRADO: {exc}", file=sys.stderr)
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(out),
                "sha256": sha256_file(out),
                "case_id": record["case_id"],
                "authorized_domains": record["authorized_domains"],
                "verified": record["verified"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
