#!/usr/bin/env python3
"""Runtime/Resource Gate adapter for a session-promoted latest-tested candidate.

The canonical gate normally checks repository-pinned versions. A latest candidate is
instead version-locked by its Conda inventory + image digest after the synthetic canary.
This adapter keeps every reference/sample/caller check from runtime_resource_gate.py but
changes the executable check from 'equals repository pin' to 'executes successfully and
is captured in evidence'. It MUST only be used after freshness_gate ready_for_dna=true.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import runtime_resource_gate as core


def check_promoted_state(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("ready_for_dna") is not True:
        raise RuntimeError("latest-tested runtime gate refused: freshness gate is not ready_for_dna=true")


def check_tools_latest():
    observed = {}
    failures = []
    for tool, (_, cmd) in core.EXPECTED_TOOLS.items():
        path = shutil.which(tool)
        if not path:
            observed[tool] = {"status":"NÃO DISPONÍVEL", "path":None}
            failures.append(f"{tool}:missing")
            continue
        code, output = core.run(cmd)
        first = output.splitlines()[0] if output else ""
        ok = code == 0 and bool(output.strip())
        observed[tool] = {
            "status":"EXECUTADO" if ok else "NÃO DISPONÍVEL",
            "observed":first,
            "path":path,
            "exit_code":code,
            "version_policy":"session-promoted-latest-tested",
        }
        if not ok:
            failures.append(f"{tool}:execution")
    return core.item("EXECUTADO" if not failures else "NÃO DISPONÍVEL", "runtime:tool-versions-latest-tested", tools=observed, failures=failures)


def main() -> int:
    if "--freshness-gate" not in sys.argv:
        raise SystemExit("--freshness-gate is required")
    idx = sys.argv.index("--freshness-gate")
    try:
        path = Path(sys.argv[idx + 1])
    except IndexError as exc:
        raise SystemExit("--freshness-gate requires a path") from exc
    del sys.argv[idx:idx + 2]
    check_promoted_state(path)
    core.check_tools = check_tools_latest
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
