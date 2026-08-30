"""The check that says the scientific core has no external runtime dependency.

`scripts/validate_repo.py` printed `PASS optional_adapters` as a literal with nothing behind
it while `array_pipeline/ancestry.py` imported NumPy at module scope. `validate_core_runtime_
dependencies` replaced the literal with an actual walk — and arrived with no test of its own,
so the thing that checks the claim was itself unchecked.

Its first version reasoned that "an import nested in a `try` is guarded by construction" and
looked only at `tree.body`. `tree.body` holds the `ast.Try` node, not the `ast.Import` inside
it, so *any* `try` hid the import from the walk: `try: import numpy` / `except ValueError:`
passed the validator and still raised `ModuleNotFoundError` at import time. What makes an
import optional is the handler catching `ImportError`, which is a property that has to be read
rather than assumed.

These tests run the real function against synthetic package trees, so they assert what it
accepts and refuses rather than restating its implementation.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "validate_repo_under_test",
    Path(__file__).resolve().parents[1] / "scripts" / "validate_repo.py",
)
validate_repo = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = validate_repo
_SPEC.loader.exec_module(validate_repo)


GUARDED = """\
try:
    import numpy as np
except ImportError:
    np = None
"""


class CoreRuntimeDependencyCheckTest(unittest.TestCase):
    def _errors_for(self, source: str) -> list[str]:
        """Run the real check over a throwaway core package containing `source`."""
        errors: list[str] = []
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for package in validate_repo.CORE_PACKAGES:
                (root / package).mkdir()
                (root / package / "__init__.py").write_text("", encoding="utf-8")
            (root / validate_repo.CORE_PACKAGES[0] / "module.py").write_text(
                source, encoding="utf-8"
            )
            validate_repo.validate_core_runtime_dependencies(root, errors)
        return errors

    def assert_refused(self, source: str, name: str = "numpy") -> None:
        errors = self._errors_for(source)
        self.assertTrue(errors, f"expected a refusal, got none for:\n{source}")
        self.assertIn(name, errors[0])

    def test_an_unguarded_module_scope_import_is_refused(self):
        """The original defect: NumPy imported at module scope in the scientific core."""
        self.assert_refused("import numpy as np\n")
        self.assert_refused("from numpy import isfinite\n")

    def test_a_try_except_importerror_guard_is_accepted(self):
        """The accepting case, so every refusal below is a distinction and not a blanket no."""
        self.assertEqual([], self._errors_for(GUARDED))

    def test_a_try_that_catches_something_else_does_not_make_an_import_optional(self):
        """`tree.body` holds the `ast.Try`, so looking only there saw no import at all.

        Each of these still raises `ModuleNotFoundError` when NumPy is absent — the handler
        never runs — while the first version of the check reported them clean.
        """
        for handler in ("ValueError", "OSError", "KeyError"):
            with self.subTest(handler=handler):
                self.assert_refused(
                    f"try:\n    import numpy as np\nexcept {handler}:\n    np = None\n"
                )

    def test_an_over_broad_handler_is_not_accepted_as_a_guard(self):
        """`except Exception` and a bare `except` do catch it, and hide everything else too.

        Refused rather than accepted: the contract is that absence of the adapter degrades to
        a stated refusal, and a handler that also swallows a corrupt install or a failing
        module-level side effect cannot tell the caller which happened.
        """
        for handler in ("Exception", "BaseException", ""):
            with self.subTest(handler=handler or "bare"):
                clause = f"except {handler}:" if handler else "except:"
                self.assert_refused(
                    f"try:\n    import numpy as np\n{clause}\n    np = None\n"
                )

    def test_a_tuple_naming_only_the_import_errors_is_accepted(self):
        for clause in (
            "except (ImportError, ModuleNotFoundError):",
            "except ModuleNotFoundError:",
            "except (ModuleNotFoundError, ImportError):",
        ):
            with self.subTest(clause=clause):
                self.assertEqual(
                    [],
                    self._errors_for(f"try:\n    import numpy as np\n{clause}\n    np = None\n"),
                )

    def test_a_tuple_that_also_catches_something_else_is_not_a_guard(self):
        """`except (ImportError, AttributeError)` does catch it, and hides more than absence.

        This is the same argument that refuses `except Exception`, and the tuple form slipped
        past a check that accepted any handler *containing* ImportError. An `AttributeError`
        raised while the module executes its own import-time code is a defect in the
        dependency, not its absence, and binding `np = None` for it reports a missing optional
        adapter where there is a broken installed one.
        """
        for extra in ("AttributeError", "ValueError", "OSError", "Exception"):
            with self.subTest(extra=extra):
                self.assert_refused(
                    f"try:\n    import numpy as np\n"
                    f"except (ImportError, {extra}):\n    np = None\n"
                )

    def test_an_import_in_else_or_finally_is_not_covered_by_the_handler(self):
        """Only the `try` body is protected; `else` and `finally` run outside it."""
        self.assert_refused(
            "try:\n    pass\nexcept ImportError:\n    pass\nelse:\n    import numpy as np\n"
        )
        self.assert_refused(
            "try:\n    pass\nexcept ImportError:\n    pass\nfinally:\n    import numpy as np\n"
        )

    def test_an_import_nested_deeper_at_module_scope_is_still_found(self):
        """A conditional or a nested `try` executes at import time just the same."""
        self.assert_refused("if True:\n    import numpy as np\n")
        self.assert_refused("while True:\n    import numpy as np\n    break\n")
        self.assert_refused(
            "try:\n    try:\n        import numpy as np\n"
            "    except ValueError:\n        np = None\n"
            "except OSError:\n    np = None\n"
        )

    def test_an_outer_importerror_handler_guards_an_inner_try_that_does_not(self):
        """Accepted, because it genuinely holds: the inner handler declines, the outer catches.

        With NumPy absent the inner `except ValueError` does not match, `ModuleNotFoundError`
        propagates out of the inner `try`, and the outer handler binds `np = None`. The module
        imports. Asserting a refusal here would be refusing correct code — the guard is
        wherever ImportError is actually caught, not necessarily the nearest `try`.
        """
        self.assertEqual(
            [],
            self._errors_for(
                "try:\n    try:\n        import numpy as np\n"
                "    except ValueError:\n        np = None\n"
                "except ImportError:\n    np = None\n"
            ),
        )

    def test_an_except_star_group_is_walked_like_any_other_try(self):
        """`try`/`except*` is a separate AST node, and the walk only knew `ast.Try`.

        `ast.TryStar` (Python 3.11) is not an `ast.Try`, so an import inside one was invisible
        to the walk exactly as every import was before the handler started being read. The
        guard rule is the same, and `except* ImportError` does catch a plain
        `ModuleNotFoundError` raised by the import, so it qualifies.
        """
        for handler in ("ValueError", "OSError", "Exception"):
            with self.subTest(handler=handler):
                self.assert_refused(
                    f"try:\n    import numpy as np\nexcept* {handler}:\n    np = None\n"
                )
        for clause in ("except* ImportError:", "except* ModuleNotFoundError:"):
            with self.subTest(clause=clause):
                self.assertEqual(
                    [],
                    self._errors_for(f"try:\n    import numpy as np\n{clause}\n    np = None\n"),
                )

    def test_an_import_in_a_match_case_is_still_module_scope(self):
        """A `case` body runs at import time like any other branch."""
        self.assert_refused(
            "x = 1\nmatch x:\n    case 1:\n        import numpy as np\n    case _:\n        np = None\n"
        )
        self.assert_refused(
            "x = 1\nmatch x:\n    case 1:\n        pass\n    case _:\n        import numpy as np\n"
        )

    def test_an_import_inside_a_function_is_not_a_module_scope_dependency(self):
        """A lazy import is the pattern this check exists to permit.

        `array_pipeline/annotation.py` loads `evidence_adapters` this way so the core imports
        without it, and flagging that would refuse the very fix the contract asks for.
        """
        self.assertEqual(
            [],
            self._errors_for("def get():\n    import numpy as np\n    return np\n"),
        )
        self.assertEqual(
            [],
            self._errors_for(
                "class Loader:\n    def get(self):\n        import numpy\n        return numpy\n"
            ),
        )

    def test_the_standard_library_and_local_packages_are_allowed(self):
        self.assertEqual([], self._errors_for("import json\nimport math\n"))
        self.assertEqual([], self._errors_for("from array_pipeline import assembly\n"))

    def test_an_optional_local_package_is_not_allowed_at_module_scope(self):
        """It lives in this repository, which is exactly why "is it local?" was the wrong test."""
        for package in sorted(validate_repo.OPTIONAL_LOCAL_PACKAGES):
            with self.subTest(package=package):
                self.assert_refused(f"import {package}\n", name=package)

    def test_the_real_repository_passes_this_check(self):
        """The check is worth nothing if it only ever runs against fixtures."""
        errors: list[str] = []
        validate_repo.validate_core_runtime_dependencies(
            Path(__file__).resolve().parents[1], errors
        )
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
