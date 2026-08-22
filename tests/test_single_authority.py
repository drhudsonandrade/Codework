"""Only the policy engine may declare a run authorised.

An external audit named this the root architectural defect, and it was right. Nine report
builders passed their own `publication_gate` and `policy_evaluation` into `compile`:
`consent_verified` was `bool(case_id)`, `evidence_verified` was the literal `True`, and all
four planes plus FINAL_AUDIT_GATE went to PASS whenever a local variable called `verified`
was true. The component that produced the report also declared it authorised.

Measured on a real case, the two authorities disagreed exactly as expected: `genoma_policy`
returned `ready_for_requested_operation: False` for the same run whose payloads all carried
`True` — and the array manifest, by omitting its `operation` block, had silently switched
DATA_PROVENANCE_GATE, CONSENT_GATE, QC_GATE and RUNTIME_RESOURCE_GATE off while the plane
that contains them reported PASS.

The verdict is no longer a parameter. It is copied from a registered policy evaluation with
that artifact's SHA-256 beside it, and a payload that registers none refuses.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.provenance import (
    POLICY_EVALUATION_ARTIFACT,
    REQUIRED_PLANES,
    Artifact,
    PayloadCompiler,
)

ARTIFACT = {"metrics": {"call_rate": 0.99, "rows": 10}}

PASS_VERDICT = {
    "ready_for_requested_operation": True,
    "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
    "gates": [
        {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
        {"gate": "CONSENT_GATE", "state": "PASS", "blocking": True},
        {"gate": "QC_GATE", "state": "PASS", "blocking": True},
    ],
}


def _verdict_file(verdict: dict) -> Path:
    path = Path(tempfile.mkdtemp()) / "policy-evaluation.json"
    path.write_text(json.dumps(verdict), encoding="utf-8")
    return path


def _consent_file() -> Path:
    from tests.attestations import consent_file

    return consent_file(Path(tempfile.mkdtemp()), case_id="CASO-AUT")


def _payload(verdict: dict | None, *, consent: Path | None = None) -> dict:
    compiler = PayloadCompiler(
        case_id="CASO-AUT", report_id="09",
        policy_evaluation=_verdict_file(verdict) if verdict is not None else None,
        consent=consent,
    )
    compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
    compiler.derive(
        "summary", artifact="array-qc", locator="metrics.call_rate",
        status="VERIFICADO", basis="call rate",
    )
    compiler.state("sources", ["array-qc"], kind="case_control", basis="set", status="VERIFICADO")
    compiler.state("limitations", "escopo", kind="case_control", basis="escopo", status="VERIFICADO")
    return compiler.compile()


class NoVerdictMeansNoAuthorityTest(unittest.TestCase):
    def test_a_payload_without_an_evaluation_grants_nothing(self):
        data = _payload(None)
        self.assertIs(data["publication_gate"]["passed"], False)
        self.assertIs(data["publication_gate"]["consent_verified"], False)
        self.assertIs(data["publication_gate"]["evidence_verified"], False)
        self.assertIs(data["policy_evaluation"]["ready_for_requested_operation"], False)
        for plane in REQUIRED_PLANES:
            self.assertEqual(data["policy_evaluation"]["planes"][plane]["state"], "BLOCKED")

    def test_the_refusal_names_the_artifact_that_would_change_it(self):
        source = _payload(None)["policy_evaluation"]["source"]
        self.assertEqual(source["status"], "NÃO DISPONÍVEL")
        self.assertIn(POLICY_EVALUATION_ARTIFACT, source["reason"])

    def test_the_reserved_artifact_name_cannot_be_registered(self):
        """The door the first version of this fix left open.

        Moving the verdict out of `compile`'s parameters closed one route and left another:
        `register(Artifact.from_payload("policy-evaluation", {...ready: True...}))` installed
        an invented verdict under the reserved name and published FINAL with
        `operational_status: VERIFICADO`. Verified by doing it before closing it.
        """
        from reporting.provenance import ProvenanceError

        compiler = PayloadCompiler(case_id="CASO-AUT", report_id="09")
        with self.assertRaises(ProvenanceError) as caught:
            compiler.register(Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, PASS_VERDICT))
        message = str(caught.exception)
        self.assertIn("not a registrable artifact", message)
        self.assertIn("policy_evaluation=<path>", message)

    def test_a_fixture_verdict_cannot_carry_measured_values(self):
        """Layout QA may render FINAL; it may not publish a measurement on that authority."""
        from reporting.provenance import ProvenanceError, fixture_payload

        # The legitimate use: every value a fixture, status floored at NÃO DISPONÍVEL.
        data = fixture_payload(case_id="CASO-QA", report_id="09", summary="s", basis="qa")
        self.assertEqual(data["operational_status"], "NÃO DISPONÍVEL")
        self.assertEqual(data["policy_evaluation"]["source"]["origin"], "fixture")

        compiler = PayloadCompiler(case_id="CASO-QA", report_id="09")
        compiler._install_verdict(
            Artifact.from_payload(POLICY_EVALUATION_ARTIFACT, PASS_VERDICT), fixture=True
        )
        compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
        compiler.derive(
            "summary", artifact="array-qc", locator="metrics.call_rate",
            status="VERIFICADO", basis="uma medição real",
        )
        compiler.state("sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO")
        compiler.state("limitations", "x", kind="case_control", basis="l", status="VERIFICADO")
        with self.assertRaises(ProvenanceError) as caught:
            compiler.compile()
        self.assertIn("fixture policy verdict cannot carry measured values", str(caught.exception))

    def test_a_builder_can_no_longer_hand_compile_a_verdict(self):
        compiler = PayloadCompiler(case_id="CASO-AUT", report_id="09")
        with self.assertRaises(TypeError):
            compiler.compile(policy_evaluation=PASS_VERDICT)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            compiler.compile(publication_gate={"passed": True})  # type: ignore[call-arg]

    def test_extra_cannot_reinstate_the_verdict_that_the_parameters_no_longer_accept(self):
        """The third door: `extra` merges into the payload after the anchors are fixed.

        It refused keys that had been *anchored*, and `publication_gate` and
        `policy_evaluation` are not anchors — they are derived blocks. So the one-line
        replacement for the removed parameter was `extra={"publication_gate": {"passed":
        True, ...}}`, and `reporting.engine.render_blockers` reads exactly that block to
        decide whether a FINAL document may be produced. Verified by doing it before closing
        it: the payload rendered FINAL on a verdict the engine had refused.
        """
        from reporting.provenance import ProvenanceError

        for block in ("publication_gate", "policy_evaluation", "post_deployment",
                      "operational_status", "artifacts", "provenance"):
            with self.subTest(block=block):
                compiler = PayloadCompiler(case_id="CASO-AUT", report_id="09")
                compiler.register(Artifact.from_payload("array-qc", ARTIFACT))
                compiler.derive(
                    "summary", artifact="array-qc", locator="metrics.call_rate",
                    status="VERIFICADO", basis="call rate",
                )
                compiler.state(
                    "sources", ["array-qc"], kind="case_control", basis="s", status="VERIFICADO"
                )
                compiler.state(
                    "limitations", "x", kind="case_control", basis="l", status="VERIFICADO"
                )
                with self.assertRaises(ProvenanceError) as caught:
                    compiler.compile(extra={block: {"passed": True}})
                self.assertIn(block, str(caught.exception))


class VerdictIsCopiedNotComposedTest(unittest.TestCase):
    def test_a_pass_verdict_is_carried_with_the_hash_of_its_artifact(self):
        data = _payload(PASS_VERDICT)
        self.assertIs(data["publication_gate"]["passed"], True)
        self.assertIs(data["publication_gate"]["consent_verified"], True)
        self.assertIs(data["publication_gate"]["qc_verified"], True)
        source = data["policy_evaluation"]["source"]
        self.assertEqual(source["status"], "VERIFICADO")
        self.assertTrue(source["sha256"])
        self.assertEqual(source["origin"], "policy-engine-output")
        self.assertTrue(source["path"])

    def test_a_refused_verdict_is_carried_verbatim(self):
        """The builder cannot upgrade what the engine withheld."""
        blocked = {
            "ready_for_requested_operation": False,
            "planes": {
                "policy_control": {"state": "PASS"}, "scientific_data": {"state": "FAIL"},
                "evidence": {"state": "PASS"}, "audit": {"state": "PASS"},
            },
            "gates": [{"gate": "CONSENT_GATE", "state": "FAIL", "blocking": True}],
        }
        data = _payload(blocked)
        self.assertIs(data["publication_gate"]["passed"], False)
        self.assertIs(data["publication_gate"]["consent_verified"], False)
        self.assertEqual(data["policy_evaluation"]["planes"]["scientific_data"]["state"], "FAIL")

    def test_a_plane_the_evaluation_omits_is_blocked_not_assumed(self):
        partial = {"ready_for_requested_operation": True, "planes": {"audit": {"state": "PASS"}}, "gates": []}
        data = _payload(partial)
        self.assertEqual(data["policy_evaluation"]["planes"]["evidence"]["state"], "BLOCKED")
        self.assertEqual(data["policy_evaluation"]["planes"]["audit"]["state"], "PASS")

    def test_consent_comes_from_the_consent_gate_not_from_the_case_id(self):
        """`bool(case_id)` was the old test; an identifier is not a consent instrument."""
        no_consent = dict(PASS_VERDICT, gates=[
            {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
            {"gate": "CONSENT_GATE", "state": "FAIL", "blocking": True},
        ])
        data = _payload(no_consent)
        self.assertTrue(data["case_id"])
        self.assertIs(data["publication_gate"]["consent_verified"], False)


class RenderRefusesAnUnauthorisedPayloadTest(unittest.TestCase):
    def test_final_publication_is_blocked_without_a_verdict(self):
        from reporting.engine import ReportReleaseError, render_document

        with self.assertRaises(ReportReleaseError) as caught:
            render_document("09", _payload(None), mode="FINAL")
        message = str(caught.exception)
        self.assertIn("policy_evaluation:ready_for_requested_operation", message)
        self.assertIn("publication_gate:passed", message)

    def test_final_publication_proceeds_on_a_real_verdict(self):
        from reporting.engine import render_document

        rendered = render_document(
            "09", _payload(PASS_VERDICT, consent=_consent_file()), mode="FINAL"
        )
        self.assertIn("markdown", rendered)

    def test_a_verdict_alone_no_longer_publishes_without_a_consent_record(self):
        """CONSENT_GATE PASS says a consent exists, not that it covers this report."""
        from reporting.engine import ReportReleaseError, render_document

        with self.assertRaises(ReportReleaseError) as caught:
            render_document("09", _payload(PASS_VERDICT), mode="FINAL")
        self.assertIn("publication_gate:consent_scope_verified", str(caught.exception))


class ArrayManifestAnswersItsGatesTest(unittest.TestCase):
    """The manifest must not silence the scientific-data plane by omission."""

    def _manifest(self, consent=None):
        from scripts.build_array_case_manifest import build_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            qc_path = root / "qc.json"
            annotation_path = root / "annotation.json"
            qc = {
                "case_id": "CASO-AUT", "operational_status": "VERIFICADO",
                "gates": {"LIMITED_INTERPRETATION_GATE": {"state": "PASS"}},
                "input": {"sha256": "a" * 64, "build": "GRCh37", "strand": "forward",
                          "schema": "harmonized_genera_myheritage_v1"},
                "metrics": {"unique_rsids": 10, "call_rate": 0.99}, "limitations": [],
            }
            annotation = {
                "case_id": "CASO-AUT", "input_sha256": "a" * 64, "mode": "plan-only",
                "operational_status": "PROPOSTO", "evidence_gate": {"state": "BLOCKED"},
                "observations": [], "evidence_retrievals": [], "limitations": [],
            }
            qc_path.write_text(json.dumps(qc), encoding="utf-8")
            annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
            return build_manifest(qc, annotation, qc_path, annotation_path, consent=consent)

    def test_the_operation_block_is_declared_so_the_gates_run(self):
        manifest = self._manifest()
        self.assertTrue(manifest["session_id"])
        self.assertIs(manifest["operation"]["analysis_relevant"], True)
        self.assertIs(manifest["operation"]["requires_real_calling"], False)
        self.assertEqual(manifest["operation"]["output"], "ANALYSIS")
        self.assertIsInstance(manifest["section_attestations"], list)

    def test_the_session_id_is_bound_to_the_bytes_analysed(self):
        self.assertIn("a" * 16, self._manifest()["session_id"])

    def test_consent_is_unverified_when_no_record_was_supplied(self):
        consent = self._manifest()["consent"]
        self.assertIs(consent["verified"], False)
        self.assertIn("nenhum registro de consentimento", consent["basis"])

    def test_a_supplied_consent_record_is_carried_not_invented(self):
        from tests.attestations import consent_record

        record = consent_record(
            case_id="CASO-AUT", input_sha256="a" * 64,
            version="v2", authorized_domains=["CLÍNICO"],
        )
        consent = self._manifest(record)["consent"]
        self.assertIs(consent["verified"], True)
        self.assertEqual(consent["version"], "v2")
        self.assertEqual(consent["authorized_domains"], ["CLÍNICO"])
        self.assertEqual(consent["subject_id"], record["subject_id"])

    def test_three_typed_fields_no_longer_clear_the_gate(self):
        """The exact payload that used to pass: the whole of what consent had to be.

        `--consent '{"verified": true, "version": "x", "authorized_domains": ["CLÍNICO"]}'`
        satisfied every check CONSENT_GATE makes, and CONSENT_GATE is what stands between a
        genomic file and a published report about a person.
        """
        consent = self._manifest(
            {"verified": True, "version": "v2", "authorized_domains": ["CLÍNICO"]}
        )["consent"]
        self.assertIs(consent["verified"], False)
        self.assertIn("recusado", consent["basis"])

    def test_a_record_for_another_case_does_not_authorise_this_one(self):
        from tests.attestations import consent_record

        consent = self._manifest(
            consent_record(case_id="OUTRO-CASO", input_sha256="a" * 64)
        )["consent"]
        self.assertIs(consent["verified"], False)
        self.assertIn("não viaja entre casos", consent["basis"])

    def test_a_record_for_other_bytes_does_not_authorise_this_file(self):
        from tests.attestations import consent_record

        consent = self._manifest(
            consent_record(case_id="CASO-AUT", input_sha256="b" * 64)
        )["consent"]
        self.assertIs(consent["verified"], False)
        self.assertIn("não viaja entre arquivos", consent["basis"])

    def test_the_inputs_carry_provenance_for_the_provenance_gate(self):
        for artifact in self._manifest()["inputs"]:
            for field in ("id", "kind", "source", "sha256"):
                self.assertTrue(artifact.get(field), artifact)
            if artifact.get("transformed"):
                self.assertTrue(artifact.get("parent_sha256"))


if __name__ == "__main__":
    unittest.main()


class OrchestratorAsksTheEngineTest(unittest.TestCase):
    """`run_full_case` had no policy plane at all — the engine could never disagree."""

    #: The aliases `run_full_case.run` imports its eleven builders under.
    BUILDERS = frozenset({"p01", "p02", "p03", "p05", "p06", "p09", "p10", "p11", "passoc"})

    def _builder_calls(self):
        """Every call to a report builder inside `run`, as AST nodes.

        Read from the syntax tree rather than matched as text: the first version of this test
        asserted on literal call strings like `p05(qc_path, matrix_path, probe_path,
        policy_path)`, so reformatting the call broke the test while adding a *new* builder
        that received nothing would not have. What matters is that each call carries the
        run's single verdict and its single witness, not how the line is wrapped.
        """
        tree = ast.parse((ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8"))
        run = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        return [
            node for node in ast.walk(run)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in self.BUILDERS
        ]

    def test_the_entrypoint_runs_the_engine_and_threads_its_verdict(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn("def evaluate_policy(", source)
        self.assertIn('"genoma_policy", "evaluate"', source)

        calls = self._builder_calls()
        self.assertEqual(len(self.BUILDERS), len({c.func.id for c in calls}))
        for call in calls:
            passed = {
                node.id for node in ast.walk(call)
                if isinstance(node, ast.Name) and node.id in {"policy_path", "witness_path"}
            }
            # Every builder receives the same evaluation and the same witness; none composes
            # either. `build_association_report` accepted `policy_evaluation` and dropped it
            # on the floor, so reports 04/07/08 took the refusal path whatever the engine had
            # said — which is why the signature check below exists as well.
            self.assertEqual(
                {"policy_path", "witness_path"}, passed,
                f"{call.func.id} at line {call.lineno} does not receive both",
            )

    def test_every_builder_accepts_the_verdict_and_the_witness(self):
        """A parameter the builder accepts and never forwards is not plumbing."""
        modules = (
            "build_clinical_report", "build_ancestry_report", "build_reproductive_report",
            "build_association_report", "build_technical_report",
            "build_pharmacogenomic_report", "build_completeness_report",
            "build_one_page_summary", "build_editorial_guide",
        )
        for name in modules:
            module = importlib.import_module(f"scripts.{name}")
            parameters = inspect.signature(module.build_payload).parameters
            with self.subTest(module=name):
                self.assertIn("policy_evaluation", parameters)
                self.assertIn("post_deployment_witness", parameters)
                source = inspect.getsource(module.build_payload)
                self.assertIn("policy_evaluation=policy_evaluation", source)
                self.assertIn("post_deployment_witness=post_deployment_witness", source)

    def test_the_plaintext_ruleset_is_removed_after_the_evaluation(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn("stale.unlink(missing_ok=True)", source)

    def test_consent_is_an_input_the_operator_supplies(self):
        source = (ROOT / "scripts/run_full_case.py").read_text(encoding="utf-8")
        self.assertIn('"--consent"', source)
