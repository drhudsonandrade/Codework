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
            # The parse result used to be discarded, so any decodable JSON became
            # VERIFICADO — including `{}` and a provider's own error envelope. Bytes that
            # parse are not an answer to the question that was asked.
            document = json.loads(payload.decode("utf-8"))
            problem = _semantic_problem(self.key, document)
            if problem:
                base.update({
                    "status": "NÃO DISPONÍVEL",
                    "accessible": True,
                    "evidence_grade": "NÃO RECUPERADO",
                    "semantic_refusal": problem,
                    "retrieval_evidence": {
                        "method": "HTTPS",
                        "result_digest": hashlib.sha256(payload).hexdigest(),
                        "content_type": normalized_headers.get("content-type"),
                    },
                })
                return base
            digest = hashlib.sha256(payload).hexdigest()
            version = normalized_headers.get("etag") or normalized_headers.get("last-modified") or f"snapshot-{checked_at}"
            base.update({
                "status": "VERIFICADO",
                "accessible": True,
                # VERIFICADO here has always meant "these bytes were fetched and parsed",
                # never "the science in them was reviewed". Saying so in its own field stops
                # a consumer reading a successful HTTP call as curated evidence.
                "evidence_grade": "RECUPERAÇÃO VERIFICADA",
                "evidence_grade_note": (
                    "recuperação verificada: bytes obtidos, decodificados e conferidos contra "
                    "um envelope de erro ou resultado vazio. Não é curadoria científica; "
                    "classificação clínica exige revisão humana registrada."
                ),
                "record_count": _record_count(self.key, document),
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


#: Keys a provider uses to say "this went wrong" while still returning HTTP 200 and valid
#: JSON. Checked generically because every provider spells it differently and a response
#: carrying one of these is a refusal, not a result.
ERROR_ENVELOPE_KEYS = ("error", "errors", "fault", "exception", "detail")

#: Where each provider puts the records, so "zero results" can be told from "results".
#: A provider absent from this map is checked only for emptiness of the document itself —
#: stated rather than silently assumed complete.
RECORD_CONTAINERS: dict[str, tuple[str, ...]] = {
    "clinvar": ("esearchresult", "idlist"),
    "clingen": ("rows",),
    "cpic": (),
    "clinpgx": (),
    "gnomad": ("data",),
    "pgs_catalog": ("results",),
}


def _walk(document: Any, path: tuple[str, ...]) -> Any:
    current = document
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _semantic_problem(key: str, document: Any) -> str | None:
    """Why this response is not an answer, or None if it is one.

    Deliberately conservative: it refuses an error envelope and an empty document, and it
    does not attempt to judge whether the content is scientifically right. That distinction
    is the point — retrieval and curation are different claims, and only the first is
    something this adapter can make.
    """
    if document is None:
        return "resposta JSON nula"
    if isinstance(document, (list, dict)) and len(document) == 0:
        return "resposta vazia: o provedor retornou um documento sem conteúdo"
    if isinstance(document, dict):
        for envelope in ERROR_ENVELOPE_KEYS:
            value = document.get(envelope)
            if value:
                return f"envelope de erro do provedor em {envelope!r}: {str(value)[:200]}"
        # ClinVar reports its failures inside the result object rather than at the top.
        esearch = document.get("esearchresult")
        if isinstance(esearch, dict) and esearch.get("ERROR"):
            return f"erro do ClinVar: {str(esearch['ERROR'])[:200]}"
    return None


def _record_count(key: str, document: Any) -> int | None:
    """How many records came back, or None when this adapter cannot tell.

    None is not zero. A provider whose container is unknown returns None so that a reader
    cannot mistake "not counted" for "counted and empty" — the same distinction the rest of
    this project draws between NÃO INTERROGADO and NEGATIVO.
    """
    container = RECORD_CONTAINERS.get(key)
    if not container:
        return None
    value = _walk(document, container)
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, dict):
        return len(value)
    return None


ADAPTERS = {key: spec.name for key, spec in SPECS.items()}


def get_adapter(name: str, *, transport: Transport | None = None) -> EvidenceAdapter:
    return EvidenceAdapter(name, transport=transport)


__all__ = ["ADAPTERS", "EvidenceAdapter", "get_adapter"]
