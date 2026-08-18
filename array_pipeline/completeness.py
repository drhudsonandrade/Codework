"""Genome Completeness & Blind Spots — the classification behind report 09 (GCM).

The catalogue has declared report 09 since v3.0 and the approved template is sealed in the
store, but nothing computed its content. That gap matters more than a missing document:
report 09 is the one that keeps a *silent* result from reading as a *negative* one. Without
it, "rs6025 não aparece no relatório" is indistinguishable from "rs6025 foi testado e está
ausente", which is the single most consequential false negative an array can produce.

Every target in the registry lands in exactly one class:

``OBSERVADO``      assayed, called, and usable for interpretation.
``NO-CALL``        the chip carries the locus but this sample has no valid genotype.
``NÃO TESTADO``    the locus is not on this array at all. Nothing can be said about it.
``NÃO REPORTÁVEL`` observed, but excluded from interpretation — an unresolved
                   cross-platform conflict, or orientation that was never verified, so the
                   reported allele could be the complement of the true one.
``NÃO DETECTADO``  assayed, called, and the assessed allele is absent — the only class that
                   licenses a negative statement, and only for that locus.

`NÃO DETECTADO` requires the registry to declare which allele was being looked for. Where
`assessed_allele` is absent the locus stays `OBSERVADO` and the matrix says why: reading a
genotype without knowing the risk allele cannot establish absence, and guessing one would be
an invented clinical assertion of exactly the kind section 6 forbids.

Beyond the per-locus classes there are whole variant classes an array cannot see at any
locus — CNV, SV, repeat expansions, HLA, CYP2D6 structural alleles, mosaicism, deep intronic
variation. Those are reported separately as structural blind spots, because they are not
gaps in this sample but limits of the platform.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import normative
from array_pipeline.annotation import UNSUPPORTED_ARRAY_CLAIMS, _orientation
from array_pipeline.qc import (
    HARMONIZED_COLUMNS,
    RAW_COLUMNS,
    UNRESOLVED_OVERLAP_STATUSES,
    _canonical_gt,
    _is_valid_consensus,
    _read_header_and_metadata,
    _text_stream,
    sha256_file,
)
from array_pipeline.targets import load_target_manifest, sha256_json

SCHEMA = "genoma-genome-completeness-matrix-v1"
RULESET = normative.ruleset_block()

OBSERVADO = "OBSERVADO"
NO_CALL = "NO-CALL"
NAO_TESTADO = "NÃO TESTADO"
NAO_REPORTAVEL = "NÃO REPORTÁVEL"
NAO_DETECTADO = "NÃO DETECTADO"

CLASSES = (OBSERVADO, NAO_DETECTADO, NO_CALL, NAO_TESTADO, NAO_REPORTAVEL)

#: Classes that may support a statement about this person's genotype at that locus.
INTERPRETABLE = frozenset({OBSERVADO, NAO_DETECTADO})


def _row_reader(path: Path):
    fh, _ = _text_stream(path)
    try:
        header, _metadata = _read_header_and_metadata(fh)
        if header == HARMONIZED_COLUMNS:
            schema = "harmonized_genera_myheritage_v1"
        elif header == RAW_COLUMNS:
            schema = "raw_snp_array_v1"
        else:
            raise ValueError(f"unsupported SNP-array CSV header: {header}")
        import csv

        for row in csv.DictReader(fh, fieldnames=header):
            yield schema, row
    finally:
        fh.close()


def _classify(
    row: dict[str, str] | None,
    schema: str | None,
    target: dict[str, Any],
) -> tuple[str, str]:
    """Return (class, basis) for one target locus."""
    if row is None:
        return NAO_TESTADO, "locus não presente no arquivo do array; nada foi interrogado"

    if schema and schema.startswith("harmonized"):
        raw_gt = row.get("CONSENSUS_RESULT")
        status = (row.get("STATUS") or "").strip().lower()
    else:
        raw_gt = row.get("RESULT")
        status = "observed"

    duplicate = row.get("__duplicate_conflict")
    if duplicate:
        return (
            NAO_REPORTAVEL,
            f"o arquivo traz linhas duplicadas com genótipos divergentes para este rsid ({duplicate}); "
            "escolher uma delas seria arbitrar um conflito",
        )

    if status in UNRESOLVED_OVERLAP_STATUSES:
        return (
            NAO_REPORTAVEL,
            f"registro cross-platform não resolvido ({status}); conflitos nunca são resolvidos por arbitragem",
        )

    if not _is_valid_consensus(raw_gt):
        return NO_CALL, "locus ensaiado, mas sem genótipo válido nesta amostra"

    orientation = (row.get("__orientation_status") or "").strip()
    if orientation not in {"VERIFICADO", "INFERIDO"}:
        return (
            NAO_REPORTAVEL,
            f"orientação de fita não estabelecida ({orientation or 'ausente'}); "
            "o alelo relatado pode ser o complementar",
        )

    genotype = _canonical_gt(raw_gt) or ""
    assessed = str(target.get("assessed_allele") or "").strip().upper()
    if not assessed:
        return (
            OBSERVADO,
            "genótipo chamado; ausência não pode ser afirmada porque o registro não declara o alelo avaliado",
        )
    if assessed in set(genotype):
        return OBSERVADO, f"genótipo chamado contém o alelo avaliado {assessed}"
    return (
        NAO_DETECTADO,
        f"genótipo chamado {genotype} não contém o alelo avaliado {assessed}; ausência vale apenas para este locus",
    )


def build_completeness_matrix(
    input_path: Path,
    qc_path: Path,
    target_manifest_path: Path,
    *,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Classify every registry target against what this array actually interrogated."""
    qc = json.loads(Path(qc_path).read_text(encoding="utf-8"))
    if qc.get("input", {}).get("sha256") != sha256_file(input_path):
        raise ValueError("input SHA-256 does not match QC evidence")

    gate = qc.get("gates", {}).get("LIMITED_INTERPRETATION_GATE", {})
    qc_passed = gate.get("state") == "PASS" and qc.get("operational_status") == "VERIFICADO"

    manifest = load_target_manifest(target_manifest_path)
    targets = {str(t["rsid"]).lower(): t for t in manifest["targets"]}

    # Every row for a target is collected, not just the first. `qc.inspect_array` allows a
    # raw vendor export to carry duplicate RSID rows, so keeping only the first silently
    # picked a winner whenever two rows disagreed — resolving a conflict by arbitration,
    # which sections 4 and 7 forbid.
    collected: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for schema, row in _row_reader(Path(input_path)):
        rsid = (row.get("RSID") or "").strip().lower()
        if rsid not in targets:
            continue
        enriched = dict(row)
        # Orientation is derived per row for every target, not read back from the QC
        # baseline-marker list. That list covers only the 14 baseline rsids, so keying
        # off it silently exempted every other target from the strand check and let an
        # unoriented locus be classified OBSERVADO.
        status, basis = _orientation(row, schema, qc)
        enriched["__orientation_status"] = status
        enriched["__orientation_basis"] = basis
        collected.setdefault(rsid, []).append((schema, enriched))

    seen: dict[str, tuple[str, dict[str, str]]] = {}
    for rsid, rows in collected.items():
        schema, first = rows[0]
        if len(rows) > 1:
            genotypes = {
                _canonical_gt(r.get("CONSENSUS_RESULT") or r.get("RESULT")) for _s, r in rows
            }
            if len(genotypes) > 1:
                marked = dict(first)
                marked["__duplicate_conflict"] = ", ".join(
                    sorted(str(g) for g in genotypes if g is not None)
                ) or "sem genótipo válido"
                seen[rsid] = (schema, marked)
                continue
        seen[rsid] = (schema, first)

    entries: list[dict[str, Any]] = []
    for rsid in sorted(targets):
        target = targets[rsid]
        schema, row = seen.get(rsid, (None, None))
        classification, basis = _classify(row, schema, target)
        entries.append(
            {
                "rsid": rsid,
                "gene": target.get("gene"),
                "scope": target.get("scope"),
                "label": target.get("label"),
                "classification": classification,
                "basis": basis,
                "interpretable": classification in INTERPRETABLE,
                # The genotype is withheld unless the locus is interpretable. A conflicting
                # or unoriented record still *has* a called value, and carrying it in the
                # entry meant every consumer that printed `genotype or classification`
                # displayed it as though it were usable — which is precisely the arbitration
                # the NÃO REPORTÁVEL class exists to refuse.
                "genotype": (
                    _canonical_gt((row or {}).get("CONSENSUS_RESULT") or (row or {}).get("RESULT"))
                    if row is not None and classification in INTERPRETABLE
                    else None
                ),
                "genotype_withheld": row is not None and classification not in INTERPRETABLE,
                "assessed_allele": target.get("assessed_allele"),
            }
        )

    counts = {name: sum(1 for e in entries if e["classification"] == name) for name in CLASSES}
    interpretable = sum(1 for e in entries if e["interpretable"])
    total = len(entries)

    now = evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        # The matrix describes coverage, which is a measurement. It is only VERIFICADO when
        # the QC gate that established callability actually passed.
        "operational_status": "VERIFICADO" if qc_passed else "NÃO DISPONÍVEL",
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
        "case_id": qc.get("case_id"),
        "input_sha256": qc.get("input", {}).get("sha256"),
        "qc_gate_passed": qc_passed,
        "target_manifest": {
            "id": manifest.get("id"),
            "version": manifest.get("version"),
            "sha256": sha256_file(Path(target_manifest_path)),
        },
        "totals": {
            "targets": total,
            "interpretable": interpretable,
            "interpretable_fraction": (interpretable / total) if total else 0.0,
            **{f"class_{name}": counts[name] for name in CLASSES},
        },
        "entries": entries,
        "structural_blind_spots": [
            {
                "class": item,
                "status": "NÃO DISPONÍVEL",
                "basis": "classe de variação não resolvida por genotipagem em array, em nenhum locus",
            }
            for item in UNSUPPORTED_ARRAY_CLAIMS
        ],
        "negative_statement_policy": (
            "Somente loci em NÃO DETECTADO admitem afirmação de ausência, e apenas para aquele locus. "
            "NÃO TESTADO, NO-CALL e NÃO REPORTÁVEL nunca são evidência de ausência."
        ),
        "limitations": [
            "A matriz descreve cobertura do array; não estabelece significado clínico de nenhum locus.",
            "Ausência genome-wide não é demonstrável a partir de genotipagem em array.",
            "NÃO DETECTADO depende de o registro declarar o alelo avaliado; sem isso o locus permanece OBSERVADO.",
            "Pontos cegos estruturais são limites da plataforma, não achados desta amostra.",
        ],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def write_matrix(result: dict[str, Any], output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
