"""The bootstrap probe replaced a human, so it must be impossible to satisfy dishonestly.

Every check used to be flipped to `true` by a person who had read the deployed
configuration. Automating that is only an improvement if the automation is *harder* to
fool than the person was — so each test here stands up a deployment that violates exactly
one property and requires the probe to catch it. A probe that cannot fail is not evidence.
"""
from __future__ import annotations

import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import normative
from scripts.verify_bootstrap_live import PROBES, ProbeError, render_attestation, verify


def _compliant_ruleset() -> dict[str, Any]:
    return {
        "status": normative.STATUS,
        "version": normative.VERSION,
        "effective_date": normative.EFFECTIVE_DATE,
        "sha256": normative.RAW_SHA256,
    }


class FakeDeployment:
    """A deployment whose behaviour can be broken one property at a time."""

    def __init__(self, **flaws: bool):
        self.flaws = flaws
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None

    # -- behaviour -------------------------------------------------------------------

    def ruleset(self) -> dict[str, Any]:
        payload = _compliant_ruleset()
        if self.flaws.get("wrong_status"):
            payload["status"] = "REVOGADA"
        # Composed, never written literally: the repository forbids a superseded identity
        # from appearing anywhere in the tree, and a test fixture is no exception. These
        # are "some version that is not the current one", derived from the current one.
        if self.flaws.get("wrong_version"):
            major, minor = normative.VERSION.removeprefix("v").split(".")
            payload["version"] = f"v{major}.{int(minor) - 1}"
        if self.flaws.get("wrong_date"):
            day, month, year = normative.EFFECTIVE_DATE.split("/")
            payload["effective_date"] = f"{int(day) - 3:02d}/{month}/{year}"
        return payload

    def evaluate(self, manifest: dict[str, Any]) -> dict[str, Any]:
        operation = manifest.get("operation") or {}
        declared = manifest.get("ruleset") or {}
        gates: list[dict[str, Any]] = []
        ready = True

        ruleset_ok = (
            declared.get("version") == normative.VERSION
            and declared.get("sha256") == normative.RAW_SHA256
        )
        if self.flaws.get("tolerates_wrong_ruleset"):
            ruleset_ok = True
        gates.append({"gate": "RULESET_GATE", "state": "PASS" if ruleset_ok else "BLOCKED"})
        ready = ready and ruleset_ok

        if operation.get("requires_real_calling"):
            granted = bool(self.flaws.get("skips_runtime_gate"))
            gates.append({"gate": "RUNTIME_RESOURCE_GATE", "state": "PASS" if granted else "BLOCKED"})
            ready = ready and granted

        # The real engine fails an analysis-relevant manifest that carries no inputs or
        # consent, which is why it answers 422. Modelling that keeps the fake faithful.
        if operation.get("analysis_relevant") and not manifest.get("inputs"):
            gates.append({
                "gate": "DATA_PROVENANCE_GATE", "state": "FAIL",
                "reasons": ["analysis-relevant operation has no input artifacts"],
            })
            ready = False

        # Section 261: a QC status outside the vocabulary must be refused, and the refusal
        # must name the vocabulary — that is how the real engine words it
        # ("QC is not EXECUTADO or VERIFICADO").
        qc = manifest.get("qc") or {}
        if qc:
            valid = qc.get("status") in {"EXECUTADO", "VERIFICADO"}
            if self.flaws.get("ignores_status_contract"):
                valid = True
            elif self.flaws.get("rejects_every_status"):
                valid = False
            gates.append(
                {
                    "gate": "QC_GATE",
                    "state": "PASS" if valid else "FAIL",
                    "reasons": [] if valid else ["QC is not EXECUTADO or VERIFICADO"],
                }
            )
            ready = ready and valid

        post = manifest.get("post_deployment") or {}
        if post:
            if self.flaws.get("grants_post_deployment"):
                state = "PASS"
            else:
                state = "PASS" if post.get("live_smoke_count") == 15 and not post.get("critical_failures") else "BLOCKED"
            gates.append({"gate": "POST_DEPLOYMENT_GATE", "state": state})

        if self.flaws.get("waves_analysis_through"):
            gates = []

        payload: dict[str, Any] = {
            "ready_for_requested_operation": ready,
            "gates": gates,
            "ruleset": self.ruleset(),
        }
        return payload

    # -- plumbing --------------------------------------------------------------------

    def __enter__(self) -> str:
        deployment = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status: int, payload: object) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/v1/ruleset":
                    self._send(200, deployment.ruleset())
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                manifest = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/v1/evaluate":
                    payload = deployment.evaluate(manifest)
                    # A conforming deployment answers an unprocessable manifest with 422
                    # while still reporting its gates; that must not read as a probe failure.
                    code = 422 if (deployment.flaws.get("refuse_with_422") and not payload["ready_for_requested_operation"]) else 200
                    self._send(code, payload)
                else:
                    self._send(404, {"error": "not found"})

            def log_message(self, *_args: object) -> None:
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_exc: object) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)


def _verify(url: str):
    return verify(url, deployment_id="deploy-test", revision="abc1234")


class CompliantDeploymentTest(unittest.TestCase):
    def test_a_deployment_that_behaves_correctly_is_verified(self):
        with FakeDeployment() as url:
            result = _verify(url)
        self.assertEqual(result["status"], "VERIFICADO", result["failures"])
        self.assertEqual(result["checks_passed"], result["checks_total"])
        self.assertEqual(result["failures"], [])

    def test_a_conforming_422_refusal_is_not_read_as_a_probe_failure(self):
        """A deployment that answers an incomplete analysis manifest with 422 is conforming.

        The first version of this probe required HTTP 200, so the real policy engine's
        correct fail-closed refusal was scored as a failure.
        """
        deployment = FakeDeployment(refuse_with_422=True)
        with deployment as url:
            result = _verify(url)
        self.assertTrue(result["checks"]["consult_ruleset_before_relevant_genetic_analysis"])
        detail = result["evidence"]["consult_ruleset_before_relevant_genetic_analysis"]
        self.assertEqual(detail["http_status"], 422)

    def test_every_probe_records_a_response_hash(self):
        """The verdict must be recomputable, not merely asserted."""
        with FakeDeployment() as url:
            result = _verify(url)
        for name, detail in result["evidence"].items():
            with self.subTest(check=name):
                self.assertIn("response_sha256", detail)
                self.assertRegex(detail["response_sha256"], r"^[0-9a-f]{64}$")

    def test_the_attestation_names_the_deployment_it_certifies(self):
        with FakeDeployment() as url:
            attestation = render_attestation(_verify(url))
        self.assertEqual(attestation["status"], "VERIFICADO")
        self.assertEqual(attestation["actor_type"], "SOFTWARE")
        self.assertEqual(attestation["deployment"]["revision"], "abc1234")
        self.assertEqual(attestation["deployment"]["deployment_id"], "deploy-test")
        self.assertTrue(all(attestation["checks"].values()))
        self.assertRegex(attestation["evidence_sha256"], r"^[0-9a-f]{64}$")

    def test_the_attestation_covers_exactly_the_shipped_check_names(self):
        """A probe set that drifted from the attestation would silently verify nothing."""
        shipped = json.loads(
            (ROOT / "deploy/attestations/bootstrap-project-v3.4.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(PROBES), set(shipped["checks"]))


class BrokenDeploymentTest(unittest.TestCase):
    """One flaw at a time: each must be caught by its own probe and named in the failure."""

    def _assert_caught(self, check: str, **flaws: bool):
        with FakeDeployment(**flaws) as url:
            result = _verify(url)
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertFalse(result["checks"][check], f"{check} passed against a broken deployment")
        self.assertTrue(any(check in f for f in result["failures"]), result["failures"])
        return result

    def test_a_revoked_ruleset_status_is_caught(self):
        self._assert_caught("require_status_vigente", wrong_status=True)

    def test_a_superseded_ruleset_version_is_caught(self):
        self._assert_caught("require_version_v3_4", wrong_version=True)

    def test_a_wrong_effective_date_is_caught(self):
        self._assert_caught("require_effective_date_2026_08_17", wrong_date=True)

    def test_a_deployment_that_tolerates_a_wrong_ruleset_is_caught(self):
        self._assert_caught(
            "fail_closed_on_missing_or_conflicting_ruleset", tolerates_wrong_ruleset=True
        )

    def test_a_deployment_that_allows_real_calling_without_the_runtime_gate_is_caught(self):
        self._assert_caught("runtime_resource_gate_before_real_calling", skips_runtime_gate=True)

    def test_a_deployment_that_grants_post_deployment_on_an_empty_claim_is_caught(self):
        self._assert_caught(
            "post_deployment_requires_live_15_of_15_zero_critical", grants_post_deployment=True
        )

    def test_a_deployment_that_evaluates_no_gates_is_caught(self):
        self._assert_caught(
            "consult_ruleset_before_relevant_genetic_analysis", waves_analysis_through=True
        )

    def test_a_deployment_failing_for_an_unrelated_reason_does_not_satisfy_the_runtime_probe(self):
        """Specificity: the runtime gate itself must block, not merely some other gate.

        The probe originally accepted any `ready == False`, so a deployment that waved real
        calling through still passed whenever an unrelated gate happened to fail.
        """
        with FakeDeployment(skips_runtime_gate=True) as url:
            result = _verify(url)
        detail = result["evidence"]["runtime_resource_gate_before_real_calling"]
        self.assertEqual(detail["runtime_gate_state"], "PASS")
        self.assertIs(detail["ready_for_requested_operation"], False)
        self.assertFalse(result["checks"]["runtime_resource_gate_before_real_calling"])

    def test_a_deployment_that_accepts_a_status_outside_the_vocabulary_is_caught(self):
        self._assert_caught("operational_status_contract_present", ignores_status_contract=True)

    def test_a_deployment_that_refuses_every_status_does_not_pass_the_contract_probe(self):
        """The paired control: rejecting the invalid status only counts if the valid one passes.

        Without it, a deployment that refused every manifest would satisfy this probe while
        enforcing nothing at all.
        """
        result = self._assert_caught(
            "operational_status_contract_present", rejects_every_status=True
        )
        detail = result["evidence"]["operational_status_contract_present"]
        self.assertTrue(detail["invalid_status_probe"]["qc_gate_objections"])
        self.assertTrue(detail["valid_status_control"]["qc_gate_objections"])

    def test_a_broken_deployment_never_yields_a_verified_attestation(self):
        with FakeDeployment(wrong_version=True) as url:
            attestation = render_attestation(_verify(url))
        self.assertEqual(attestation["status"], "PROPOSTO")
        self.assertIsNone(attestation["verified_at"])
        self.assertIsNone(attestation["actor_id"])
        self.assertTrue(attestation["failures"])


class RefusalTest(unittest.TestCase):
    """There is no offline mode and no self-certification."""

    def test_an_unreachable_deployment_yields_unavailable_not_pass(self):
        # Port 1 on loopback refuses connections.
        result = verify("http://127.0.0.1:1", deployment_id="d", revision="r")
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["checks_passed"], 0)
        self.assertTrue(all(not v for v in result["checks"].values()))

    def test_a_missing_base_url_is_refused(self):
        for url in ("", "   "):
            with self.subTest(url=url), self.assertRaises(ProbeError) as ctx:
                verify(url, deployment_id="d", revision="r")
            self.assertIn("no offline verification mode", str(ctx.exception))

    def test_the_caller_must_name_the_deployment_being_certified(self):
        """Automation establishes behaviour; authorisation stays with the operator."""
        with FakeDeployment() as url:
            for kwargs in ({"deployment_id": "", "revision": "r"}, {"deployment_id": "d", "revision": ""}):
                with self.subTest(**kwargs), self.assertRaises(ProbeError) as ctx:
                    verify(url, **kwargs)
                self.assertIn("required to bind the attestation", str(ctx.exception))

    def test_a_deployment_serving_non_json_is_not_treated_as_passing(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html>tudo certo</html>")

            do_POST = do_GET  # noqa: N815
            def log_message(self, *_a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = verify(
                f"http://127.0.0.1:{server.server_port}", deployment_id="d", revision="r"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        self.assertEqual(result["status"], "NÃO DISPONÍVEL")
        self.assertEqual(result["checks_passed"], 0)


class SmokeChainTest(unittest.TestCase):
    """The generated attestation must actually drive the POST-DEPLOYMENT verdict.

    An attestation the smoke test ignored would make the whole automation decorative, so
    both directions are pinned: a verified one unblocks the bootstrap check, and the same
    attestation with its status downgraded blocks it.
    """

    def _attestation(self, **flaws):
        with FakeDeployment(**flaws) as url:
            return render_attestation(_verify(url))

    def test_a_generated_attestation_satisfies_the_smoke_bootstrap_check(self):
        from scripts.run_live_post_deployment_smoke import evaluate_bootstrap

        ok, reasons = evaluate_bootstrap(self._attestation())
        self.assertTrue(ok, reasons)
        self.assertEqual(reasons, [])

    def test_a_downgraded_attestation_blocks_the_smoke_bootstrap_check(self):
        from scripts.run_live_post_deployment_smoke import evaluate_bootstrap

        attestation = self._attestation()
        attestation["status"] = "PROPOSTO"
        ok, reasons = evaluate_bootstrap(attestation)
        self.assertFalse(ok)
        self.assertTrue(any("PROPOSTO" in r for r in reasons), reasons)

    def test_an_attestation_from_a_broken_deployment_blocks_the_smoke(self):
        from scripts.run_live_post_deployment_smoke import evaluate_bootstrap

        ok, reasons = evaluate_bootstrap(self._attestation(wrong_version=True))
        self.assertFalse(ok)
        self.assertTrue(reasons)

    def test_the_smoke_requires_every_check_the_probe_sets(self):
        """A probe key the smoke does not require would be verified for nothing."""
        from scripts.run_live_post_deployment_smoke import REQUIRED_BOOTSTRAP_CHECKS

        self.assertEqual(set(REQUIRED_BOOTSTRAP_CHECKS), set(PROBES))


if __name__ == "__main__":
    unittest.main()
