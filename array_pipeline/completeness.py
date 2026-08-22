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
    detect_schema,
    UNRESOLVED_OVERLAP_STATUSES,
    _canonical_gt,
    _is_valid_consensus,
    _read_header_and_metadata,
    _text_stream,
    sha256_file,
)
from array_pipeline.targets import load_target_manifest, sha256_json
from reporting.assay import assay_for_schema

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


def assessed_bases(target: dict[str, Any]) -> set[str]:
    """Every base whose presence at this locus this registry can test for.

    `assessed_allele` holds the single alternate base when ClinVar asserts exactly one at the
    coordinate. When it asserts several, the expander declines to name one and records them
    all in `clinvar_alternate_alleles` — and, before this function existed, the classifier
    read only the singular field, found it empty, and fell through to OBSERVADO with
    "ausência não pode ser afirmada".

    That was the wrong reading twice over. At one coordinate a single alternate base *is* a
    single variant, so the called genotype answers presence for each of them independently:
    a genotype sharing no base with any asserted alternate is a real NÃO DETECTADO. And
    `clinical_findings` read the resulting OBSERVADO as presence, so a person homozygous for
    the reference base was graded "homozigoto para variante patogênica". On the first real
    array this produced 3.412 false positives out of 3.153 reported risk genotypes,
    including familial adenomatous polyposis from a plain reference call in APC.
    """
    single = str(target.get("assessed_allele") or "").strip().upper()
    if single:
        return {single}
    return {
        str(base).strip().upper()
        for base in (target.get("clinvar_alternate_alleles") or [])
        if str(base).strip()
    }


def _header_of(path: Path) -> list[str]:
    fh, _ = _text_stream(path)
    try:
        header, _metadata = _read_header_and_metadata(fh)
        return header
    finally:
        fh.close()


def _row_reader(path: Path):
    fh, _ = _text_stream(path)
    try:
        header, _metadata = _read_header_and_metadata(fh)
        schema = detect_schema(header)
        import csv

        for row in csv.DictReader(fh, fieldnames=header):
            yield schema, row
    finally:
        fh.close()


def _classify(
    row: dict[str, str] | None,
    schema: str | None,
    target: dict[str, Any],
    file_schema: str,
) -> tuple[str, str]:
    """Return (class, basis) for one target locus."""
    if row is None:
        # Why the locus was not interrogated depends on what produced the table. For an array
        # it is absent from the chip; for a VCF projection it is a position the file said
        # nothing about — and absence in a VCF is not reference, which is the whole reason
        # this class exists rather than a negative one.
        return NAO_TESTADO, assay_for_schema(file_schema).absence_note

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
    assessed = assessed_bases(target)
    if not assessed:
        return (
            OBSERVADO,
            "genótipo chamado; ausência não pode ser afirmada porque o registro não declara o alelo avaliado",
        )
    present = sorted(assessed & set(genotype))
    named = ", ".join(sorted(assessed))
    if present:
        return OBSERVADO, f"genótipo chamado {genotype} contém o alelo avaliado {', '.join(present)}"
    return (
        NAO_DETECTADO,
        f"genótipo chamado {genotype} não contém nenhuma das {len(assessed)} base(s) "
        f"avaliada(s) ({named}); ausência vale apenas para este locus",
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

    gates = qc.get("gates", {}) or {}

    # Until this refusal existed the QC verdict was advisory: an array whose STRUCTURE_GATE
    # failed on 332,291 impossible coordinates still produced a clinical report naming 27
    # actionable findings, and no report said the QC had failed. Every builder derives from
    # this matrix, so the refusal belongs here rather than in the orchestrator, which a
    # direct caller bypasses.
    #
    # Only STRUCTURE_GATE blocks, and the line is where it is on purpose. A structural
    # failure says the file is not a valid array — malformed rows, chromosomes that do not
    # exist, coordinates that cannot exist — and there is nothing to describe. A failing
    # CALLABILITY_GATE or CROSS_PLATFORM_GATE says a *valid* file is of poor quality, which
    # is precisely what this matrix is built to express, locus by locus: a no-call becomes
    # NÃO TESTADO and an unresolved conflict becomes NÃO REPORTÁVEL. Refusing those would
    # withhold the measurement instead of qualifying it, and `operational_status` already
    # drops to NÃO DISPONÍVEL so nothing built on them can publish.
    structure = gates.get("STRUCTURE_GATE") or {}
    blocking = structure.get("blocking_reasons")
    if blocking is None:
        # A QC file written before the gate distinguished severities. Falling back to the
        # whole reason list is the fail-closed reading: an old file that failed structurally
        # is refused rather than admitted on the grounds that its severity is unstated.
        blocking = structure.get("reasons") or [] if structure.get("state") == "FAIL" else []
    if blocking:
        detail = "; ".join(blocking) or "sem razão registrada"
        raise ValueError(
            f"array QC failed structurally and no coverage can be derived from it ({detail}). "
            "Corrija o arquivo de entrada e rode o QC novamente; interpretar sobre ele "
            "produziria achados cuja base o próprio QC recusou."
        )

    gate = gates.get("LIMITED_INTERPRETATION_GATE", {})
    qc_passed = gate.get("state") == "PASS" and qc.get("operational_status") == "VERIFICADO"

    # When the matrix is not VERIFICADO, every report built on it inherits that status with
    # no way to say why. Carrying the non-passing gates through means the reason travels
    # with the measurement instead of being left behind in the QC file.
    qc_reservations = [
        {
            "gate": name,
            "state": (gates[name] or {}).get("state"),
            "reasons": list((gates[name] or {}).get("reasons") or []),
        }
        for name in sorted(gates)
        if (gates[name] or {}).get("state") not in ("PASS", "NOT_APPLICABLE", None)
    ]

    manifest = load_target_manifest(target_manifest_path)
    targets = {str(t["rsid"]).lower(): t for t in manifest["targets"]}

    # Every row for a target is collected, not just the first. `qc.inspect_array` allows a
    # raw vendor export to carry duplicate RSID rows, so keeping only the first silently
    # picked a winner whenever two rows disagreed — resolving a conflict by arbitration,
    # which sections 4 and 7 forbid.
    collected: dict[str, list[tuple[str, dict[str, str]]]] = {}
    # The file's own schema, read once from its header, so a target the table never
    # mentions can still be explained in the vocabulary of what produced the table.
    file_schema = detect_schema(_header_of(Path(input_path)))
    assay = assay_for_schema(file_schema)
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
        classification, basis = _classify(row, schema, target, file_schema)
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
                # Every base the classification was actually able to test for. Empty means
                # the registry could name none, so OBSERVADO at this locus says "chamado",
                # never "presente" — and `clinical_findings` must refuse to grade it rather
                # than read the class alone.
                "assessed_alleles": sorted(assessed_bases(target)),
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
        "qc_reservations": qc_reservations,
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
            # Both sentences named the array as a constant. The matrix now also describes a
            # WGS projection, where the first is the wrong subject and the second the wrong
            # reason — a projection is bounded by the target registry, not by a chip.
            f"A matriz descreve {assay.coverage_subject}; não estabelece significado clínico "
            "de nenhum locus.",
            assay.genome_wide_note,
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
