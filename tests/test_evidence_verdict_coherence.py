"""No committed evidence artifact may offer a current verdict it also disclaims.

`EDITORIAL_V3_DOCX_PARITY_150DPI_*.json` declared `reproducibility.status` and
`aggregate.result` as NÃO DISPONÍVEL — the artifact's own reason says the run is historical
and "não constitui evidência reproduzível para uma publicação atual" — while
`aggregate.structural_parity` still read "PASS" and `aggregate.within_envelope` still read
true. A consumer quoting either field extracts an approval from an artifact that denies
having one.

Scope: the summary block's *verdict* fields. Raw per-report measurements (`geometry_preserved`,
`page_count_matches`, pixel fractions) are observations and stay as recorded — they are what
the artifact is for. What may not stand is a field whose name reads as a judgement, in the
same block that declares the evidence unavailable. Checked over the whole evidence directory
rather than the two files that had the problem, so the next artifact cannot reintroduce it.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parents[1] / "docs" / "evidence"

UNAVAILABLE = "NÃO DISPONÍVEL"

#: Keys whose value a reader takes as this artifact's judgement rather than a measurement.
VERDICT_KEYS = frozenset(
    {"result", "status", "verdict", "structural_parity", "within_envelope", "outcome"}
)

#: Strings that read as an approval. `True` is handled separately: `1 == True` in Python,
#: so a page count of 1 would otherwise be read as a passing boolean.
PASSING_STRINGS = frozenset({"PASS", "PASSED", "OK", "APROVADO", "VERIFICADO"})

#: A key carrying this suffix is explicitly labelled as history, not as a live verdict.
HISTORICAL_SUFFIX = "_historical_observation"


def _artifacts() -> list[Path]:
    return sorted(EVIDENCE_DIR.glob("*.json"))


def _is_passing(value: object) -> bool:
    if isinstance(value, bool):
        return value is True
    return isinstance(value, str) and value.strip().upper() in PASSING_STRINGS


def _summary_blocks(document: dict) -> list[tuple[str, dict]]:
    """The document root and its immediate object children — where verdicts live."""
    blocks = [("", document)]
    blocks.extend(
        (key, value) for key, value in document.items() if isinstance(value, dict)
    )
    return blocks


class EvidenceVerdictCoherenceTest(unittest.TestCase):
    def test_the_evidence_directory_is_not_empty(self):
        """A vacuous pass here would hide the whole rule."""
        self.assertTrue(_artifacts(), f"no evidence artifacts found under {EVIDENCE_DIR}")

    def test_an_unavailable_artifact_offers_no_passing_verdict(self):
        checked = 0
        for path in _artifacts():
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                continue
            blocks = _summary_blocks(document)
            unavailable = any(
                block.get(key) == UNAVAILABLE
                for _, block in blocks
                for key in ("result", "status")
            )
            if not unavailable:
                continue
            checked += 1
            offending = [
                f"{prefix + '.' if prefix else ''}{key}"
                for prefix, block in blocks
                for key, value in block.items()
                if key in VERDICT_KEYS
                and not key.endswith(HISTORICAL_SUFFIX)
                and _is_passing(value)
            ]
            with self.subTest(artifact=path.name):
                self.assertEqual(
                    offending,
                    [],
                    f"{path.name} declares {UNAVAILABLE} yet still publishes a passing "
                    f"verdict at {offending}: rename the field with the "
                    f"{HISTORICAL_SUFFIX} suffix or set it to {UNAVAILABLE}",
                )
        self.assertGreater(
            checked, 0, "no artifact declared NÃO DISPONÍVEL, so the rule never ran"
        )


if __name__ == "__main__":
    unittest.main()
