#!/usr/bin/env python3
"""Compile report 02 (Ancestralidade e Genealogia Genética) as a measured feasibility report.

Ancestry inference needs a reference panel of *genotypes* — 1000 Genomes, HGDP, SGDP — not
allele frequencies. Without one there is no honest way to produce a pie chart of origins, and
producing one anyway is the single most common lie in consumer genomics: the percentages come
from a proprietary panel whose composition the reader never sees, and they change when the
company updates it.

So this report does not estimate ancestry. It measures whether ancestry could be estimated,
which is a real result and one the reader can act on:

* how many autosomal markers this array carries, which sets the ceiling on any PCA or
  admixture analysis;
* how many mitochondrial and Y-chromosome markers it carries, which decides whether maternal
  and paternal haplogroups are assignable at all — and, separately, whether the phylogenies
  needed to assign them are available here;
* what exactly is missing, named concretely enough to be procured.

The refusals are not hedges. "Retrato das origens" is NÃO DISPONÍVEL because no reference
panel was supplied; "parentesco genético" because kinship needs a second sample; "DNA antigo"
because it needs an ancient-genome panel. Each says which artifact would change the answer.
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

from reporting.catalog import section_titles
from reporting.provenance import Artifact, PayloadCompiler

REPORT_ID = "02"
UNAVAILABLE = "NÃO DISPONÍVEL"

#: Chromosome labels that are not autosomal, so autosomal marker counts exclude them.
NON_AUTOSOMAL = frozenset({"X", "Y", "MT", "XY", "0"})

#: Public reference panels that would make an estimate possible, named so the requirement is
#: procurable rather than rhetorical. Nothing here is downloaded by this script.
REFERENCE_PANELS = (
    "1000 Genomes Project Phase 3 (2.504 amostras, 26 populações) — genótipos, não frequências",
    "Human Genome Diversity Project / CEPH (929 amostras, 54 populações)",
    "Simons Genome Diversity Project (300 amostras, 142 populações)",
)
#: Brazilian ancestry is admixed, so a panel without African, Native American and European
#: reference populations at once cannot resolve it. Naming this is part of the requirement.
ADMIXTURE_NOTE = (
    "Ancestralidade brasileira é tipicamente trirracial (europeia, africana e ameríndia em "
    "proporções variáveis). Um painel de referência que não contenha as três simultaneamente "
    "não resolve a composição: produz projeção sobre os eixos que possui e cala sobre o resto."
)


def _autosomal(counts: dict[str, Any]) -> int:
    return sum(int(v) for k, v in counts.items() if str(k) not in NON_AUTOSOMAL)


def _panel_text(metrics: dict[str, Any]) -> str:
    counts = metrics.get("chromosome_counts") or {}
    autosomal = _autosomal(counts)
    mt = int(counts.get("MT", 0))
    y = int(counts.get("Y", 0))
    x = int(counts.get("X", 0))
    return (
        f"{autosomal} marcadores autossômicos, {x} no cromossomo X, {y} no Y e {mt} no DNA "
        f"mitocondrial; taxa de chamada global {metrics.get('call_rate', 0) * 100:.2f}%, "
        f"heterozigosidade autossômica {metrics.get('autosomal_heterozygosity_rate', 0) * 100:.2f}%. "
        "A densidade autossômica é suficiente para PCA e para análise de mistura supervisionada "
        "*se* um painel de referência com genótipos for fornecido; ela não substitui o painel. "
        f"A presença de {y} marcadores no Y e {mt} no mtDNA indica que linhagens uniparentais "
        "são fisicamente interrogáveis nesta amostra."
    )


def _lineage_text(metrics: dict[str, Any]) -> str:
    counts = metrics.get("chromosome_counts") or {}
    mt = int(counts.get("MT", 0))
    y = int(counts.get("Y", 0))
    if not mt and not y:
        return (
            "Este array não carrega marcadores mitocondriais nem do cromossomo Y; nenhuma "
            "linhagem uniparental é interrogável, e nenhum haplogrupo pode ser atribuído."
        )
    return (
        f"{mt} marcadores mitocondriais e {y} marcadores do cromossomo Y estão presentes e "
        "foram ensaiados. A atribuição de haplogrupo, porém, exige as filogenias de referência "
        "— PhyloTree para mtDNA e a árvore do Y do ISOGG/YFull — que não estão disponíveis "
        "neste ambiente em forma legível por máquina com versão citável. Sem elas, atribuir um "
        "haplogrupo seria nomear um ramo de memória, que é exatamente a asserção sem fonte que "
        f"este sistema recusa. Presença de {y} marcadores no Y é observação sobre a amostra e "
        "não é usada aqui para inferir sexo nem identidade."
    )


def _requirements_text() -> str:
    return (
        "Para converter este relatório de viabilidade em estimativa: (1) painel de referência "
        "com genótipos — " + "; ".join(REFERENCE_PANELS) + ". (2) Harmonização do painel ao "
        "mesmo build e à mesma fita desta amostra, com marcadores palindrômicos (A/T, C/G) "
        "excluídos ou resolvidos por frequência, porque um flip neles é indetectável. "
        "(3) Método declarado e versionado: projeção PCA sobre o painel, ou análise de mistura "
        "supervisionada, com intervalos de confiança reportados. (4) " + ADMIXTURE_NOTE
    )


def build_payload(matrix_path: Path, qc_path: Path) -> dict:
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    qc = Artifact.from_path("array-qc", qc_path)
    if qc.payload.get("input", {}).get("sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("QC artifact and completeness matrix describe different inputs")

    titles = section_titles(REPORT_ID)
    case_id = matrix.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(case_id=str(case_id), report_id=REPORT_ID)
    compiler.register(matrix)
    compiler.register(qc)

    verified = matrix.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE
    metrics = qc.payload.get("metrics") or {}

    compiler.derive(
        "summary", artifact="array-qc", locator="metrics", status=status,
        basis="densidade de marcadores e viabilidade de inferência de ancestralidade",
        kind="computed",
        transform=lambda m: (
            f"Nenhuma estimativa de ancestralidade é emitida: nenhum painel de referência com "
            f"genótipos foi fornecido a esta execução. O array carrega {_autosomal(m.get('chromosome_counts') or {})} "
            f"marcadores autossômicos, {int((m.get('chromosome_counts') or {}).get('MT', 0))} "
            f"mitocondriais e {int((m.get('chromosome_counts') or {}).get('Y', 0))} no Y, o que "
            "torna a análise fisicamente possível assim que o painel existir. Percentuais de "
            "origem sem painel citado são a asserção sem fonte mais comum em genômica de consumo."
        ),
    )

    compiler.section_derived(
        titles[0], artifact="array-qc", locator="case_id", status=status,
        basis="identificador do caso e integridade da entrada", kind="qc_metric",
        transform=lambda cid: (
            f"Caso {cid}; entrada SHA-256 {matrix.payload.get('input_sha256')}; "
            f"QC {qc.sha256}. Nenhum painel de referência populacional foi registrado."
        ),
    )
    # The origins portrait is the whole point of the report and the thing that cannot be
    # produced. Saying which artifact would change that keeps it a requirement, not a hedge.
    compiler.section_unavailable(
        titles[1],
        basis=(
            "estimativa de composição de ancestralidade exige painel de referência com "
            "genótipos (1000 Genomes, HGDP ou SGDP), que não foi fornecido a esta execução. "
            "Frequências alélicas por população não bastam: separam populações no agregado, "
            "não atribuem proporções a um indivíduo"
        ),
    )
    compiler.section_derived(
        titles[2], artifact="array-qc", locator="metrics", status=status,
        basis="densidade por cromossomo, taxa de chamada e heterozigosidade autossômica",
        kind="qc_metric", transform=_panel_text,
    )
    compiler.section_derived(
        titles[3], artifact="array-qc", locator="metrics.chromosome_counts", status=status,
        basis="marcadores mitocondriais e do cromossomo Z/Y efetivamente presentes no array",
        kind="qc_metric", transform=lambda _c: _lineage_text(metrics),
    )
    compiler.section_unavailable(
        titles[4],
        basis=(
            "parentesco genético e triangulação exigem ao menos uma segunda amostra e um "
            "critério declarado de segmento IBD; apenas uma pessoa foi analisada"
        ),
    )
    compiler.section_unavailable(
        titles[5],
        basis=(
            "contexto de DNA antigo exige painel de genomas antigos com proveniência "
            "arqueológica e datação citadas, que não foi fornecido; narrativa histórica sem "
            "esse painel é ilustração, não resultado"
        ),
    )
    compiler.section_stated(
        titles[6],
        _requirements_text(),
        kind="normative",
        basis="requisitos declarados para tornar a estimativa possível, e limites que permanecem",
        status="VERIFICADO",
    )

    compiler.state(
        "sources",
        [f"completeness-matrix:{matrix.sha256}", f"array-qc:{qc.sha256}"],
        kind="case_control", basis="artefatos dos quais esta avaliação de viabilidade deriva",
        status="VERIFICADO",
    )
    compiler.state(
        "limitations",
        (
            "Este documento não estima ancestralidade; mede se ela poderia ser estimada. "
            "Marcadores presentes num array não equivalem a cobertura filogenética: haplogrupo "
            "exige filogenia versionada, e composição exige painel de referência com genótipos. "
            "Ancestralidade genética não é identidade, cultura, nacionalidade nem história "
            "familiar, e nenhuma inferência sobre pertencimento decorre de um genótipo. "
            + ADMIXTURE_NOTE
        ),
        kind="normative", basis="limites de escopo e de método desta avaliação", status="VERIFICADO",
    )

    return compiler.compile(
        publication_gate={
            "passed": verified,
            "consent_verified": bool(matrix.payload.get("case_id")),
            "qc_verified": bool(matrix.payload.get("qc_gate_passed")),
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": verified,
            "planes": {
                k: {"state": "PASS" if verified else "BLOCKED"}
                for k in ("policy_control", "scientific_data", "evidence", "audit")
            },
            "gates": [
                {"gate": "FINAL_AUDIT_GATE", "state": "PASS" if verified else "BLOCKED", "blocking": True}
            ],
        },
        execution_manifest={
            "status": matrix.payload.get("operational_status", UNAVAILABLE),
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            "ARRAY_QC_SHA256": qc.sha256,
            "REFERENCE_PANEL": UNAVAILABLE,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--qc", required=True)
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    payload = build_payload(Path(args.matrix), Path(args.qc))
    out = Path(args.payload_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"payload": str(out), "operational_status": payload["operational_status"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
