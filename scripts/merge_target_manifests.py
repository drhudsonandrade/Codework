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


def _verified_digest(path: Path, manifest: dict[str, Any]) -> str:
    """The manifest's digest, computed from its content and refused if it disagrees.

    `merge_basis` and `merged_from` published `manifest.get("sha256")` as read, and the
    merged panel's own `version` is derived from `merge_basis`. So a manifest carrying
    someone else's digest — or a typo — produced a panel whose provenance named content that
    is not what was merged, and the version string encoded that wrong name. A digest is a
    claim about bytes; it is checked against them or it is not published.

    Computed over the manifest without its own `sha256` key, because a digest cannot cover
    the field that holds it.
    """
    computed = sha256_json({key: value for key, value in manifest.items() if key != "sha256"})
    declared = manifest.get("sha256")
    if declared is not None and declared != computed:
        raise ValueError(
            f"{path}: declared sha256 {declared!r} does not match the content digest "
            f"{computed!r}; the merged panel cites this value as the provenance of what it "
            "merged, and publishing it unchecked would name content that was never read"
        )
    return computed


def _scope_rank(target: dict, rsid: str) -> int:
    """Rank of this target's scope, refusing a value the ranking does not know.

    Ranking by `.index` is right — the order is the point — but an unlisted or null scope
    reached it and raised a bare ValueError naming a tuple. Defaulting instead would be
    worse: the fallback was CURIOSIDADE, the weakest rank, so an unrecognised scope would
    have quietly demoted a locus rather than stopped the merge.
    """
    scope = target.get("scope")
    if scope in SCOPE_RANK:
        return SCOPE_RANK.index(scope)
    raise ValueError(
        f"{rsid}: scope {scope!r} is not one of {list(SCOPE_RANK)}; the merge ranks loci by "
        "scope and cannot place a value it does not know"
    )

#: Fields that describe which allele the locus is scored against. They are decided only by
#: the explicit conflict logic, never by the generic field-carry-over.
ASSESSED_ALLELE_FIELDS = frozenset(
    {
        "assessed_allele",
        "assessed_allele_source",
        "assessed_allele_status",
        "assessed_allele_reason",
        "assessed_allele_conflict",
        "assessed_allele_evidence",
        "assessed_allele_references",
    }
)

IDENTITY_FIELDS = ("coordinates", "grch38", "reference_allele")


def merge(paths: list[Path]) -> dict[str, Any]:
    """Combine target manifests, refusing rather than arbitrating on the scientific claims.

    The guarantee is specific, so state it specifically. Where two registries disagree about
    the **assessed allele** or about **locus identity** (`ASSESSED_ALLELE_FIELDS` and
    `IDENTITY_FIELDS`), the merge records the conflict and *removes* the contested value
    rather than picking one: choosing would manufacture a consensus no source states.

    Everything else is arbitrated, deliberately and by a stated rule:

    * `scope` takes the strongest of the two by `SCOPE_RANK`, so a locus that one registry
      calls clinical is not demoted by another that calls it a curiosity.
    * Any other field absent or empty on the existing entry takes the incoming value, so a
      coordinate or a citation is not lost by arriving second. The assessed-allele and
      identity namespaces are excluded from that carry-over precisely because it would
      undo the refusal above.

    Refusals are made durable: `identity_conflict` sits outside the `assessed_allele_`
    namespace so that clearing that namespace cannot erase the record of why it was cleared.
    That durability is not a property of this text — it is asserted by
    `tests/test_target_expansion.py::test_a_third_registry_cannot_restore_an_allele_refused_for_reference_conflict`,
    which is the case that used to ship an arbitrated allele at rs3918290, and by
    `::test_silence_is_not_disagreement` for the case that must *not* be treated as a
    conflict. Run them with::

        python3 -m unittest discover -s tests -p test_target_expansion.py
    """
    manifests = [(path, load_target_manifest(path)) for path in paths]
    for path, manifest in manifests:
        _verified_digest(path, manifest)

    merged: dict[str, dict[str, Any]] = {}
    origin: dict[str, list[str]] = {}
    conflicts: list[dict[str, Any]] = []
    identity_conflicts: list[dict[str, Any]] = []
    conflicted_identity: dict[str, set[str]] = {}

    for path, manifest in manifests:
        registry = str(manifest.get("id") or path.name)
        for target in manifest["targets"]:
            rsid = str(target["rsid"]).lower()
            incoming = dict(target)
            incoming["rsid"] = rsid
            # `load_target_manifest` validates `scope.upper()` against ALLOWED_SCOPES and
            # returns the entry unchanged, so `"clinico"` passed validation and then reached
            # `_scope_rank`, which compares against the canonical uppercase tuple and refused
            # it — on a manifest the loader had just accepted. `targets_from_manifest`
            # already normalises the same way; the merge did not. rsid is normalised on the
            # line above for exactly this reason.
            if incoming.get("scope") is not None:
                incoming["scope"] = str(incoming["scope"]).upper()
            if rsid not in merged:
                merged[rsid] = incoming
                origin[rsid] = [registry]
                continue

            existing = merged[rsid]
            origin[rsid].append(registry)

            old = str(existing.get("assessed_allele") or "").strip().upper()
            new = str(incoming.get("assessed_allele") or "").strip().upper()
            recorded = {
                str(value).strip().upper()
                for value in (existing.get("assessed_allele_conflict") or [])
                if str(value).strip()
            }
            if new and recorded:
                recorded.add(new)
                values = sorted(recorded)
                existing["assessed_allele_conflict"] = values
                existing["assessed_allele_reason"] = (
                    f"registros divergem sobre o alelo avaliado deste locus "
                    f"({', '.join(values)}, em {', '.join(origin[rsid])}); escolher um seria "
                    "arbitrar um conflito, e o locus não admite NÃO DETECTADO"
                )
                for conflict in conflicts:
                    if conflict["rsid"] == rsid:
                        conflict["assessed_alleles"] = values
                        conflict["registries"] = list(origin[rsid])
                        break
            elif old and new and old != new:
                conflicts.append(
                    {
                        "rsid": rsid,
                        "registries": list(origin[rsid]),
                        "assessed_alleles": sorted({old, new}),
                    }
                )
                for key in list(existing):
                    if key == "assessed_allele" or key.startswith("assessed_allele_"):
                        existing.pop(key, None)
                existing["assessed_allele_conflict"] = sorted({old, new})
                existing["assessed_allele_reason"] = (
                    f"registros divergem sobre o alelo avaliado deste locus ({old} vs {new}, "
                    f"em {', '.join(origin[rsid])}); escolher um seria arbitrar um conflito, e "
                    "o locus não admite NÃO DETECTADO"
                )
            elif (
                new
                and not old
                and "assessed_allele_conflict" not in existing
                and not existing.get("identity_conflict")
            ):
                # Silence is not disagreement: a registry that declares nothing does not
                # override one that does.
                #
                # The `identity_conflict` guard closes a way back in. A reference_allele
                # conflict below clears every `assessed_allele*` key — the sentinel
                # `assessed_allele_conflict` among them, since it lives in that namespace —
                # so by the time a third registry arrived this branch saw a locus with no
                # allele and no conflict marker and copied its allele straight in. The locus
                # was refused for disagreeing about which base is the reference, and it came
                # out of the merge with an assessed allele anyway. `identity_conflict` is
                # deliberately outside the `assessed_allele_` prefix so that clearing cannot
                # erase it.
                # Every field in the namespace, not a hand-written four. The generic
                # carry-over below deliberately skips this whole namespace, so a key omitted
                # here has no other way in: `assessed_allele_evidence` and
                # `assessed_allele_references` were left out, and the merged panel scored the
                # locus against an allele while naming nothing that supported it. An allele
                # without its provenance is a claim this project does not make.
                #
                # `assessed_allele_conflict` is excluded on purpose: it is the sentinel this
                # branch's own guard reads, and copying a conflict marker from a registry
                # that is not in conflict here would invent one.
                for key in sorted(ASSESSED_ALLELE_FIELDS - {"assessed_allele_conflict"}):
                    if incoming.get(key) is not None:
                        existing[key] = incoming[key]

            for field in IDENTITY_FIELDS:
                old_value = existing.get(field)
                new_value = incoming.get(field)
                field_conflicts = conflicted_identity.setdefault(rsid, set())
                if field in field_conflicts:
                    continue
                if old_value not in (None, "", [], {}) and new_value not in (None, "", [], {}):
                    if old_value != new_value:
                        identity_conflicts.append(
                            {
                                "rsid": rsid,
                                "field": field,
                                "registries": list(origin[rsid]),
                                "values": [old_value, new_value],
                            }
                        )
                        field_conflicts.add(field)
                        existing.pop(field, None)
                        # Outside the `assessed_allele_` namespace on purpose: the clearing
                        # loop just below removes everything in that namespace, so a sentinel
                        # kept inside it would be erased by the very refusal it records, and
                        # a later registry would find the locus indistinguishable from one
                        # that had simply never been assessed.
                        existing["identity_conflict"] = sorted(field_conflicts)
                        if field == "reference_allele":
                            for key in list(existing):
                                if key == "assessed_allele" or key.startswith(
                                    "assessed_allele_"
                                ):
                                    existing.pop(key, None)
                            existing["assessed_allele_reason"] = (
                                "alelo avaliado removido porque os registros divergem sobre "
                                "o alelo de referência"
                            )
                elif old_value in (None, "", [], {}) and new_value not in (None, "", [], {}):
                    existing[field] = new_value

            # `.index` on an unlisted scope raised a bare ValueError naming a tuple, and the
            # `.get` default only covered a *missing* key — a scope present but null, or a
            # value this ranking has never seen, still reached it. Refused with the gene and
            # the value named, because silently defaulting an unknown scope to the lowest
            # rank would demote a clinical target to a curiosity.
            existing_rank = _scope_rank(existing, rsid)
            incoming_rank = _scope_rank(incoming, rsid)
            if incoming_rank < existing_rank:
                existing["scope"] = incoming["scope"]
            # Keep whichever fields the other registry supplied and this one lacks, so a
            # coordinate or a citation is never lost by arriving second — but never through
            # this loop for the assessed-allele fields. Removing the allele on a conflict and
            # then copying "any key the target lacks" put it straight back, which silently
            # undid the refusal three lines above and shipped an arbitrated allele at
            # rs3918290. Those fields are settled by the explicit logic or not at all.
            for key, value in incoming.items():
                if (
                    key in ASSESSED_ALLELE_FIELDS
                    or key.startswith("assessed_allele_")
                    or key in IDENTITY_FIELDS
                ):
                    continue
                if key not in existing and value not in (None, "", [], {}):
                    existing[key] = value

    for rsid, registries in origin.items():
        merged[rsid]["source_registries"] = sorted(set(registries))

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    merge_basis = [
        {
            "path": str(path),
            "id": manifest.get("id"),
            "version": manifest.get("version"),
            # The verified digest, never the declared one. `_verified_digest` has already
            # refused any manifest whose declaration disagrees with its bytes, so the two are
            # equal here by construction — computing it is what makes that true rather than
            # assumed, and a manifest that declared nothing still gets a real digest.
            "sha256": _verified_digest(path, manifest),
        }
        for path, manifest in manifests
    ]
    payload = {
        "schema": "genoma-partial-genome-targets-v1",
        "id": "GENOMA-MERGED-PANEL",
        "version": (
            generated[:10].replace("-", "") + "." + sha256_json(merge_basis)[:12]
        ),
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
                "sha256": _verified_digest(path, manifest),
            }
            for path, manifest in manifests
        ],
        "assessed_allele_conflicts": conflicts,
        "identity_conflicts": identity_conflicts,
        "totals": {
            "targets": len(merged),
            "with_assessed_allele": sum(1 for t in merged.values() if t.get("assessed_allele")),
            "assessed_allele_conflicts": len(conflicts),
            "identity_conflicts": len(identity_conflicts),
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
    """Merge the given target manifests into one panel and write it out."""
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
