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
import io
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


class AdapterAbsenceReachesTheCallerAsARefusalTest(unittest.TestCase):
    """Raising a named error is only half of it: someone has to be catching it.

    `_get_adapter` converts the absent package into `AdapterUnavailableError` so retrieval can
    degrade to NÃO DISPONÍVEL — but nothing on either path was catching it.
    `_live_retrieve` loaded the adapter *before* the `try` that turns a failed retrieval into
    a NÃO DISPONÍVEL record, and `scripts/annotate_partial_genome.py` caught only
    `(ValueError, OSError, JSONDecodeError)`, so the error escaped as an unhandled traceback:
    no `ANNOTATION BLOCKED` line, no exit code 2, no artifact. The import-time failure had
    been moved to call time, not removed.
    """

    @staticmethod
    def _adapters_absent():
        """A context manager under which importing `evidence_adapters` fails."""
        real_import = builtins.__import__

        def refuse_adapters(name, *args, **kwargs):
            if name == "evidence_adapters" or name.startswith("evidence_adapters."):
                raise ImportError("No module named 'evidence_adapters'")
            return real_import(name, *args, **kwargs)

        return patch.object(builtins, "__import__", side_effect=refuse_adapters)

    def test_live_retrieval_records_a_refusal_instead_of_raising(self):
        """Live mode degrades: the retrieval is NÃO DISPONÍVEL and the run continues."""
        from array_pipeline import annotation

        with patch.dict(sys.modules):
            sys.modules.pop("evidence_adapters", None)
            with self._adapters_absent():
                record = annotation._live_retrieve(
                    "clinvar", {"term": "rs1799945"}, "2026-08-30T00:00:00Z",
                    max_payload_bytes=1000,
                )
        self.assertEqual("NÃO DISPONÍVEL", record["status"])
        self.assertEqual("AdapterUnavailableError", record["error_class"])
        self.assertEqual("clinvar", record["source"])
        # The record still identifies what was attempted, so the refusal is auditable.
        self.assertEqual({"term": "rs1799945"}, record["query"])
        self.assertIn("clinvar", record["error"])

    def test_the_cli_turns_the_refusal_into_its_documented_blocked_exit(self):
        """Plan-only mode cannot degrade — the locator comes from the adapter — so it blocks.

        `annotate_partial_genome` raises, and the CLI's job is to report that in the shape it
        reports every other blocked run: a named message on stderr and exit 2, rather than a
        traceback that says nothing about which contract stopped the run.
        """
        import importlib

        from array_pipeline.annotation import AdapterUnavailableError

        cli = importlib.import_module("scripts.annotate_partial_genome")
        argv = [
            "annotate_partial_genome", "--input", "in.csv", "--qc", "qc.json",
            "--output", "out.json", "--mode", "plan-only",
        ]
        with patch.object(
            cli, "annotate_partial_genome",
            side_effect=AdapterUnavailableError("adaptador do Evidence Plane indisponível"),
        ), patch.object(sys, "argv", argv), patch("sys.stderr", new=io.StringIO()) as err:
            code = cli.main()
        self.assertEqual(2, code)
        self.assertIn("ANNOTATION BLOCKED", err.getvalue())
        self.assertIn("indisponível", err.getvalue())


if __name__ == "__main__":
    unittest.main()
