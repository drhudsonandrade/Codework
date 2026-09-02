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
    {
        "result",
        "status",
        "verdict",
        "structural_parity",
        "within_envelope",
        "outcome",
        "all_pass",
    }
)

#: Strings that read as an approval. `True` is handled separately: `1 == True` in Python,
#: so a page count of 1 would otherwise be read as a passing boolean.
PASSING_STRINGS = frozenset({"PASS", "PASSED", "OK", "APROVADO", "VERIFICADO"})

#: A key carrying this suffix is explicitly labelled as history, not as a live verdict.
HISTORICAL_SUFFIX = "_historical_observation"


def _artifacts() -> list[Path]:
    """Every evidence artifact shipped in the repository."""
    return sorted(EVIDENCE_DIR.glob("*.json"))


def _is_passing(value: object) -> bool:
    """Whether this value is one of the recognised passing verdicts."""
    if isinstance(value, bool):
        return value is True
    return isinstance(value, str) and value.strip().upper() in PASSING_STRINGS


def _blocks(node: object, prefix: str = ""):
    """Every object anywhere in the artifact, with the dotted path that reaches it.

    The walk is recursive, through lists as well as objects, so that every block is *offered*
    to the rule. What it fixes is a block that was never examined: one at depth two or more
    carrying both `result: "NÃO DISPONÍVEL"` and a passing verdict among its own keys went
    unchecked, because the previous walk stopped at the root's immediate children. Depth is
    not a property a consumer quoting the field would notice.

    It does not make the rule a subtree rule. Each block is judged on its own keys — see
    `_passing_verdicts`, which explains why, and the two tests that pin both sides of that
    boundary. `{"status": "NÃO DISPONÍVEL", "detail": {"verdict": "PASS"}}` is therefore
    *not* an incoherence here: `detail` is a different block making a statement about a
    different subject, and it is checked only against its own declaration.
    """
    if isinstance(node, dict):
        yield prefix, node
        for key, value in node.items():
            yield from _blocks(value, f"{prefix}.{key}" if prefix else key)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _blocks(item, f"{prefix}[{index}]")


def _declares_unavailable(block: dict) -> bool:
    """Whether this object says of itself that it is not available."""
    return any(block.get(key) == UNAVAILABLE for key in VERDICT_KEYS)


def _passing_verdicts(block: dict, prefix: str = "") -> list[str]:
    """Paths of every verdict field *of this block* that reads as an approval.

    This block's own keys, not its subtree. A subtree rule was written first and refused on
    evidence: run over the shipped artifacts it flagged nine coherent blocks, all of the shape
    `gene_validity.VKORC1` has in `GENE_DISEASE_VALIDITY.json` — an outer
    `status: "NÃO DISPONÍVEL"` meaning *this gene's disease validity is not established*, over
    an inner `clingen.status: "VERIFICADO"` meaning *the ClinGen lookup was performed*. Those
    are verdicts about two different subjects, and the inner one is what lets a reader see
    that the outer refusal rests on a source that answered rather than on a source that was
    never asked. Reading them as a contradiction would push the artifact to hide its own
    provenance.

    The gap the recursive walk closes is a different one: a block at depth two or more that
    carries both `result: "NÃO DISPONÍVEL"` and a passing verdict *among its own keys* was
    never examined at all, because the walk stopped at the root's immediate children.
    """
    return [
        f"{prefix}.{key}" if prefix else key
        for key, value in block.items()
        if key in VERDICT_KEYS
        and not key.endswith(HISTORICAL_SUFFIX)
        and _is_passing(value)
    ]


class EvidenceVerdictCoherenceTest(unittest.TestCase):
    """No evidence artifact may offer a passing verdict while declaring itself unavailable."""
    def test_the_evidence_directory_is_not_empty(self):
        """A vacuous pass here would hide the whole rule."""
        self.assertTrue(_artifacts(), f"no evidence artifacts found under {EVIDENCE_DIR}")

    def test_an_unavailable_artifact_offers_no_passing_verdict(self):
        """A block declaring NÃO DISPONÍVEL offers no passing verdict among its own fields.

        Its own fields, not its subtree: a nested block states something about a different
        subject and is judged against its own declaration when the walk reaches it.
        `_passing_verdicts` records the measurement that settled the scope.
        """
        checked = 0
        for path in _artifacts():
            document = json.loads(path.read_text(encoding="utf-8"))
            for prefix, block in _blocks(document):
                if not _declares_unavailable(block):
                    continue
                checked += 1
                offending = _passing_verdicts(block, prefix)
                with self.subTest(artifact=path.name, block=prefix or "<root>"):
                    self.assertEqual(
                        offending,
                        [],
                        f"{path.name} declares {UNAVAILABLE} at "
                        f"{prefix or '<root>'} yet still publishes a passing verdict at "
                        f"{offending}: rename the field with the {HISTORICAL_SUFFIX} "
                        f"suffix or set it to {UNAVAILABLE}",
                    )
        self.assertGreater(
            checked, 0, "no artifact declared NÃO DISPONÍVEL, so the rule never ran"
        )

    @staticmethod
    def _offending(document: object) -> list[str]:
        """Every incoherence the rule finds in this document."""
        return sorted(
            found
            for prefix, block in _blocks(document)
            if _declares_unavailable(block)
            for found in _passing_verdicts(block, prefix)
        )

    def test_a_deep_block_is_reached_by_the_walk(self):
        """The depth at which the earlier walk stopped looking.

        It examined the root and its immediate object children, so a block three levels down
        — including one inside a list — could declare itself unavailable and publish an
        approval in the same breath without ever being looked at. Asserted on a synthetic
        document rather than on a shipped artifact, so it keeps holding as the evidence
        directory changes.
        """
        document = {
            "a": {"b": {"c": {"status": UNAVAILABLE, "verdict": "PASS"}}},
            "runs": [{"result": UNAVAILABLE, "outcome": "APROVADO"}],
        }
        self.assertEqual(
            self._offending(document),
            ["a.b.c.verdict", "runs[0].outcome"],
        )

    def test_all_pass_cannot_approve_unavailable_evidence(self):
        self.assertEqual(
            self._offending({"status": UNAVAILABLE, "all_pass": True}),
            ["all_pass"],
        )

    def test_every_verdict_key_can_declare_unavailability(self):
        for key in ("verdict", "outcome"):
            with self.subTest(key=key):
                self.assertEqual(
                    self._offending({key: UNAVAILABLE, "status": "PASS"}),
                    ["status"],
                )

    def test_a_source_status_under_a_refused_block_is_not_an_incoherence(self):
        """The scope this rule deliberately does not have.

        `gene_validity.<gene>` in `GENE_DISEASE_VALIDITY.json` is exactly this shape: the
        outer refusal is about the gene's disease validity, the inner `VERIFICADO` is about
        whether the source was reached. Treating the pair as a contradiction would flag nine
        coherent blocks in the shipped evidence and push artifacts to drop the very field
        that shows the refusal rests on an answer rather than on silence.
        """
        document = {
            "status": UNAVAILABLE,
            "clingen": {"status": "VERIFICADO", "established": False},
        }
        self.assertEqual(self._offending(document), [])


if __name__ == "__main__":
    unittest.main()
