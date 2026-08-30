"""The scientific core must import without the Evidence Plane adapter package.

`array_pipeline/annotation.py` imported `evidence_adapters` at module scope, and
`array_pipeline/completeness.py` imported *annotation* purely to reuse one constant. So
importing `completeness` — and everything downstream of it — required an adapter the
repository declares optional (`.coderabbit.yaml` lists `evidence_adapters/**` as such), even
on paths that never retrieve any evidence. A module that cannot be imported without an
optional component has made it mandatory, whatever the contract says.

That is the same defect as the NumPy one on this branch, and it hid better: the package
lives inside this repository, so an "is it a local module?" check counts it as fine.
`scripts/validate_repo.py` now excludes it from that allowance, and these tests pin the
runtime behaviour that check is asserting.
"""
from __future__ import annotations

import builtins
import importlib
import sys
import unittest
from unittest.mock import patch


class CoreImportsWithoutAdaptersTest(unittest.TestCase):
    @staticmethod
    def _import_with_adapters_missing(module_name: str):
        """Import `module_name` fresh, with `evidence_adapters` unavailable."""
        real_import = builtins.__import__

        def refuse_adapters(name, *args, **kwargs):
            if name == "evidence_adapters" or name.startswith("evidence_adapters."):
                raise ImportError("No module named 'evidence_adapters'")
            return real_import(name, *args, **kwargs)

        with patch.dict(sys.modules):
            for loaded in list(sys.modules):
                if loaded.startswith(("array_pipeline", "evidence_adapters")):
                    del sys.modules[loaded]
            with patch.object(builtins, "__import__", side_effect=refuse_adapters):
                return importlib.import_module(module_name)

    def test_the_core_modules_import_with_the_adapter_package_absent(self):
        for module_name in (
            "array_pipeline.claims",
            "array_pipeline.completeness",
            "array_pipeline.pharmacogenomics",
            "array_pipeline.annotation",
        ):
            with self.subTest(module=module_name):
                module = self._import_with_adapters_missing(module_name)
                self.assertIsNotNone(module)

    def test_the_constant_is_the_same_object_wherever_it_is_read(self):
        """Re-exporting must not fork the list into two definitions that can drift."""
        from array_pipeline import annotation, claims, completeness

        self.assertIs(annotation.UNSUPPORTED_ARRAY_CLAIMS, claims.UNSUPPORTED_ARRAY_CLAIMS)
        self.assertIs(completeness.UNSUPPORTED_ARRAY_CLAIMS, claims.UNSUPPORTED_ARRAY_CLAIMS)

    def test_retrieval_refuses_with_a_named_error_when_the_adapter_is_absent(self):
        """Absence must surface as a domain refusal at call time, not an ImportError.

        The point of the lazy load is that evidence retrieval degrades to NÃO DISPONÍVEL
        while the rest of the pipeline keeps working; an unhandled ImportError halfway
        through a run would be the import-time failure moved, not removed.
        """
        from array_pipeline import annotation

        real_import = builtins.__import__

        def refuse_adapters(name, *args, **kwargs):
            if name == "evidence_adapters" or name.startswith("evidence_adapters."):
                raise ImportError("No module named 'evidence_adapters'")
            return real_import(name, *args, **kwargs)

        # The refusal has to be raised by the *call*, so the block has to still be in force
        # when it happens — the package really is installed here, and a check made after the
        # patch lifted would simply import it and pass for the wrong reason.
        with patch.dict(sys.modules):
            sys.modules.pop("evidence_adapters", None)
            with patch.object(builtins, "__import__", side_effect=refuse_adapters):
                with self.assertRaises(annotation.AdapterUnavailableError) as caught:
                    annotation._get_adapter("clinvar")
        self.assertIn("clinvar", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
