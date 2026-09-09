"""Deterministic non-personal fixtures for the reporting language boundary."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from reporting import engine, provenance

BASE_SHA = "0a643128f3ac3e99a51428644c3012a2d638ab8b"
FIXED_INSTANT = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


class FixtureClock(datetime):
    """Freeze only generation timestamps, never the publication gate."""

    @classmethod
    def now(cls, tz=None):
        """Return the fixed fixture instant in the requested timezone."""
        return FIXED_INSTANT.astimezone(tz) if tz else FIXED_INSTANT.replace(tzinfo=None)


def make_payload(report_id: str) -> dict:
    """Use the existing fixture compiler; every claim remains marked as unavailable."""
    model = engine.load_catalog()[report_id]
    values = ("Texto sintético: ação, público e limitações.", {"zeta": 2, "alfa": 1}, 0, False)
    sections = {title: values[index % len(values)] for index, title in enumerate(model["sections"])}
    with patch.object(provenance, "datetime", FixtureClock):
        payload = provenance.fixture_payload(
            case_id="SYNTHETIC-LOCALE-NO-PERSONAL-DATA",
            report_id=report_id,
            summary="Fixture de idioma; não representa paciente nem análise genética.",
            sections=sections,
            basis="Teste sintético de compatibilidade de apresentação.",
        )
    payload["ruleset"] = dict(engine.EXPECTED_RULESET)
    payload["publication_gate"]["placeholders_resolved"] = True
    return payload


def render_fixture(report_id: str, mode: str) -> dict:
    """Exercise the public renderer with deterministic metadata and real fixture gates."""
    data = make_payload(report_id) if mode == "FINAL" else {}
    with patch.object(engine, "datetime", FixtureClock):
        return engine.render_document(report_id, data, mode=mode)


def text_digest(value: str) -> str:
    """Hash exact Unicode output, including punctuation and whitespace."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def output_snapshot() -> dict:
    """Capture all eleven public MODEL/FINAL bundles without editing their payloads."""
    cases = {}
    with TemporaryDirectory() as directory:
        root = Path(directory)
        for report_id in engine.load_catalog():
            for mode in ("MODEL", "FINAL"):
                rendered = render_fixture(report_id, mode)
                before = deepcopy(rendered)
                outputs = engine.write_bundle(rendered, root / report_id / mode)
                assert rendered == before, "writer mutated the input fixture"
                cases[f"{report_id}:{mode}"] = {
                    "markdown": text_digest(rendered["markdown"]),
                    "html": text_digest(rendered["html"]),
                    "files": {
                        key: {
                            "name": path.name,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                        }
                        for key, path in outputs.items()
                    },
                    "metadata_keys": sorted(rendered["metadata"]),
                }
    # Private formatting characterization only: this deliberately unprovenanced fixture
    # is never passed off as an authorized FINAL document or written to a public bundle.
    raw_data: dict[str, object] = {
        "case_id": None,
        "summary": {"zeta": "fim", "alfa": "início"},
        "findings": [
            {
                "id": None,
                "domain": "PESQUISA",
                "nature": "HIPÓTESE",
                "priority": 0,
                "observed_data": {"z": 2, "a": 1},
                "qc": False,
                "evidence_refs": [],
                "interpretation": "<x>& ação",
            }
        ],
        "sources": [],
        "limitations": None,
        "execution_manifest": {"b": 2, "a": 1},
    }
    raw = engine._final_markdown("01", engine.load_catalog()["01"], raw_data)
    cases["private-formatting-only"] = {
        "markdown": text_digest(raw),
        "html": text_digest(engine._to_html(raw, "<Título & sintético>")),
    }
    return {"base_sha": BASE_SHA, "cases": cases}
