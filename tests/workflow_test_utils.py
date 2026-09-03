from __future__ import annotations


def job_block(workflow: str, job_name: str) -> str:
    marker = f"  {job_name}:\n"
    if marker not in workflow:
        raise AssertionError(f"job {job_name!r} is missing")
    tail = workflow.split(marker, 1)[1]
    lines: list[str] = []
    for line in tail.splitlines(keepends=True):
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            break
        lines.append(line)
    return "".join(lines)
