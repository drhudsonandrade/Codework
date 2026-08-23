"""The Python versions across build, CI and runtime must stay mutually coherent.

The repository deliberately runs on more than one interpreter: the conda NGS
image pins one version in environment.yml, GitHub Actions and the policy image
run another, and policy_engine/pyproject.toml declares the floor both must clear.
That is supportable, but only while it is stated. Left implicit, the interpreters
drift apart until code validated by CI fails inside the container that actually
runs the pipeline — so the relationship is pinned here instead of assumed.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "policy_engine" / "pyproject.toml"
ENVIRONMENT = ROOT / "environment.yml"
POLICY_DOCKERFILE = ROOT / "policy_engine" / "Dockerfile"
WORKFLOWS = ROOT / ".github" / "workflows"


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def _declared_floor() -> tuple[int, ...]:
    match = re.search(r'^requires-python\s*=\s*">=\s*([0-9]+(?:\.[0-9]+)*)"', PYPROJECT.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise AssertionError("policy_engine/pyproject.toml must declare a '>=' requires-python floor")
    return _version(match.group(1))


class PythonRuntimeVersionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.floor = _declared_floor()

    def test_conda_environment_python_clears_the_declared_floor(self) -> None:
        match = re.search(r"^\s*-\s*python=([0-9]+(?:\.[0-9]+)*)\s*$", ENVIRONMENT.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(match, "environment.yml must pin an explicit python version")
        assert match is not None
        self.assertGreaterEqual(
            _version(match.group(1)),
            self.floor,
            f"environment.yml pins python={match.group(1)}, below the declared floor "
            f"{'.'.join(str(p) for p in self.floor)}; the NGS image would run code CI never validates",
        )

    def test_policy_image_python_clears_the_declared_floor(self) -> None:
        match = re.search(r"^FROM python:([0-9]+(?:\.[0-9]+)*)", POLICY_DOCKERFILE.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(match, "policy_engine/Dockerfile must pin an explicit python base image")
        assert match is not None
        self.assertGreaterEqual(_version(match.group(1)), self.floor)

    def test_every_workflow_python_clears_the_declared_floor(self) -> None:
        seen = 0
        for workflow in sorted(WORKFLOWS.glob("*.yml")):
            for raw in re.findall(
                r"^\s*python-version:\s*['\"]?([0-9]+(?:\.[0-9]+)*)['\"]?\s*$",
                workflow.read_text(encoding="utf-8"),
                re.MULTILINE,
            ):
                seen += 1
                with self.subTest(workflow=workflow.name, version=raw):
                    self.assertGreaterEqual(_version(raw), self.floor)
        self.assertGreater(seen, 0, "no workflow declares a python-version to check")

    def test_continuous_integration_pins_one_python_version(self) -> None:
        """Every job must agree, so a green check means the same interpreter everywhere."""
        versions = {
            raw
            for workflow in WORKFLOWS.glob("*.yml")
            for raw in re.findall(
                r"^\s*python-version:\s*['\"]?([0-9]+(?:\.[0-9]+)*)['\"]?\s*$",
                workflow.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        }
        self.assertEqual(len(versions), 1, f"workflows disagree on the CI interpreter: {sorted(versions)}")


if __name__ == "__main__":
    unittest.main()
