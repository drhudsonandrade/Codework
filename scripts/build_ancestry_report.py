#!/usr/bin/env python3
"""Compile report 02 (Ancestralidade e Genealogia Genética).

Ancestry inference needs a reference panel of *genotypes* — allele frequencies separate
populations in aggregate but cannot place an individual. Without one there is no honest way
to produce a pie chart of origins, and producing one anyway is the commonest lie in consumer
genomics: the percentages come from a proprietary panel whose composition the reader never
sees, and they change when the company updates it.

The report therefore has two modes, and which one it is in is stated on its face.

**With a panel** (`--panel`, built by `scripts/build_ancestry_panel.py` from the 1000 Genomes
Omni chip release plus the Mao et al. Native American reference), the case is projected onto
components computed from the reference alone, and the section reports population affinity
with proportions and bootstrap intervals — or affinity alone when the marker overlap is too
low for proportions to survive projection shrinkage.

**Without one**, it measures whether ancestry *could* be estimated, which is itself a result
the reader can act on:

* how many autosomal markers this array carries, which sets the ceiling on any PCA or
  admixture analysis;
* how many mitochondrial and Y-chromosome markers it carries, which decides whether maternal
  and paternal haplogroups are assignable at all — and, separately, whether the phylogenies
  needed to assign them are available here;
* what exactly is missing, named concretely enough to be procured.

The remaining refusals are not hedges. "Parentesco genético" needs a second sample; "DNA
antigo" needs an ancient-genome panel. Each names the artifact that would change the answer.
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


def _origins_text(projection: dict[str, Any]) -> str:
    """The origins portrait, or the measured reason there is none."""
    if projection.get("status") != "INFERIDO":
        return str(projection.get("reason") or UNAVAILABLE)
    affinity = ", ".join(
        f"{a['population']} (distância {a['distance']})" for a in projection["affinity"][:4]
    )
    lines = [
        f"Projeção sobre {projection['markers_used']} marcadores do painel "
        f"({projection['overlap_fraction']:.1%} do painel). "
        f"Populações de referência mais próximas: {affinity}."
    ]
    if projection.get("proportions"):
        # The floor is the panel's own measured artefact size, not a display threshold. It
        # was 0.5% here while the projection measured 20%, so components the panel itself
        # cannot distinguish from noise were printed as numbers with confidence intervals —
        # and a bootstrap interval measures sampling spread over markers, never the
        # systematic artefact the validation found, so it understated the uncertainty by an
        # order of magnitude while looking authoritative.
        floor = projection.get("minor_component_floor")
        ordered = sorted(projection["proportions"], key=lambda x: -x["proportion"])
        if floor is None:
            lines.append(
                "Nenhuma composição é emitida: este painel não traz artefato de validação, "
                "então o tamanho de um componente espúrio não foi medido e não há piso "
                "abaixo do qual um componente deixe de ser estabelecido."
            )
            lines.append(str(projection["proportions_method"]))
            return " ".join(lines)
        established = [p for p in ordered if p["proportion"] >= floor]
        below = [p for p in ordered if p["proportion"] < floor]
        if established:
            composition = "; ".join(
                f"{p['population']} {p['proportion']:.1%} "
                f"(IC95% {p['interval_95'][0]:.1%}–{p['interval_95'][1]:.1%})"
                for p in established
            )
            lines.append(f"Composição aproximada: {composition}.")
        else:
            lines.append(
                f"Nenhum componente atinge o piso de {floor:.0%} abaixo do qual esta "
                "projeção não estabelece composição; leia a afinidade acima."
            )
        if below:
            lines.append(
                f"Não estabelecidos (abaixo do piso de {floor:.0%}): "
                + ", ".join(p["population"] for p in below)
                + ". O valor ajustado para cada um está abaixo do maior componente espúrio já "
                "observado neste painel ao projetar indivíduos de origem conhecida, e o "
                "intervalo bootstrap mede dispersão amostral entre marcadores, não esse "
                "artefato — citá-los como percentuais seria dar precisão a ruído."
            )
        if projection.get("fit_quality_warning"):
            lines.append(str(projection["fit_quality_warning"]))
        lines.append(str(projection["proportions_method"]))
    else:
        lines.append(str(projection.get("proportions_reason") or UNAVAILABLE))
    return " ".join(lines)


def _projection_quality(projection: dict[str, Any]) -> str:
    return (
        f"{projection['markers_used']} marcadores usados de "
        f"{projection['panel']['markers']} do painel; "
        f"{projection['markers_absent_from_case']} ausentes do array, "
        f"{projection['markers_allele_mismatch']} com alelos incompatíveis com o painel, "
        f"{projection['markers_strand_flipped']} resolvidos por complemento de fita. "
        f"Painel {projection['panel']['id']} v{projection['panel']['version']}, "
        f"build {projection['panel']['build']}, "
        f"populações de referência: "
        + ", ".join(f"{k} n={v}" for k, v in sorted(projection["panel"]["populations"].items()))
        + "."
    )


def build_payload(
    matrix_path: Path,
    qc_path: Path,
    *,
    panel_path: Path | None = None,
    input_path: Path | None = None,
    policy_evaluation: Path | None = None,
    post_deployment_witness: Path | None = None,
) -> dict:
    matrix = Artifact.from_path("completeness-matrix", matrix_path)
    qc = Artifact.from_path("array-qc", qc_path)
    if qc.payload.get("input", {}).get("sha256") != matrix.payload.get("input_sha256"):
        raise ValueError("QC artifact and completeness matrix describe different inputs")

    titles = section_titles(REPORT_ID)
    case_id = matrix.payload.get("case_id") or UNAVAILABLE
    compiler = PayloadCompiler(
        case_id=str(case_id),
        report_id=REPORT_ID,
        policy_evaluation=policy_evaluation,
        post_deployment_witness=post_deployment_witness,
    )
    compiler.register(matrix)
    compiler.register(qc)

    verified = matrix.payload.get("operational_status") == "VERIFICADO"
    status = "VERIFICADO" if verified else UNAVAILABLE
    metrics = qc.payload.get("metrics") or {}

    # The projection is an artifact of its own, so every sentence about origins is anchored
    # to a value that was computed and stored rather than to prose written here.
    projection = None
    if panel_path is not None and input_path is not None:
        from array_pipeline.ancestry import load_panel, project_case, read_case_genotypes

        panel = load_panel(panel_path)
        build = str(
            (qc.payload.get("gates", {}).get("BUILD_GATE", {}) or {}).get("declared")
            or qc.payload.get("declared_build")
            or panel.get("build")
        )
        genotypes, read_stats = read_case_genotypes(
            input_path, {str(m["rsid"]).lower() for m in panel["markers"]}
        )
        projection = project_case(panel, genotypes, case_build=build)
        projection["case_read_statistics"] = read_stats
        compiler.register(Artifact.from_payload("ancestry-projection", projection))

    if projection is not None:
        compiler.derive(
            "summary", artifact="ancestry-projection", locator="affinity",
            status=projection["status"] if projection["status"] != UNAVAILABLE else UNAVAILABLE,
            basis="projeção do caso nos componentes principais do painel de referência",
            kind="computed",
            transform=lambda _a: _origins_text(projection),
        )
    else:
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

    # The panel sentence is conditional, not a constant. It was written unconditionally, so a
    # run that *did* project the case onto a panel printed "Nenhum painel de referência
    # populacional foi registrado" in its control block while the summary two lines above
    # reported EUR/AFR/SAS percentages derived from that very panel. A reader given both has
    # to decide which half of the same page to believe, and the identity of the panel — the
    # one thing that makes the percentages auditable — was the half that was thrown away.
    def _control(case_id: Any) -> str:
        head = (
            f"Caso {case_id}; entrada SHA-256 {matrix.payload.get('input_sha256')}; "
            f"QC {qc.sha256}. "
        )
        if projection is not None and projection["status"] == "INFERIDO":
            panel = projection["panel"]
            return head + (
                f"Painel de referência {panel['id']} v{panel['version']}, build "
                f"{panel['build']}, SHA-256 {panel['sha256']}."
            )
        return head + "Nenhum painel de referência populacional foi registrado."

    compiler.section_derived(
        titles[0], artifact="array-qc", locator="case_id", status=status,
        basis="identificador do caso e integridade da entrada", kind="qc_metric",
        transform=_control,
    )
    # The origins portrait: derived when a panel was supplied and the case projected onto it,
    # and otherwise refused with the artifact that would change the answer named.
    if projection is not None and projection["status"] == "INFERIDO":
        compiler.section_derived(
            titles[1], artifact="ancestry-projection", locator="affinity", status="INFERIDO",
            basis=(
                "posição do caso no espaço de componentes principais do painel, e distância aos "
                "centróides das populações de referência"
            ),
            kind="computed", transform=lambda _a: _origins_text(projection),
        )
    elif projection is not None:
        compiler.section_unavailable(
            titles[1],
            basis=str(projection.get("reason") or "projeção não estabelecida"),
        )
    else:
        compiler.section_unavailable(
            titles[1],
            basis=(
                "estimativa de composição de ancestralidade exige painel de referência com "
                "genótipos, que não foi fornecido a esta execução. Frequências alélicas por "
                "população não bastam: separam populações no agregado, não atribuem proporções "
                "a um indivíduo"
            ),
        )
    if projection is not None:
        compiler.section_derived(
            titles[2], artifact="ancestry-projection", locator="markers_used", status=status,
            basis="cobertura do painel pelo array e resolução de fita na projeção",
            kind="qc_metric",
            transform=lambda _n: _panel_text(metrics) + " " + _projection_quality(projection),
        )
    else:
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
        [f"completeness-matrix:{matrix.sha256}", f"array-qc:{qc.sha256}"]
        + (
            [f"ancestry-panel:{projection['panel']['sha256']}"]
            + list(projection["panel"].get("sources") or [])
            if projection is not None
            else []
        ),
        kind="case_control", basis="artefatos e painéis dos quais este relatório deriva",
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
        execution_manifest={
            "status": matrix.payload.get("operational_status", UNAVAILABLE),
            "COMPLETENESS_MATRIX_SHA256": matrix.sha256,
            "ARRAY_QC_SHA256": qc.sha256,
                "REFERENCE_PANEL": (
                f"{projection['panel']['id']} v{projection['panel']['version']} "
                f"sha256={projection['panel']['sha256']}"
                if projection is not None
                else UNAVAILABLE
            ),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", required=True)
    parser.add_argument("--qc", required=True)
    parser.add_argument("--panel", help="ancestry reference panel from scripts/build_ancestry_panel.py")
    parser.add_argument("--input", help="SNP-array file; required with --panel")
    parser.add_argument("--payload-out", required=True)
    args = parser.parse_args()

    if bool(args.panel) != bool(args.input):
        parser.error("--panel and --input must be supplied together")

    payload = build_payload(
        Path(args.matrix),
        Path(args.qc),
        panel_path=Path(args.panel) if args.panel else None,
        input_path=Path(args.input) if args.input else None,
    )
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
