#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA40 = re.compile(r"^[0-9a-f]{40}$")
USE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")


def fail(message: str) -> None:
    print(f"FAIL\t{message}")
    raise SystemExit(1)


def main() -> int:
    actions = json.loads((ROOT / "locks/actions-lock.json").read_text(encoding="utf-8"))["actions"]
    runtime = json.loads((ROOT / "locks/runtime-lock.json").read_text(encoding="utf-8"))
    expected = {name: meta["sha"] for name, meta in actions.items()}
    seen: set[str] = set()

    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for line_no, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = USE.match(line)
            if not m:
                continue
            ref = m.group(1)
            if ref.startswith("./"):
                continue
            if "@" not in ref:
                fail(f"{wf}:{line_no}: action reference lacks @ identity: {ref}")
            name, ident = ref.rsplit("@", 1)
            if not SHA40.fullmatch(ident):
                fail(f"{wf}:{line_no}: mutable/non-SHA action identity: {ref}")
            if name not in expected:
                fail(f"{wf}:{line_no}: action absent from actions-lock.json: {name}")
            if expected[name] != ident:
                fail(f"{wf}:{line_no}: action SHA differs from lock: {name}@{ident}")
            seen.add(name)

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    base = runtime["base_image"]["reference"]
    if not dockerfile.startswith(f"FROM {base}\n"):
        fail("Dockerfile base image is not the immutable runtime-lock reference")

    env = (ROOT / "environment.yml").read_text(encoding="utf-8")
    for package, version in runtime["conda"].items():
        if f"- {package}={version}" not in env:
            fail(f"environment.yml does not exactly pin locked package {package}={version}")

    for required in (runtime["python_requirements"], runtime["npm_lock"], runtime["template_manifest"], runtime["actions_lock"]):
        if not (ROOT / required).is_file():
            fail(f"locked artifact missing: {required}")

    print(f"PASS\tactions_immutable\t{len(seen)} action identities observed")
    print("PASS\tcontainer_digests\tbase image")
    print("PASS\truntime_versions\texact critical conda pins")
    return 0


if __name__ == "__main__":
    sys.exit(main())
