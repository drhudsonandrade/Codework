from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import PolicyEngine
from .ledger import append_event, verify_ledger
from .paths import AssetResolutionError, resolve_manifest_path, resolve_ruleset_path
from .ruleset import compiled_catalog, enforce_unique_active_ruleset, load_ruleset, verify_external_manifest
from .scaffold import scaffold_manifest
from .smoke import run_smoke


def _write_json(value: object, output: str | None) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output:
        Path(output).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="genoma-policy", description="Executable policy engine for GENOMA ruleset v3.4")
    p.add_argument("--ruleset")
    p.add_argument("--sha-manifest")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("ruleset-check")
    c = sub.add_parser("catalog"); c.add_argument("--output")
    s = sub.add_parser("scaffold"); s.add_argument("--case-id", default="CASE-ID"); s.add_argument("--output", required=True)
    e = sub.add_parser("evaluate"); e.add_argument("manifest"); e.add_argument("--output")
    sm = sub.add_parser("smoke"); sm.add_argument("--output")
    la = sub.add_parser("ledger-append"); la.add_argument("ledger"); la.add_argument("event_type"); la.add_argument("payload")
    lv = sub.add_parser("ledger-verify"); lv.add_argument("ledger")
    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8787)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ruleset_path = Path(args.ruleset) if args.ruleset else resolve_ruleset_path(Path.cwd())
        sha_manifest = Path(args.sha_manifest) if args.sha_manifest else resolve_manifest_path(ruleset_path, Path.cwd())
    except AssetResolutionError as exc:
        sys.stderr.write(str(exc) + "\n")
        return 65
    ruleset = load_ruleset(ruleset_path)
    enforce_unique_active_ruleset(ruleset_path.parent, ruleset_path)
    verify_external_manifest(ruleset, sha_manifest)
    engine = PolicyEngine(ruleset, external_manifest=sha_manifest)
    if args.command == "ruleset-check": _write_json({"status": "PASS", "ruleset": ruleset.metadata()}, None); return 0
    if args.command == "catalog": _write_json(compiled_catalog(ruleset), args.output); return 0
    if args.command == "scaffold": _write_json(scaffold_manifest(ruleset, case_id=args.case_id), args.output); return 0
    if args.command == "evaluate":
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8")); report = engine.evaluate(manifest); _write_json(report.to_dict(), args.output); return 0 if report.ready else 2
    if args.command == "smoke":
        result = run_smoke(engine); _write_json(result, args.output); return 0 if result["all_pass"] else 3
    if args.command == "ledger-append":
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8")); record = append_event(args.ledger, args.event_type, payload); _write_json(record, None); return 0
    if args.command == "ledger-verify":
        valid, errors = verify_ledger(args.ledger); _write_json({"valid": valid, "errors": errors}, None); return 0 if valid else 4
    if args.command == "serve":
        from .server import serve
        serve(engine, host=args.host, port=args.port); return 0
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
