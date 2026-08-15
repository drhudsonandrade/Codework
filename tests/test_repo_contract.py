import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_repo.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("validate_repo", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load repository validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RepoContractTest(unittest.TestCase):
    def test_contract_detects_missing_paths(self):
        validator = load_validator()
        with tempfile.TemporaryDirectory() as directory:
            errors = validator.validate(Path(directory))
        self.assertTrue(any("missing required path" in error for error in errors))

    def test_contract_accepts_repository_scaffold(self):
        validator = load_validator()
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(validator.validate(root), [])


if __name__ == "__main__":
    unittest.main()
