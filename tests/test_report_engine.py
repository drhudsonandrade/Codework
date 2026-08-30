import tempfile
import unittest
from pathlib import Path

import normative
from ruleset_test_support import RULESET


def passing_policy_evaluation():
    return {
        "ready_for_requested_operation": True,
        # `policy_verdict` binds the evaluation to the canonical ruleset, so a fixture
        # without it is refused — which is the point of the binding.
        "ruleset": {"sha256": normative.RAW_SHA256},
        "planes": {
            "policy_control": {"state": "PASS"},
            "scientific_data": {"state": "PASS"},
            "evidence": {"state": "PASS"},
            "audit": {"state": "PASS"},
        },
        "gates": [
            {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
            {"gate": "POST_DEPLOYMENT_GATE", "state": "PENDING", "blocking": False},
        ],
    }


def final_fixture(report_id="01"):
    from reporting.provenance import fixture_payload

    data = fixture_payload(
        case_id="CASE-001",
        report_id=report_id,
        summary="Nenhum achado fictício é inserido pelo motor.",
        basis="fixture de teste do motor de relatórios",
    )
    data["ruleset"] = dict(RULESET)
    data["publication_gate"]["placeholders_resolved"] = True
    return data


class ReportEngineTest(unittest.TestCase):
    def assert_release_rejected(self, callable_, expected_reason=None):
        from reporting.engine import ReportReleaseError

        try:
            callable_()
        except ReportReleaseError as exc:
            if expected_reason is not None:
                self.assertIn(expected_reason, str(exc))
            return
        self.fail("expected ReportReleaseError")

    def test_catalog_contains_all_eleven_v3_models(self):
        from reporting.engine import load_catalog

        catalog = load_catalog()
        self.assertEqual(sorted(catalog), [f"{i:02d}" for i in range(1, 12)])
        self.assertEqual(catalog["01"]["slug"], "genoma-clinico")
        self.assertEqual(catalog["11"]["slug"], "guia-editorial-matriz-preenchimento")

    def test_model_mode_is_explicitly_non_result(self):
        from reporting.engine import render_document

        result = render_document("01", {}, mode="MODEL")
        self.assertIn("MODELO — NÃO É RESULTADO GENÉTICO", result["markdown"])
        self.assertEqual(result["metadata"]["mode"], "MODEL")
        self.assertEqual(result["metadata"]["ruleset_required"], RULESET)

    def test_final_mode_fails_closed_without_publication_gate(self):
        from reporting.engine import render_document

        self.assert_release_rejected(
            lambda: render_document("01", {"case_id": "CASE-001"}, mode="FINAL"),
            expected_reason="publication_gate:passed",
        )

    def test_final_mode_rejects_consent_outside_report_domain(self):
        from reporting.engine import render_document

        data = final_fixture()
        data["publication_gate"]["consent_scope_verified"] = False
        self.assert_release_rejected(
            lambda: render_document("01", data, mode="FINAL"),
            expected_reason="publication_gate:consent_scope_verified",
        )

    def test_final_mode_rejects_wrong_ruleset_digest(self):
        from reporting.engine import render_document

        bad_ruleset = dict(RULESET)
        bad_ruleset["sha256"] = "0" * 64
        data = {
            "case_id": "CASE-001",
            "ruleset": bad_ruleset,
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "consent_scope_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": passing_policy_evaluation(),
        }
        self.assert_release_rejected(
            lambda: render_document("01", data, mode="FINAL"),
            expected_reason="ruleset:sha256",
        )

    def test_final_mode_rejects_unready_policy_evaluation(self):
        from reporting.engine import render_document

        data = {
            "case_id": "CASE-001",
            "ruleset": dict(RULESET),
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "consent_scope_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": {
                "ready_for_requested_operation": False,
                "planes": {},
                "gates": [],
            },
        }
        self.assert_release_rejected(
            lambda: render_document("01", data, mode="FINAL"),
            expected_reason="policy_evaluation:ready_for_requested_operation",
        )

    def test_final_mode_requires_final_audit_pass(self):
        from reporting.engine import render_document

        policy = passing_policy_evaluation()
        policy["gates"] = [
            {"gate": "FINAL_AUDIT_GATE", "state": "FAIL", "blocking": True}
        ]
        data = {
            "case_id": "CASE-001",
            "ruleset": dict(RULESET),
            "publication_gate": {
                "passed": True,
                "consent_verified": True,
                "consent_scope_verified": True,
                "qc_verified": True,
                "evidence_verified": True,
                "placeholders_resolved": True,
            },
            "policy_evaluation": policy,
        }
        self.assert_release_rejected(
            lambda: render_document("01", data, mode="FINAL"),
            expected_reason="policy_evaluation:FINAL_AUDIT_GATE",
        )

    def test_final_mode_writes_json_markdown_and_html_when_gate_passes(self):
        from reporting.engine import render_document, write_bundle

        data = final_fixture()
        rendered = render_document("01", data, mode="FINAL")
        with tempfile.TemporaryDirectory() as td:
            paths = write_bundle(rendered, Path(td), stem="case-001-genoma-clinico")
            self.assertEqual(set(paths), {"json", "markdown", "html"})
            self.assertTrue(all(path.is_file() for path in paths.values()))
            self.assertNotIn("[[", paths["markdown"].read_text(encoding="utf-8"))
            markdown = paths["markdown"].read_text(encoding="utf-8")
            self.assertIn("POST-DEPLOYMENT: PENDENTE", markdown)
            self.assertIn("Ruleset: v3.4 / VIGENTE / 17/08/2026", markdown)
            self.assertIn(RULESET["sha256"], markdown)


class PayloadIsBoundToTheModelItAuthorisesTest(unittest.TestCase):
    """A payload compiled for one report may not be rendered as another.

    `render_document(report_id, data, mode="FINAL")` picked the catalog entry by its own
    argument and never compared it to `data["report_id"]`. Every gate it runs was computed
    for the payload's report: `PayloadCompiler.consent_scope` resolves the consent domain
    through `reporting.consent.REPORT_DOMAINS[report_id]`, and `provenance_blockers` anchors
    `report_id` as an identity field. Both agreed with each other and neither was compared
    to the model actually being rendered.

    So `render_document("02", payload_compiled_for_01, mode="FINAL")` produced the
    Ancestralidade e Genealogia Genética document, with zero blockers, under a consent
    verdict computed for the CLÍNICO domain — reports 01 and 02 sit in different domains
    (`CLÍNICO` and `ANCESTRALIDADE`). That is a real consent, for the wrong thing, reading
    as authorisation: the exact failure `consent_scope`'s docstring says it exists to
    prevent, reintroduced one layer below it.
    """

    def _payload_for(self, report_id: str):
        data = final_fixture(report_id=report_id)
        return data

    def test_rendering_a_payload_as_a_different_report_is_refused(self):
        from reporting.engine import ReportReleaseError, render_document

        data = self._payload_for("01")
        with self.assertRaises(ReportReleaseError) as caught:
            render_document("02", data, mode="FINAL")
        message = str(caught.exception)
        self.assertIn("report_id", message)
        self.assertIn("01", message)
        self.assertIn("02", message)

    def test_every_other_model_is_refused_the_same_way(self):
        """One pair proves the check exists; the sweep proves it is not special-cased."""
        from reporting.engine import ReportReleaseError, load_catalog, render_document

        data = self._payload_for("01")
        for report_id in load_catalog():
            if report_id == "01":
                continue
            with self.subTest(rendered_as=report_id):
                with self.assertRaises(ReportReleaseError):
                    render_document(report_id, data, mode="FINAL")

    def test_the_matching_report_still_renders(self):
        """The accepting case, so the refusal above is a binding and not a blanket no."""
        from reporting.engine import render_document

        rendered = render_document("01", self._payload_for("01"), mode="FINAL")
        self.assertEqual("01", rendered["metadata"]["report_id"])
        self.assertEqual("01", rendered["data"]["report_id"])

    def test_a_payload_carrying_no_report_id_cannot_publish(self):
        """Absence is not agreement: nothing may render FINAL without saying which report."""
        from reporting.engine import ReportReleaseError, render_document

        for value in (None, "", "1", 1):
            with self.subTest(report_id=value):
                data = self._payload_for("01")
                data["report_id"] = value
                with self.assertRaises(ReportReleaseError):
                    render_document("01", data, mode="FINAL")

    def test_model_mode_is_unaffected(self):
        """MODEL renders the empty template and reads no payload, so it keeps working."""
        from reporting.engine import render_document

        result = render_document("02", {"report_id": "01"}, mode="MODEL")
        self.assertIn("MODELO — NÃO É RESULTADO GENÉTICO", result["markdown"])


if __name__ == "__main__":
    unittest.main()
