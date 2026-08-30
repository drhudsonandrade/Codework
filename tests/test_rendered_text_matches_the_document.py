"""What the provenance block says was observed must be what the document prints.

`reporting.provenance.render_value` produces the `observed_value` an anchor records;
`reporting.engine._safe` produces the text the FINAL document actually shows. Its docstring
claimed the two "must agree character for character" and named `tests/test_report_provenance.py`
as what kept them from drifting apart. That file does not exist, and nothing else asserted the
agreement — so they had drifted: `_safe` serialises mappings with `sort_keys=True` and
`render_value` did not.

The consequence is the failure this module exists to catch, inverted. `provenance_blockers`
recomputes `render_value(value)` and compares it to the anchor, so both sides of the gate moved
together and the payload passed with zero blockers, while the document face printed
`{"alfa": "a", "zeta": "z"}` under a provenance block asserting the observed value was
`{"zeta": "z", "alfa": "a"}`. An anchor that does not match the printed text has stopped
attesting to the document.

The fix makes the agreement structural — `_safe` renders through `render_value` — so the two
cannot drift again. These tests pin both the property and the one difference that remains
deliberate: `_safe` substitutes a caller-chosen default for an absent value, and that
substitution is bounded below.
"""
from __future__ import annotations

import unittest

from ruleset_test_support import RULESET

from reporting import engine
from reporting.provenance import (
    UNAVAILABLE,
    fixture_payload,
    provenance_blockers,
    render_value,
)

#: Values chosen for the ways two JSON renderings can disagree: key order, nesting, mappings
#: inside sequences, and the scalars where agreement was never in doubt and must stay so.
RENDERABLE = (
    {"zeta": "z", "alfa": "a"},
    {"z": 1, "a": {"y": 2, "b": 3}},
    [{"b": 1, "a": 2}, {"d": 4, "c": 3}],
    {"b": [1, {"n": 0, "m": 9}]},
    {},
    [],
    ["a", "b"],
    ("a", "b"),
    "texto",
    0,
    False,
    3.5,
    None,
    "",
)


class RenderedTextMatchesTheDocumentTest(unittest.TestCase):
    def test_every_renderable_value_prints_as_its_anchor_records_it(self):
        """The property the docstring claimed and no test had ever checked."""
        for value in RENDERABLE:
            with self.subTest(value=value):
                self.assertEqual(render_value(value), engine._safe(value))

    def test_a_mapping_whose_keys_are_not_already_sorted_is_the_case_that_broke(self):
        """Named on its own: sorted-key inputs agreed by luck and hid the divergence."""
        self.assertEqual(
            render_value({"zeta": "z", "alfa": "a"}),
            engine._safe({"zeta": "z", "alfa": "a"}),
        )
        self.assertEqual('{"alfa": "a", "zeta": "z"}', render_value({"zeta": "z", "alfa": "a"}))

    def test_a_compiled_payload_prints_exactly_what_its_anchor_attests(self):
        """End to end, through the public API, on a payload the gate passes.

        This is the shape that published a mismatched document with zero blockers: the gate
        compares `render_value` against the anchor, so it agreed with itself while the
        rendered text did not agree with either.
        """
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary={"zeta": "z", "alfa": "a"},
            basis="fixture de regressão",
        )
        self.assertEqual([], provenance_blockers(payload))
        self.assertEqual(
            payload["provenance"]["fields"]["summary"]["observed_value"],
            engine._safe(payload["summary"]),
        )

    def test_the_anchored_text_appears_verbatim_in_the_rendered_document(self):
        """Agreeing helpers are worth nothing if the document is assembled some other way."""
        payload = fixture_payload(
            case_id="CASE-001",
            report_id="01",
            summary={"zeta": "z", "alfa": "a"},
            # A section this model actually prints: the catalog decides which titles reach
            # the document, so anchoring one it does not carry would assert nothing.
            sections={"Resumo clínico executivo": {"segundo": 2, "primeiro": 1}},
            basis="fixture de regressão",
        )
        # The same two fields `tests/test_report_engine.final_fixture` sets: a fixture payload
        # is fully anchored but carries no ruleset block and no placeholder sweep, and FINAL
        # mode refuses without them.
        payload["ruleset"] = dict(RULESET)
        payload["publication_gate"]["placeholders_resolved"] = True
        markdown = engine.render_document("01", payload, mode="FINAL")["markdown"]
        for name in ("summary", "sections[Resumo clínico executivo]"):
            with self.subTest(field=name):
                self.assertIn(
                    payload["provenance"]["fields"][name]["observed_value"], markdown
                )

    def test_the_substitution_for_an_absent_value_is_the_only_licensed_difference(self):
        """`_safe` may choose what to print in place of nothing; it may not reshape a value.

        `post_deployment_status` is printed with the default `PENDENTE` and `findings[].id`
        with `ACHADO SEM ID`, so on an absent value the two helpers differ by design. That
        difference is confined to substitution: for any value that is actually present they
        agree, and the gate below shows the substituted case cannot be published anyway.
        """
        for default in ("PENDENTE", "ACHADO SEM ID"):
            with self.subTest(default=default):
                self.assertEqual(default, engine._safe(None, default))
                self.assertEqual(default, engine._safe("", default))
                self.assertEqual(UNAVAILABLE, render_value(None))
        for value in RENDERABLE:
            if value is None or value == "":
                continue
            with self.subTest(value=value):
                self.assertEqual(engine._safe(value, "PENDENTE"), render_value(value))

    def test_deleting_a_field_the_document_would_substitute_for_is_still_blocked(self):
        """The bound on the substitution: a value the anchor recorded cannot go missing."""
        payload = fixture_payload(
            case_id="CASE-1",
            report_id="01",
            summary="fixture",
            basis="fixture de regressão",
        )
        payload["post_deployment_status"] = ""
        self.assertIn(
            "provenance:mismatch:post_deployment_status", provenance_blockers(payload)
        )


if __name__ == "__main__":
    unittest.main()
