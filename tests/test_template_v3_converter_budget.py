"""The external page converters must be bounded and speak the renderer's error type.

``pdftocairo`` and ``pdftoppm`` are third-party binaries running on untrusted-length
input. Without an explicit budget a wedged converter blocks the whole render, and
without translation its failures escape as ``CalledProcessError``/``TimeoutExpired``,
past every caller written to handle ``TemplateV3Error``.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reporting.template_v3 import (
    PAGE_CONVERSION_TIMEOUT_SECONDS,
    TemplateV3Error,
    _convert_template_pages,
)


class TemplateV3ConverterBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.work = Path(self._tmp.name)
        self.template = self.work / "template.pdf"
        self.template.write_bytes(b"%PDF-1.7\n")
        # Both binaries are reported present so the tests exercise execution, not
        # the missing-dependency branch.
        which = mock.patch(
            "reporting.template_v3.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        )
        which.start()
        self.addCleanup(which.stop)

    def test_every_converter_invocation_carries_an_explicit_timeout(self) -> None:
        def fake_run(argv, **kwargs):
            self.assertEqual(kwargs.get("timeout"), PAGE_CONVERSION_TIMEOUT_SECONDS)
            if "-svg" in argv:
                Path(argv[-1]).write_text("<svg/>", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run) as run:
            svgs, pngs = _convert_template_pages(self.template, self.work, 2)

        self.assertEqual(len(svgs), 2)
        self.assertEqual(len(pngs), 2)
        self.assertEqual(run.call_count, 4, "two converters per page")

    def test_a_hung_converter_becomes_a_template_error_naming_tool_and_page(self) -> None:
        for tool, marker in (("pdftocairo", "-svg"), ("pdftoppm", "-png")):
            with self.subTest(tool=tool):

                def fake_run(argv, **kwargs):
                    if marker in argv:
                        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
                    Path(argv[-1]).write_text("<svg/>", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0)

                with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
                    with self.assertRaises(TemplateV3Error) as caught:
                        _convert_template_pages(self.template, self.work, 1)
                message = str(caught.exception)
                self.assertIn(tool, message)
                self.assertIn("page 1", message)
                self.assertIn(str(PAGE_CONVERSION_TIMEOUT_SECONDS), message)

    def test_a_failing_converter_becomes_a_template_error_naming_tool_and_page(self) -> None:
        for tool, marker in (("pdftocairo", "-svg"), ("pdftoppm", "-png")):
            with self.subTest(tool=tool):

                def fake_run(argv, **kwargs):
                    if marker in argv:
                        raise subprocess.CalledProcessError(3, argv)
                    Path(argv[-1]).write_text("<svg/>", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0)

                with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
                    with self.assertRaises(TemplateV3Error) as caught:
                        _convert_template_pages(self.template, self.work, 1)
                message = str(caught.exception)
                self.assertIn(tool, message)
                self.assertIn("page 1", message)
                self.assertIn("3", message)

    def test_the_converters_own_diagnosis_survives_into_the_domain_error(self) -> None:
        """An exit status cannot separate a bad PDF from a missing font; stderr can."""
        for tool, marker in (("pdftocairo", "-svg"), ("pdftoppm", "-png")):
            with self.subTest(tool=tool):

                def fake_run(argv, **kwargs):
                    self.assertEqual(
                        kwargs.get("stderr"),
                        subprocess.PIPE,
                        "stderr must be captured, not discarded",
                    )
                    if marker in argv:
                        raise subprocess.CalledProcessError(
                            1, argv, stderr=b"Syntax Error: Couldn't find trailer dictionary\n"
                        )
                    Path(argv[-1]).write_text("<svg/>", encoding="utf-8")
                    return subprocess.CompletedProcess(argv, 0)

                with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
                    with self.assertRaises(TemplateV3Error) as caught:
                        _convert_template_pages(self.template, self.work, 1)
                self.assertIn("Couldn't find trailer dictionary", str(caught.exception))

    def test_two_failures_with_the_same_exit_status_remain_distinguishable(self) -> None:
        """The regression itself: identical status, different cause, same message before."""
        messages = []
        for diagnosis in (b"Syntax Error: Couldn't find trailer dictionary\n", b"Error: Cannot open output file\n"):

            def fake_run(argv, _diagnosis=diagnosis, **kwargs):
                raise subprocess.CalledProcessError(1, argv, stderr=_diagnosis)

            with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
                with self.assertRaises(TemplateV3Error) as caught:
                    _convert_template_pages(self.template, self.work, 1)
            messages.append(str(caught.exception))
        self.assertNotEqual(messages[0], messages[1])

    def test_a_converter_that_fails_silently_still_reports_tool_and_page(self) -> None:
        def fake_run(argv, **kwargs):
            raise subprocess.CalledProcessError(1, argv, stderr=b"")

        with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
            with self.assertRaises(TemplateV3Error) as caught:
                _convert_template_pages(self.template, self.work, 1)
        message = str(caught.exception)
        self.assertIn("pdftocairo", message)
        self.assertIn("page 1", message)

    def test_converters_run_from_the_resolved_absolute_path(self) -> None:
        """What ``shutil.which`` validated has to be what is executed."""
        seen: list[str] = []

        def fake_run(argv, **kwargs):
            seen.append(argv[0])
            if "-svg" in argv:
                Path(argv[-1]).write_text("<svg/>", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0)

        with mock.patch("reporting.template_v3.subprocess.run", side_effect=fake_run):
            _convert_template_pages(self.template, self.work, 1)

        self.assertEqual(seen, ["/usr/bin/pdftocairo", "/usr/bin/pdftoppm"])

    def test_a_missing_converter_still_fails_before_any_execution(self) -> None:
        with mock.patch("reporting.template_v3.shutil.which", return_value=None):
            with mock.patch("reporting.template_v3.subprocess.run") as run:
                with self.assertRaises(TemplateV3Error):
                    _convert_template_pages(self.template, self.work, 1)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
