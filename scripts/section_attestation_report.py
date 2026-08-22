#!/usr/bin/env python3
"""Show the 263 section judgements beside the live rule text, and what is still missing.

RULE_COVERAGE_GATE refuses a run until every section of the vigente ruleset has been judged.
The judgements live in `config/section_attestations_array.json`, keyed by section number and
pinned to each section's SHA-256 — deliberately without the section titles, because a stored
title is a copy that can drift from the text it names, and one of them carries a superseded
date the normative-identity guard refuses to see anywhere in the tree.

So the titles are read from the ruleset here, at review time, from the artifact the SHA-256
pins. That also makes this the honest place to answer three questions a curator actually has:

    which sections have no judgement yet?
    which judgements were written against text that has since changed?
    which entries are internally inconsistent?

The third is answered by `validate_curation`; the second is the difference between the curated
`rule_sha256` and the live section hash, and it is a *drift* rather than a mistake — the text
moved, so the judgement about it has to be made again.

    python3 scripts/section_attestation_report.py            # summary + gaps
    python3 scripts/section_attestation_report.py --all      # every section, one line each
    python3 scripts/section_attestation_report.py --section 26 --text
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "policy_engine"))

from reporting.section_attestations import (  # noqa: E402
    CurationError,
    coverage_report,
    load_curation,
    validate_curation,
)


def live_sections() -> list[Any]:
    """Read the sections from the vigente ruleset, then delete the plaintext copy.

    The ruleset is only ever materialised for the duration of a read; an active plaintext
    copy must not survive in the working tree.
    """
    from genoma_policy.ruleset import load_ruleset

    directory = Path(tempfile.mkdtemp())
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/materialize_ruleset.py"),
         "--output-dir", str(directory)],
        check=True, capture_output=True, text=True,
    )
    canonical = next(directory.glob("REGRAS_PROJETO_GENOMA_VIGENTE_*.txt"))
    try:
        return list(load_ruleset(canonical).sections)
    finally:
        canonical.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--all", action="store_true", help="one line per section")
    parser.add_argument("--section", type=int, help="show one section in full")
    parser.add_argument("--text", action="store_true", help="with --section, print the rule text")
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args()

    try:
        curation = load_curation()
    except CurationError as exc:
        print(f"CURADORIA NÃO DISPONÍVEL: {exc}", file=sys.stderr)
        return 2

    sections = live_sections()
    entries = curation["sections"]
    drifted = [
        s.number for s in sections
        if str(s.number) in entries and entries[str(s.number)]["rule_sha256"] != s.sha256
    ]
    missing = [s.number for s in sections if str(s.number) not in entries]
    problems = validate_curation(curation)
    summary = {
        **coverage_report(curation),
        "drifted_sections": drifted,
        "live_section_count": len(sections),
    }

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if not (missing or drifted or problems) else 1

    if args.section is not None:
        section = next((s for s in sections if s.number == args.section), None)
        if section is None:
            print(f"seção {args.section} não existe no ruleset vigente", file=sys.stderr)
            return 2
        entry = entries.get(str(args.section))
        print(f"{section.number}. {section.title}")
        print(f"  rule_id      {section.rule_id}")
        print(f"  sha256       {section.sha256}")
        if entry is None:
            print("  JUÍZO        PENDENTE — nenhuma curadoria para esta seção")
        else:
            pinned = "ok" if entry["rule_sha256"] == section.sha256 else "DIVERGENTE"
            print(f"  fixado a     {entry['rule_sha256']} ({pinned})")
            print(f"  aplicável    {entry['applicability']} / {entry['decision']} / {entry['status']}")
            print(f"  evidência    {entry['evidence_refs'] or '—'}")
            print(f"  justificativa\n    {entry['justification']}")
        if args.text:
            print("\n--- texto da seção ---")
            print(section.body)
        return 0

    print(f"ruleset vigente: {summary['total_rules']} seções")
    print(f"  curadas:    {summary['curated']}")
    print(f"  pendentes:  {summary['pending']}")
    print(f"  divergentes:{len(drifted)}")
    for name, count in sorted(summary["by_applicability"].items()):
        print(f"  {name:16s} {count}")

    if args.all:
        print()
        for section in sections:
            entry = entries.get(str(section.number))
            if entry is None:
                mark = "PENDENTE      "
            elif entry["rule_sha256"] != section.sha256:
                mark = "DIVERGENTE    "
            else:
                mark = f"{entry['applicability']:14s}"
            print(f"  {section.number:3d} {mark} {section.title[:70]}")

    if missing:
        print(f"\nsem juízo ({len(missing)}): {missing}")
    if drifted:
        print(
            f"\ntexto mudou desde a curadoria ({len(drifted)}): {drifted}\n"
            "  um juízo sobre outras palavras não é um juízo sobre estas; recurar cada uma."
        )
    if problems:
        print(f"\nproblemas na curadoria ({len(problems)}):")
        for problem in problems[:20]:
            print(f"  - {problem}")

    if missing or drifted or problems:
        print("\nRULE_COVERAGE_GATE recusará esta execução, e está certo em recusar.")
        return 1
    print("\ncuradoria completa e fixada ao texto vigente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
