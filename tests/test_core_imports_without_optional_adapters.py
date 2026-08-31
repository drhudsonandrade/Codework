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
from pathlib import Path
from unittest.mock import patch


class CoreImportsWithoutAdaptersTest(unittest.TestCase):
    """The core modules import and run with the optional adapter package absent."""
    @staticmethod
    def _import_with_adapters_missing(module_name: str):
        """Import `module_name` fresh, with `evidence_adapters` unavailable."""
        real_import = builtins.__import__

        def refuse_adapters(name, *args, **kwargs):
            """An __import__ that refuses evidence_adapters and passes everything else through."""
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
        """Each core module imports with the adapter package absent."""
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
            """An __import__ that refuses evidence_adapters and passes everything else through."""
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
            """An __import__ that refuses evidence_adapters and passes everything else through."""
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

    @staticmethod
    def _real_run_inputs(root):
        """A genotype file and a QC record good enough for a real plan-only run.

        Built with the same sequence `tests/test_partial_genome_annotation.py` uses, because
        the point of the CLI test below is that the refusal comes out of the actual code path
        — not out of a patched stand-in that was told to raise.
        """
        import gzip
        import hashlib
        import json

        from array_pipeline.qc import inspect_array

        array = root / "array.csv.gz"
        with gzip.open(array, "wt", encoding="utf-8", newline="") as handle:
            handle.write(
                "RSID,CHROMOSOME,POSITION,CONSENSUS_RESULT,STATUS,"
                "GENERA_RESULT,MYHERITAGE_RESULT,SOURCES\n"
            )
            handle.write("rs1799807,3,165548529,CT,consensus,CT,CT,GM\n")
            handle.write("rs999999,1,100,AA,consensus,AA,AA,GM\n")

        digest = hashlib.sha256(array.read_bytes()).hexdigest()

        def evidence(asserted_value: str) -> str:
            """A build/strand attestation asserting this value."""
            return json.dumps({
                "status": "VERIFICADO",
                "decision": "SATISFIED",
                "asserted_value": asserted_value,
                "justification": "Synthetic fixture explicitly controls build and strand.",
                "evidence_refs": ["synthetic-annotation-fixture"],
                "trace": {
                    "attestation_id": "adapter-absence-fixture",
                    "created_at": "2026-08-17T00:00:00Z",
                    "actor_type": "SOFTWARE",
                    "actor_id": "tests.test_core_imports_without_optional_adapters",
                    "method": "deterministic fixture",
                    "run_id": "unit-test",
                    "input_sha256": [digest],
                    "output_sha256": [],
                    "tool_versions": {"test": "1"},
                },
            })

        qc = inspect_array(
            array,
            case_id="SYN",
            build="GRCh37",
            strand="forward",
            build_evidence=evidence("GRCh37"),
            strand_evidence=evidence("forward"),
        )
        qc_path = root / "qc.json"
        qc_path.write_text(json.dumps(qc), encoding="utf-8")

        # A local, minimal manifest rather than `config/partial_genome_annotation_targets.json`.
        # The contract under test is the absence of the adapter, not the size of the production
        # catalogue: the CLI defaults to `--max-targets 250`, so once that file grows past the
        # limit the *accepting* case below would start failing with exit 2 for a reason with
        # nothing to do with optional adapters, and the control would stop controlling what it
        # claims to. It also adds no coverage here — the synthetic array carries two rsids.
        targets = root / "targets.json"
        targets.write_text(
            json.dumps({
                "schema": "genoma-partial-genome-targets-v1",
                "id": "ADAPTER-ABSENCE-FIXTURE",
                "version": "1",
                "targets": [
                    {
                        "rsid": "rs1799807",
                        "scope": "CLINICO",
                        "label": "fixture",
                        "queries": {"clinvar": {"term": "rs1799807"}},
                    }
                ],
            }),
            encoding="utf-8",
        )
        return array, qc_path, targets

    def test_the_cli_turns_the_refusal_into_its_documented_blocked_exit(self):
        """Plan-only mode cannot degrade — the locator comes from the adapter — so it blocks.

        Driven through the real path: valid inputs, `evidence_adapters` genuinely absent, and
        `annotate_partial_genome` left unpatched, so the `AdapterUnavailableError` is raised
        by `_get_adapter` where it really would be. Patching the function to raise would have
        tested only that the CLI catches an exception someone handed it, and would keep
        passing if the real path stopped producing one.

        The CLI's job is to report it in the shape it reports every other blocked run: a
        named message on stderr and exit 2, rather than a traceback that says nothing about
        which contract stopped the run.
        """
        import importlib
        import tempfile

        cli = importlib.import_module("scripts.annotate_partial_genome")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array, qc_path, targets = self._real_run_inputs(root)
            out = root / "out.json"
            argv = [
                "annotate_partial_genome",
                "--input", str(array), "--qc", str(qc_path),
                "--targets", str(targets), "--output", str(out),
                "--mode", "plan-only",
            ]
            with patch.dict(sys.modules):
                sys.modules.pop("evidence_adapters", None)
                with self._adapters_absent(), patch.object(sys, "argv", argv), patch(
                    "sys.stderr", new=io.StringIO()
                ) as err:
                    code = cli.main()
            self.assertEqual(2, code)
            self.assertIn("ANNOTATION BLOCKED", err.getvalue())
            self.assertIn("adaptador do Evidence Plane", err.getvalue())
            # Blocked means blocked: no artifact is written for a run that never retrieved.
            self.assertFalse(out.exists())

    def test_the_same_inputs_succeed_when_the_adapter_is_present(self):
        """The control: without this, the test above could pass for any reason at all."""
        import importlib
        import tempfile

        cli = importlib.import_module("scripts.annotate_partial_genome")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            array, qc_path, targets = self._real_run_inputs(root)
            out = root / "out.json"
            argv = [
                "annotate_partial_genome",
                "--input", str(array), "--qc", str(qc_path),
                "--targets", str(targets), "--output", str(out),
                "--mode", "plan-only",
            ]
            with patch.object(sys, "argv", argv), patch("sys.stdout", new=io.StringIO()):
                code = cli.main()
            self.assertEqual(0, code)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
