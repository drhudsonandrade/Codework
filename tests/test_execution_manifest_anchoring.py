"""The execution manifest is printed, so it has to be anchored like everything else printed.

`PayloadCompiler.compile` serialised `execution_manifest` straight into the payload as
`dict(execution_manifest or {})`. `template_fill` prints it — the workflow-log field reads it
for workflow logs and tool versions — but `provenance_blockers` had no anchor to compare it
against, so editing a tool version, rewriting a log locator, or deleting a key after
compilation produced no blocker and the document went on presenting the result as the record
of how it was made.
"""
from __future__ import annotations

import unittest

from reporting.provenance import ProvenanceError, provenance_blockers
from reporting import provenance as prov


def _payload(**kwargs):
    """A compiled payload. `fixture_payload` supplies its own execution manifest."""
    defaults = {
        "case_id": "CASE-ANCHOR",
        "report_id": "01",
        "summary": "resumo de teste",
        "basis": "teste de ancoragem do manifesto de execução",
    }
    defaults.update(kwargs)
    return prov.fixture_payload(**defaults)


class ExecutionManifestAnchoringTest(unittest.TestCase):
    """Every execution-manifest value must be anchored in the provenance block."""
    def _compiled(self):
        """A compiled payload whose execution manifest is a mapping."""
        payload = _payload()
        self.assertIsInstance(payload.get("execution_manifest"), dict)
        return payload

    def test_every_execution_manifest_key_is_anchored(self):
        """Every execution-manifest key is anchored as a provenance field."""
        payload = self._compiled()
        self.assertTrue(payload["execution_manifest"])
        fields = payload["provenance"]["fields"]
        for key in payload["execution_manifest"]:
            with self.subTest(key=key):
                self.assertIn(f"execution_manifest[{key}]", fields)

    def test_a_clean_payload_has_no_blockers_for_the_manifest(self):
        """A clean payload raises no manifest blocker."""
        payload = self._compiled()
        manifest_blockers = [
            b for b in provenance_blockers(payload) if "execution_manifest" in b
        ]
        self.assertEqual(manifest_blockers, [])

    def test_mutating_a_manifest_value_is_blocked(self):
        """Mutating a manifest value is blocked as a mismatch against its anchor."""
        payload = self._compiled()
        key = sorted(payload["execution_manifest"])[0]
        payload["execution_manifest"][key] = "adulterado"
        self.assertIn(
            f"provenance:mismatch:execution_manifest[{key}]",
            provenance_blockers(payload),
        )

    def test_removing_a_manifest_key_is_blocked(self):
        """Removing a manifest key is blocked as a missing value."""
        payload = self._compiled()
        key = sorted(payload["execution_manifest"])[0]
        del payload["execution_manifest"][key]
        self.assertIn(
            f"provenance:missing_value:execution_manifest[{key}]",
            provenance_blockers(payload),
        )

    def test_adding_an_unanchored_manifest_key_is_blocked(self):
        """Adding a key with no anchor is blocked as unanchored."""
        payload = self._compiled()
        payload["execution_manifest"]["injected"] = "veio de lugar nenhum"
        self.assertIn(
            "provenance:unanchored:execution_manifest[injected]",
            provenance_blockers(payload),
        )

    def test_replacing_the_whole_block_through_extra_is_refused(self):
        """Anchoring each key while letting the container be swapped would close nothing."""
        with self.assertRaises(ProvenanceError) as caught:
            _payload(extra={"execution_manifest": {"workflow": "outro"}})
        self.assertIn("execution_manifest", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
