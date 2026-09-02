from __future__ import annotations

import json
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

from array_pipeline.allele_discrimination import partition_alleles
from scripts import (
    build_pgx_panel,
    build_pgx_registry,
    curate_assessed_alleles,
    curate_gene_disease,
    expand_clinvar_targets,
    https_transport,
    verify_provenance_markers,
)


def opener_factory(*results):
    """Stand in for `policy_opener`, returning an opener whose `.open` yields `results`.

    The fetchers no longer call `urllib.request.urlopen`: they build an opener that
    re-applies the transport policy to every redirect hop, so the seam the tests must hold is
    `policy_opener`, not `urlopen`. Patching the old name would leave every one of these
    tests passing without exercising anything.
    """
    opener = MagicMock()
    opener.open.side_effect = list(results)
    return MagicMock(return_value=opener), opener


class CpicRetryPolicyTest(unittest.TestCase):
    """Which CPIC fetch failures are retried and which are not."""
    def test_non_transient_http_error_is_not_retried(self):
        """A 404 is a fact about the request and is not retried."""
        error = urllib.error.HTTPError(
            "https://api.cpicpgx.org/v1/gene", 404, "Not Found", None, None
        )
        factory, opener = opener_factory(error, error, error, error)
        with patch.object(build_pgx_registry, "policy_opener", factory):
            with patch.object(build_pgx_registry.time, "sleep") as slept:
                with self.assertRaises(build_pgx_registry.CpicError):
                    build_pgx_registry._get("gene", attempts=4)
        self.assertEqual(opener.open.call_count, 1)
        slept.assert_not_called()

    def test_transient_http_error_is_retried(self):
        """A 503 is transient and is retried."""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([]).encode()
        error = urllib.error.HTTPError(
            "https://api.cpicpgx.org/v1/gene", 503, "Unavailable", None, None
        )
        factory, opener = opener_factory(error, response)
        with patch.object(build_pgx_registry, "policy_opener", factory):
            with patch.object(build_pgx_registry.time, "sleep") as slept:
                self.assertEqual(build_pgx_registry._get("gene", attempts=2), [])
        self.assertEqual(opener.open.call_count, 2)
        slept.assert_called_once_with(1)

    def test_assessed_allele_fetch_errors_name_the_registry_not_cpic(self):
        """The shared NCBI/GWAS transport does not misattribute failures to CPIC."""
        factory, _opener = opener_factory(urllib.error.URLError("offline"))
        with (
            patch.object(curate_assessed_alleles, "policy_opener", factory),
            self.assertRaisesRegex(
                curate_assessed_alleles.CurationError, "registry fetch failed"
            ),
        ):
            curate_assessed_alleles._get(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", attempts=1
            )
        factory.assert_called_once_with(
            curate_assessed_alleles.is_https, "the public registry API"
        )

    def test_curated_identity_requires_the_live_canonical_spdi(self):
        """Accession and alternate are insufficient when the pinned SPDI disagrees."""
        decision = {
            "assessed_allele": "G",
            "clinvar_accession": "VCV000000010",
            "canonical_spdi": "NC_000006.12:26090950:C:G",
            "basis": "fixture",
        }
        matched = [{
            "alternate": "G",
            "accession": "VCV000000010",
            "canonical_spdi": "NC_000006.12:26090951:C:G",
        }]
        with self.assertRaisesRegex(curate_assessed_alleles.CurationError, "canonical SPDI"):
            curate_assessed_alleles._apply_curated_identity_decision(
                "rs1799945", {"reference_allele": "C"}, matched, decision
            )


class TransportSchemeTest(unittest.TestCase):
    """No fetcher opens a URL whose scheme is not the one it was written for.

    `urllib.request.urlopen` honours `file:`, `ftp:` and `data:` exactly as readily as it
    honours `https:`. Every fetcher in `scripts/` takes its URL from a module constant, a CLI
    flag or a caller argument, so a `file:` URL reaching any of them would turn a *download*
    into a read of the runner's own filesystem, and the bytes would be handed on as if a
    public registry had published them — a curated registry, a marker verification or a
    fifteen-case smoke, all built from local files nobody audited.

    Each case asserts the refusal happens *before* the network layer is reached, by patching
    `policy_opener` to fail loudly if it is ever reached. `RedirectTransportPolicyTest` covers
    the other half: the same policy on every redirect hop, which a check on the initial URL
    cannot reach.
    """

    @staticmethod
    def _never_called(*_args, **_kwargs):
        """A stand-in for `policy_opener` that fails if the guard let the request through.

        It replaces the opener *factory*, not the opener, so a refusal that happened only
        after the transport layer had been built would still be caught.
        """
        raise AssertionError("the transport layer was reached for a refused scheme")

    def test_the_cpic_fetcher_refuses_a_non_https_base(self):
        """A `file:` CPIC base is refused: the allele registry is built from that response."""
        with patch.object(build_pgx_registry, "CPIC_BASE", "file:///etc"):
            with patch.object(build_pgx_registry, "policy_opener", self._never_called):
                with self.assertRaisesRegex(build_pgx_registry.CpicError, "non-HTTPS"):
                    build_pgx_registry._get("passwd")

    def test_the_bulk_export_fetcher_refuses_a_non_https_url(self):
        """A `file:` bulk-export URL is refused: local bytes would become the target panel."""
        with patch.object(expand_clinvar_targets, "policy_opener", self._never_called):
            with self.assertRaisesRegex(RuntimeError, "non-HTTPS"):
                expand_clinvar_targets._fetch("file:///etc/passwd")

    def test_the_dbsnp_fetcher_refuses_a_non_https_endpoint(self):
        """A `file:` dbSNP endpoint is refused: it is the authority the marker table is checked against."""
        with patch.object(verify_provenance_markers, "REFSNP_URL", "file:///etc/{rsid}"):
            with patch.object(verify_provenance_markers, "policy_opener", self._never_called):
                with self.assertRaisesRegex(
                    verify_provenance_markers.MarkerVerificationError, "non-HTTPS"
                ):
                    verify_provenance_markers.fetch_refsnp("rs1800562")

    def test_https_is_still_admitted(self):
        """The negative control: the guard must not refuse the scheme every caller uses."""
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps([]).encode()
        factory, _ = opener_factory(response)
        with patch.object(build_pgx_registry, "policy_opener", factory):
            self.assertEqual(build_pgx_registry._get("gene"), [])


class RedirectTransportPolicyTest(unittest.TestCase):
    """The transport policy holds on every hop, not only on the request the caller built.

    Raised in review on this pull request, and correct: the scheme guard each fetcher applies
    runs once, against the `Request` object. `urllib.request.urlopen` then installs an
    `HTTPRedirectHandler` that follows `Location` without consulting the caller, so
    `https://api.cpicpgx.org/...` answered with `Location: http://attacker/...` was downgraded
    in silence and the fetcher accepted unauthenticated bytes under a check that had already
    passed. A guard on the first URL is not a transport policy.

    These exercise the handler urllib actually calls — `redirect_request`, the single method
    every hop goes through — rather than an initially-bad URL, which the previous tests
    already covered and which never reaches this code path.
    """

    @staticmethod
    def _hop(handler, newurl, *, from_url="https://api.cpicpgx.org/v1/gene"):
        """Ask the handler to follow one redirect, exactly as urllib would."""
        request = urllib.request.Request(from_url)
        return handler.redirect_request(
            request, None, 302, "Found", {"location": newurl}, newurl
        )

    def test_an_https_request_is_not_allowed_to_be_downgraded_to_http(self):
        handler = https_transport.PolicyRedirectHandler(
            https_transport.is_https, "the CPIC API"
        )
        with self.assertRaisesRegex(https_transport.TransportPolicyError, "refusing a redirect"):
            self._hop(handler, "http://attacker.example/v1/gene")

    def test_a_redirect_into_another_scheme_is_refused(self):
        """`file:` and `ftp:` are reachable by redirect exactly as they are by a bad URL."""
        handler = https_transport.PolicyRedirectHandler(
            https_transport.is_https, "the CPIC API"
        )
        for target in ("file:///etc/passwd", "ftp://example/x", "data:text/plain,x"):
            with self.subTest(target=target):
                with self.assertRaises(https_transport.TransportPolicyError):
                    self._hop(handler, target)

    def test_an_https_redirect_is_followed(self):
        """The negative control: the policy must not refuse the hops that are legitimate.

        A CDN or an apex-to-www move is an ordinary HTTPS redirect, and a handler that
        refused those would break every fetcher while looking like a security improvement.
        """
        handler = https_transport.PolicyRedirectHandler(
            https_transport.is_https, "the CPIC API"
        )
        followed = self._hop(handler, "https://cdn.cpicpgx.org/v1/gene")
        self.assertIsNotNone(followed)
        self.assertEqual(followed.full_url, "https://cdn.cpicpgx.org/v1/gene")

    def test_the_live_smoke_allows_http_only_on_its_own_loopback_endpoint(self):
        """HTTP to another host would send the smoke's POST bodies to a third party.

        `http_json` posts the case manifests, so admitting plain HTTP to any host puts the
        payloads on the wire in clear text to whoever answers — reached directly through
        `--base-url`, or by a redirect after the guard has passed.
        """
        allow = https_transport.loopback_http_or_https
        self.assertTrue(allow("http://127.0.0.1:8787/v1/case"))
        self.assertTrue(allow("https://deployed.example/v1/case"))
        for refused in (
            "http://127.0.0.1:9999/v1/case",
            "http://localhost:8787/v1/case",
            "http://attacker.example/v1/case",
            "file:///etc/passwd",
        ):
            with self.subTest(refused=refused):
                self.assertFalse(allow(refused))

        handler = https_transport.PolicyRedirectHandler(allow, "the live smoke")
        with self.assertRaises(https_transport.TransportPolicyError):
            self._hop(
                handler,
                "http://attacker.example/v1/case",
                from_url="http://127.0.0.1:8787/v1/case",
            )

    def test_a_refused_hop_raises_instead_of_returning_the_redirect_body(self):
        """Returning `None` would make urllib hand the 3xx response back as the document.

        That is the failure mode this test exists to keep out: a refusal that reads, to the
        caller, like a successful fetch of a very short body.
        """
        handler = https_transport.PolicyRedirectHandler(
            https_transport.is_https, "the CPIC API"
        )
        try:
            self._hop(handler, "http://attacker.example/")
        except https_transport.TransportPolicyError:
            pass
        else:
            self.fail("a refused hop returned instead of raising")

    def test_every_fetcher_builds_its_opener_through_the_policy(self):
        """The policy is worthless if a fetcher still calls `urlopen` directly.

        Each module is checked for the imported name rather than for a string in its source:
        a module that never imported `policy_opener` cannot be applying it.
        """
        for module in (
            build_pgx_registry,
            expand_clinvar_targets,
            verify_provenance_markers,
            curate_assessed_alleles,
            curate_gene_disease,
        ):
            with self.subTest(module=module.__name__):
                self.assertIs(module.policy_opener, https_transport.policy_opener)
                self.assertIs(module.is_https, https_transport.is_https)


class SharedHttpRetryPolicyTest(unittest.TestCase):
    """The same retry policy, applied by the dbSNP and ClinVar fetchers."""
    @staticmethod
    def _marker_error(code: int):
        """A MarkerVerificationError caused by an HTTPError with this status."""
        http = urllib.error.HTTPError("https://dbsnp", code, "error", None, None)
        try:
            raise verify_provenance_markers.MarkerVerificationError("fetch failed") from http
        except verify_provenance_markers.MarkerVerificationError as exc:
            return exc

    def test_dbsnp_permanent_http_error_is_not_retried(self):
        """A permanent dbSNP error is raised on the first attempt, with no sleep."""
        error = self._marker_error(404)
        with patch.object(
            verify_provenance_markers,
            "fetch_refsnp",
            side_effect=error,
        ) as fetched:
            with patch.object(verify_provenance_markers.time, "sleep") as slept:
                with self.assertRaises(
                    verify_provenance_markers.MarkerVerificationError
                ):
                    verify_provenance_markers._fetch_with_retries("rs1", attempts=4)
        self.assertEqual(fetched.call_count, 1)
        slept.assert_not_called()

    def test_transient_dbsnp_error_is_retried_and_then_succeeds(self):
        """The retry branch itself had no coverage.

        The suite pinned only the permanent-error path and the invalid rsid, so a regression
        that propagated every MarkerVerificationError immediately — losing the retry that
        exists for 429/5xx/URLError — would have left both existing tests green.
        """
        payload = {"refsnp_id": "1"}
        for transient in (429, 503):
            with self.subTest(transient=transient):
                with patch.object(
                    verify_provenance_markers,
                    "fetch_refsnp",
                    side_effect=[self._marker_error(transient), payload],
                ) as fetched, patch.object(
                    verify_provenance_markers.time, "sleep"
                ) as slept:
                    result = verify_provenance_markers._fetch_with_retries(
                        "rs1", attempts=4
                    )
                self.assertEqual(result, payload)
                self.assertEqual(fetched.call_count, 2)
                self.assertEqual(slept.call_count, 1)

    def test_invalid_dbsnp_identifier_fails_before_fetch(self):
        """An identifier that is not an rsid fails before any fetch is attempted."""
        with patch.object(verify_provenance_markers, "fetch_refsnp") as fetched:
            with self.assertRaises(
                verify_provenance_markers.MarkerVerificationError
            ):
                verify_provenance_markers._fetch_with_retries("not-an-rsid")
        fetched.assert_not_called()

    def test_bulk_download_permanent_http_error_is_not_retried(self):
        """A permanent error on the ClinVar bulk download is not retried."""
        error = urllib.error.HTTPError("https://clinvar", 403, "Forbidden", None, None)
        factory, opener = opener_factory(error, error, error, error)
        with patch.object(expand_clinvar_targets, "policy_opener", factory):
            with patch.object(expand_clinvar_targets.time, "sleep") as slept:
                with self.assertRaises(RuntimeError):
                    expand_clinvar_targets._fetch("https://clinvar", attempts=4)
        self.assertEqual(opener.open.call_count, 1)
        slept.assert_not_called()


class PartialDefinitionTest(unittest.TestCase):
    """An allele CPIC defines only partially, and what the consumer may do with it."""
    def test_builder_marks_partial_definition_and_panel_incomplete(self):
        """The builder marks a partial definition and the panel it belongs to as incomplete."""
        rows = {
            "allele": [{"name": "*2", "definitionid": 1}],
            "allele_definition": [
                {"id": 1, "matchesreferencesequence": False, "structuralvariation": False}
            ],
            "sequence_location": [
                {"id": 10, "dbsnpid": "rs1", "position": 1},
                {"id": 11, "dbsnpid": "", "position": 2},
            ],
            "gene": [{"chr": "chr1", "chromosequenceid": "NC_000001.11"}],
            "allele_location_value": [
                {"alleledefinitionid": 1, "locationid": 10, "variantallele": "A"},
                {"alleledefinitionid": 1, "locationid": 11, "variantallele": "T"},
            ],
            "diplotype": [],
        }

        def fake_get(path, **_params):
            """Serve the fixture rows for this CPIC endpoint."""
            return rows[path]

        with patch.object(build_pgx_registry, "_get", side_effect=fake_get):
            with patch.object(build_pgx_registry.time, "sleep"):
                record = build_pgx_registry.fetch_gene("TEST")

        definition = record["alleles"]["TEST*2"]
        self.assertFalse(record["complete_panel"])
        self.assertFalse(definition["definition_complete"])
        self.assertIn("TEST*2 (parcial)", record["alleles_without_usable_snp_definition"])

    def test_consumer_refuses_a_partial_definition_even_when_observed(self):
        """The consumer refuses a partial definition even when its positions were observed."""
        spec = {
            "alleles": {
                "TEST*2": {
                    "definition_complete": False,
                    "defining": [{"rsid": "rs1", "allele": "A"}],
                }
            }
        }
        result = partition_alleles(spec, {"rs1": "OBSERVADO"})
        self.assertEqual(result["discriminable"], [])
        self.assertEqual(result["indiscriminable"], ["TEST*2"])
        self.assertIn("definição parcial", result["alleles"]["TEST*2"]["basis"])


class PgxPanelIdentityTest(unittest.TestCase):
    """The panel's identity, derived from the registry rather than declared."""
    @staticmethod
    def _registry(position=10):
        """A registry whose two alleles place rs1 at these positions."""
        return {
            "id": "fixture",
            "version": "1",
            "source": "fixture",
            "genes": {
                "G": {
                    "alleles": {
                        "G*2": {
                            "defining": [{
                                "rsid": "rs1", "allele": "A", "position": 10,
                                "chromosome": "chr1", "reference_accession": "NC_000001.11",
                                "cpic_location": "loc", "chromosome_location": "1:10",
                            }]
                        },
                        "G*3": {
                            "defining": [{
                                "rsid": "rs1", "allele": "T", "position": position,
                                "chromosome": "chr1", "reference_accession": "NC_000001.11",
                                "cpic_location": "loc", "chromosome_location": "1:10",
                            }]
                        },
                    }
                }
            },
        }

    def test_conflicting_coordinates_for_one_rsid_are_rejected(self):
        """Two coordinates for one rsid are rejected instead of one being picked."""
        with self.assertRaisesRegex(ValueError, "rs1.*position"):
            build_pgx_panel.build_panel(self._registry(position=11))

    def test_version_changes_when_registry_content_changes(self):
        """The panel version changes when the registry content changes."""
        first = build_pgx_panel.build_panel(self._registry())
        second_registry = self._registry()
        second_registry["version"] = "2"
        second = build_pgx_panel.build_panel(second_registry)
        self.assertNotEqual(first["version"], second["version"])

    def test_invalid_grch38_identity_is_rejected(self):
        """Every unusable GRCh38 identity field independently blocks the target."""
        cases = (
            ("position", 0, "position"),
            ("chromosome", "chrUn", "chromosome"),
            ("reference_accession", "GRCh38", "reference_accession"),
        )
        for field, value, expected in cases:
            with self.subTest(field=field):
                invalid = self._registry()
                item = invalid["genes"]["G"]["alleles"]["G*2"]["defining"][0]
                item[field] = value
                with self.assertRaisesRegex(ValueError, rf"rs1.*{expected}"):
                    build_pgx_panel.build_panel(invalid)


if __name__ == "__main__":
    unittest.main()
