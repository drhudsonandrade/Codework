import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY_TESTS = ROOT / "policy_engine" / "tests"


class PolicyEngineUtf8PortabilityTest(unittest.TestCase):
    def test_policy_engine_test_reads_are_explicit_utf8(self):
        violations: list[str] = []
        for path in sorted(POLICY_TESTS.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute) or node.func.attr != "read_text":
                    continue
                encoding = next((kw.value for kw in node.keywords if kw.arg == "encoding"), None)
                if not isinstance(encoding, ast.Constant) or encoding.value != "utf-8":
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual([], violations, f"read_text calls without explicit UTF-8: {violations}")
