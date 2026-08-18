"""Compile report payloads whose every printed value is bound to a pipeline artifact.

`scripts/generate_report.py` documents its input as "already-curated JSON". That phrasing
hides the largest remaining hole in the system: the four-plane audit, the gates, the sealed
templates and the pixel QA all protect *rendering*, while the scientific content enters
through a hand-written file. Nothing downstream could tell an observed genotype from a typed
one, so ruleset section 6 (NO FALSE CERTAINTY) was enforced by operator discipline rather
than by the pipeline.

This module closes that hole with a two-stage binding, so that neither stage can be
satisfied by writing prose:

1. **Compile time** (artifacts on disk): every value is anchored to a locator inside a
   named artifact, and the compiler re-reads that locator and compares. A value the
   artifact does not actually contain raises `ProvenanceError`. This is what makes
   inventing a genotype impossible rather than merely discouraged.
2. **Render time** (artifacts may be long gone): `PROVENANCE_GATE` in the report engine
   re-checks that the text about to be printed equals the anchored `observed_value`, and
   that every rendered field carries an anchor at all.

There is deliberately **no bypass flag**. A payload that is not derived from real artifacts
is not blocked from existing — it is compiled with `fixture` anchors, which can never carry
an executed status, so the resulting document reports NÃO DISPONÍVEL on its face. Honesty is
obtained by making the weak case *say* it is weak, not by making it unrepresentable; a
master switch that turned the checking off would be the same defect this module exists to
remove.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import normative

SCHEMA = "genoma-report-provenance-v1"

#: Anchor kinds that may carry a status stronger than NÃO DISPONÍVEL. A kind outside this
#: set describes a value that was not measured, so it can never back an executed claim.
DERIVED_KINDS = frozenset({"observation", "qc_metric", "evidence_retrieval", "computed"})
#: Kinds that describe the run itself rather than the person; they may be VERIFICADO but
#: never constitute a genomic result.
CONTEXT_KINDS = frozenset({"normative", "case_control"})
#: Non-measurement content: QA fixtures, layout probes, editorial scaffolding.
FIXTURE_KINDS = frozenset({"fixture"})
ANCHOR_KINDS = DERIVED_KINDS | CONTEXT_KINDS | FIXTURE_KINDS

#: Section 261 operational-status vocabulary.
OPERATIONAL_STATUSES = ("EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL")
#: Ordered weakest-first: a compiled report is never stronger than its weakest anchor.
_STATUS_RANK = {
    "NÃO DISPONÍVEL": 0,
    "PROPOSTO": 1,
    "INFERIDO": 2,
    "VERIFICADO": 3,
    "EXECUTADO": 4,
}

UNAVAILABLE = "NÃO DISPONÍVEL"

#: A locator is a dotted/bracketed path into the artifact, e.g.
#: ``observations[rs1799807].records[0].genotype`` or ``metrics.call_rate``.
_LOCATOR_STEP = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


class ProvenanceError(Exception):
    """A value could not be bound to the artifact it claims to come from."""


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def render_value(value: Any) -> str:
    """Render a value exactly as `reporting.engine._safe` will print it.

    The gate compares printed text against the anchor, so the two renderings must agree
    character for character or a correct payload would fail the gate for a formatting
    reason. Keeping this function beside the anchors — and asserting the agreement in
    `tests/test_report_provenance.py` — is what keeps them from drifting apart.
    """
    if value is None or value == "":
        return UNAVAILABLE
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _resolve(artifact: Any, locator: str) -> Any:
    """Read `locator` out of `artifact`, raising ProvenanceError if the path is absent.

    Mapping keys are tried before list indices, so a numeric dictionary key still resolves.
    """
    current = artifact
    for match in _LOCATOR_STEP.finditer(locator):
        key = match.group(1) if match.group(1) is not None else match.group(2)
        if isinstance(current, dict):
            if key in current:
                current = current[key]
                continue
            raise ProvenanceError(f"locator {locator!r}: no key {key!r} in artifact")
        if isinstance(current, (list, tuple)):
            try:
                index = int(key)
            except ValueError as exc:
                raise ProvenanceError(f"locator {locator!r}: {key!r} is not a list index") from exc
            if not -len(current) <= index < len(current):
                raise ProvenanceError(f"locator {locator!r}: index {index} out of range")
            current = current[index]
            continue
        raise ProvenanceError(f"locator {locator!r}: cannot descend into {type(current).__name__}")
    return current


@dataclass(frozen=True)
class Artifact:
    """A pipeline output that values may be anchored to."""

    name: str
    payload: dict[str, Any]
    sha256: str
    path: str | None = None

    @classmethod
    def from_path(cls, name: str, path: Path) -> "Artifact":
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProvenanceError(f"artifact {name!r} must be a JSON object")
        return cls(name=name, payload=payload, sha256=hashlib.sha256(raw).hexdigest(), path=str(path))

    @classmethod
    def from_payload(cls, name: str, payload: dict[str, Any]) -> "Artifact":
        """Anchor to an in-memory artifact, identified by the hash of its own content."""
        if not isinstance(payload, dict):
            raise ProvenanceError(f"artifact {name!r} must be a JSON object")
        return cls(name=name, payload=payload, sha256=sha256_json(payload), path=None)


@dataclass(frozen=True)
class Anchor:
    """Where one printed value came from, in enough detail to re-derive it."""

    kind: str
    artifact: str
    artifact_sha256: str
    locator: str
    observed_value: str
    operational_status: str
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "artifact": self.artifact,
            "artifact_sha256": self.artifact_sha256,
            "locator": self.locator,
            "observed_value": self.observed_value,
            "operational_status": self.operational_status,
            "basis": self.basis,
        }


def _validate_anchor(anchor: Anchor) -> None:
    if anchor.kind not in ANCHOR_KINDS:
        raise ProvenanceError(f"unknown anchor kind: {anchor.kind!r}")
    if anchor.operational_status not in OPERATIONAL_STATUSES:
        raise ProvenanceError(f"invalid operational status: {anchor.operational_status!r}")
    if not anchor.basis.strip():
        raise ProvenanceError("an anchor must state its basis")
    if anchor.kind in FIXTURE_KINDS and anchor.operational_status != UNAVAILABLE:
        # A fixture describes no measurement. Letting it carry VERIFICADO would recreate
        # exactly the loophole this module removes, one indirection further away.
        raise ProvenanceError("a fixture anchor may only carry NÃO DISPONÍVEL")
    if anchor.kind in CONTEXT_KINDS and anchor.operational_status == "EXECUTADO":
        raise ProvenanceError("context anchors describe the run, not an executed measurement")


@dataclass
class CompiledPayload:
    """A report payload plus the provenance block that proves each value."""

    data: dict[str, Any]
    anchors: dict[str, Anchor] = dataclass_field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = dict(self.data)
        payload["provenance"] = provenance_block(self.anchors)
        return payload


def status_distribution(anchors: Any) -> dict[str, int]:
    """How many fields sit at each operational status.

    The floor alone is conservative to the point of being uninformative: one deliberately
    absent section drags the whole report to NÃO DISPONÍVEL, which reads the same as a
    report where nothing was measured at all. The distribution keeps the conservative
    headline while letting a reader see that the absence is one field out of seven.
    """
    counts = {status: 0 for status in OPERATIONAL_STATUSES}
    for anchor in anchors:
        counts[anchor.operational_status] += 1
    return counts


def provenance_block(anchors: dict[str, Anchor]) -> dict[str, Any]:
    fields = {name: anchors[name].to_dict() for name in sorted(anchors)}
    floor = weakest_status(anchors.values())
    block = {
        "schema": SCHEMA,
        "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ruleset": normative.ruleset_block(include_sha256=False),
        "field_count": len(fields),
        "operational_status_floor": floor,
        "status_distribution": status_distribution(anchors.values()),
        "fields": fields,
    }
    block["sha256"] = sha256_json({k: v for k, v in block.items() if k != "compiled_at"})
    return block


def weakest_status(anchors: Any) -> str:
    """The report can be no stronger than its weakest anchor."""
    ranks = [_STATUS_RANK[a.operational_status] for a in anchors]
    if not ranks:
        return UNAVAILABLE
    floor = min(ranks)
    for status, rank in _STATUS_RANK.items():
        if rank == floor:
            return status
    return UNAVAILABLE


class PayloadCompiler:
    """Assemble a FINAL report payload where every value is anchored and verified.

    The compiler never invents a value: callers supply a locator, and the *artifact*
    supplies the text. `field()` therefore has no `value` parameter for derived kinds —
    passing one would let a caller print something other than what was measured.
    """

    def __init__(self, *, case_id: str, report_id: str) -> None:
        if not str(case_id).strip():
            raise ProvenanceError("case_id is required")
        self.case_id = str(case_id)
        self.report_id = str(report_id)
        self._artifacts: dict[str, Artifact] = {}
        self._anchors: dict[str, Anchor] = {}
        self._values: dict[str, Any] = {}
        self._sections: dict[str, Any] = {}
        self._findings: list[dict[str, Any]] = []

    # -- artifacts ---------------------------------------------------------------

    def register(self, artifact: Artifact) -> Artifact:
        existing = self._artifacts.get(artifact.name)
        if existing is not None and existing.sha256 != artifact.sha256:
            raise ProvenanceError(f"artifact {artifact.name!r} registered twice with different content")
        self._artifacts[artifact.name] = artifact
        return artifact

    def artifact(self, name: str) -> Artifact:
        try:
            return self._artifacts[name]
        except KeyError as exc:
            raise ProvenanceError(f"artifact {name!r} is not registered") from exc

    # -- fields ------------------------------------------------------------------

    def derive(
        self,
        name: str,
        *,
        artifact: str,
        locator: str,
        status: str,
        basis: str,
        kind: str = "observation",
        transform: Any = None,
    ) -> Any:
        """Bind `name` to the value actually stored at `locator` inside `artifact`.

        `transform` may reshape the read value for presentation (e.g. formatting a rate),
        but the anchor records the *rendered* result, so the gate still compares the
        printed text against something derived from the artifact rather than typed.
        """
        if kind not in DERIVED_KINDS:
            raise ProvenanceError(f"derive() requires a derived kind, got {kind!r}")
        source = self.artifact(artifact)
        raw = _resolve(source.payload, locator)
        value = transform(raw) if transform is not None else raw
        rendered = render_value(value)
        anchor = Anchor(
            kind=kind,
            artifact=source.name,
            artifact_sha256=source.sha256,
            locator=locator,
            observed_value=rendered,
            operational_status=status,
            basis=basis,
        )
        _validate_anchor(anchor)
        self._anchors[name] = anchor
        self._values[name] = value
        return value

    def state(self, name: str, value: Any, *, kind: str, basis: str, status: str) -> Any:
        """Record a value that is *not* read from a scientific artifact.

        Used for run context (`normative`, `case_control`) and for non-measurement content
        (`fixture`). It is deliberately the only way to introduce free text, and the anchor
        it produces can never claim an executed measurement.
        """
        if kind in DERIVED_KINDS:
            raise ProvenanceError("derived values must go through derive(), which reads the artifact")
        rendered = render_value(value)
        anchor = Anchor(
            kind=kind,
            artifact=kind,
            artifact_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
            locator=name,
            observed_value=rendered,
            operational_status=status,
            basis=basis,
        )
        _validate_anchor(anchor)
        self._anchors[name] = anchor
        self._values[name] = value
        return value

    def unavailable(self, name: str, *, basis: str) -> str:
        """Declare a field explicitly absent. Absence is a result and is anchored too."""
        return self.state(name, UNAVAILABLE, kind="fixture", basis=basis, status=UNAVAILABLE)

    # -- sections and findings ---------------------------------------------------
    #
    # These wrappers exist so the anchor name is computed from the payload key rather than
    # typed alongside it. A caller that spelled the two independently could anchor
    # "Resumo clínico" while printing "Resumo clinico", and the gate would only report an
    # unanchored field long after the mistake.

    def section_derived(
        self,
        title: str,
        *,
        artifact: str,
        locator: str,
        status: str,
        basis: str,
        kind: str = "observation",
        transform: Any = None,
    ) -> Any:
        value = self.derive(
            _anchor_name_for_section(title),
            artifact=artifact,
            locator=locator,
            status=status,
            basis=basis,
            kind=kind,
            transform=transform,
        )
        self._sections[title] = value
        return value

    def section_stated(self, title: str, text: Any, *, kind: str, basis: str, status: str) -> Any:
        value = self.state(_anchor_name_for_section(title), text, kind=kind, basis=basis, status=status)
        self._sections[title] = value
        return value

    def section_unavailable(self, title: str, *, basis: str) -> str:
        value = self.unavailable(_anchor_name_for_section(title), basis=basis)
        self._sections[title] = value
        return value

    def finding(self, finding_id: str, *, basis: str) -> "FindingBuilder":
        """Start a structured finding whose every field is individually anchored."""
        return FindingBuilder(self, finding_id, basis=basis)

    # -- output ------------------------------------------------------------------

    def value(self, name: str) -> Any:
        return self._values.get(name)

    @property
    def anchors(self) -> dict[str, Anchor]:
        return dict(self._anchors)

    def status_floor(self) -> str:
        return weakest_status(self._anchors.values())

    def compile(
        self,
        *,
        publication_gate: dict[str, Any],
        policy_evaluation: dict[str, Any],
        execution_manifest: dict[str, Any] | None = None,
        post_deployment_status: str = "PENDENTE",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce the payload `reporting.engine.render_document` consumes.

        Sections and findings come from what was actually anchored during compilation, not
        from a parameter: accepting them here would let a caller pass content that was
        never bound to an artifact.
        """
        for required in ("summary", "sources", "limitations"):
            if required not in self._anchors:
                raise ProvenanceError(f"{required!r} must be anchored before compiling")
        data: dict[str, Any] = {
            "case_id": self.case_id,
            "report_id": self.report_id,
            "summary": self.value("summary"),
            "ruleset": normative.ruleset_block(include_sha256=False),
            "publication_gate": dict(publication_gate),
            "policy_evaluation": dict(policy_evaluation),
            "post_deployment_status": post_deployment_status,
            "sections": dict(self._sections),
            "findings": [dict(x) for x in self._findings],
            "execution_manifest": dict(execution_manifest or {}),
            "sources": self.value("sources"),
            "limitations": self.value("limitations"),
            "operational_status": self.status_floor(),
            "artifacts": {
                name: {"sha256": art.sha256, "path": art.path}
                for name, art in sorted(self._artifacts.items())
            },
        }
        if extra:
            data.update(extra)
        data["provenance"] = provenance_block(self._anchors)
        return data


class FindingBuilder:
    """Assemble one structured finding, anchoring each field as it is set."""

    def __init__(self, compiler: PayloadCompiler, finding_id: str, *, basis: str) -> None:
        if not str(finding_id).strip():
            raise ProvenanceError("a finding needs an id")
        self._compiler = compiler
        self._id = str(finding_id)
        self._fields: dict[str, Any] = {}
        # The id is itself printed, so it is anchored like any other value.
        compiler.state(
            f"findings[{self._id}].id",
            self._id,
            kind="case_control",
            basis=basis,
            status="VERIFICADO",
        )

    def derived(
        self,
        key: str,
        *,
        artifact: str,
        locator: str,
        status: str,
        basis: str,
        kind: str = "observation",
        transform: Any = None,
    ) -> "FindingBuilder":
        if key not in FINDING_FIELDS:
            raise ProvenanceError(f"unknown finding field: {key!r}")
        value = self._compiler.derive(
            _anchor_name_for_finding(self._id, key),
            artifact=artifact,
            locator=locator,
            status=status,
            basis=basis,
            kind=kind,
            transform=transform,
        )
        self._fields[key] = value
        return self

    def stated(self, key: str, value: Any, *, kind: str, basis: str, status: str) -> "FindingBuilder":
        if key not in FINDING_FIELDS:
            raise ProvenanceError(f"unknown finding field: {key!r}")
        stored = self._compiler.state(
            _anchor_name_for_finding(self._id, key), value, kind=kind, basis=basis, status=status
        )
        self._fields[key] = stored
        return self

    def unavailable(self, key: str, *, basis: str) -> "FindingBuilder":
        return self.stated(key, UNAVAILABLE, kind="fixture", basis=basis, status=UNAVAILABLE)

    def add(self) -> dict[str, Any]:
        """Attach the finding to the payload under construction."""
        missing = [k for k in FINDING_FIELDS if k not in self._fields]
        if missing:
            # A finding that silently omits "uncertainties" or "confirmation" reads as if
            # there were none. Section 6 requires the absence to be stated, not implied.
            raise ProvenanceError(
                f"finding {self._id!r} leaves fields unstated: {', '.join(missing)}"
            )
        finding = {"id": self._id, **{k: self._fields[k] for k in FINDING_FIELDS}}
        self._compiler._findings.append(finding)
        return finding


# ---------------------------------------------------------------------------------
# Render-time gate
# ---------------------------------------------------------------------------------

#: Top-level payload keys that are printed verbatim in a FINAL report.
SCALAR_FIELDS = ("summary", "sources", "limitations")
#: Per-finding keys printed verbatim by `reporting.engine._final_markdown`.
FINDING_FIELDS = (
    "domain", "nature", "priority", "observed_data", "qc",
    "evidence_refs", "interpretation", "uncertainties", "confirmation", "status",
)


def _anchor_name_for_section(title: str) -> str:
    return f"sections[{title}]"


def _anchor_name_for_finding(finding_id: str, key: str) -> str:
    return f"findings[{finding_id}].{key}"


def fixture_payload(
    *,
    case_id: str,
    report_id: str,
    summary: str,
    sections: dict[str, Any] | None = None,
    basis: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fully-anchored payload for layout QA and tests.

    Visual QA has to render a FINAL document to measure it, but it must not be able to
    publish a genomic claim to do so. Rather than exempting QA from the gate — which would
    reopen the hole for anything that could call itself QA — every field is anchored as
    `fixture`, so the payload passes the gate while its own status floor stays
    NÃO DISPONÍVEL and the document says so on its face.
    """
    compiler = PayloadCompiler(case_id=case_id, report_id=report_id)
    compiler.state("summary", summary, kind="fixture", basis=basis, status=UNAVAILABLE)
    compiler.state("sources", [basis], kind="fixture", basis=basis, status=UNAVAILABLE)
    compiler.state("limitations", basis, kind="fixture", basis=basis, status=UNAVAILABLE)
    for title, value in (sections or {}).items():
        compiler.section_stated(title, value, kind="fixture", basis=basis, status=UNAVAILABLE)
    return compiler.compile(
        publication_gate={
            "passed": True,
            "consent_verified": True,
            "qc_verified": True,
            "evidence_verified": True,
            "placeholders_resolved": True,
        },
        policy_evaluation={
            "ready_for_requested_operation": True,
            "planes": {k: {"state": "PASS"} for k in ("policy_control", "scientific_data", "evidence", "audit")},
            "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True}],
        },
        execution_manifest={"status": UNAVAILABLE, "nature": basis},
        extra=extra,
    )


def provenance_blockers(data: dict[str, Any]) -> list[str]:
    """Every value about to be printed must equal the value its anchor recorded.

    This runs where the artifacts are no longer available, so it cannot re-read the
    pipeline; what it can do — and what defeats a hand-edited payload — is prove that the
    text and the anchor still agree, and that nothing is printed without an anchor at all.
    """
    blockers: list[str] = []
    block = data.get("provenance")
    if not isinstance(block, dict):
        return ["provenance:absent"]
    if block.get("schema") != SCHEMA:
        blockers.append("provenance:schema")
    fields = block.get("fields")
    if not isinstance(fields, dict):
        return blockers + ["provenance:fields"]

    recomputed = sha256_json({k: v for k, v in block.items() if k not in {"compiled_at", "sha256"}})
    if block.get("sha256") != recomputed:
        blockers.append("provenance:sha256")

    def check(name: str, value: Any) -> None:
        anchor = fields.get(name)
        if not isinstance(anchor, dict):
            blockers.append(f"provenance:unanchored:{name}")
            return
        for key in ("kind", "artifact", "artifact_sha256", "locator", "observed_value", "operational_status", "basis"):
            if not isinstance(anchor.get(key), str) or not anchor[key].strip():
                blockers.append(f"provenance:malformed:{name}:{key}")
                return
        if anchor["kind"] not in ANCHOR_KINDS:
            blockers.append(f"provenance:kind:{name}")
            return
        if anchor["operational_status"] not in OPERATIONAL_STATUSES:
            blockers.append(f"provenance:status:{name}")
            return
        if anchor["kind"] in FIXTURE_KINDS and anchor["operational_status"] != UNAVAILABLE:
            blockers.append(f"provenance:fixture_overclaim:{name}")
            return
        if render_value(value) != anchor["observed_value"]:
            # The printed text drifted from what was measured: either the payload was
            # edited after compilation, or the anchor was copied from another field.
            blockers.append(f"provenance:mismatch:{name}")

    for name in SCALAR_FIELDS:
        check(name, data.get(name))

    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    for title, value in sections.items():
        check(_anchor_name_for_section(str(title)), value)

    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            blockers.append(f"provenance:finding_shape:{index}")
            continue
        finding_id = str(finding.get("id") or f"index-{index}")
        check(f"findings[{finding_id}].id", finding.get("id"))
        for key in FINDING_FIELDS:
            if key in finding:
                check(_anchor_name_for_finding(finding_id, key), finding[key])

    # The floor and the distribution are both derived from the same anchors, so they are
    # recomputed here rather than trusted. A block that merely *stated* a reassuring floor
    # would be decoration.
    statuses = [
        a.get("operational_status")
        for a in fields.values()
        if isinstance(a, dict) and a.get("operational_status") in _STATUS_RANK
    ]
    if statuses:
        recomputed_floor = min(statuses, key=lambda s: _STATUS_RANK[s])
        if block.get("operational_status_floor") != recomputed_floor:
            blockers.append("provenance:floor_mismatch")
        counts = {status: 0 for status in OPERATIONAL_STATUSES}
        for status in statuses:
            counts[status] += 1
        if block.get("status_distribution") != counts:
            blockers.append("provenance:distribution_mismatch")

    declared = data.get("operational_status")
    floor = block.get("operational_status_floor")
    if isinstance(declared, str) and isinstance(floor, str):
        if _STATUS_RANK.get(declared, -1) > _STATUS_RANK.get(floor, -1):
            # Claiming a status above the weakest anchor is the headline form of the lie
            # this module exists to prevent.
            blockers.append("provenance:status_above_floor")
    return sorted(set(blockers))
