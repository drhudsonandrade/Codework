"""Pharmacogenomic passport (report 06 / PGX) over verified SNP-array observations.

Report 06 is the most useful thing this project can deliver from data it already has — and
the easiest place to publish something false, because the conventional output of a
pharmacogenomic panel is a *diplotype* (`CYP2C19 *1/*2`) and a *phenotype* ("metabolizador
lento"), and a consumer array can almost never support either.

Two facts make the usual shortcut wrong:

1. A star allele is defined by a set of positions. Observing three of CYP2C19's defining
   SNPs and finding none of them says "nenhum dos alelos testados foi detectado", **not**
   `*1`. `*1` is the reference haplotype, an assertion about every defining position,
   including the ones the chip never carried. Reporting `*1/*1` from a partial panel
   converts NÃO TESTADO into NÃO DETECTADO — the exact substitution report 09 exists to
   prevent.
2. A diplotype needs phase. Two heterozygous calls in one gene are consistent with two
   different diplotypes, and an array provides no read-level evidence to separate them.

So this module reports what was observed, states per gene exactly why a diplotype could not
be established, and refuses to emit a phenotype without one. When a curated allele-definition
registry *is* supplied — hash-pinned, with its source cited — it computes which defining
alleles were interrogated and which were detected, and still withholds the diplotype unless
that registry declares the panel complete for the gene.

CYP2D6 deserves its own mention: its clinically important variation is structural
(hybrids, duplications, deletions), which array genotyping does not resolve at any locus.
It is already listed in `UNSUPPORTED_ARRAY_CLAIMS` and is never diplotyped here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import normative
from array_pipeline.allele_discrimination import analyse_gene
from array_pipeline.completeness import INTERPRETABLE, NAO_DETECTADO
from array_pipeline.targets import load_target_manifest, sha256_json

SCHEMA = "genoma-pharmacogenomic-passport-v1"
REGISTRY_SCHEMA = "genoma-pgx-registry-v1"
RULESET = normative.ruleset_block()

UNAVAILABLE = "NÃO DISPONÍVEL"

#: A target is pharmacogenomic when the registry routes it to a pharmacogenomic knowledge
#: base. This is read from the data rather than hardcoded, so extending the target registry
#: extends the passport without editing this module.
PGX_EVIDENCE_SOURCES = frozenset({"clinpgx", "cpic"})

#: Genes whose clinically relevant variation is structural, so no array genotype set can
#: yield a diplotype for them however many SNPs are covered.
STRUCTURALLY_UNRESOLVED_GENES = frozenset({"CYP2D6"})


class PgxRegistryError(ValueError):
    """The supplied allele-definition registry is unusable."""


def load_pgx_registry(path: Path) -> dict[str, Any]:
    """Load a curated allele-definition registry.

    The registry is the only route by which star-allele language may enter a report, so it
    must name the source of its definitions. An uncited definition table is an invented
    clinical assertion wearing a schema.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema") != REGISTRY_SCHEMA:
        raise PgxRegistryError(f"unsupported PGx registry schema: {payload.get('schema')!r}")
    if not str(payload.get("source") or "").strip():
        raise PgxRegistryError("PGx registry must cite the source of its allele definitions")
    genes = payload.get("genes")
    if not isinstance(genes, dict) or not genes:
        raise PgxRegistryError("PGx registry must declare a non-empty genes object")
    for gene, spec in genes.items():
        if not isinstance(spec, dict):
            raise PgxRegistryError(f"gene {gene!r} must map to an object")
        alleles = spec.get("alleles", {})
        if not isinstance(alleles, dict):
            raise PgxRegistryError(f"gene {gene!r}: alleles must be an object")
        for allele, definition in alleles.items():
            defining = (definition or {}).get("defining")
            if not isinstance(defining, list) or not defining:
                raise PgxRegistryError(f"{gene} {allele}: defining positions are required")
            for item in defining:
                if not isinstance(item, dict) or not item.get("rsid") or not item.get("allele"):
                    raise PgxRegistryError(f"{gene} {allele}: each defining position needs rsid and allele")
    return payload


def _pgx_targets(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for target in manifest["targets"]:
        sources = set(target.get("queries", {}))
        if sources & PGX_EVIDENCE_SOURCES:
            out[str(target["rsid"]).lower()] = target
    return out


def _evidence_for(rsid: str, annotation: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Verified external retrievals linked to this locus, if evidence was collected."""
    if not annotation:
        return []
    retrievals = {r["id"]: r for r in annotation.get("evidence_retrievals", []) if isinstance(r, dict)}
    out = []
    for link in annotation.get("target_evidence_links", []):
        if str(link.get("target_id", "")).lower() != rsid:
            continue
        retrieval = retrievals.get(link.get("retrieval_id"))
        if not isinstance(retrieval, dict):
            continue
        out.append(
            {
                "id": retrieval["id"],
                "source": retrieval.get("source"),
                "status": retrieval.get("status", UNAVAILABLE),
                "locator": retrieval.get("locator"),
                "checked_at": retrieval.get("checked_at"),
                "result_digest": (retrieval.get("retrieval_evidence") or {}).get("result_digest"),
            }
        )
    return sorted(out, key=lambda x: x["id"])


def _allele_findings(
    gene: str,
    spec: dict[str, Any],
    by_rsid: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """For each defined allele, say whether it was interrogable and whether it was seen.

    `by_rsid` is keyed by every locus whose classification is known — the curated target
    registry plus, when one is supplied, the full CPIC defining-position panel. Passing only
    the curated targets is what made every CPIC position outside them read as NÃO TESTADO
    regardless of what the array carried.
    """
    findings: list[dict[str, Any]] = []
    gaps: list[str] = []
    for allele in sorted(spec.get("alleles", {})):
        defining = spec["alleles"][allele]["defining"]
        positions: list[dict[str, Any]] = []
        interrogable = True
        detected = True
        for item in defining:
            rsid = str(item["rsid"]).lower()
            expected = str(item["allele"]).upper()
            locus = by_rsid.get(rsid)
            classification = locus["classification"] if locus else "NÃO TESTADO"
            genotype = (locus or {}).get("genotype") or ""
            usable = classification in INTERPRETABLE
            present = usable and expected in set(str(genotype).upper())
            if not usable:
                interrogable = False
                gaps.append(f"{allele}:{rsid}:{classification}")
            if not present:
                detected = False
            positions.append(
                {
                    "rsid": rsid,
                    "expected_allele": expected,
                    "classification": classification,
                    "genotype": genotype or None,
                    "interrogable": usable,
                    "allele_present": present if usable else None,
                }
            )
        # Zygosity decides whether a detected allele occupies one chromosome or both, which
        # is what turns a list of detected alleles into a two-element diplotype.
        zygosity = None
        if interrogable and detected:
            homozygous = all(
                len(set(str(p["genotype"] or "").upper())) == 1 for p in positions
            )
            zygosity = "HOMOZIGOTO" if homozygous else "HETEROZIGOTO"

        if interrogable:
            status = "DETECTADO" if detected else NAO_DETECTADO
            basis = (
                "todas as posições definidoras foram interrogadas e carregam o alelo definidor"
                if detected
                else "todas as posições definidoras foram interrogadas; ao menos uma não carrega o alelo definidor"
            )
        else:
            status = UNAVAILABLE
            basis = "ao menos uma posição definidora não é interpretável nesta amostra"
        findings.append(
            {
                "allele": allele,
                "gene": gene,
                "status": status,
                "basis": basis,
                "zygosity": zygosity,
                "positions": positions,
            }
        )
    return findings, sorted(set(gaps))


def _heterozygous_defining_positions(
    spec: dict[str, Any] | None,
    observations: dict[str, dict[str, Any]],
) -> list[str]:
    """Interpretable defining positions of this gene that came back heterozygous.

    Phase ambiguity is a property of the positions that were actually read, so counting it
    over the gene's whole curated locus list — which may include positions no CPIC allele
    uses — would block calls for a reason CPIC's definitions do not support.
    """
    if not spec:
        return []
    positions = {
        str(item["rsid"]).lower()
        for definition in (spec.get("alleles") or {}).values()
        for item in definition.get("defining") or []
    }
    heterozygous: list[str] = []
    for rsid in sorted(positions):
        observation = observations.get(rsid)
        if not observation or observation["classification"] not in INTERPRETABLE:
            continue
        genotype = str(observation.get("genotype") or "")
        if genotype and len(set(genotype)) > 1:
            heterozygous.append(rsid)
    return heterozygous


#: Genotype strings that mean "this position was not read". A no-call is not a homozygous
#: reference call, and the difference decides whether a diplotype may be stated at all.
NO_CALL_GENOTYPES = frozenset({"", "--", "-", "NA", "N/A", "NULL", ".", "00", "0"})


def _is_called_genotype(value: Any) -> bool:
    """True when the value is a real genotype rather than a placeholder for a missing one."""
    text = str(value or "").strip().upper()
    if not text or text in NO_CALL_GENOTYPES:
        return False
    # A call is bases. Anything containing a gap character is a partial read, not a genotype.
    return all(character in "ACGTID" for character in text)


def _diplotype_for(
    gene: str,
    spec: dict[str, Any] | None,
    loci: list[dict[str, Any]],
    allele_findings: list[dict[str, Any]],
    gaps: list[str],
) -> dict[str, Any]:
    """A diplotype is withheld unless every precondition for one actually holds."""
    reasons: list[str] = []
    if gene.upper() in STRUCTURALLY_UNRESOLVED_GENES:
        reasons.append(
            "variação clinicamente relevante deste gene é estrutural (híbridos, duplicações, deleções) "
            "e não é resolvida por genotipagem em array"
        )
    if spec is None:
        reasons.append("registro curado de definições de alelos não foi fornecido para este gene")
    elif spec.get("definitions_unavailable"):
        # The registry was supplied but the source publishes nothing for this gene. Saying
        # so beats the generic "no registry" message, which would misdirect the reader into
        # thinking a registry would fix it.
        reasons.append(str(spec["definitions_unavailable"]))
    else:
        if not spec.get("complete_panel"):
            reasons.append(
                "o registro não declara o painel completo para este gene; alelos não definidos "
                "permaneceriam indistinguíveis do haplótipo de referência"
            )
        elif not str(spec.get("reference_allele") or "").strip():
            # A diplotype has two elements. A heterozygous carrier of one defined allele
            # occupies the other chromosome with the reference haplotype, which has to be
            # *named* by the registry — this module will not coin "*1" on its own.
            reasons.append(
                "o registro declara painel completo mas não nomeia o haplótipo de referência "
                "(reference_allele); sem ele um portador heterozigoto não tem segundo elemento"
            )
        if gaps:
            # CPIC defines dozens of alleles per gene while a consumer array carries a
            # handful of their positions, so listing every gap produced an unreadable
            # sentence. The count is the point: it says how far the panel is from complete.
            positions = sorted({gap.split(":")[1] for gap in gaps if ":" in gap})
            covered = sorted(
                {p["rsid"] for f in allele_findings for p in f["positions"] if p["interrogable"]}
            )
            sample = ", ".join(positions[:5])
            more = f" (+{len(positions) - 5})" if len(positions) > 5 else ""
            reasons.append(
                f"painel incompleto nesta amostra: {len(covered)} de "
                f"{len(covered) + len(positions)} posições definidoras do registro são "
                f"interpretáveis; faltam {sample}{more}"
            )

    detected_findings = [f for f in allele_findings if f["status"] == "DETECTADO"]
    if len(detected_findings) > 1:
        # Two defined alleles in one gene are a compound genotype; which chromosome carries
        # which is a phase question an array cannot answer.
        reasons.append(
            "genótipo composto: mais de um alelo definido foi detectado "
            f"({', '.join(sorted(f['allele'] for f in detected_findings))}) e a atribuição "
            "a cada cromossomo exige fase"
        )

    # Zygosity is read only from loci that were actually called. The test used to be
    # `len(set(genotype)) > 1` over any locus carrying a truthy genotype, and a no-call
    # string like "--" has a set of size one: an uninterrogated position was counted as
    # homozygous. That is the wrong direction twice over — it removed a position from the
    # heterozygous count, so a gene with two het positions and one no-call could drop to one
    # and stop raising phase ambiguity, and it let an unknown genotype stand as evidence of
    # the reference haplotype.
    called = [
        locus
        for locus in loci
        if locus.get("interpretable") and _is_called_genotype(locus.get("genotype"))
    ]
    uncalled = sorted(
        str(locus["rsid"])
        for locus in loci
        if not locus.get("interpretable") or not _is_called_genotype(locus.get("genotype"))
    )
    heterozygous = [
        str(locus["rsid"]) for locus in called if len(set(str(locus["genotype"]))) > 1
    ]
    if len(heterozygous) > 1:
        # Two or more het positions in one gene are consistent with more than one diplotype
        # and an array carries no read-level evidence to resolve the phase.
        reasons.append(
            f"fase não resolvida: {len(heterozygous)} posições heterozigotas "
            f"({', '.join(sorted(heterozygous))}) admitem mais de um diplótipo"
        )
    if uncalled:
        # Stated as its own refusal rather than folded into the panel-gap count, because
        # these are positions the panel *does* carry and this sample did not read. Assuming
        # the reference base at them is exactly the closed-world claim a diplotype must not
        # make silently.
        sample = ", ".join(uncalled[:5])
        more = f" (+{len(uncalled) - 5})" if len(uncalled) > 5 else ""
        reasons.append(
            f"{len(uncalled)} posição(ões) do painel deste gene sem genótipo interpretável "
            f"({sample}{more}); presumir a base de referência nelas é justamente a hipótese "
            "de mundo fechado que um diplótipo não pode assumir em silêncio"
        )

    if reasons:
        return {"status": UNAVAILABLE, "value": None, "reasons": reasons}

    # Exactly two elements, always. The registry named the reference haplotype, so a
    # heterozygous carrier gets allele/reference and a non-carrier gets reference/reference.
    reference = str(spec["reference_allele"]).strip()
    if not detected_findings:
        value = f"{reference}/{reference}"
    else:
        finding = detected_findings[0]
        other = finding["allele"] if finding["zygosity"] == "HOMOZIGOTO" else reference
        value = "/".join(sorted([finding["allele"], other]))

    return {
        "status": "INFERIDO",
        "value": value,
        "reasons": [
            "painel declarado completo, todas as posições definidoras interpretáveis e sem "
            "ambiguidade de fase; ainda assim INFERIDO, nunca EXECUTADO, porque a inferência "
            "vem de genótipos e não de haplótipos observados"
        ],
    }


def _phenotype_for(gene: str, spec: dict[str, Any] | None, diplotype: dict[str, Any]) -> dict[str, Any]:
    """Translate an established diplotype through the registry's cited guideline table.

    The label is looked up, never composed. A diplotype the table does not list yields
    NÃO DISPONÍVEL rather than a nearest match, because "closest entry" is how a
    metabolizer status gets invented.
    """
    if diplotype["status"] == UNAVAILABLE or not diplotype.get("value"):
        return {
            "status": UNAVAILABLE,
            "value": None,
            "reason": "fenótipo depende de diplótipo estabelecido; diplótipo não estabelecido",
        }
    table = (spec or {}).get("phenotype_map") or {}
    if not table:
        return {
            "status": UNAVAILABLE,
            "value": None,
            "reason": "registro não fornece tabela diplótipo→fenótipo para este gene",
        }

    # Registry keys are bare star names (`*1/*2`); the diplotype carries the gene prefix.
    parts = [part.replace(gene, "", 1).strip() for part in str(diplotype["value"]).split("/")]
    for key in ("/".join(parts), "/".join(reversed(parts))):
        entry = table.get(key)
        if entry:
            return {
                "status": "INFERIDO",
                "value": entry.get("phenotype"),
                "activity_score": entry.get("activity_score"),
                "description": entry.get("description"),
                "source": (spec or {}).get("phenotype_map_source", UNAVAILABLE),
                "reason": (
                    "traduzido pela tabela diplótipo→fenótipo do registro citado; INFERIDO "
                    "porque o diplótipo de origem é inferido de genótipos, não de haplótipos observados"
                ),
            }
    return {
        "status": UNAVAILABLE,
        "value": None,
        "reason": f"diplótipo {diplotype['value']} não consta na tabela do registro; "
        "nenhum fenótipo aproximado é emitido",
    }


def build_pharmacogenomic_passport(
    completeness_path: Path,
    target_manifest_path: Path,
    *,
    annotation_path: Path | None = None,
    pgx_registry_path: Path | None = None,
    panel_matrix_path: Path | None = None,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Assemble the passport from the completeness matrix and the target registry.

    `panel_matrix_path` is a second completeness matrix, built over the full CPIC
    defining-position panel (`scripts/build_pgx_panel.py`). Without it the passport can only
    see the curated targets, so every other CPIC position is NÃO TESTADO by construction and
    the coverage figure measures this pipeline's target list rather than the array. It is
    optional so that existing callers keep working, and its absence is recorded on the face
    of the passport instead of being silently equivalent to full coverage.
    """
    matrix = json.loads(Path(completeness_path).read_text(encoding="utf-8"))
    if matrix.get("schema") != "genoma-genome-completeness-matrix-v1":
        raise ValueError("completeness matrix schema mismatch")

    panel_matrix = None
    if panel_matrix_path is not None:
        panel_matrix = json.loads(Path(panel_matrix_path).read_text(encoding="utf-8"))
        if panel_matrix.get("schema") != "genoma-genome-completeness-matrix-v1":
            raise ValueError("panel matrix schema mismatch")
        if panel_matrix.get("input_sha256") != matrix.get("input_sha256"):
            raise ValueError("panel matrix and completeness matrix describe different inputs")

    manifest = load_target_manifest(Path(target_manifest_path))
    pgx_targets = _pgx_targets(manifest)

    annotation = None
    if annotation_path is not None:
        annotation = json.loads(Path(annotation_path).read_text(encoding="utf-8"))
        if annotation.get("input_sha256") != matrix.get("input_sha256"):
            raise ValueError("annotation and completeness matrix describe different inputs")

    registry = None
    if pgx_registry_path is not None:
        registry = load_pgx_registry(Path(pgx_registry_path))

    entries = {str(e["rsid"]).lower(): e for e in matrix.get("entries", [])}

    genes: dict[str, list[dict[str, Any]]] = {}
    for rsid, target in pgx_targets.items():
        entry = entries.get(rsid)
        gene = str(target.get("gene") or "sem gene declarado")
        genes.setdefault(gene, []).append(
            {
                "rsid": rsid,
                "label": target.get("label"),
                "scope": target.get("scope"),
                "classification": (entry or {}).get("classification", "NÃO TESTADO"),
                "basis": (entry or {}).get("basis", "locus ausente da matriz de completude"),
                "genotype": (entry or {}).get("genotype"),
                "interpretable": bool((entry or {}).get("interpretable")),
                "evidence": _evidence_for(rsid, annotation),
            }
        )

    # Every locus whose classification is known, from either matrix. The curated targets win
    # a collision: they carry a hand-verified assessed allele, while the panel entry is
    # derived. Both matrices are built from the same input file, checked above by SHA-256.
    observations: dict[str, dict[str, Any]] = {}
    for entry in (panel_matrix or {}).get("entries", []):
        observations[str(entry["rsid"]).lower()] = {
            "rsid": str(entry["rsid"]).lower(),
            "classification": entry.get("classification", "NÃO TESTADO"),
            "genotype": entry.get("genotype"),
            "interpretable": bool(entry.get("interpretable")),
        }
    for entry in matrix.get("entries", []):
        observations[str(entry["rsid"]).lower()] = {
            "rsid": str(entry["rsid"]).lower(),
            "classification": entry.get("classification", "NÃO TESTADO"),
            "genotype": entry.get("genotype"),
            "interpretable": bool(entry.get("interpretable")),
        }
    classifications = {rsid: obs["classification"] for rsid, obs in observations.items()}

    gene_records: list[dict[str, Any]] = []
    for gene in sorted(genes):
        loci = sorted(genes[gene], key=lambda x: x["rsid"])
        spec = (registry or {}).get("genes", {}).get(gene) if registry else None
        if spec is not None:
            allele_findings, gaps = _allele_findings(gene, spec, observations)
        else:
            allele_findings, gaps = [], []
        diplotype = _diplotype_for(gene, spec, loci, allele_findings, gaps)
        gene_records.append(
            {
                "gene": gene,
                "loci": loci,
                "interrogated_loci": sum(1 for x in loci if x["interpretable"]),
                "total_loci": len(loci),
                "allele_findings": allele_findings,
                "diplotype": diplotype,
                # A phenotype is a function of a diplotype. Without one there is nothing to
                # translate, and "normal metabolizer" would be an invented default. With one,
                # the translation still comes from the registry's cited guideline table —
                # this module never authors a phenotype label.
                "phenotype": _phenotype_for(gene, spec, diplotype),
                # The discrimination analysis is additive. It never relaxes `diplotype`; it
                # answers the separate question of how much of the gene the panel could
                # exclude, and what it would take to exclude the rest.
                "discrimination": analyse_gene(
                    gene,
                    spec,
                    classifications,
                    allele_findings,
                    _heterozygous_defining_positions(spec, observations),
                    structurally_unresolved=gene.upper() in STRUCTURALLY_UNRESOLVED_GENES,
                ),
            }
        )

    anesthesia = _anesthesia_card(gene_records, registry)

    interrogated = sum(g["interrogated_loci"] for g in gene_records)
    total = sum(g["total_loci"] for g in gene_records)
    now = evaluated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        # The passport is a restatement of observations whose status the matrix already
        # established; it cannot be stronger than that.
        "operational_status": matrix.get("operational_status", UNAVAILABLE),
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
        "case_id": matrix.get("case_id"),
        "input_sha256": matrix.get("input_sha256"),
        "completeness_matrix_sha256": matrix.get("sha256"),
        "pgx_registry": (
            {
                "id": registry.get("id"),
                "version": registry.get("version"),
                "source": registry.get("source"),
                "sha256": sha256_json(registry),
            }
            if registry
            else {"status": UNAVAILABLE, "reason": "nenhum registro curado de definições de alelos foi fornecido"}
        ),
        "evidence_linked": annotation is not None,
        "totals": {
            "genes": len(gene_records),
            "loci": total,
            "interrogated_loci": interrogated,
            "interrogated_fraction": (interrogated / total) if total else 0.0,
            "genes_with_diplotype": sum(1 for g in gene_records if g["diplotype"]["status"] != UNAVAILABLE),
            # Counted, not asserted. Hardcoding 0 here would have stayed "true" only for as
            # long as nothing emitted a phenotype, and would have gone quietly wrong the
            # moment something did — the vacuous-constant pattern this project keeps finding.
            "genes_with_phenotype": sum(
                1 for g in gene_records if g["phenotype"]["status"] != UNAVAILABLE
            ),
            # Counted the same way, from the records themselves. Conditional calls are kept
            # in their own totals so a reader can never mistake ten conditional diplotypes
            # for ten established ones.
            "genes_with_conditional_diplotype": sum(
                1
                for g in gene_records
                if (g["discrimination"].get("conditional_diplotype") or {}).get("status")
                not in (None, UNAVAILABLE)
            ),
            "genes_with_conditional_phenotype": sum(
                1
                for g in gene_records
                if (g["discrimination"].get("conditional_phenotype") or {}).get("status")
                not in (None, UNAVAILABLE)
            ),
            "defining_positions_total": sum(
                g["discrimination"].get("positions_total", 0) for g in gene_records
            ),
            "defining_positions_interpretable": sum(
                g["discrimination"].get("positions_interpretable", 0) for g in gene_records
            ),
            "alleles_catalogued": sum(
                g["discrimination"].get("alleles_catalogued", 0) for g in gene_records
            ),
            "alleles_discriminable": sum(
                g["discrimination"].get("alleles_discriminable", 0) for g in gene_records
            ),
        },
        "panel_matrix": (
            {
                "case_id": panel_matrix.get("case_id"),
                "sha256": panel_matrix.get("sha256"),
                "target_manifest": panel_matrix.get("target_manifest"),
                "totals": panel_matrix.get("totals"),
            }
            if panel_matrix
            else {
                "status": UNAVAILABLE,
                "reason": (
                    "nenhuma matriz do painel completo de posições definidoras do CPIC foi "
                    "fornecida; a cobertura abaixo mede apenas os alvos curados, e posições que "
                    "o array pode carregar aparecem como NÃO TESTADO por construção. Gerar com "
                    "scripts/build_pgx_panel.py + scripts/build_completeness_report.py."
                ),
            }
        ),
        "sequencing_requisitions": [
            g["discrimination"]["sequencing_requisition"]
            for g in gene_records
            if (g["discrimination"].get("sequencing_requisition") or {}).get("status") == "PROPOSTO"
        ],
        "genes": gene_records,
        "anesthesia_card": anesthesia,
        "prescribing_policy": (
            "Este documento não prescreve, não substitui diretriz clínica e não estabelece dose. "
            "Genótipo observado é ponto de partida para decisão, sempre com confirmação apropriada "
            "e avaliação de fenoconversão (interações, função hepática/renal, idade, comorbidade)."
        ),
        "limitations": [
            "Genotipagem em array interroga apenas as posições ensaiadas; alelos não cobertos permanecem indistinguíveis do haplótipo de referência.",
            "Diplótipo exige painel completo e fase; array não fornece evidência de fase.",
            "Fenótipo farmacogenético não é emitido sem diplótipo estabelecido e diretriz versionada.",
            "CYP2D6 não é diplotipado: sua variação clinicamente relevante é estrutural.",
            "Fenoconversão por interação medicamentosa e por estado clínico não é derivável do genótipo.",
            "Achados acionáveis exigem confirmação por método ortogonal antes de mudar conduta.",
            "Diplótipo condicional não é diplótipo estabelecido: vale sob a suposição declarada "
            "de que nenhum alelo não interrogado está presente, e o risco residual dessa "
            "suposição está quantificado por grupo biogeográfico.",
            "Risco residual sem limite superior (alelo sem frequência publicada pelo CPIC) "
            "impede a emissão de fenótipo condicional.",
        ],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def _anesthesia_card(gene_records: list[dict[str, Any]], registry: dict[str, Any] | None) -> dict[str, Any]:
    """The emergency-facing card: observations only, never a clearance or a diagnosis.

    Which genes belong on the card is a clinical judgement, so it is read from the curated
    registry rather than hardcoded here. Without a registry the card reports that its
    relevance list was never declared instead of guessing one.
    """
    if not registry:
        return {
            "status": UNAVAILABLE,
            "reason": "registro curado não fornecido; a relevância anestésica não foi declarada por fonte citável",
            "genes": [],
            "observations": [],
        }

    relevant = [
        record
        for record in gene_records
        if (registry.get("genes", {}).get(record["gene"], {}) or {}).get("anesthesia_relevant")
    ]
    observations: list[dict[str, Any]] = []
    for record in relevant:
        for locus in record["loci"]:
            observations.append(
                {
                    "gene": record["gene"],
                    "rsid": locus["rsid"],
                    "classification": locus["classification"],
                    "genotype": locus["genotype"],
                    "interpretable": locus["interpretable"],
                    "note": (registry["genes"][record["gene"]] or {}).get("anesthesia_note") or UNAVAILABLE,
                }
            )

    usable = [o for o in observations if o["interpretable"]]
    return {
        # The card describes observations; it never states that anaesthesia is safe.
        "status": "VERIFICADO" if usable else UNAVAILABLE,
        "genes": sorted({r["gene"] for r in relevant}),
        "observations": sorted(observations, key=lambda x: (x["gene"], x["rsid"])),
        "interpretable_observations": len(usable),
        "clearance_policy": (
            "Este cartão não libera nem contraindica anestesia. Genótipo observado não substitui "
            "dosagem de atividade enzimática nem avaliação pré-anestésica, e ausência de achado "
            "não exclui risco: apenas as posições ensaiadas foram interrogadas."
        ),
    }


def write_passport(result: dict[str, Any], output: Path) -> Path:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
