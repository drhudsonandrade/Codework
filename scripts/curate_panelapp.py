#!/usr/bin/env python3
"""Curate gene-level evidence from PanelApp, the diagnostic panels of two health services.

ClinGen curates gene–disease validity and GenCC aggregates several such efforts, but neither
answers a question a reproductive or clinical report actually turns on: *is this gene on a
diagnostic panel a health service is willing to bill for?* PanelApp does, for Genomics
England's NHS Genomic Medicine Service and for PanelApp Australia, and it publishes the
answer with a traffic-light confidence per gene, a mode of inheritance, a penetrance field
and the publications behind each entry.

That makes it a third kind of evidence, kept separate from the other two rather than folded
in. ClinGen says the relationship is real. GenCC says several curators agree. PanelApp says a
health service tests for it in practice — a statement about clinical adoption, not about
biology, and useful precisely because it is different.

**Only green genes count as curated here.** PanelApp's own convention is that green means
diagnostic-grade, amber means insufficient evidence to report, red means the panel considered
and rejected it. Reading amber as evidence would take a gene the curators explicitly declined
to endorse and put it in a report; both are kept, and only green is marked established.

**Modes of inheritance are normalised, and the raw string is preserved.** PanelApp writes
`BIALLELIC, autosomal or pseudoautosomal` where ClinGen writes `AR`. Comparing them
unnormalised makes every gene the sources agree on look like a gene they disagree on.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.clinical_findings import (
    AUTOSOMAL_DOMINANT,
    AUTOSOMAL_RECESSIVE,
    MOI_UNKNOWN,
    X_LINKED,
)
from array_pipeline.targets import sha256_json

SOURCES = {
    "Genomics England PanelApp": "https://panelapp.genomicsengland.co.uk/api/v1",
    "PanelApp Australia": "https://panelapp-aus.org/api/v1",
}
PAGE_SIZE = 100
REQUEST_INTERVAL_SECONDS = 0.2

#: PanelApp's traffic light. Only green is diagnostic-grade by their own convention.
GREEN = 3
CONFIDENCE_LABELS = {3: "verde (grau diagnóstico)", 2: "âmbar (evidência insuficiente)", 1: "vermelho (rejeitado)"}

UNAVAILABLE = "NÃO DISPONÍVEL"


class PanelAppError(RuntimeError):
    pass


def _normalise_moi(label: Any) -> str:
    """PanelApp's prose mode of inheritance onto the abbreviations the rest of the system uses."""
    text = str(label or "").strip().lower()
    if not text:
        return MOI_UNKNOWN
    # Order matters and is not alphabetical. PanelApp's vocabulary nests: the X-linked terms
    # read `X-LINKED: hemizygous mutation in males, biallelic mutations in females`, and the
    # undetermined term reads `BOTH monoallelic and biallelic`. A naive `"biallelic" in text`
    # first would call both of those recessive — the X-linked gene silently, which is the
    # worst kind, because an X-linked male hemizygote is not a carrier.
    if "both monoallelic and biallelic" in text:
        return MOI_UNKNOWN
    if text.startswith("x-linked") or "x linked" in text or "x_linked" in text:
        return X_LINKED
    if "biallelic" in text:
        return AUTOSOMAL_RECESSIVE
    if "monoallelic" in text:
        # PanelApp distinguishes imprinted monoallelic forms; all are dominant in the sense
        # that matters here — one altered copy suffices — so they collapse to AD, and the
        # raw string is kept beside it for anyone who needs the distinction.
        return AUTOSOMAL_DOMINANT
    return MOI_UNKNOWN


def _get(url: str, *, attempts: int = 4) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "genoma-panelapp/1.0"}
    )
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise PanelAppError(f"PanelApp fetch failed for {url}: {last}")


def fetch_entries(base: str, *, max_pages: int | None = None) -> tuple[list[dict[str, Any]], int]:
    """Every gene-panel entry the instance publishes, paged.

    A partial sweep is not a smaller registry, it is a registry that silently omits whichever
    panels sort last — so the expected total is returned alongside, and the caller refuses a
    short read rather than shipping it.
    """
    url = f"{base}/genes/?page_size={PAGE_SIZE}"
    entries: list[dict[str, Any]] = []
    expected = 0
    pages = 0
    while url:
        payload = _get(url)
        expected = int(payload.get("count") or 0)
        for row in payload.get("results", []):
            gene = (row.get("gene_data") or {}).get("gene_symbol")
            if not gene:
                continue
            panel = row.get("panel") or {}
            entries.append(
                {
                    "gene": gene,
                    "confidence": int(row.get("confidence_level") or 0),
                    "mode_of_inheritance_reported": row.get("mode_of_inheritance") or "",
                    "mode_of_inheritance": _normalise_moi(row.get("mode_of_inheritance")),
                    "penetrance": row.get("penetrance") or UNAVAILABLE,
                    "phenotypes": [p for p in (row.get("phenotypes") or []) if p],
                    "publications": [p for p in (row.get("publications") or []) if p][:6],
                    "panel": panel.get("name"),
                    "panel_id": panel.get("id"),
                    "panel_version": panel.get("version"),
                }
            )
        pages += 1
        if max_pages is not None and pages >= max_pages:
            break
        url = payload.get("next")
        if url:
            time.sleep(REQUEST_INTERVAL_SECONDS)
    return entries, expected


def count_panels(entries: list[dict[str, Any]]) -> dict[str, int]:
    """How many distinct panels the sweep saw, and how many carry a green gene.

    Counted here from every entry rather than from the per-gene records, which keep only the
    first eight panels each. Counting distinct panels from those would silently report a
    lower bound as if it were the total.
    """
    all_panels = {e["panel_id"] for e in entries if e.get("panel_id") is not None}
    green_panels = {
        e["panel_id"] for e in entries if e["confidence"] == GREEN and e.get("panel_id") is not None
    }
    return {"panels": len(all_panels), "panels_with_a_green_gene": len(green_panels)}


def summarise(entries: list[dict[str, Any]], instance: str) -> dict[str, dict[str, Any]]:
    """Group one instance's entries by gene."""
    by_gene: dict[str, dict[str, Any]] = {}
    for entry in entries:
        record = by_gene.setdefault(
            entry["gene"],
            {
                "instance": instance,
                "green_panels": [],
                "other_panels": [],
                "modes_of_inheritance": set(),
                "phenotypes": set(),
                "publications": set(),
                "penetrance": set(),
            },
        )
        bucket = "green_panels" if entry["confidence"] == GREEN else "other_panels"
        record[bucket].append(
            {
                "panel": entry["panel"],
                "panel_id": entry["panel_id"],
                "panel_version": entry["panel_version"],
                "confidence": CONFIDENCE_LABELS.get(entry["confidence"], str(entry["confidence"])),
                "mode_of_inheritance_reported": entry["mode_of_inheritance_reported"],
            }
        )
        if entry["confidence"] == GREEN:
            # Only a green entry contributes a mode of inheritance. An amber gene's MOI is a
            # curator's provisional note on a gene they declined to endorse.
            if entry["mode_of_inheritance"] != MOI_UNKNOWN:
                record["modes_of_inheritance"].add(entry["mode_of_inheritance"])
            record["phenotypes"].update(entry["phenotypes"][:4])
            record["publications"].update(entry["publications"])
            if entry["penetrance"] != UNAVAILABLE:
                record["penetrance"].add(entry["penetrance"])

    return {
        gene: {
            "instance": data["instance"],
            "established": bool(data["green_panels"]),
            "green_panel_count": len(data["green_panels"]),
            "green_panels": sorted(data["green_panels"], key=lambda p: str(p["panel"]))[:8],
            "other_panel_count": len(data["other_panels"]),
            "modes_of_inheritance": sorted(data["modes_of_inheritance"]),
            "phenotypes": sorted(data["phenotypes"])[:8],
            "publications": sorted(data["publications"])[:8],
            "penetrance": sorted(data["penetrance"]),
        }
        for gene, data in by_gene.items()
    }


def build(*, max_pages: int | None = None) -> dict[str, Any]:
    per_instance: dict[str, dict[str, Any]] = {}
    totals: dict[str, Any] = {}
    for name, base in SOURCES.items():
        entries, expected = fetch_entries(base, max_pages=max_pages)
        if max_pages is None and expected and len(entries) < expected:
            raise PanelAppError(
                f"{name}: leitura curta, {len(entries)} entradas de {expected} anunciadas. "
                "Um varrimento parcial omite silenciosamente os painéis que ordenam por último."
            )
        per_instance[name] = summarise(entries, name)
        totals[name] = {
            "entries": len(entries),
            "expected": expected,
            **count_panels(entries),
            "genes": len(per_instance[name]),
            "green_genes": sum(1 for g in per_instance[name].values() if g["established"]),
        }
        print(f"  {name}: {len(entries):,} entradas, {totals[name]['green_genes']:,} genes verdes",
              flush=True)

    merged: dict[str, Any] = {}
    for name, genes in per_instance.items():
        for gene, record in genes.items():
            target = merged.setdefault(
                gene,
                {"instances": {}, "established": False, "modes_of_inheritance": set(),
                 "green_panel_count": 0, "phenotypes": set(), "publications": set()},
            )
            target["instances"][name] = record
            target["established"] = target["established"] or record["established"]
            target["green_panel_count"] += record["green_panel_count"]
            target["modes_of_inheritance"].update(record["modes_of_inheritance"])
            target["phenotypes"].update(record["phenotypes"])
            target["publications"].update(record["publications"])

    genes = {
        gene: {
            "status": "VERIFICADO" if data["established"] else UNAVAILABLE,
            "established": data["established"],
            "established_by": sorted(
                name for name, record in data["instances"].items() if record["established"]
            ),
            "green_panel_count": data["green_panel_count"],
            "modes_of_inheritance": sorted(data["modes_of_inheritance"]),
            # Two instances disagreeing on the mode for one gene is recorded, never resolved.
            "mode_of_inheritance_conflict": len(data["modes_of_inheritance"]) > 1,
            "phenotypes": sorted(data["phenotypes"])[:10],
            "publications": sorted(data["publications"])[:10],
            "instances": data["instances"],
        }
        for gene, data in sorted(merged.items())
    }

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "genoma-panelapp-curation-v1",
        "curated_at": generated,
        "sources": [
            f"{name} REST API, {base}/genes/, recuperado em {generated}"
            for name, base in SOURCES.items()
        ],
        "method": (
            "Todas as entradas gene-painel das duas instâncias, agrupadas por gene. Apenas "
            "entradas verdes contam como estabelecidas: verde é grau diagnóstico pela "
            "convenção do próprio PanelApp, âmbar é evidência insuficiente para reportar e "
            "vermelho é gene considerado e rejeitado. Modos de herança são normalizados para "
            "as abreviações do resto do sistema, com a string original preservada. Uma "
            "leitura curta é recusada em vez de publicada."
        ),
        "scope_note": (
            "PanelApp responde uma pergunta diferente de ClinGen e GenCC: não se a relação "
            "gene-doença é real, mas se um serviço de saúde a testa na prática. É afirmação "
            "sobre adoção clínica, não sobre biologia, e por isso é mantida separada."
        ),
        "confidence_convention": CONFIDENCE_LABELS,
        "totals": {
            "instances": totals,
            "genes": len(genes),
            "green_genes": sum(1 for g in genes.values() if g["established"]),
            "genes_in_both_instances": sum(1 for g in genes.values() if len(g["instances"]) > 1),
            "panels": sum(t["panels"] for t in totals.values()),
            "panels_with_a_green_gene": sum(t["panels_with_a_green_gene"] for t in totals.values()),
            "mode_conflicts": sum(1 for g in genes.values() if g["mode_of_inheritance_conflict"]),
        },
        "genes": genes,
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "docs/evidence/PANELAPP_CURATION.json.gz"))
    parser.add_argument("--max-pages", type=int, help="cap pages per instance (smoke tests only)")
    args = parser.parse_args()

    payload = build(max_pages=args.max_pages)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        out.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(out), "bytes": out.stat().st_size, **payload["totals"]},
                     ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
