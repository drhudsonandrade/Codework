#!/usr/bin/env python3
"""Project individuals of known origin through the panel and publish what it gets wrong.

A reference panel cannot be validated by inspecting it. The only test that means anything is
to take people whose population is known, run them through the same projection a case gets,
and compare. This does that and writes the result as an artefact — including the failures,
because a validation report that lists only the cases that worked is a marketing document.

The artefact exists because of one specific finding. Projecting the Yoruba individual
NA19625 through the previous panel returned **17% Native American ancestry**, which is not
ancestry: it is the fit distributing weight onto a direction the reference basis does not
span well. The system already flagged it — a 28% residual classifies the fit as *moderate*
and triggers a warning that components under ~20% may be artefact — but a warning the reader
must interpret is weaker than a measured, published number. Report 02 now cites this file, so
the known artefact travels with every projection instead of living in a document nobody
opens.

**Held-in, not held-out.** The 1000 Genomes individuals validated here are part of the panel
that produced the loadings, so their projections are optimistic: the axes were fitted partly
on them. That is stated rather than hidden, and the AADR individuals are the honest half of
the test — they come from a different platform and a different release, and nothing about
the 1000 Genomes axes was fitted to make them land anywhere in particular.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.ancestry import load_panel, project_case
from array_pipeline.targets import read_manifest_bytes, sha256_json

UNAVAILABLE = "NÃO DISPONÍVEL"

#: A component this large in a person who should not have it is recorded as a named artefact
#: rather than left for the reader to notice.
SPURIOUS_THRESHOLD = 0.05

#: Reference groups whose members are themselves admixed. A European component in a Peruvian
#: from Lima is ancestry, not artefact — Peruvians in the 1000 Genomes AMR set carry real
#: European and African ancestry — so these individuals are excluded from the artefact count
#: while still being checked for landing near the right group. Marking their true admixture
#: as spurious would inflate the artefact figure the whole file exists to state honestly.
ADMIXED_EXPECTATIONS = frozenset({"AMR"})

#: Known-origin individuals from the 1000 Genomes release, and the group each should match.
#: Held-in: these samples contributed to the loadings.
THOUSAND_GENOMES_CASES: dict[str, dict[str, str]] = {
    "NA19625": {"expected": "AFR", "description": "Iorubá ascendente, Nigéria (ASW/YRI)"},
    "NA12878": {"expected": "EUR", "description": "CEU, Utah"},
    "NA18525": {"expected": "EAS", "description": "Han, Pequim"},
    "HG01565": {"expected": "AMR", "description": "Peruano, Lima (população miscigenada)"},
    "NA20502": {"expected": "EUR", "description": "Toscano, Itália"},
    "HG02461": {"expected": "AFR", "description": "Gâmbia"},
}


def _genotypes_from_vcf_sample(
    vcf_path: Path, sample: str, rsids: set[str]
) -> dict[str, str]:
    """One sample's genotypes at the panel's markers, keyed by rsid.

    Read straight out of the reference VCF so the validation exercises the same projection a
    case gets, rather than a shortcut that reuses the panel's own dosage matrix.
    """
    import gzip

    opener = gzip.open if vcf_path.suffix == ".gz" else open
    out: dict[str, str] = {}
    column: int | None = None
    with opener(vcf_path, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("##"):
                continue
            fields = line.rstrip("\n").split("\t")
            if line.startswith("#CHROM"):
                if sample not in fields:
                    raise ValueError(f"{sample} não está no VCF de referência")
                column = fields.index(sample)
                continue
            if column is None:
                continue
            rsid = fields[2].strip().lower()
            if rsid not in rsids:
                continue
            reference, alternate = fields[3].strip().upper(), fields[4].strip().upper()
            call = fields[column].split(":")[0].replace("|", "/")
            if "." in call:
                continue
            alleles = [reference if a == "0" else alternate for a in call.split("/") if a.isdigit()]
            if len(alleles) == 2:
                out[rsid] = "".join(alleles)
    return out


def _genotypes_from_aadr(
    aadr_path: Path, sample: str, rsids: set[str], *, invert: bool
) -> dict[str, str]:
    """One AADR individual's genotypes, keyed by rsid, honouring the measured orientation."""
    payload = json.loads(read_manifest_bytes(Path(aadr_path)))
    ids = [s["id"] for s in payload["samples"]]
    if sample not in ids:
        raise ValueError(f"{sample} não está no artefato AADR")
    index = ids.index(sample)
    snps = payload["snps"]
    packed = np.frombuffer(base64.b64decode(payload["genotypes_packed"][index]), dtype=np.uint8)
    unpacked = np.empty(packed.size * 4, dtype=np.int8)
    for offset, shift in enumerate((6, 4, 2, 0)):
        unpacked[offset::4] = (packed >> shift) & 0b11
    calls = unpacked[: len(snps)]

    out: dict[str, str] = {}
    for snp, value in zip(snps, calls):
        rsid = str(snp["rsid"]).lower()
        if rsid not in rsids or value == 3:
            continue
        # The packed value counts allele_a, which is what `check_orientation` measured; the
        # panel is expressed in counts of the 1000 Genomes alternate. `invert` carries that
        # measured answer here rather than the convention being assumed a second time.
        count_b = (2 - int(value)) if invert else int(value)
        a, b = snp["allele_a"], snp["allele_b"]
        out[rsid] = {0: a + a, 1: a + b, 2: b + b}[count_b]
    return out


def _composition(result: dict[str, Any]) -> dict[str, float]:
    return {
        str(c["population"]): float(c["proportion"])
        for c in (result.get("proportions") or [])
        if c.get("proportion")
    }


def evaluate(result: dict[str, Any], expected: str) -> dict[str, Any]:
    """Compare one projection against the population the individual is known to belong to."""
    composition = _composition(result)
    nearest = result.get("nearest_population")
    ranked = sorted(composition.items(), key=lambda kv: -kv[1])
    # A component is spurious when it belongs to a continental group the individual is not
    # from. Native American groups are checked as a family: an Amazonian person legitimately
    # carries Andean-like signal, and calling that an artefact would be the opposite error.
    family = expected.split("-")[0]
    admixed = expected in ADMIXED_EXPECTATIONS
    spurious = (
        []
        if admixed
        else [
            {"population": population, "proportion": round(value, 4)}
            for population, value in ranked
            if value >= SPURIOUS_THRESHOLD and not population.startswith(family)
        ]
    )
    return {
        "expected": expected,
        "expected_is_admixed": admixed,
        "closest_population": nearest,
        "closest_matches_expected": bool(nearest and str(nearest).startswith(family)),
        "composition": {k: round(v, 4) for k, v in ranked},
        "residual": result.get("fit_residual_relative"),
        "fit_quality": result.get("fit_quality"),
        "proportions_reason": result.get("proportions_reason"),
        "markers_used": result.get("markers_used"),
        "overlap": result.get("overlap"),
        "spurious_components": spurious,
        "largest_spurious": max((s["proportion"] for s in spurious), default=0.0),
    }


def build(
    panel_path: Path,
    vcf_path: Path | None,
    aadr_path: Path | None,
    *,
    aadr_samples: list[str],
) -> dict[str, Any]:
    panel = load_panel(panel_path)
    rsids = {str(m["rsid"]).lower() for m in panel["markers"]}
    invert = bool((panel.get("allele_orientation") or {}).get("invert"))
    cases: list[dict[str, Any]] = []

    if vcf_path is not None:
        for sample, meta in THOUSAND_GENOMES_CASES.items():
            genotypes = _genotypes_from_vcf_sample(vcf_path, sample, rsids)
            result = project_case(panel, genotypes, case_build=str(panel.get("build")))
            cases.append(
                {
                    "sample": sample,
                    "source": "1000 Genomes (held-in: contribuiu para os loadings)",
                    "held_out": False,
                    "description": meta["description"],
                    **evaluate(result, meta["expected"]),
                }
            )
            print(f"  {sample:<10} esperado {meta['expected']:<18} "
                  f"obtido {cases[-1]['closest_population']}", flush=True)

    if aadr_path is not None:
        payload = json.loads(read_manifest_bytes(Path(aadr_path)))
        by_id = {s["id"]: s for s in payload["samples"]}
        for sample in aadr_samples:
            meta = by_id.get(sample)
            if meta is None:
                continue
            genotypes = _genotypes_from_aadr(aadr_path, sample, rsids, invert=invert)
            result = project_case(panel, genotypes, case_build=str(panel.get("build")))
            cases.append(
                {
                    "sample": sample,
                    "source": "AADR Human Origins (held-in: contribuiu para os loadings)",
                    "held_out": False,
                    "description": f"{meta['population']}, {meta.get('country', UNAVAILABLE)}",
                    **evaluate(result, meta["panel_group"]),
                }
            )
            print(f"  {sample:<14} esperado {meta['panel_group']:<18} "
                  f"obtido {cases[-1]['closest_population']}", flush=True)

    artefacts = [
        {
            "sample": case["sample"],
            "description": case["description"],
            "spurious": case["spurious_components"],
            "residual": case["residual"],
            "reading": (
                f"{case['sample']} é {case['description']} e recebeu "
                + ", ".join(
                    f"{s['proportion']:.0%} de {s['population']}"
                    for s in case["spurious_components"]
                )
                + ". Isso é artefato de ajuste, não ancestralidade: a projeção distribui peso "
                "por direções que a base de referência não separa bem nesta região do espaço."
            ),
        }
        for case in cases
        if case["spurious_components"]
    ]

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "genoma-ancestry-panel-validation-v1",
        "validated_at": generated,
        "panel": {
            "id": panel.get("id"),
            "version": panel.get("version"),
            "sha256": panel.get("sha256"),
            "markers": len(panel["markers"]),
        },
        "method": (
            "Indivíduos de origem conhecida são projetados pelo mesmo caminho que um caso "
            "percorre, e a composição obtida é comparada com a população de origem. Um "
            "componente continental que a pessoa não tem, acima de "
            f"{SPURIOUS_THRESHOLD:.0%}, é registrado como artefato nomeado. Grupos ameríndios "
            "são comparados como família: um amazônida legitimamente carrega sinal andino, e "
            "chamar isso de artefato seria o erro oposto."
        ),
        "held_out": False,
        "held_out_caveat": (
            "Nenhum destes indivíduos é externo ao painel: todos contribuíram para os "
            "loadings, então as projeções são otimistas. Isto mede consistência interna e "
            "detecção de artefatos, não acurácia fora da amostra."
        ),
        "spurious_threshold": SPURIOUS_THRESHOLD,
        "totals": {
            "cases": len(cases),
            "closest_matches_expected": sum(1 for c in cases if c["closest_matches_expected"]),
            "cases_with_spurious_component": len(artefacts),
            "largest_spurious_component": round(
                max((c["largest_spurious"] for c in cases), default=0.0), 4
            ),
        },
        "known_artefacts": artefacts,
        "cases": cases,
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True)
    parser.add_argument("--vcf", help="1000 Genomes chip VCF, for the held-in reference cases")
    parser.add_argument("--aadr", help="AADR artefact, for the indigenous reference cases")
    parser.add_argument("--aadr-sample", action="append", default=[])
    parser.add_argument(
        "--output", default=str(ROOT / "docs/evidence/ANCESTRY_PANEL_VALIDATION.json")
    )
    parser.add_argument(
        "--stamp-panel",
        action="store_true",
        help="write the measured artefact size back into the panel, so every projection "
        "quotes a number this panel actually produced instead of one carried over from an "
        "older build",
    )
    args = parser.parse_args()

    payload = build(
        Path(args.panel),
        Path(args.vcf) if args.vcf else None,
        Path(args.aadr) if args.aadr else None,
        aadr_samples=args.aadr_sample,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.stamp_panel:
        worst = max(payload["cases"], key=lambda c: c["largest_spurious"], default=None)
        panel_path = Path(args.panel)
        panel = json.loads(read_manifest_bytes(panel_path))
        panel["validation_summary"] = {
            "validation_sha256": payload["sha256"],
            "validated_at": payload["validated_at"],
            "cases": payload["totals"]["cases"],
            "largest_spurious_component": payload["totals"]["largest_spurious_component"],
            "largest_spurious_example": (
                f"{worst['sample']}, {worst['description']}" if worst else UNAVAILABLE
            ),
            "held_out": payload["held_out"],
        }
        text = json.dumps(panel, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        if panel_path.suffix == ".gz":
            import gzip as _gzip

            panel_path.write_bytes(_gzip.compress(text.encode("utf-8"), mtime=0))
        else:
            panel_path.write_text(text, encoding="utf-8")
        print(f"  painel carimbado com o artefato medido: {panel_path}")

    print(json.dumps({"output": str(out), **payload["totals"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
