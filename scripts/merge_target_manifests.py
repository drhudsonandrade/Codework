#!/usr/bin/env python3
"""Union several target manifests into the one a case run interrogates.

Four registries now exist — the hand-curated twenty-nine, the CPIC defining positions, the
ClinVar P/LP expansion and the GWAS trait loci — and a case should be interrogated against
all of them in one pass rather than four, so that report 09's coverage figure describes the
whole panel instead of whichever slice happened to be passed in.

The only hard part is a locus that appears in more than one registry, and the rule is the one
this project applies everywhere else: **a conflict is never arbitrated.**

* Same rsid, same assessed allele → merged, provenance from both recorded.
* Same rsid, different assessed allele → merged with **no** assessed allele at all, the
  disagreement listed. The locus can then only reach OBSERVADO, never NÃO DETECTADO, because
  there is no single allele it was tested against.
* Same rsid, one registry declares an allele and another declares none → the declared one is
  kept, since silence is not disagreement.

Scope follows the same ordering as the sources: a locus that is clinical in one registry and
a curiosity in another is clinical. Downgrading it would move a pathogenic variant into the
trait atlas.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from array_pipeline.targets import load_target_manifest, sha256_json

#: Strongest first. A locus present in two registries keeps the stronger scope.
SCOPE_RANK = ("CLINICO", "PREDISPOSICAO", "PESQUISA", "CURIOSIDADE")

#: Fields that describe which allele the locus is scored against. They are decided only by
#: the explicit conflict logic, never by the generic field-carry-over.
ASSESSED_ALLELE_FIELDS = frozenset(
    {
        "assessed_allele",
        "assessed_allele_source",
        "assessed_allele_status",
        "assessed_allele_reason",
        "assessed_allele_conflict",
    }
)


def merge(paths: list[Path]) -> dict[str, Any]:
    manifests = [(path, load_target_manifest(path)) for path in paths]

    merged: dict[str, dict[str, Any]] = {}
    origin: dict[str, list[str]] = {}
    conflicts: list[dict[str, Any]] = []

    for path, manifest in manifests:
        registry = str(manifest.get("id") or path.name)
        for target in manifest["targets"]:
            rsid = str(target["rsid"]).lower()
            incoming = dict(target)
            incoming["rsid"] = rsid
            if rsid not in merged:
                merged[rsid] = incoming
                origin[rsid] = [registry]
                continue

            existing = merged[rsid]
            origin[rsid].append(registry)

            old = str(existing.get("assessed_allele") or "").strip().upper()
            new = str(incoming.get("assessed_allele") or "").strip().upper()
            if old and new and old != new:
                conflicts.append(
                    {
                        "rsid": rsid,
                        "registries": list(origin[rsid]),
                        "assessed_alleles": sorted({old, new}),
                    }
                )
                existing.pop("assessed_allele", None)
                existing.pop("assessed_allele_source", None)
                existing.pop("assessed_allele_status", None)
                existing["assessed_allele_conflict"] = sorted({old, new})
                existing["assessed_allele_reason"] = (
                    f"registros divergem sobre o alelo avaliado deste locus ({old} vs {new}, "
                    f"em {', '.join(origin[rsid])}); escolher um seria arbitrar um conflito, e "
                    "o locus não admite NÃO DETECTADO"
                )
            elif new and not old and "assessed_allele_conflict" not in existing:
                # Silence is not disagreement: a registry that declares nothing does not
                # override one that does.
                for key in (
                    "assessed_allele",
                    "assessed_allele_source",
                    "assessed_allele_status",
                    "assessed_allele_reason",
                ):
                    if incoming.get(key) is not None:
                        existing[key] = incoming[key]

            existing_rank = SCOPE_RANK.index(str(existing.get("scope", "CURIOSIDADE")))
            incoming_rank = SCOPE_RANK.index(str(incoming.get("scope", "CURIOSIDADE")))
            if incoming_rank < existing_rank:
                existing["scope"] = incoming["scope"]
            # Keep whichever fields the other registry supplied and this one lacks, so a
            # coordinate or a citation is never lost by arriving second — but never through
            # this loop for the assessed-allele fields. Removing the allele on a conflict and
            # then copying "any key the target lacks" put it straight back, which silently
            # undid the refusal three lines above and shipped an arbitrated allele at
            # rs3918290. Those fields are settled by the explicit logic or not at all.
            for key, value in incoming.items():
                if key in ASSESSED_ALLELE_FIELDS:
                    continue
                if key not in existing and value not in (None, "", [], {}):
                    existing[key] = value

    for rsid, registries in origin.items():
        merged[rsid]["source_registries"] = sorted(set(registries))

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "schema": "genoma-partial-genome-targets-v1",
        "id": "GENOMA-MERGED-PANEL",
        "version": generated[:10].replace("-", "") + ".1",
        "description": (
            "União dos registros de alvos interrogados numa execução de caso. Colisão de rsid "
            "com alelos avaliados divergentes não é arbitrada: o alelo é removido e a "
            "divergência registrada. Reproduzir com scripts/merge_target_manifests.py."
        ),
        "generated_at": generated,
        "merged_from": [
            {
                "id": manifest.get("id"),
                "version": manifest.get("version"),
                "path": str(path),
                "targets": len(manifest["targets"]),
                "sha256": manifest.get("sha256"),
            }
            for path, manifest in manifests
        ],
        "assessed_allele_conflicts": conflicts,
        "totals": {
            "targets": len(merged),
            "with_assessed_allele": sum(1 for t in merged.values() if t.get("assessed_allele")),
            "assessed_allele_conflicts": len(conflicts),
            "in_more_than_one_registry": sum(1 for v in origin.values() if len(set(v)) > 1),
            "by_scope": {
                scope: sum(1 for t in merged.values() if t.get("scope") == scope)
                for scope in SCOPE_RANK
            },
        },
        "targets": [merged[rsid] for rsid in sorted(merged, key=lambda r: int(r[2:]) if r[2:].isdigit() else 0)],
    }
    payload["sha256"] = sha256_json({k: v for k, v in payload.items() if k != "sha256"})
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="+", help="target manifests to union")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = merge([Path(p) for p in args.manifests])
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        out.write_text(text, encoding="utf-8")
    load_target_manifest(out)

    print(json.dumps({"output": str(out), "bytes": out.stat().st_size, **payload["totals"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
