#!/usr/bin/env python3
"""Decide whether the raw DNA of this submission may be read at all.

This is the gate that stands between a person's FASTQ/BAM/CRAM and the first byte of analysis,
and it used to be satisfiable by six typed strings:

    {"sample_id": "x",
     "consent":    {"status": "VERIFICADO", "consent_id": "a", "version": "1",
                    "purposes": ["genomic_analysis"]},
     "provenance": {"status": "VERIFICADO", "source": "a", "chain_of_custody_ref": "b"}}

`status: "VERIFICADO"` was read from the manifest the caller wrote — the self-declared field
feeding the gate that reads it, again — and nothing tied any of it to the bytes about to be
read. A consent captured for one sample cleared the gate for another, and a manifest with no
consent behind it at all cleared it too, reporting `ready_for_first_dna_read: true`.

So the consent now arrives the way it does everywhere else in this project: as a record
`reporting.consent` validates — seven explicit affirmations, a closed domain vocabulary, an
expiry, a named instrument and a named person who captured it — bound to the SHA-256 of the
files themselves. The files are hashed here, by this gate, from the paths it was given; the
digest is not copied from the manifest, because a digest a caller supplies is another typed
string.

An embedded `consent` block is refused outright rather than ignored, on the same reasoning
that makes `PayloadCompiler.register` refuse a composed policy verdict: leaving the old door
open means the old shape keeps working.

Chain of custody stays where it was — it is a fact about the physical sample that no file can
establish — but it can no longer grant the gate by itself. It is recorded as the operator's
declaration, and the verdict comes from the consent record.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.consent import (
    ALLOWED_DOMAINS,
    ConsentError,
    input_set_sha256,
    load_record,
)

SCHEMA = "genoma-consent-provenance-gate-v2"


class ConsentGateError(Exception):
    """The gate cannot be evaluated, and the message says what is missing."""


def evaluate_consent(
    manifest: dict[str, Any],
    *,
    requested_domain: str,
    consent_path: Path,
    input_paths: list[Path],
) -> dict[str, Any]:
    """Grant or refuse the first read of this submission's raw DNA.

    `input_paths` are hashed here. The manifest supplies identity and chain of custody, and
    nothing else: it can no longer supply the consent.
    """
    if requested_domain not in ALLOWED_DOMAINS:
        raise ConsentGateError(
            f"domínio {requested_domain!r} fora do vocabulário fechado {list(ALLOWED_DOMAINS)}"
        )
    if "consent" in manifest:
        raise ConsentGateError(
            "o manifesto traz um bloco `consent`: o consentimento é lido do registro do "
            "operador, via --consent <arquivo>, e nunca de campos que quem escreve o "
            "manifesto digita. Um bloco embutido é uma afirmação de que alguém consentiu, "
            "feita pelo próprio código que quer prosseguir."
        )

    errors: list[str] = []
    sample_id = str(manifest.get("sample_id") or "").strip()
    if not sample_id:
        errors.append("sample_id ausente no manifesto")

    missing = [str(path) for path in input_paths if not Path(path).is_file()]
    if missing:
        raise ConsentGateError(f"arquivos de entrada não encontrados: {missing}")
    composite, inputs = input_set_sha256(input_paths)

    record: dict[str, Any] | None = None
    consent_sha: str | None = None
    try:
        # Bound to this case and to these exact bytes. A record for another sample, an
        # expired one, or one whose affirmations are incomplete raises here.
        record, consent_sha = load_record(
            consent_path, case_id=sample_id or None, input_sha256=composite
        )
    except ConsentError as exc:
        errors.append(f"consentimento: {exc}")

    authorized = list(record.get("authorized_domains") or []) if record else []
    if record is not None and requested_domain not in authorized:
        errors.append(
            f"o domínio pedido {requested_domain!r} não está autorizado; o registro autoriza "
            f"{authorized}"
        )

    # Chain of custody is about the physical sample and stays an operator declaration. It is
    # required and recorded, and it is not what grants the gate.
    provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
    for field in ("source", "chain_of_custody_ref"):
        if not str(provenance.get(field) or "").strip():
            errors.append(f"provenance.{field} ausente")

    return {
        "schema": SCHEMA,
        "gate": "CONSENT_PROVENANCE_GATE",
        "status": "VERIFICADO" if not errors else "NÃO DISPONÍVEL",
        "sample_id": sample_id or None,
        "requested_domain": requested_domain,
        "ready_for_first_dna_read": not errors,
        "inputs": inputs,
        # The digest the consent had to name. Computed here from the files, so the binding is
        # measured rather than asserted.
        "input_set_sha256": composite,
        "consent_record_sha256": consent_sha,
        "consent_version": record.get("version") if record else None,
        "consent_subject": record.get("subject_id") if record else None,
        "authorized_domains": authorized,
        "secondary_findings": (
            (record.get("affirmations") or {}).get("secondary_findings_choice_recorded")
            if record else None
        ),
        "chain_of_custody": {
            "status": "DECLARADO PELO OPERADOR",
            "source": provenance.get("source"),
            "chain_of_custody_ref": provenance.get("chain_of_custody_ref"),
            "note": (
                "cadeia de custódia é fato sobre a amostra física; nenhum arquivo a "
                "estabelece, e ela não concede este gate por si só"
            ),
        },
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--manifest", required=True, help="identidade da amostra e cadeia de custódia")
    parser.add_argument(
        "--consent", required=True,
        help="registro de consentimento produzido por scripts/capture_consent.py",
    )
    parser.add_argument(
        "--input", required=True, action="append",
        help="um arquivo bruto a ser lido; repita para FASTQ R1/R2 ou BAM+BAI. Estes "
             "arquivos são hasheados aqui e o consentimento tem de nomear esse conjunto.",
    )
    parser.add_argument(
        "--domain", default="TÉCNICO", choices=list(ALLOWED_DOMAINS),
        help="o domínio de consentimento sob o qual esta leitura ocorre",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    try:
        result = evaluate_consent(
            manifest,
            requested_domain=args.domain,
            consent_path=Path(args.consent),
            input_paths=[Path(item) for item in args.input],
        )
    except (ConsentGateError, ConsentError) as exc:
        print(f"CONSENT_PROVENANCE_GATE NÃO DISPONÍVEL: {exc}", file=sys.stderr)
        return 2

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ready_for_first_dna_read"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
