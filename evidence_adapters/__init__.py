from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

Transport = Callable[[urllib.request.Request], tuple[bytes, dict[str, str]]]


# These probes run before every real DNA analysis, so an oversized or hanging response
# must degrade the source to NÃO DISPONÍVEL rather than exhaust the runner.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


def _default_transport(request: urllib.request.Request) -> tuple[bytes, dict[str, str]]:
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError(f"provider response exceeds {MAX_RESPONSE_BYTES} bytes")
        return payload, {str(k).lower(): str(v) for k, v in response.headers.items()}


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
            payload, headers = self.transport(request)
            normalized_headers = {str(k).lower(): str(v) for k, v in headers.items()}
            json.loads(payload.decode("utf-8"))
            digest = hashlib.sha256(payload).hexdigest()
            version = normalized_headers.get("etag") or normalized_headers.get("last-modified") or f"snapshot-{checked_at}"
            base.update({
                "status": "VERIFICADO",
                "accessible": True,
                "version": version,
                "version_kind": "http-etag" if normalized_headers.get("etag") else ("http-last-modified" if normalized_headers.get("last-modified") else "retrieval-snapshot"),
                "retrieval_evidence": {
                    "method": "HTTPS",
                    "result_digest": digest,
                    **({"etag": normalized_headers["etag"]} if normalized_headers.get("etag") else {}),
                    **({"last_modified": normalized_headers["last-modified"]} if normalized_headers.get("last-modified") else {}),
                    "content_type": normalized_headers.get("content-type"),
                },
            })
            return base
        except Exception as exc:
            base["error_class"] = type(exc).__name__
            base["error"] = str(exc)[:300]
            return base


ADAPTERS = {key: spec.name for key, spec in SPECS.items()}


def get_adapter(name: str, *, transport: Transport | None = None) -> EvidenceAdapter:
    return EvidenceAdapter(name, transport=transport)


__all__ = ["ADAPTERS", "EvidenceAdapter", "get_adapter"]
