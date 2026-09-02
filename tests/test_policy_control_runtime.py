"""Runtime-boundary regressions for canonical policy re-execution."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from policy_engine.genoma_policy import paths
from reporting import policy_control


class PolicyControlRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        _engine, _binding, lifetime = policy_control._runtime()
        lifetime.cleanup()
        policy_control._runtime.cache_clear()

    def tearDown(self) -> None:
        policy_control._runtime.cache_clear()

    def test_runtime_uses_the_shared_canonical_manifest_path(self):
        policy_control._runtime.cache_clear()
        relative = Path("alternate-manifests") / "canonical.sha256"
        temporary = mock.Mock(name="temporary_directory", name_value="unused")
        temporary.name = "/tmp/policy-runtime"
        ruleset = object()
        engine = object()

        with (
            mock.patch.object(paths, "CANONICAL_MANIFEST_RELATIVE", relative),
            mock.patch.object(
                policy_control, "TemporaryDirectory", return_value=temporary
            ),
            mock.patch(
                "scripts.materialize_ruleset.materialize",
                return_value=(Path("/tmp/policy-runtime/ruleset.txt"), {}),
            ),
            mock.patch(
                "policy_engine.genoma_policy.ruleset.load_ruleset", return_value=ruleset
            ),
            mock.patch(
                "policy_engine.genoma_policy.ruleset.verify_external_manifest"
            ) as verify,
            mock.patch(
                "policy_engine.genoma_policy.engine.PolicyEngine", return_value=engine
            ) as ctor,
        ):
            actual_engine, _binding, lifetime = policy_control._runtime()

        expected = Path(policy_control.__file__).resolve().parents[1] / relative
        self.assertIs(actual_engine, engine)
        self.assertIs(lifetime, temporary)
        verify.assert_called_once_with(ruleset, expected)
        ctor.assert_called_once_with(ruleset, external_manifest=expected)

    def test_runtime_cleans_temporary_directory_when_materialization_fails(self):
        policy_control._runtime.cache_clear()
        temporary = mock.Mock(name="temporary_directory")
        temporary.name = "/tmp/policy-runtime"

        with (
            mock.patch.object(
                policy_control, "TemporaryDirectory", return_value=temporary
            ),
            mock.patch(
                "scripts.materialize_ruleset.materialize",
                side_effect=OSError("materialization failed"),
            ),
            self.assertRaises(policy_control.PolicyEvaluationVerificationError),
        ):
            policy_control._runtime()

        temporary.cleanup.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
