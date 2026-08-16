from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .engine import PolicyEngine
from .ruleset import compiled_catalog
from .smoke import run_smoke


class PolicyHandler(BaseHTTPRequestHandler):
    engine: PolicyEngine
    server_version = "GENOMA-Policy/0.3.0"

    def _json(self, status: int, payload: object) -> None:
        body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 20 * 1024 * 1024:
            raise ValueError("request body must be between 1 byte and 20 MiB")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._json(200, {"status": "ok", "engine": "genoma-policy-engine", "version": "0.3.0"})
            return
        if self.path == "/v1/ruleset":
            self._json(200, self.engine.ruleset.metadata())
            return
        if self.path == "/v1/catalog":
            self._json(200, compiled_catalog(self.engine.ruleset))
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            if self.path == "/v1/evaluate":
                manifest = self._read_json()
                report = self.engine.evaluate(manifest)
                self._json(200 if report.ready else 422, report.to_dict())
                return
            if self.path == "/v1/smoke":
                self._json(200, run_smoke(self.engine))
                return
            self._json(404, {"error": "not found"})
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": f"policy evaluation failed: {type(exc).__name__}"})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(engine: PolicyEngine, host: str = "127.0.0.1", port: int = 8787) -> None:
    handler = type("BoundPolicyHandler", (PolicyHandler,), {"engine": engine})
    httpd = ThreadingHTTPServer((host, port), handler)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
