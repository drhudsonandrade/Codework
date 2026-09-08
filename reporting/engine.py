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

from reporting.provenance import provenance_blockers, render_value

ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "catalog.json"
EXPECTED_RULESET = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}
RULESET_LABEL = (
    f"{EXPECTED_RULESET['version']} / {EXPECTED_RULESET['status']} / "
    f"{EXPECTED_RULESET['effective_date']}"
)
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")


class ReportReleaseError(RuntimeError):
    """A document may not be released in the form that was asked for.

    Every refusal in this module raises it, because they mean the same thing to a caller: the
    artifact you would get is not the one the gates authorise, so none is produced.
    """


def _assert_serializable_provenance(rendered: dict[str, Any]) -> None:
    """Re-run provenance and derived-view checks at a FINAL write boundary.

    ``render_document`` validates the source payload, but editorial preparation happens later
    and may legitimately add renderer disclosures. A caller can also mutate a prepared
    object. Writers therefore validate the *current* data rather than trusting the earlier
    gate. The check runs before ``mkdir`` so a refusal leaves no partial output behind.
    """
    metadata = rendered.get("metadata") if isinstance(rendered.get("metadata"), dict) else {}
    render_mode = rendered.get("_render_mode")
    metadata_mode = str(metadata.get("mode", "")).upper()
    if render_mode not in {"MODEL", "FINAL"}:
        raise ReportReleaseError("rendered bundle carries no trusted render mode")
    if metadata_mode != render_mode:
        raise ReportReleaseError(
            f"rendered mode was mutated after rendering: {metadata_mode!r} != {render_mode!r}"
        )
    raw_data = rendered.get("data")
    data = raw_data if isinstance(raw_data, dict) else {}
    report_id = str(metadata.get("report_id") or "")
    model = load_catalog().get(report_id)
    if model is None:
        raise ReportReleaseError(f"unknown report model: {report_id!r}")
    if render_mode == "FINAL":
        blockers = _publication_blockers(data, report_id)
        if blockers:
            raise ReportReleaseError(
                "post-render publication gate failed: " + ", ".join(blockers)
            )
        expected_markdown = _final_markdown(report_id, model, data)
    else:
        expected_markdown = _model_markdown(report_id, model)
    if rendered.get("markdown") != expected_markdown:
        raise ReportReleaseError("rendered markdown no longer matches the bundled payload")
    expected_html = _to_html(expected_markdown, model["title"])
    if rendered.get("html") != expected_html:
        raise ReportReleaseError("rendered HTML no longer matches the bundled payload")


def load_catalog() -> dict[str, dict[str, Any]]:
    """The eleven v3 report models, refusing any catalog that is not exactly 01..11.

    A partial catalog would let a render pick a model nobody approved, and a model missing
    its editorial metadata would render a document with empty headings.
    """
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict) or sorted(catalog) != [f"{i:02d}" for i in range(1, 12)]:
        raise ReportReleaseError("report catalog must contain exactly models 01..11")
    required = {"code", "accent", "slug", "title", "tagline", "purpose", "audience", "sections"}
    for report_id, model in catalog.items():
        if not isinstance(model, dict) or not required.issubset(model):
            raise ReportReleaseError(f"report model {report_id} missing v3 editorial metadata")
    return catalog


def _publication_blockers(data: dict[str, Any], report_id: str) -> list[str]:
    """Every reason this payload may not be published as `report_id`.

    Reasons accumulate rather than raising at the first one, so a caller sees everything
    wrong in a single run instead of fixing them one release at a time.
    """
    blockers: list[str] = []
    # Every other check here was computed for the payload's *own* report, and none of them
    # looked at which model is being rendered. `PayloadCompiler.consent_scope` resolves the
    # consent domain through `reporting.consent.REPORT_DOMAINS[report_id]`, and
    # `provenance_blockers` anchors `report_id` as an identity field — so the two agreed with
    # each other while agreeing with nothing here. `render_document("02", payload compiled
    # for "01", mode="FINAL")` therefore published the Ancestralidade document with zero
    # blockers under a consent verdict computed for the CLÍNICO domain: a real consent, for
    # the wrong thing, reading as authorisation.
    declared = data.get("report_id")
    if declared != report_id:
        blockers.append(f"report_id:mismatch:{declared!r}!={report_id!r}")

    ruleset = data.get("ruleset") if isinstance(data.get("ruleset"), dict) else {}
    for key, expected in EXPECTED_RULESET.items():
        if ruleset.get(key) != expected:
            blockers.append(f"ruleset:{key}")

    publication = (
        data.get("publication_gate") if isinstance(data.get("publication_gate"), dict) else {}
    )
    for key in (
        "passed",
        "consent_verified",
        "consent_scope_verified",
        "qc_verified",
        "evidence_verified",
        "placeholders_resolved",
    ):
        if publication.get(key) is not True:
            blockers.append(f"publication_gate:{key}")

    policy = (
        data.get("policy_evaluation") if isinstance(data.get("policy_evaluation"), dict) else {}
    )
    if policy.get("ready_for_requested_operation") is not True:
        blockers.append("policy_evaluation:ready_for_requested_operation")
    planes = policy.get("planes") if isinstance(policy.get("planes"), dict) else {}
    for plane_name in REQUIRED_PLANES:
        plane = planes.get(plane_name) if isinstance(planes.get(plane_name), dict) else {}
        if plane.get("state") != "PASS":
            blockers.append(f"policy_evaluation:plane:{plane_name}")

    gates = policy.get("gates") if isinstance(policy.get("gates"), list) else []
    final_audit = next(
        (g for g in gates if isinstance(g, dict) and g.get("gate") == "FINAL_AUDIT_GATE"),
        None,
    )
    if not isinstance(final_audit, dict) or final_audit.get("state") != "PASS":
        blockers.append("policy_evaluation:FINAL_AUDIT_GATE")
    blockers.extend(provenance_blockers(data))
    return blockers


def _safe(value: Any, default: str = "NÃO DISPONÍVEL") -> str:
    """Print `value` for the document, or `default` when there is nothing to print.

    The rendering itself belongs to `reporting.provenance.render_value`, which is what an
    anchor records as `observed_value`; this function only chooses what stands in for an
    absent value. It used to hold its own copy of the serialisation rules, and the copies
    drifted on mapping key order — see `render_value` and
    `tests/test_rendered_text_matches_the_document.py`.
    """
    if value is None or value == "":
        return default
    return render_value(value)


def _model_markdown(report_id: str, model: dict[str, Any]) -> str:
    """The empty template for a model, with every slot left as a visible placeholder.

    Reads no payload at all. MODEL mode exists to show the shape of a report without
    asserting anything, so the placeholders are printed rather than filled — a blank where a
    result belongs would read as a measurement that came back empty.
    """
    lines = [
        f"# {model['title']}",
        "",
        f"**{model['tagline']}**",
        "",
        "**MODELO — NÃO É RESULTADO GENÉTICO**",
        "",
        f"Modelo GENOMA v3.0 / {model['code']}. Ruleset exigido: {RULESET_LABEL}.",
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
            (
                "Preencher somente com dados rastreáveis. Não inventar resultado, "
                "execução, fonte, confirmação ou valor ausente."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _final_markdown(report_id: str, model: dict[str, Any], data: dict[str, Any]) -> str:
    """The published document: every printed value comes from the payload.

    Values are rendered through `reporting.provenance.render_value`, which is also what the
    anchors record, so the text on the page and the provenance block describing it cannot
    disagree. Raises if any placeholder syntax survives into the output.
    """
    lines = [
        f"# {model['title']}",
        "",
        f"**{model['tagline']}**",
        "",
        "**RESULTADO GENÔMICO — SAÍDA DETERMINÍSTICA DO PIPELINE DE RELATÓRIO**",
        "",
        f"Caso: {_safe(data.get('case_id'))}",
        f"Versão do modelo: v3.0/{model['code']}",
        f"Ruleset: {RULESET_LABEL}",
        f"Ruleset SHA-256: {EXPECTED_RULESET['sha256']}",
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
            json.dumps(
                data.get("execution_manifest", {}), ensure_ascii=False, indent=2, sort_keys=True
            ),
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
    """Convert the rendered Markdown to standalone HTML, escaping every dynamic value.

    A deliberately small converter rather than a Markdown library: the input is this module's
    own output, and the set of constructs it emits is fixed and known. Content is escaped, so
    a value carrying HTML is displayed rather than interpreted.
    """
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
    css = (
        "body{font-family:system-ui,-apple-system,sans-serif;"
        "max-width:980px;margin:40px auto;padding:0 24px;line-height:1.5}"
        "h1,h2{page-break-after:avoid}pre{white-space:pre-wrap;"
        "background:#f4f4f4;padding:16px}"
    )
    return (
        f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title><style>{css}</style>"
        f"</head><body>{''.join(body)}</body></html>"
    )


def render_document(report_id: str, data: dict[str, Any], *, mode: str = "MODEL") -> dict[str, Any]:
    """Render one report in MODEL or FINAL mode, returning payload, Markdown and HTML.

    MODEL renders the empty template from the catalogue and never touches `data`: it shows
    what a report of this kind looks like, and must remain producible for a case that has no
    evidence at all. FINAL renders the case and is gated — `_publication_blockers` runs
    first and any blocker raises `ReportReleaseError` instead of returning a document.

    The gate raises rather than returning a bundle with `publication_blockers` filled in.
    A blocked FINAL that still produced Markdown would be a publishable file on disk whose
    only warning lived in a sibling metadata field; the caller has to be unable to obtain
    the text at all. `publication_blockers` in the metadata is therefore always empty on a
    FINAL that was returned, and carries the (empty) list on MODEL for schema stability.

    `data` is deep-copied into the bundle so a later mutation by the caller cannot change
    what the rendered Markdown was rendered from.
    """
    catalog = load_catalog()
    if report_id not in catalog:
        raise ReportReleaseError(f"unknown report model: {report_id}")
    mode = mode.upper()
    if mode not in {"MODEL", "FINAL"}:
        raise ReportReleaseError("mode must be MODEL or FINAL")
    model = catalog[report_id]
    blockers: list[str] = []
    if mode == "FINAL":
        blockers = _publication_blockers(data, report_id)
        if blockers:
            raise ReportReleaseError("publication gate failed: " + ", ".join(blockers))
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
        "_render_mode": mode,
        "metadata": metadata,
        "data": deepcopy(data),
        "markdown": markdown,
        "html": _to_html(markdown, model["title"]),
    }


def write_bundle(
    rendered: dict[str, Any], output_dir: Path, *, stem: str | None = None
) -> dict[str, Path]:
    """Write the JSON, Markdown and HTML of one render, and return where each landed.

    All three share a stem so a reader can tell they describe the same document, and the JSON
    travels beside the rendered text so the payload behind a page is always recoverable.
    """
    _assert_serializable_provenance(rendered)
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
    }
    paths["json"].write_text(
        json.dumps(bundle_json, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(rendered["markdown"] + "\n", encoding="utf-8")
    paths["html"].write_text(rendered["html"] + "\n", encoding="utf-8")
    return paths
