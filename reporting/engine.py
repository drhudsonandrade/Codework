#!/usr/bin/env python3
"""Vendor-neutral deterministic report renderer for the GENOMA v3.0 model suite.

The renderer never interprets DNA. It only turns already-curated, provenance-bearing
structured data into publication artifacts. Scientific interpretation remains upstream
behind the policy/QC/evidence/audit gates.
"""
from __future__ import annotations

import hashlib
import html
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

import normative

from reporting.provenance import provenance_blockers

CATALOG_PATH = ROOT / "catalog.json"
EXPECTED_RULESET = normative.ruleset_block(include_sha256=False)
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")


class ReportReleaseError(RuntimeError):
    pass


def load_catalog() -> dict[str, dict[str, Any]]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or sorted(catalog) != [f"{i:02d}" for i in range(1, 12)]:
        raise ReportReleaseError("report catalog must contain exactly models 01..11")
    required = {"code", "accent", "slug", "title", "tagline", "purpose", "audience", "sections"}
    for report_id, model in catalog.items():
        if not isinstance(model, dict) or not required.issubset(model):
            raise ReportReleaseError(f"report model {report_id} missing v3 editorial metadata")
    return catalog


def _publication_blockers(data: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    ruleset = data.get("ruleset") if isinstance(data.get("ruleset"), dict) else {}
    for key, expected in EXPECTED_RULESET.items():
        if ruleset.get(key) != expected:
            blockers.append(f"ruleset:{key}")

    publication = data.get("publication_gate") if isinstance(data.get("publication_gate"), dict) else {}
    for key in ("passed", "consent_verified", "qc_verified", "evidence_verified", "placeholders_resolved"):
        if publication.get(key) is not True:
            blockers.append(f"publication_gate:{key}")

    policy = data.get("policy_evaluation") if isinstance(data.get("policy_evaluation"), dict) else {}
    if policy.get("ready_for_requested_operation") is not True:
        blockers.append("policy_evaluation:ready_for_requested_operation")
    planes = policy.get("planes") if isinstance(policy.get("planes"), dict) else {}
    for plane_name in REQUIRED_PLANES:
        plane = planes.get(plane_name) if isinstance(planes.get(plane_name), dict) else {}
        if plane.get("state") != "PASS":
            blockers.append(f"policy_evaluation:plane:{plane_name}")

    gates = policy.get("gates") if isinstance(policy.get("gates"), list) else []
    final_audit = next((g for g in gates if isinstance(g, dict) and g.get("gate") == "FINAL_AUDIT_GATE"), None)
    if not isinstance(final_audit, dict) or final_audit.get("state") != "PASS":
        blockers.append("policy_evaluation:FINAL_AUDIT_GATE")

    # PROVENANCE_GATE. The gates above establish that the run was authorized; none of them
    # establishes that the printed sentences came from the data. Without this check the
    # payload is free text, and a hand-typed genotype is indistinguishable from a measured
    # one at every later stage.
    blockers.extend(provenance_blockers(data))
    return blockers


def _safe(value: Any, default: str = "NÃO DISPONÍVEL") -> str:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _model_markdown(report_id: str, model: dict[str, Any]) -> str:
    lines = [
        f"# {model['title']}",
        "",
        f"**{model['tagline']}**",
        "",
        "**MODELO — NÃO É RESULTADO GENÉTICO**",
        "",
        f"Modelo GENOMA v3.0 / {model['code']}. Ruleset exigido: v3.4 / VIGENTE / 17/08/2026.",
        "",
        f"Finalidade: {model['purpose']}",
        f"Público: {model['audience']}",
        "",
    ]
    for section in model["sections"]:
        lines.extend([f"## {section}", "", "[[DADO_RASTREAVEL_OU_NAO_DISPONIVEL]]", ""])
    lines.extend(
        [
            "## Contrato de segurança",
            "",
            "Preencher somente com dados rastreáveis. Não inventar resultado, execução, fonte, confirmação ou valor ausente.",
            "",
        ]
    )
    return "\n".join(lines)


def _final_markdown(report_id: str, model: dict[str, Any], data: dict[str, Any]) -> str:
    lines = [
        f"# {model['title']}",
        "",
        f"**{model['tagline']}**",
        "",
        "**RESULTADO GENÔMICO — SAÍDA DETERMINÍSTICA DO PIPELINE DE RELATÓRIO**",
        "",
        f"Caso: {_safe(data.get('case_id'))}",
        f"Versão do modelo: v3.0/{model['code']}",
        "Ruleset: v3.4 / VIGENTE / 17/08/2026",
        f"POST-DEPLOYMENT: {_safe(data.get('post_deployment_status'), 'PENDENTE')}",
        "",
        "## Finalidade",
        "",
        model["purpose"],
        "",
        "## Público",
        "",
        model["audience"],
        "",
        "## Resumo executivo",
        "",
        _safe(data.get("summary")),
        "",
    ]
    section_data = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    for section in model["sections"]:
        value = section_data.get(section)
        lines.extend([f"## {section}", "", _safe(value), ""])

    lines.extend(["## Achados estruturados", ""])
    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    if not findings:
        lines.append("NÃO DISPONÍVEL")
    else:
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            lines.extend(
                [
                    f"### {_safe(finding.get('id'), 'ACHADO SEM ID')}",
                    f"- Domínio: {_safe(finding.get('domain'))}",
                    f"- Natureza: {_safe(finding.get('nature'))}",
                    f"- Prioridade: {_safe(finding.get('priority'))}",
                    f"- Dado observado: {_safe(finding.get('observed_data'))}",
                    f"- QC: {_safe(finding.get('qc'))}",
                    f"- Evidência: {_safe(finding.get('evidence_refs'))}",
                    f"- Interpretação: {_safe(finding.get('interpretation'))}",
                    f"- Incertezas: {_safe(finding.get('uncertainties'))}",
                    f"- Confirmação: {_safe(finding.get('confirmation'))}",
                    f"- Status operacional: {_safe(finding.get('status'))}",
                    "",
                ]
            )
    lines.extend(
        [
            "## Execution Manifest",
            "",
            "```json",
            json.dumps(data.get("execution_manifest", {}), ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            "## Fontes",
            "",
            _safe(data.get("sources")),
            "",
            "## Limitações",
            "",
            _safe(data.get("limitations")),
            "",
        ]
    )
    markdown = "\n".join(lines)
    if "[[" in markdown or "]]" in markdown:
        raise ReportReleaseError("FINAL report contains unresolved placeholder syntax")
    return markdown


def _to_html(markdown: str, title: str) -> str:
    body: list[str] = []
    in_code = False
    code: list[str] = []
    for raw in markdown.splitlines():
        if raw.strip() == "```json":
            in_code = True
            code = []
            continue
        if in_code and raw.strip() == "```":
            body.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
            in_code = False
            continue
        if in_code:
            code.append(raw)
            continue
        if raw.startswith("### "):
            body.append(f"<h3>{html.escape(raw[4:])}</h3>")
        elif raw.startswith("## "):
            body.append(f"<h2>{html.escape(raw[3:])}</h2>")
        elif raw.startswith("# "):
            body.append(f"<h1>{html.escape(raw[2:])}</h1>")
        elif raw.startswith("- "):
            body.append(f"<p>• {html.escape(raw[2:])}</p>")
        elif raw.strip():
            body.append(f"<p>{html.escape(raw)}</p>")
    css = "body{font-family:system-ui,-apple-system,sans-serif;max-width:980px;margin:40px auto;padding:0 24px;line-height:1.5}h1,h2{page-break-after:avoid}pre{white-space:pre-wrap;background:#f4f4f4;padding:16px}"
    return f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


def _stamp_ruleset_into_manifest(data: dict[str, Any]) -> dict[str, Any]:
    """Record the governing ruleset inside the report's own Execution Manifest.

    A published report has to be auditable on its own, away from CI logs, so the reader
    can tell which normative version produced it. The identity is attested here rather
    than copied from the caller's payload, so the printed line reflects what was actually
    verified at render time.
    """
    stamped = deepcopy(data)
    manifest = stamped.get("execution_manifest")
    if not isinstance(manifest, dict):
        manifest = {"status": _safe(manifest, "NÃO DISPONÍVEL")}
    attested = normative.attested_ruleset_block()
    manifest["RULESET"] = attested["attestation"]
    manifest["VERSÃO"] = attested["version"]
    manifest["VIGÊNCIA"] = attested["effective_date"]
    if attested["attestation"] == "VERIFICADO":
        manifest["RULESET_SHA256"] = attested["sha256"]
    else:
        manifest["RULESET_MOTIVO"] = attested["reason"]
    stamped["execution_manifest"] = manifest
    return stamped


def render_document(report_id: str, data: dict[str, Any], *, mode: str = "MODEL") -> dict[str, Any]:
    catalog = load_catalog()
    if report_id not in catalog:
        raise ReportReleaseError(f"unknown report model: {report_id}")
    mode = mode.upper()
    if mode not in {"MODEL", "FINAL"}:
        raise ReportReleaseError("mode must be MODEL or FINAL")
    model = catalog[report_id]
    blockers: list[str] = []
    if mode == "FINAL":
        blockers = _publication_blockers(data)
        if blockers:
            raise ReportReleaseError("publication gate failed: " + ", ".join(blockers))
        data = _stamp_ruleset_into_manifest(data)
        markdown = _final_markdown(report_id, model, data)
    else:
        markdown = _model_markdown(report_id, model)
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    metadata = {
        "schema": "genoma-report-bundle-v1",
        "report_id": report_id,
        "code": model["code"],
        "accent": model["accent"],
        "slug": model["slug"],
        "title": model["title"],
        "tagline": model["tagline"],
        "purpose": model["purpose"],
        "audience": model["audience"],
        "mode": mode,
        "generated_at": generated_at,
        "ruleset_required": deepcopy(EXPECTED_RULESET),
        "publication_blockers": blockers,
    }
    return {
        "metadata": metadata,
        "data": deepcopy(data),
        "markdown": markdown,
        "html": _to_html(markdown, model["title"]),
    }


def write_bundle(rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None) -> dict[str, Path]:
    """Write the bundle and a checksum sidecar covering every file it wrote.

    `artifact_sha256` covered the markdown and the HTML and stopped there — not the JSON
    written on the next line, and not the PDF a separate renderer produces from the same
    payload. A manifest that omits the artifacts actually delivered cannot be used to verify
    a delivery, which is the only thing it is for. The sidecar is written last, over the
    bytes on disk rather than over the strings in memory, so it describes what a recipient
    will actually receive.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = rendered["metadata"]
    stem = stem or f"{metadata['report_id']}-{metadata['slug']}"
    paths = {
        "json": output_dir / f"{stem}.json",
        "markdown": output_dir / f"{stem}.md",
        "html": output_dir / f"{stem}.html",
    }
    bundle_json = {
        "metadata": metadata,
        "data": rendered["data"],
        "artifact_sha256": {
            "markdown": hashlib.sha256(rendered["markdown"].encode("utf-8")).hexdigest(),
            "html": hashlib.sha256(rendered["html"].encode("utf-8")).hexdigest(),
        },
        # Named here so a reader of the JSON alone knows the JSON's own digest, and the
        # PDF's, live in the sidecar rather than concluding they were never computed.
        "artifact_sha256_note": (
            f"digests of every written file, including this JSON and any PDF rendered from "
            f"the same payload, are in {stem}.SHA256SUMS"
        ),
    }
    paths["json"].write_text(json.dumps(bundle_json, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["markdown"].write_text(rendered["markdown"] + "\n", encoding="utf-8")
    paths["html"].write_text(rendered["html"] + "\n", encoding="utf-8")

    paths["checksums"] = write_checksums(output_dir, stem, [paths[k] for k in ("json", "markdown", "html")])
    return paths


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(output_dir: Path, stem: str, files: list[Path]) -> Path:
    """Write (or extend) the sidecar so it names every delivered file exactly once.

    Extending rather than overwriting lets the PDF renderer add its output to the same
    manifest after the fact, which is the only way one file can cover artifacts produced by
    two entry points.
    """
    sidecar = output_dir / f"{stem}.SHA256SUMS"
    existing: dict[str, str] = {}
    if sidecar.is_file():
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            digest, _, name = line.partition("  ")
            if digest and name:
                existing[name] = digest
    for path in files:
        if path.is_file():
            existing[path.name] = sha256_path(path)
    sidecar.write_text(
        "".join(f"{existing[name]}  {name}\n" for name in sorted(existing)), encoding="utf-8"
    )
    return sidecar
