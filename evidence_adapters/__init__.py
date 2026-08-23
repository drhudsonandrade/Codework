from __future__ import annotations

import hashlib
import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

HeaderValue = str | tuple[str, ...] | list[str]
Transport = Callable[[urllib.request.Request], tuple[bytes, Mapping[str, HeaderValue]]]
LOGGER = logging.getLogger(__name__)
PUBLIC_RETRIEVAL_ERROR = "evidence source retrieval failed"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class EvidenceURLPolicyError(ValueError):
    """Raised when an evidence request violates the fixed outbound URL policy."""


class EvidenceResponseTooLargeError(ValueError):
    """Raised when an evidence response exceeds the fixed retrieval budget."""


def _normalize_headers(headers: Mapping[str, HeaderValue]) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for key, raw in headers.items():
        name = str(key).lower()
        if isinstance(raw, str):
            values = (raw,)
        else:
            values = tuple(str(value) for value in raw)
        if not values:
            continue
        normalized[name] = normalized.get(name, ()) + values
    return normalized


def _first_header(headers: Mapping[str, tuple[str, ...]], name: str) -> str | None:
    values = headers.get(name.lower(), ())
    return values[0] if values else None


def _default_transport(request: urllib.request.Request) -> tuple[bytes, Mapping[str, HeaderValue]]:
    _validate_request(request)
    initial_host = urllib.parse.urlparse(request.full_url).hostname
    opener = urllib.request.build_opener(_AllowlistedRedirectHandler(initial_host))
    with opener.open(request, timeout=30) as response:
        headers: dict[str, tuple[str, ...]] = {}
        for name in response.headers:
            values = response.headers.get_all(name) or []
            if values:
                headers[str(name).lower()] = tuple(str(value) for value in values)
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise EvidenceResponseTooLargeError(
                f"evidence response exceeds {MAX_RESPONSE_BYTES} bytes"
            )
        return payload, headers


def _qs(params: dict[str, Any]) -> str:
    return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)


@dataclass(frozen=True)
class AdapterSpec:
    name: str
    base_url: str
    kind: str
    official: bool = True


SPECS = {
    "clinvar": AdapterSpec("ClinVar", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/", "clinvar"),
    "clingen": AdapterSpec("ClinGen", "https://erepo.clinicalgenome.org/evrepo/api/", "clingen"),
    "cpic": AdapterSpec("CPIC", "https://api.cpicpgx.org/v1/", "cpic"),
    "clinpgx": AdapterSpec("ClinPGx", "https://api.clinpgx.org/v1/", "clinpgx"),
    "gnomad": AdapterSpec("gnomAD", "https://gnomad.broadinstitute.org/api", "gnomad"),
    "pgs_catalog": AdapterSpec("PGS Catalog", "https://www.pgscatalog.org/rest/", "pgs_catalog"),
}
ALLOWED_HOSTS = frozenset(
    host
    for spec in SPECS.values()
    if (host := urllib.parse.urlparse(spec.base_url).hostname) is not None
)


def _validate_url(url: str, *, expected_host: str | None = None) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise EvidenceURLPolicyError("evidence adapters require HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise EvidenceURLPolicyError("credentials are not allowed in evidence URLs")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise EvidenceURLPolicyError("evidence host is not allowlisted")
    if expected_host is not None and parsed.hostname != expected_host:
        raise EvidenceURLPolicyError("evidence request changed its configured host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EvidenceURLPolicyError("evidence URL contains an invalid port") from exc
    if port not in (None, 443):
        raise EvidenceURLPolicyError("evidence adapters only allow HTTPS port 443")
    if parsed.fragment:
        raise EvidenceURLPolicyError("URL fragments are not allowed in evidence requests")


def _validate_request(request: urllib.request.Request, *, expected_host: str | None = None) -> None:
    _validate_url(request.full_url, expected_host=expected_host)


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, expected_host: str | None):
        super().__init__()
        self.expected_host = expected_host

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_url(newurl, expected_host=self.expected_host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class EvidenceAdapter:
    def __init__(self, key: str, *, transport: Transport | None = None):
        if key not in SPECS:
            raise KeyError(key)
        self.key = key
        self.spec = SPECS[key]
        self.transport = transport or _default_transport

    def _request(self, query: dict[str, Any]) -> urllib.request.Request:
        if self.key == "clinvar":
            term = str(query.get("term") or "")
            url = self.spec.base_url + "esearch.fcgi?" + _qs({"db": "clinvar", "term": term, "retmax": int(query.get("retmax", 20)), "retmode": "json"})
            return urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        if self.key == "clingen":
            path = str(query.get("path") or "classifications").lstrip("/")
            params = query.get("params") if isinstance(query.get("params"), dict) else {}
            url = self.spec.base_url + path + (("?" + _qs(params)) if params else "")
            return urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        if self.key == "cpic":
            path = str(query.get("path") or "guideline_summary_view").lstrip("/")
            params = query.get("params") if isinstance(query.get("params"), dict) else {}
            if "limit" in query:
                params = {**params, "limit": query["limit"]}
            url = self.spec.base_url + path + (("?" + _qs(params)) if params else "")
            return urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        if self.key == "clinpgx":
            # ClinPGx publishes an OpenAPI contract at /openapi.json. Query parameters
            # are endpoint-specific (for /data/gene: accessionId, symbol, view); unlike
            # CPIC, a generic `limit` parameter is not valid. We therefore pass only the
            # explicit `params` object and never invent cross-provider pagination fields.
            path = str(query.get("path") or "data/gene").lstrip("/")
            params = query.get("params") if isinstance(query.get("params"), dict) else {}
            url = self.spec.base_url + path + (("?" + _qs(params)) if params else "")
            return urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        if self.key == "gnomad":
            graphql = str(query.get("graphql") or "query { __typename }")
            variables = query.get("variables") if isinstance(query.get("variables"), dict) else {}
            body = json.dumps({"query": graphql, "variables": variables}, ensure_ascii=False, sort_keys=True).encode("utf-8")
            return urllib.request.Request(self.spec.base_url, data=body, method="POST", headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        if self.key == "pgs_catalog":
            score_id = query.get("score_id")
            if score_id:
                path = f"score/{urllib.parse.quote(str(score_id), safe='')}"
            else:
                path = str(query.get("path") or "info").lstrip("/")
            url = self.spec.base_url + path
            return urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "GENOMA-evidence-adapter/1"})
        raise AssertionError(self.key)

    def query(self, query: dict[str, Any], *, checked_at: str) -> dict[str, Any]:
        request = self._request(query)
        locator = request.full_url
        base = {
            "id": f"{self.key}:{hashlib.sha256((locator + json.dumps(query, ensure_ascii=False, sort_keys=True)).encode('utf-8')).hexdigest()[:16]}",
            "name": self.spec.name,
            "adapter": self.key,
            "status": "NÃO DISPONÍVEL",
            "accessible": False,
            "primary_or_official": self.spec.official,
            "mutable": True,
            "checked_at": checked_at,
            "locator": locator,
            "query": query,
            "retrieval_evidence": {"method": "HTTPS"},
        }
        try:
            expected_host = urllib.parse.urlparse(self.spec.base_url).hostname
            _validate_request(request, expected_host=expected_host)
            payload, headers = self.transport(request)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise EvidenceResponseTooLargeError(
                    f"evidence response exceeds {MAX_RESPONSE_BYTES} bytes"
                )
            normalized_headers = _normalize_headers(headers)
            json.loads(payload.decode("utf-8"))
            digest = hashlib.sha256(payload).hexdigest()
            etag = _first_header(normalized_headers, "etag")
            last_modified = _first_header(normalized_headers, "last-modified")
            version = etag or last_modified or f"snapshot-{checked_at}"
            retrieval_evidence: dict[str, Any] = {
                "method": "HTTPS",
                "result_digest": digest,
                "content_type": _first_header(normalized_headers, "content-type"),
            }
            if etag:
                retrieval_evidence["etag"] = etag
                if len(normalized_headers.get("etag", ())) > 1:
                    retrieval_evidence["etag_values"] = list(normalized_headers["etag"])
            if last_modified:
                retrieval_evidence["last_modified"] = last_modified
                if len(normalized_headers.get("last-modified", ())) > 1:
                    retrieval_evidence["last_modified_values"] = list(normalized_headers["last-modified"])
            base.update({
                "status": "VERIFICADO",
                "accessible": True,
                "version": version,
                "version_kind": "http-etag" if etag else ("http-last-modified" if last_modified else "retrieval-snapshot"),
                "retrieval_evidence": retrieval_evidence,
            })
            return base
        except Exception as exc:
            LOGGER.warning(
                "evidence retrieval failed adapter=%s error_class=%s",
                self.key,
                type(exc).__name__,
            )
            base["error_class"] = type(exc).__name__
            base["error"] = PUBLIC_RETRIEVAL_ERROR
            return base


ADAPTERS = {key: spec.name for key, spec in SPECS.items()}


def get_adapter(name: str, *, transport: Transport | None = None) -> EvidenceAdapter:
    return EvidenceAdapter(name, transport=transport)


__all__ = ["ADAPTERS", "EvidenceAdapter", "get_adapter"]
