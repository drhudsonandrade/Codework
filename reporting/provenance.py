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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import normative
from reporting import deployment_target
from reporting.consent import (
    ALLOWED_DOMAINS as ALLOWED_CONSENT_DOMAINS,
    CONSENT_ARTIFACT,
    REPORT_DOMAINS,
    REQUIRED_AFFIRMATIONS,
    SCHEMA as CONSENT_SCHEMA,
    ConsentError,
    scope_verdict as consent_scope_verdict,
    validate_record as validate_consent,
)

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

#: The artifact a builder must register for its payload to carry a normative verdict at all.
#: It is the policy engine's own `evaluation.json`; nothing else may stand in for it.
POLICY_EVALUATION_ARTIFACT = "policy-evaluation"

#: The four planes every payload must account for. Mirrored in `reporting.engine`, which
#: checks them at render time; kept here so the verdict is shaped the same way it is read.
REQUIRED_PLANES = ("policy_control", "scientific_data", "evidence", "audit")

#: The witness a live deployment produces under ruleset section 260. Like the policy verdict,
#: it is read from an artifact and never composed: `post_deployment_status` was a keyword
#: argument defaulting to the string "PENDENTE", so the one verdict reserved for an external
#: witness was, in the payload, whatever the caller typed.
POST_DEPLOYMENT_WITNESS_ARTIFACT = "post-deployment-witness"

#: What the witness must show before the payload may carry anything but PENDENTE. Named
#: individually because `all(...)` over a truncated dict is True, and this is the gate the
#: project reserves for evidence it did not produce itself.
#:
#: These are the conditions `docs/PRODUCTION_CEREMONY.md` states: "The suite can report PASS
#: only with `total=15`, `passed=15`, `critical_failures=0`, a verified ruleset-bootstrap
#: attestation tied to the exact deployment Git SHA, authenticated evidence that the
#: persistent Project Instructions are installed, `POST_DEPLOYMENT_GATE=PASS`, and
#: `post_deployment_status=PASS`."
#:
#: Four of those seven were checked. The three that were not are the ones that say the suite
#: actually *ran*: a witness declaring `post_deployment_status: "PASS"`, `all_pass: true`,
#: `bootstrap_verified: true` and `critical_failures: 0` — with no `passed`, no `total` and
#: no installed Project Instructions — was accepted and published as a POST-DEPLOYMENT PASS.
#: The basis string beneath even printed `f"{payload.get('passed')}/{payload.get('total')}"`,
#: so the verdict asserted "15/15 cases" while requiring neither number.
#: Two of these are booleans standing for conditions the contract states in more detail:
#: `bootstrap_verified` for an attestation "tied to the exact deployment Git SHA", and
#: `project_bootstrap_installed` for *authenticated* evidence. A boolean is the witness
#: asserting its own conclusion, so `_witness_binding_refusal` additionally requires the
#: structured evidence each one summarises — see `_attestation_refusal` there, and the limit
#: recorded with it: this binds the witness to a named commit, it does not authenticate it.
WITNESS_REQUIRED = {
    "post_deployment_status": "PASS",
    "all_pass": True,
    "bootstrap_verified": True,
    "critical_failures": 0,
    "passed": 15,
    "total": 15,
    "project_bootstrap_installed": True,
}

#: The gate the ceremony contract names, checked separately because it is nested rather than
#: a flat key and `WITNESS_REQUIRED` compares scalars.
WITNESS_REQUIRED_GATE = "POST_DEPLOYMENT_GATE"

#: Payload blocks `compile` derives from registered artifacts rather than from its caller.
#: `extra` merges into the payload after every anchor is fixed and refused only keys that
#: had been *anchored* — which left the two blocks the render gate actually reads
#: (`publication_gate` and `policy_evaluation`) writable from outside. Passing
#: ``extra={"publication_gate": {"passed": True, ...}}`` reinstated, in one line, the
#: self-granted PASS that moving the verdict out of `compile`'s parameters removed.
DERIVED_BLOCKS = (
    "publication_gate",
    "policy_evaluation",
    "post_deployment",
    "consent",
    "operational_status",
    "artifacts",
    "provenance",
)

#: A locator is a dotted/bracketed path into the artifact, e.g.
#: ``observations[rs1799807].records[0].genotype`` or ``metrics.call_rate``.
_LOCATOR_STEP = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


#: How long a live-deployment witness may certify a payload. Section 259 forbids inheriting
#: another session's PASS, and a witness with no expiry is exactly that: run the ceremony once
#: and every report thereafter cites it. Thirty days is short enough that a certification names
#: a service that plausibly still exists, and long enough not to force a re-run per report.
MAX_WITNESS_AGE_DAYS = 30


class ProvenanceError(Exception):
    """A value could not be bound to the artifact it claims to come from."""


def _now() -> datetime:
    """Seam for tests; production always reads the clock."""
    return datetime.now(timezone.utc)


#: A full Git commit SHA as `scripts/bootstrap_attestation` resolves and records it. Short,
#: uppercase and `UNKNOWN` are the spellings that turn up, and none of them names a commit
#: this project can look up.
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")

#: The digest of an attestation file, as the verifier records it.
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _deployment_commit_sha(payload: dict[str, Any]) -> str | None:
    """The commit the bootstrap attestation was verified against, or None if unstated."""
    verification = payload.get("bootstrap_verification")
    if not isinstance(verification, dict):
        return None
    recorded = verification.get("source_commit_sha")
    if isinstance(recorded, bool) or not isinstance(recorded, str):
        return None
    return recorded if _GIT_SHA.match(recorded) else None


def _attestation_refusal(
    payload: dict[str, Any], *, block: str, digest_key: str, subject: str, flag: str
) -> str | None:
    """Require the structured evidence a `{flag}: true` claims to summarise.

    `bootstrap_verified` and `project_bootstrap_installed` were checked as bare booleans,
    which is the witness asserting its own conclusion. The live smoke already writes what
    it actually verified — `verify_bootstrap_attestation` returns a status, the attestation
    file's SHA-256 and the resolved `source_commit_sha`, and the smoke embeds the whole
    record — so the boolean is required to agree with it rather than stand in for it.
    """
    verification = payload.get(block)
    if not isinstance(verification, dict) or not verification:
        return (
            f"a testemunha declara {flag}=true sem registrar {block}: um booleano é a própria "
            f"testemunha afirmando sua conclusão, não a verificação {subject} que ela resume"
        )
    if verification.get("status") != "VERIFICADO":
        return (
            f"a testemunha declara {flag}=true, mas {block}.status é "
            f"{verification.get('status')!r}: o booleano e a evidência ao lado dele discordam"
        )
    declared = payload.get(digest_key)
    observed = verification.get("file_sha256")
    if not isinstance(observed, str) or not _SHA256_HEX.match(observed):
        return (
            f"{block}.file_sha256 não é um SHA-256 ({observed!r}); sem ele não há como saber "
            f"qual arquivo de atestação {subject} foi verificado"
        )
    if declared != observed:
        return (
            f"a testemunha nomeia {digest_key}={declared!r} e verificou {observed!r}: dois "
            "campos para o mesmo arquivo, e um deles descreve outro"
        )
    return None


def _witness_binding_refusal(payload: dict[str, Any]) -> str | None:
    """Why this witness may not certify *this* payload, or None if it may.

    The `WITNESS_REQUIRED` keys say the smoke run succeeded. They say nothing about *what* it
    ran against or *when*, so a witness satisfying them would certify every report the project
    ever produces, including reports built on a ruleset it never saw.

    Two of those keys are the ones that were supposed to name the deployment —
    `bootstrap_verified` and `project_bootstrap_installed` — and both arrived as bare
    booleans. The ceremony contract asks for a bootstrap attestation "tied to the exact
    deployment Git SHA" and authenticated evidence for the Project Instructions; `true` is
    neither. So the structured evidence the smoke already writes is required here, and the
    commit it resolved is carried onto the verdict.

    This binds, it does not authenticate. A caller able to write the witness can write a
    well-formed SHA into it, and this repository has no signing scheme that could tell a
    witness a deployment produced from one composed afterwards; that is recorded as an open
    design question rather than improvised. What it removes is the transfer — a witness taken
    against one deployment certifying another, which the ruleset hash, the target class and
    the freshness window could not separate on their own.
    """
    target = deployment_target.refusal(payload.get("target"))
    if target is not None:
        return target
    for kwargs in (
        {
            "block": "bootstrap_verification",
            "digest_key": "bootstrap_attestation_sha256",
            "subject": "do bootstrap do ruleset",
            "flag": "bootstrap_verified",
        },
        {
            "block": "project_instructions_verification",
            "digest_key": "project_instructions_attestation_sha256",
            "subject": "das Project Instructions",
            "flag": "project_bootstrap_installed",
        },
    ):
        refusal = _attestation_refusal(payload, **kwargs)
        if refusal is not None:
            return refusal
    if _deployment_commit_sha(payload) is None:
        return (
            "a testemunha não nomeia o commit implantado: "
            f"bootstrap_verification.source_commit_sha="
            f"{(payload.get('bootstrap_verification') or {}).get('source_commit_sha')!r} não é "
            "um SHA de commit Git de 40 caracteres. Sem ele a testemunha descreve *uma* "
            "implantação verificada e não *esta*, e serve a qualquer relatório com o mesmo "
            "ruleset, a mesma classe de alvo e a mesma janela de validade"
        )
    ruleset = payload.get("ruleset") if isinstance(payload.get("ruleset"), dict) else {}
    observed = ruleset.get("sha256")
    if observed != normative.RAW_SHA256:
        return (
            f"a testemunha foi tomada contra o ruleset {observed!r}, e este relatório declara "
            f"{normative.RAW_SHA256!r}: são implantações distintas e uma não atesta a outra"
        )
    raw = payload.get("completed_at")
    try:
        completed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return (
            f"a testemunha não registra um instante de conclusão legível ({raw!r}); sem ele "
            "não há como saber se ela descreve um serviço que ainda existe"
        )
    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)
    now = _now()
    if completed > now + timedelta(minutes=5):
        return f"a testemunha declara ter concluído no futuro ({raw!r})"
    age = now - completed
    if age > timedelta(days=MAX_WITNESS_AGE_DAYS):
        return (
            f"a testemunha tem {age.days} dias, acima do limite de {MAX_WITNESS_AGE_DAYS}; "
            "a seção 259 proíbe herdar o PASS de outra sessão e uma testemunha sem validade "
            "seria exatamente isso"
        )
    return None


def _exactly(observed: Any, expected: Any) -> bool:
    """Equal *and* the same type, because `1 == True` and `False == 0` in Python.

    `payload.get(key) != expected` accepted every type-confused spelling of the four
    conditions that gate POST-DEPLOYMENT: `all_pass: 1`, `bootstrap_verified: 1`, and — worst
    — `critical_failures: false`, which is not a count of anything and was read as zero
    critical failures. A JSON producer emits any of these without meaning to, and the witness
    is the one artifact this project refuses to compose for itself, so it must be read
    exactly as written.
    """
    if isinstance(expected, bool) or isinstance(observed, bool):
        return observed is expected
    return type(observed) is type(expected) and observed == expected


def witness_verdict(
    payload: dict[str, Any],
    *,
    sha256: str | None = None,
    path: str | None = None,
    fixture: bool = False,
) -> dict[str, Any]:
    """Judge one POST-DEPLOYMENT witness, PASS or PENDENTE with the reason.

    Module-level because two components must reach the same conclusion about the same file:
    `PayloadCompiler`, which decides what a report may print, and the case-manifest builder,
    which decides what the policy engine is told. Two implementations of "is this witness
    good enough" would eventually disagree, and then the report and the engine would too.
    """
    unmet = sorted(key for key, expected in WITNESS_REQUIRED.items() if not _exactly(payload.get(key), expected))
    if unmet:
        return {
            "status": "PENDENTE",
            "basis": (
                "a testemunha registrada não sustenta um veredicto: "
                + ", ".join(f"{key}={payload.get(key)!r}" for key in unmet)
            ),
            "witness_sha256": sha256,
        }
    gate = payload.get("post_deployment_gate")
    gate = gate if isinstance(gate, dict) else {}
    if gate.get("gate") != WITNESS_REQUIRED_GATE or gate.get("state") != "PASS":
        return {
            "status": "PENDENTE",
            "basis": (
                f"a testemunha não registra {WITNESS_REQUIRED_GATE} em PASS "
                f"(gate={gate.get('gate')!r}, state={gate.get('state')!r}); o contrato da "
                "cerimônia de produção exige esse portão explicitamente"
            ),
            "witness_sha256": sha256,
        }
    if not fixture:
        refusal = _witness_binding_refusal(payload)
        if refusal is not None:
            return {"status": "PENDENTE", "basis": refusal, "witness_sha256": sha256}
    return {
        "status": "PASS",
        # The fixture gets its own sentence rather than the live one with fixture numbers
        # substituted in: "bootstrap verificado ao vivo, 0 falhas críticas" is a false
        # statement about a witness that contacted nothing, and it would have been written
        # into the anchor's basis — the field a reader consults to learn what happened.
        "basis": (
            "fixture de QA de layout: nenhuma implantação foi contatada e nenhum "
            "bootstrap foi verificado; a face PASS existe aqui apenas para medir o layout"
            if fixture
            else (
                f"{payload.get('passed')}/{payload.get('total')} casos do conjunto "
                f"{payload.get('suite')!r} contra a implantação "
                f"{payload.get('deployment_id')!r} — "
                f"{deployment_target.describe(payload.get('target'))} —, bootstrap "
                f"verificado ao vivo no commit {_deployment_commit_sha(payload)}, "
                f"{payload.get('critical_failures')} falhas críticas"
            )
        ),
        "witness_sha256": sha256,
        "witness_path": path,
        "deployment_id": payload.get("deployment_id"),
        # Which deployment this PASS is about. `deployment_id` is a label the operator chose;
        # this is the commit the bootstrap attestation was verified against. The fixture has
        # none, and must not borrow one.
        "deployment_commit_sha": None if fixture else _deployment_commit_sha(payload),
        # What the run reached, carried beside the verdict. A PASS taken against a container
        # on a CI runner and a PASS taken against a deployed host are both real results and
        # certify different things; the reader has to be able to tell them apart without
        # opening the witness file.
        "target": payload.get("target") if not fixture else None,
        "classification": payload.get("classification"),
        # Named for the same reason the policy verdict names its origin: a reader must be
        # able to tell a live witness from the layout-QA fixture without reading anchors.
        "origin": "fixture" if fixture else "live-deployment-witness",
    }


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def render_value(value: Any) -> str:
    """Render a value exactly as the FINAL document will print it.

    An anchor records this rendering as `observed_value`, and the document prints the same
    value through `reporting.engine._safe`, so the two must agree character for character:
    an anchor that reads differently from the text beside it has stopped attesting to the
    document. `_safe` used to hold a second copy of these rules and the copies drifted — it
    serialised mappings with `sort_keys=True` and this did not, so a payload carrying a dict
    whose keys were not already in order published a document whose face and provenance block
    disagreed, with zero blockers: `provenance_blockers` recomputes `render_value` on both
    sides of its comparison, so it agreed with itself while agreeing with neither.

    `_safe` now delegates here and adds only its substitution for an absent value, so there is
    one rendering and no copy left to drift. `tests/test_rendered_text_matches_the_document.py`
    pins the agreement, the end-to-end case above, and the bound on that substitution.
    """
    if value is None or value == "":
        return UNAVAILABLE
    if isinstance(value, (dict, list, tuple)):
        # `sort_keys` makes the text a function of the mapping's contents rather than of the
        # order a caller happened to build it in, so two payloads carrying the same values
        # render — and hash — identically.
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _resolve(artifact: Any, locator: str) -> Any:
    """Read `locator` out of `artifact`, raising ProvenanceError if the path is absent.

    Mapping keys are tried before list indices, so a numeric dictionary key still resolves.
    """
    if not str(locator).strip():
        # An empty locator resolves to the whole artifact, so the anchor would name no
        # particular measurement while still reading as a derived value.
        raise ProvenanceError("a locator must name a path inside the artifact")
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

    def __init__(
        self,
        *,
        case_id: str,
        report_id: str,
        policy_evaluation: "Path | str | None" = None,
        post_deployment_witness: "Path | str | None" = None,
        consent: "Path | str | None" = None,
    ) -> None:
        if not str(case_id).strip():
            raise ProvenanceError("case_id is required")
        self.case_id = str(case_id)
        self.report_id = str(report_id)
        self._artifacts: dict[str, Artifact] = {}
        self._anchors: dict[str, Anchor] = {}
        self._values: dict[str, Any] = {}
        self._sections: dict[str, Any] = {}
        self._findings: list[dict[str, Any]] = []
        # Registered here rather than by each builder, so a builder cannot forget it and
        # silently produce a payload whose verdict came from nowhere. Absent, `compile`
        # writes a refusal — which is the correct payload for a run the policy engine never
        # judged.
        self._fixture_verdict = False
        self._fixture_witness = False
        self._fixture_consent = False
        if policy_evaluation is not None:
            self._install_verdict(
                Artifact.from_path(POLICY_EVALUATION_ARTIFACT, Path(policy_evaluation))
            )
        # Same reasoning, same route: the POST-DEPLOYMENT verdict is a claim about a running
        # service, so it enters as a file that a live run wrote and never as a string the
        # builder chose.
        if post_deployment_witness is not None:
            self._install_witness(
                Artifact.from_path(POST_DEPLOYMENT_WITNESS_ARTIFACT, Path(post_deployment_witness))
            )
        # And again for the consent record. CONSENT_GATE is evaluated once per run, for the
        # whole manifest; whether *this* report falls inside what was authorised is a
        # per-report question only the compiler can answer, and it answers it from the record
        # on disk rather than from anything the builder says.
        if consent is not None:
            self._artifacts[CONSENT_ARTIFACT] = Artifact.from_path(CONSENT_ARTIFACT, Path(consent))

    # -- artifacts ---------------------------------------------------------------

    def register(self, artifact: Artifact) -> Artifact:
        """Register a pipeline artifact values may be anchored to.

        The policy verdict is not one of them. Moving the verdict out of `compile`'s
        parameters closed the door a builder used to grant itself a PASS — and left this one
        open: `register(Artifact.from_payload("policy-evaluation", {...ready: True...}))`
        installed an invented verdict under the reserved name and published FINAL with
        `operational_status: VERIFICADO`. Verified by doing it.

        The verdict may only arrive through the constructor, which reads a file the policy
        engine wrote, or through the fixture path, which can only exist on a payload whose
        every value is a fixture.
        """
        if artifact.name == POLICY_EVALUATION_ARTIFACT:
            raise ProvenanceError(
                f"{POLICY_EVALUATION_ARTIFACT!r} is not a registrable artifact: the normative "
                "verdict is read from the policy engine's own output, via "
                "PayloadCompiler(policy_evaluation=<path>). Composing one here would be the "
                "self-granted PASS this indirection exists to prevent."
            )
        if artifact.name == POST_DEPLOYMENT_WITNESS_ARTIFACT:
            raise ProvenanceError(
                f"{POST_DEPLOYMENT_WITNESS_ARTIFACT!r} is not a registrable artifact: the "
                "POST-DEPLOYMENT verdict is read from the witness a live smoke run wrote, via "
                "PayloadCompiler(post_deployment_witness=<path>). An in-memory witness is a "
                "payload asserting that a service it never contacted behaved correctly."
            )
        if artifact.name == CONSENT_ARTIFACT:
            raise ProvenanceError(
                f"{CONSENT_ARTIFACT!r} is not a registrable artifact: consent is read from the "
                "operator's record, via PayloadCompiler(consent=<path>). A consent record "
                "composed by the component that wants to publish is not consent."
            )
        existing = self._artifacts.get(artifact.name)
        if existing is not None and existing.sha256 != artifact.sha256:
            raise ProvenanceError(f"artifact {artifact.name!r} registered twice with different content")
        self._artifacts[artifact.name] = artifact
        return artifact

    def _install_verdict(self, artifact: Artifact, *, fixture: bool = False) -> None:
        """Install the policy verdict. Private, and the only route that exists."""
        self._artifacts[POLICY_EVALUATION_ARTIFACT] = artifact
        self._fixture_verdict = fixture

    def _install_witness(self, artifact: Artifact, *, fixture: bool = False) -> None:
        """Install the POST-DEPLOYMENT witness. Private, and the only route that exists."""
        self._artifacts[POST_DEPLOYMENT_WITNESS_ARTIFACT] = artifact
        self._fixture_witness = fixture

    def _install_consent(self, artifact: Artifact, *, fixture: bool = False) -> None:
        """Install the consent record. Private, and the only route that exists."""
        self._artifacts[CONSENT_ARTIFACT] = artifact
        self._fixture_consent = fixture

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

    def post_deployment(self) -> dict[str, Any]:
        """The POST-DEPLOYMENT verdict, read from a live-deployment witness.

        Section 260 reserves this for evidence that a *deployed* service behaved correctly,
        which is precisely the claim a payload cannot make about itself. It arrived as a
        keyword argument defaulting to "PENDENTE" — honest by default, and forgeable by
        anyone who passed a different string.

        A witness is accepted only when it says the suite passed in full, the bootstrap was
        verified live and no critical failure occurred. Anything short of that, or no witness
        at all, is PENDENTE with the reason attached.

        Two further bindings keep a witness from becoming a reusable token. It must have been
        taken against *this* ruleset — a smoke run against another version certifies another
        deployment — and it must be recent, because section 259 forbids inheriting a PASS from
        a session that is not this one, and a service verified a year ago may no longer exist.
        """
        artifact = self._artifacts.get(POST_DEPLOYMENT_WITNESS_ARTIFACT)
        if artifact is None:
            return {
                "status": "PENDENTE",
                "basis": (
                    "nenhuma testemunha de pós-implantação foi registrada; a seção 260 "
                    "reserva este veredicto a evidência de um serviço implantado, que um "
                    "payload não pode produzir sobre si mesmo"
                ),
            }
        return witness_verdict(
            artifact.payload if isinstance(artifact.payload, dict) else {},
            sha256=artifact.sha256,
            path=artifact.path,
            fixture=self._fixture_witness,
        )

    def consent_scope(self) -> dict[str, Any]:
        """Whether the registered consent record authorises *this* report's domain.

        `publication_gate.consent_verified` came from the engine's CONSENT_GATE, which is
        evaluated once for the whole run and checks only that some consent exists with some
        version and some non-empty domain list. It cannot know which of the eleven reports is
        being compiled, so a record authorising ANCESTRALIDADE cleared the gate for a clinical
        report — a real consent, for the wrong thing, reading as authorisation.

        The report's domain comes from `reporting.consent.REPORT_DOMAINS` keyed by
        `report_id`, never from the builder: a builder that declared its own domain could
        declare the one it happened to have consent for.

        A record that fails validation refuses here rather than raising, so the payload still
        compiles — the measurements are facts either way — and carries the reason it may not
        be published.
        """
        artifact = self._artifacts.get(CONSENT_ARTIFACT)
        record = artifact.payload if artifact is not None else None
        if artifact is not None:
            if self._fixture_consent:
                input_sha256 = "fixture"
            else:
                control_artifacts = {
                    CONSENT_ARTIFACT,
                    POLICY_EVALUATION_ARTIFACT,
                    POST_DEPLOYMENT_WITNESS_ARTIFACT,
                }
                input_hashes = {
                    str(candidate.payload.get("input_sha256") or "").strip()
                    for name, candidate in self._artifacts.items()
                    if name not in control_artifacts
                    and isinstance(candidate.payload, dict)
                    and str(candidate.payload.get("input_sha256") or "").strip()
                }
                if len(input_hashes) != 1:
                    return {
                        "covers": False,
                        "report_domain": REPORT_DOMAINS.get(str(self.report_id)),
                        "record_sha256": artifact.sha256,
                        "origin": "operator-record",
                        "basis": (
                            "o registro de consentimento não pode ser vinculado aos bytes "
                            "analisados: a execução não declara um input_sha256 único"
                        ),
                    }
                input_sha256 = next(iter(input_hashes))
            try:
                validate_consent(
                    record,
                    case_id=self.case_id,
                    input_sha256=input_sha256,
                )
            except ConsentError as exc:
                return {
                    "covers": False,
                    "report_domain": REPORT_DOMAINS.get(str(self.report_id)),
                    "record_sha256": artifact.sha256,
                    # Carried on the refusal too, so a reader inspecting the block finds the
                    # same keys whichever way it went.
                    "origin": "fixture" if self._fixture_consent else "operator-record",
                    "basis": f"o registro de consentimento não é válido para esta execução: {exc}",
                }
        try:
            verdict = consent_scope_verdict(
                record,
                self.report_id,
                sha256=artifact.sha256 if artifact is not None else None,
            )
        except ConsentError as exc:
            return {"covers": False, "report_domain": None, "basis": str(exc)}
        if artifact is not None:
            # Named for the same reason the policy verdict and the witness name theirs: a
            # reader must be able to tell the operator's record from the layout-QA fixture.
            verdict["origin"] = "fixture" if self._fixture_consent else "operator-record"
        return verdict

    def _policy_binding_refusal(self, evaluated: dict[str, Any]) -> str | None:
        """Why this evaluation may not authorise *this* payload, or None if it may.

        Mirrors `_witness_binding_refusal`: the witness is bound to the ruleset it judged and
        the moment it ran, and a policy evaluation needs the same treatment for the same
        reason. An evaluation with the right plane and gate shape says *a* run succeeded; it
        says nothing about which ruleset it judged or which case, so without these an
        evaluation produced once would authorise every report this project ever emits.

        This does not prove authorship. A caller able to write the file can copy these fields
        too. What it removes is the trivial forgery — a minimal hand-written object with four
        PASS planes — and the reuse of a real evaluation across rulesets or cases, which is
        the failure this gate most needs to stop. Cryptographic proof of origin requires a
        signing scheme this repository does not have; that is named in the PR rather than
        improvised here.
        """
        if not isinstance(evaluated, dict) or not evaluated:
            return (
                "o artefato registrado como avaliação do policy engine não é um objeto JSON "
                "com conteúdo; um arquivo vazio ou de outro formato não é um veredicto"
            )
        ruleset = evaluated.get("ruleset") if isinstance(evaluated.get("ruleset"), dict) else {}
        observed = ruleset.get("sha256")
        if observed != normative.RAW_SHA256:
            return (
                f"a avaliação foi produzida contra o ruleset {observed!r}, e este relatório "
                f"declara {normative.RAW_SHA256!r}: uma não autoriza a outra"
            )
        declared_case = evaluated.get("case_id")
        if declared_case is not None and str(declared_case) != self.case_id:
            return (
                f"a avaliação pertence ao caso {declared_case!r} e este payload é do caso "
                f"{self.case_id!r}; um veredicto não é transferível entre casos"
            )
        return None

    def policy_verdict(self) -> dict[str, Any]:
        """The single normative verdict, read from a registered policy-engine evaluation.

        Every report builder used to pass its own `publication_gate` and `policy_evaluation`
        into `compile`, and nine of them did: `consent_verified` was `bool(case_id)`,
        `evidence_verified` was the literal `True`, and all four planes plus
        FINAL_AUDIT_GATE went to PASS whenever a local variable called `verified` was true.
        The component that produced the report also declared the report authorised — which
        makes "authorised" a statement about the builder's own opinion, not about the policy
        engine's 21 gates.

        Measured on a real case, the two disagreed exactly as one would expect: the engine
        returned `ready_for_requested_operation: False` for the same run whose payloads all
        carried `True`.

        So the verdict is no longer a parameter. It is copied from the artifact a policy run
        produced, with that artifact's SHA-256 recorded beside it, and when no such artifact
        was registered this returns a refusal. A builder can still decline to register one;
        what it can no longer do is invent the answer.
        """
        artifact = self._artifacts.get(POLICY_EVALUATION_ARTIFACT)
        if artifact is None:
            return {
                "ready_for_requested_operation": False,
                "planes": {name: {"state": "BLOCKED"} for name in REQUIRED_PLANES},
                "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "BLOCKED", "blocking": True}],
                "source": {
                    "status": UNAVAILABLE,
                    "reason": (
                        f"nenhuma avaliação do policy engine foi registrada como artefato "
                        f"{POLICY_EVALUATION_ARTIFACT!r}; sem veredicto da autoridade "
                        "normativa este payload não declara autorização alguma"
                    ),
                },
            }
        evaluated = artifact.payload if isinstance(artifact.payload, dict) else {}
        # Registering *a file* is not registering an evaluation. This copied
        # `ready_for_requested_operation`, the plane states and the gate list out of whatever
        # JSON `--policy-evaluation` pointed at, recorded that file's SHA-256, and labelled
        # the result `origin: policy-engine-output` with `status: VERIFICADO`. A hand-written
        # object with four PASS planes was indistinguishable from the engine's verdict, and
        # the hash proves only that the file was read, never where it came from.
        binding = self._policy_binding_refusal(evaluated)
        if binding is not None:
            return {
                "ready_for_requested_operation": False,
                "planes": {name: {"state": "BLOCKED"} for name in REQUIRED_PLANES},
                "gates": [{"gate": "FINAL_AUDIT_GATE", "state": "BLOCKED", "blocking": True}],
                "source": {
                    "status": UNAVAILABLE,
                    "artifact": POLICY_EVALUATION_ARTIFACT,
                    "sha256": artifact.sha256,
                    "path": artifact.path,
                    "reason": binding,
                },
            }
        planes = evaluated.get("planes") if isinstance(evaluated.get("planes"), dict) else {}
        return {
            "ready_for_requested_operation": evaluated.get("ready_for_requested_operation") is True,
            "planes": {
                name: {
                    "state": str(
                        (planes.get(name) or {}).get("state", "BLOCKED")
                        if isinstance(planes.get(name), dict)
                        else "BLOCKED"
                    )
                }
                for name in REQUIRED_PLANES
            },
            "gates": [g for g in (evaluated.get("gates") or []) if isinstance(g, dict)],
            "source": {
                "status": "VERIFICADO",
                "artifact": POLICY_EVALUATION_ARTIFACT,
                "sha256": artifact.sha256,
                "path": artifact.path,
                # Named on the payload, so a reader can tell a verdict the engine wrote from
                # the layout-QA fixture without inspecting anchors.
                "origin": "fixture" if self._fixture_verdict else "policy-engine-output",
            },
        }

    def publication_gate(self, verdict: dict[str, Any], consent: dict[str, Any]) -> dict[str, Any]:
        """Derive the publication gate from the verdict, never from the builder.

        `consent_verified` was `bool(case_id)` — having an identifier for a case is not a
        consent instrument, its version, its purpose or its scope. `evidence_verified` was
        written as the literal `True`. Both are now read from the gates the policy engine
        actually evaluated, so the report cannot claim a permission the engine withheld.

        `placeholders_resolved` stays False here: it is a property of the rendered document,
        not of the payload, and `render_document` measures it against the real text.

        `consent_scope_verified` is the one key here the engine cannot supply, and it is
        strictly subtractive: it can withhold publication from a report outside the authorised
        domains, never grant it to one the engine refused.
        """
        by_gate = {str(g.get("gate")): str(g.get("state")) for g in verdict.get("gates") or []}
        planes = verdict.get("planes") or {}
        return {
            "passed": verdict.get("ready_for_requested_operation") is True,
            "consent_verified": by_gate.get("CONSENT_GATE") == "PASS",
            "consent_scope_verified": consent.get("covers") is True,
            "qc_verified": by_gate.get("QC_GATE") == "PASS",
            "evidence_verified": (planes.get("evidence") or {}).get("state") == "PASS",
            "placeholders_resolved": False,
            "derived_from": verdict.get("source"),
        }

    def compile(
        self,
        *,
        execution_manifest: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Produce the payload `reporting.engine.render_document` consumes.

        Sections and findings come from what was actually anchored during compilation, not
        from a parameter: accepting them here would let a caller pass content that was
        never bound to an artifact. The publication gate, the policy evaluation and the
        POST-DEPLOYMENT verdict are derived for the same reason — see `policy_verdict` and
        `post_deployment`.
        """
        schema_sources = [
            (name, artifact)
            for name, artifact in self._artifacts.items()
            if isinstance(artifact.payload.get("input"), dict)
            and str(artifact.payload["input"].get("schema") or "").strip()
        ]
        schemas = {
            str(artifact.payload["input"]["schema"]).strip()
            for _name, artifact in schema_sources
        }
        if len(schemas) > 1:
            raise ProvenanceError(
                f"registered artifacts disagree about input.schema: {sorted(schemas)}"
            )
        if schema_sources:
            source_name, _source = schema_sources[0]
            self.derive(
                "input.schema",
                artifact=source_name,
                locator="input.schema",
                status="VERIFICADO",
                basis="schema medido do artefato de QC/entrada compilado",
                kind="computed",
            )

        if self._fixture_verdict or self._fixture_witness or self._fixture_consent:
            # The fixture verdict exists so layout QA can render a FINAL document and measure
            # it. It is safe only while every value on the payload is a fixture, which floors
            # the operational status at NÃO DISPONÍVEL and prints that on the document's face.
            # A measured value beside a fixture verdict would publish a real claim on an
            # invented authorisation.
            measured = sorted(
                name for name, anchor in self._anchors.items() if anchor.kind not in FIXTURE_KINDS
            )
            if measured:
                raise ProvenanceError(
                    f"a fixture policy verdict cannot carry measured values {measured}; "
                    "compile with a real policy evaluation or anchor these as fixtures"
                )
        policy_evaluation = self.policy_verdict()
        consent = self.consent_scope()
        publication_gate = self.publication_gate(policy_evaluation, consent)
        post_deployment = self.post_deployment()
        for required in ("summary", "sources", "limitations"):
            if required not in self._anchors:
                raise ProvenanceError(f"{required!r} must be anchored before compiling")
        # Anchored here rather than left to each builder: they are compiler identity, not
        # measurements, and a builder that forgot one would reintroduce exactly the hole
        # this closes. `case_control` because that is what they are — the run's own context,
        # never a reading from a scientific artifact.
        self.state(
            "case_id",
            self.case_id,
            kind="case_control",
            basis="identificador do caso com que este payload foi compilado",
            status="VERIFICADO",
        )
        self.state(
            "report_id",
            self.report_id,
            kind="case_control",
            basis="identificador do relatório com que este payload foi compilado",
            status="VERIFICADO",
        )
        authority_kind = "fixture" if self._fixture_verdict else "case_control"
        authority_status = UNAVAILABLE if self._fixture_verdict else "VERIFICADO"
        self.state(
            "policy_evaluation",
            policy_evaluation,
            kind=authority_kind,
            basis="veredito de política usado para compilar este payload",
            status=authority_status,
        )
        for gate_key in (
            "passed",
            "consent_verified",
            "consent_scope_verified",
            "qc_verified",
            "evidence_verified",
        ):
            self.state(
                f"publication_gate.{gate_key}",
                publication_gate.get(gate_key),
                kind=authority_kind,
                basis="gate de publicação derivado dos artefatos de controle",
                status=authority_status,
            )
        if self._fixture_witness:
            # Layout QA has to be able to render the PASS variant of the header. It may print
            # the string; what it may not do is anchor it as anything but a fixture, which is
            # what `provenance_blockers` reads back.
            self.state(
                "post_deployment_status",
                post_deployment["status"],
                kind="fixture",
                basis=post_deployment["basis"],
                status=UNAVAILABLE,
            )
        elif post_deployment["status"] == "PASS":
            # Read out of the witness by locator, so the anchor carries that file's SHA-256.
            # A payload that prints PASS now names the document that says so, and a payload
            # compiled without one cannot reach this branch at all.
            self.derive(
                "post_deployment_status",
                artifact=POST_DEPLOYMENT_WITNESS_ARTIFACT,
                locator="post_deployment_status",
                status="VERIFICADO",
                basis=post_deployment["basis"],
                kind="evidence_retrieval",
            )
        else:
            self.state(
                "post_deployment_status",
                post_deployment["status"],
                kind="case_control",
                basis=post_deployment["basis"],
                status="VERIFICADO",
            )

        # `template_fill` prints the execution manifest — workflow logs, tool versions, the
        # QC reference — and it used to be serialised straight into the payload as
        # `dict(execution_manifest or {})`, bound to nothing. Every other printed value is
        # anchored, so an edit to it is caught by `provenance_blockers`; an edit to a tool
        # version or a log locator here was invisible, and the document went on presenting
        # it as the record of how the report was produced. Each key is anchored the way one
        # finding field is: run context, never an executed measurement.
        execution_manifest_values = dict(execution_manifest or {})
        for key in sorted(execution_manifest_values, key=str):
            self.state(
                _anchor_name_for_execution_manifest(str(key)),
                execution_manifest_values[key],
                kind="case_control",
                basis="registrado no manifesto de execução desta corrida",
                status="VERIFICADO",
            )

        data: dict[str, Any] = {
            "case_id": self.case_id,
            "report_id": self.report_id,
            **(
                {"input": {"schema": self.value("input.schema")}}
                if "input.schema" in self._anchors
                else {}
            ),
            "summary": self.value("summary"),
            "ruleset": normative.ruleset_block(include_sha256=False),
            "publication_gate": dict(publication_gate),
            "policy_evaluation": dict(policy_evaluation),
            "post_deployment_status": self.value("post_deployment_status"),
            "post_deployment": dict(post_deployment),
            "consent": dict(consent),
            "sections": dict(self._sections),
            "findings": [dict(x) for x in self._findings],
            "execution_manifest": execution_manifest_values,
            "sources": self.value("sources"),
            "limitations": self.value("limitations"),
            "operational_status": self.status_floor(),
            "artifacts": {
                name: {"sha256": art.sha256, "path": art.path}
                for name, art in sorted(self._artifacts.items())
            },
        }
        if extra:
            # `extra` writes into the payload after every anchor is fixed, so it could
            # silently replace an anchored value with something the provenance block still
            # describes in its old terms. For summary/sources/limitations the render-time
            # gate caught that; for `case_id` and `post_deployment_status` nothing did, and
            # a test fixture was in fact using it to stamp POST-DEPLOYMENT PASS on a payload
            # compiled as PENDENTE. Refused at the source rather than only at render, so a
            # caller learns immediately which field it may not reach this way.
            overwritten = sorted(key for key in extra if key in self._anchors)
            if overwritten:
                raise ProvenanceError(
                    f"extra may not overwrite anchored fields {overwritten}; pass the value "
                    "through the anchor that records it, so the payload and its provenance "
                    "cannot disagree"
                )
            # Anchored fields were refused; the derived authority blocks were not, and those
            # are the ones `reporting.engine.render_blockers` reads to decide whether a FINAL
            # document may be produced. `extra={"publication_gate": {"passed": True, ...}}`
            # published a report the policy engine had blocked. Verified by doing it.
            reserved = sorted(key for key in extra if key in DERIVED_BLOCKS)
            if reserved:
                raise ProvenanceError(
                    f"extra may not supply derived blocks {reserved}; they are read from the "
                    "artifacts registered on this compiler, and a caller that writes them is "
                    "granting itself the verdict those artifacts exist to withhold"
                )
            # The anchors above are named `execution_manifest[key]`, not
            # `execution_manifest`, so the whole-block name is not in `self._anchors` and the
            # refusal above would let `extra` replace the block wholesale — anchoring each
            # key and then permitting the container to be swapped would close nothing.
            if "execution_manifest" in extra:
                raise ProvenanceError(
                    "extra may not replace execution_manifest; pass it to compile(), which "
                    "anchors each key, so the payload and its provenance cannot disagree"
                )
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

#: Printed on the face of every FINAL report and, until this existed, anchored by nothing.
#: Editing `case_id` after compilation produced a report about a different person with zero
#: blockers — the exact hand-edit this module exists to catch, on the one field that binds a
#: genomic report to a human being. `FindingBuilder` had already reasoned that "the id is
#: itself printed, so it is anchored like any other value"; the same sentence applies here
#: and was not applied.
IDENTITY_FIELDS = ("case_id", "report_id", "post_deployment_status")
AUTHORITY_FIELDS = ("policy_evaluation",)
#: Per-finding keys printed verbatim by `reporting.engine._final_markdown`.
FINDING_FIELDS = (
    "domain", "nature", "priority", "observed_data", "qc",
    "evidence_refs", "interpretation", "uncertainties", "confirmation", "status",
)


def _anchor_name_for_section(title: str) -> str:
    return f"sections[{title}]"


def _anchor_name_for_finding(finding_id: str, key: str) -> str:
    return f"findings[{finding_id}].{key}"


def _anchor_name_for_execution_manifest(key: str) -> str:
    return f"execution_manifest[{key}]"


def fixture_payload(
    *,
    case_id: str,
    report_id: str,
    summary: str,
    sections: dict[str, Any] | None = None,
    basis: str,
    post_deployment_status: str = "PENDENTE",
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
    # Layout QA has to render a FINAL document to measure it, so it registers a verdict —
    # but a *fixture* one, carrying its own nature in `source`, and every value in the
    # payload is still anchored as `fixture`, which floors the operational status at
    # NÃO DISPONÍVEL and prints that on the document's face. The fixture verdict is a
    # payload-level object here, never a file a real run could pick up by accident.
    compiler._install_verdict(
        Artifact.from_payload(
            POLICY_EVALUATION_ARTIFACT,
            {
                "ready_for_requested_operation": True,
                # Bound like a real evaluation. The QA fixture is exempt from *producing*
                # clinical evidence, not from the binding: an unbound fixture verdict would
                # be exactly the shape `policy_verdict` now refuses, and layout QA must
                # exercise the same acceptance path a real run takes.
                "ruleset": {"sha256": normative.RAW_SHA256},
                "case_id": case_id,
                "planes": {name: {"state": "PASS"} for name in REQUIRED_PLANES},
                "gates": [
                    {"gate": "FINAL_AUDIT_GATE", "state": "PASS", "blocking": True},
                    {"gate": "CONSENT_GATE", "state": "PASS", "blocking": True},
                    {"gate": "QC_GATE", "state": "PASS", "blocking": True},
                ],
                "nature": "fixture de QA de layout; nenhuma avaliação real de política",
            },
        ),
        fixture=True,
    )
    # Layout QA renders FINAL, so it needs a consent record covering the report's domain. It
    # gets a fixture one, declared as such on the payload, bound to the fixture case, and — in
    # common with every other value here — anchored so the document's status floor stays
    # NÃO DISPONÍVEL. The bytes it authorises are the literal string "fixture", which no real
    # input can hash to.
    compiler._install_consent(
        Artifact.from_payload(
            CONSENT_ARTIFACT,
            {
                "schema": CONSENT_SCHEMA,
                "subject_id": "fixture",
                "case_id": str(case_id),
                "input_sha256": "fixture",
                "version": "fixture",
                "authorized_domains": list(ALLOWED_CONSENT_DOMAINS),
                "granted_at": "2026-01-01",
                "expires_at": None,
                "instrument": "fixture de QA de layout",
                "instrument_version": "1.0",
                "captured_by": "reporting.provenance.fixture_payload",
                "affirmations": {key: True for key in REQUIRED_AFFIRMATIONS},
                "verified": True,
                "basis": basis,
            },
        ),
        fixture=True,
    )
    # The POST-DEPLOYMENT header has a PENDENTE face and a PASS face, and layout QA has to be
    # able to render both. It gets the PASS face the same way a real run does — from a witness
    # — except that this one declares itself a fixture, is anchored as one, and so cannot be
    # mistaken for evidence that a service was contacted.
    if post_deployment_status not in {"PENDENTE", "PASS"}:
        raise ProvenanceError(
            f"post_deployment_status={post_deployment_status!r}: a fixture may render the "
            "PENDENTE or the PASS face of the header, and nothing else"
        )
    if post_deployment_status == "PASS":
        compiler._install_witness(
            Artifact.from_payload(
                POST_DEPLOYMENT_WITNESS_ARTIFACT,
                {
                    **WITNESS_REQUIRED,
                    "suite": "fixture",
                    "passed": 0,
                    "total": 0,
                    "deployment_id": "fixture",
                    "classification": (
                        "fixture de QA de layout; nenhuma implantação foi contatada"
                    ),
                },
            ),
            fixture=True,
        )
    return compiler.compile(
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

    for name in SCALAR_FIELDS + IDENTITY_FIELDS + AUTHORITY_FIELDS:
        check(name, data.get(name))
    publication = (
        data.get("publication_gate")
        if isinstance(data.get("publication_gate"), dict)
        else {}
    )
    for gate_key in (
        "passed",
        "consent_verified",
        "consent_scope_verified",
        "qc_verified",
        "evidence_verified",
    ):
        check(f"publication_gate.{gate_key}", publication.get(gate_key))

    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    for title, value in sections.items():
        check(_anchor_name_for_section(str(title)), value)

    # `template_fill` prints this block as the record of how the report was produced —
    # workflow logs, tool versions, the QC reference. Unanchored, a post-compilation edit to
    # any of it passed every check here.
    execution_manifest = (
        data.get("execution_manifest")
        if isinstance(data.get("execution_manifest"), dict)
        else {}
    )
    for key, value in execution_manifest.items():
        check(_anchor_name_for_execution_manifest(str(key)), value)

    findings = data.get("findings") if isinstance(data.get("findings"), list) else []
    present_finding_anchors: set[str] = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            blockers.append(f"provenance:finding_shape:{index}")
            continue
        finding_id = str(finding.get("id") or f"index-{index}")
        id_anchor = f"findings[{finding_id}].id"
        present_finding_anchors.add(id_anchor)
        check(id_anchor, finding.get("id"))
        for key in FINDING_FIELDS:
            if key in finding:
                name = _anchor_name_for_finding(finding_id, key)
                present_finding_anchors.add(name)
                check(name, finding[key])

    # Check the reverse direction too. A hand edit that removes a section or one finding
    # key leaves its original anchor behind; checking only values still present in `data`
    # made that deletion invisible. Limit the comparison to the two structured namespaces
    # so internal/artifact anchors do not become payload fields by accident.
    present_section_anchors = {
        _anchor_name_for_section(str(title)) for title in sections
    }
    present_execution_manifest_anchors = {
        _anchor_name_for_execution_manifest(str(key)) for key in execution_manifest
    }
    for name in fields:
        if name.startswith("sections[") and name not in present_section_anchors:
            blockers.append(f"provenance:missing_value:{name}")
        elif name.startswith("findings[") and name not in present_finding_anchors:
            blockers.append(f"provenance:missing_value:{name}")
        elif (
            name.startswith("execution_manifest[")
            and name not in present_execution_manifest_anchors
        ):
            # A deleted key leaves its anchor behind; checking only what `data` still carries
            # made the deletion invisible, and the reader loses a tool version without a word.
            blockers.append(f"provenance:missing_value:{name}")

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

    # The header prints `post_deployment_status`, which is anchored, while the detail block
    # beside it is not. Left unchecked they could disagree — a face reading PENDENTE over a
    # block naming a witness SHA-256, or the reverse. Whichever was edited, the payload is
    # no longer describing one run.
    detail = data.get("post_deployment")
    if isinstance(detail, dict) and detail.get("status") != data.get("post_deployment_status"):
        blockers.append("provenance:post_deployment_disagreement")
    # The header prints what the verdict was taken against, and that clause is read from
    # this block rather than from an anchor. Recompute the target's class from the addresses
    # the block itself records, so editing "loopback" up to "public-host" is caught here
    # exactly as `witness_verdict` catches it on the way in.
    if isinstance(detail, dict) and detail.get("target") is not None:
        if deployment_target.refusal(detail.get("target")) is not None:
            blockers.append("provenance:post_deployment_target")

    declared = data.get("operational_status")
    floor = block.get("operational_status_floor")
    if isinstance(declared, str) and isinstance(floor, str):
        if _STATUS_RANK.get(declared, -1) > _STATUS_RANK.get(floor, -1):
            # Claiming a status above the weakest anchor is the headline form of the lie
            # this module exists to prevent.
            blockers.append("provenance:status_above_floor")
    return sorted(set(blockers))
