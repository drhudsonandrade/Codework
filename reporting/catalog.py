"""Read report metadata from `reporting/catalog.json`, so no builder retypes it.

Two report builders in this project have shipped with hand-typed section titles that did not
match the catalogue. The engine looks sections up by catalogue title, so a paraphrase renders
an *empty* section while the anchored text sits unreachable under a key nobody reads — the
document loses a page and nothing errors. Both times the mistake survived until a PDF was
opened and read.

Reading the titles from the catalogue removes the possibility. `tests/test_pharmacogenomics.py` additionally asserts that report 06's declared `SECTIONS`
equals what this module returns, so that builder's literal tuple cannot drift away from it.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parent / "catalog.json"


class CatalogError(KeyError):
    """The catalogue does not describe the requested report."""


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def report(report_id: str) -> dict[str, Any]:
    catalog = load_catalog()
    entry = catalog.get(str(report_id))
    if not isinstance(entry, dict):
        raise CatalogError(f"reporting/catalog.json has no report {report_id!r}")
    return entry


def section_titles(report_id: str) -> tuple[str, ...]:
    """The report's section titles, in catalogue order."""
    sections = report(report_id).get("sections")
    if not isinstance(sections, list) or not sections:
        raise CatalogError(f"report {report_id!r} declares no sections")
    return tuple(str(title) for title in sections)


def report_ids() -> tuple[str, ...]:
    return tuple(sorted(load_catalog()))
