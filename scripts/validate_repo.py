#!/usr/bin/env python3
"""Validate static repository safety and the shared GENOMA v3.4 sealed contract."""
from __future__ import annotations

import ast
import csv
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.code_language_guard import LanguagePolicyError, validate_code_language
from scripts.sealed_ruleset import EXPECTED_NAME, EXPECTED_SHA, SealedRulesetError, verify_transport

CANONICAL_RULESET = EXPECTED_NAME
CANONICAL_RULESET_SHA256 = EXPECTED_SHA
FALLOW_ACTION_SHA = "45fd28766199acb1f939f6862274a37aad12770b"
PRODUCTION_WITNESS_CAPABILITY_GUARD = "${{ vars.GENOMA_PRODUCTION_WITNESS_ENABLED == 'true' }}"
REQUIRED_PATHS = (
    ".fallowrc.json", ".github/workflows/fallow.yml", ".github/workflows/scaffold-validation.yml",
    ".github/workflows/genoma-policy-engine.yml", ".github/workflows/genoma-production-ceremony.yml",
    ".github/workflows/genoma-production-witness.yml", ".github/workflows/genoma-ngs-runtime-gate.yml",
    ".github/workflows/genoma-snp-array.yml", ".gitignore", "Dockerfile", "environment.yml", "main.nf",
    "nextflow.config", "workflows/wgs.nf", "workflows/array.nf", "array_pipeline/qc.py",
    "array_pipeline/annotation.py", "array_pipeline/targets.py", "config/partial_genome_annotation_targets.json",
    "config/code_language_policy.json", "config/code_language_legacy_baseline.json",
    "manifests/GRCh38.sources.tsv", "manifests/GRCh38.lock.sha256.example", "manifests/RULESET_V3.4.sha256",
    "normative/sealed/MANIFEST.json", "normative/sealed/README.md",
    "scripts/__init__.py", "scripts/sealed_ruleset.py", "scripts/code_language_guard.py",
    "scripts/check_versions.sh", "scripts/fetch_grch38.sh",
    "scripts/build_bwa_mem2_index.sh", "scripts/validate_grch38.sh", "scripts/validate_bwa_mem2_functional.sh",
    "scripts/generate_canary.py", "scripts/score_variants.py", "scripts/run_canary.sh", "scripts/verify_ruleset.sh",
    "scripts/materialize_ruleset.py", "scripts/bootstrap_attestation.py", "scripts/run_live_post_deployment_smoke.py",
    "scripts/runtime_resource_gate.py", "scripts/runtime_stack.py", "scripts/prepare_latest_candidate.py",
    "scripts/promote_latest_candidate.py", "scripts/freshness_gate.py", "scripts/latest_runtime_resource_gate.py",
    "scripts/verify_runtime_gate_manifest.py", "scripts/wgs_consent_gate.py", "scripts/wgs_input_gate.py",
    "scripts/wgs_align_or_stage.sh", "scripts/build_wgs_curated_manifest.py", "scripts/query_evidence.py",
    "scripts/build_adapter_capabilities.py", "scripts/run_snp_array.py", "scripts/annotate_partial_genome.py",
    "scripts/build_array_case_manifest.py", "scripts/verify_prebuilt_bwa_mem2_bundle.py",
    "scripts/verify_supply_chain_lock.py", "scripts/generate_report.py", "scripts/generate_all_reports.py",
    "reporting/__init__.py", "reporting/catalog.json", "reporting/engine.py", "reporting/editorial_v3.py",
    "reporting/editorial_v3_hifi.py", "reporting/locale_pt_br.py",
    "reporting/requirements.txt", "reporting/reference_v3_manifest.json",
    "template_store/v3.0/MANIFEST.json", "locks/actions-lock.json", "locks/runtime-lock.json",
    "evidence_adapters/__init__.py", "policy_engine/pyproject.toml", "policy_engine/genoma_policy/engine.py",
    "policy_engine/genoma_policy/attestation.py", "policy_engine/genoma_policy/ledger.py",
    "policy_engine/genoma_policy/version.py", "policy_engine/policy/schema/execution-manifest.schema.json",
    "policy_engine/Dockerfile", "policy_engine/docker-compose.yml", "mcp/package.json", "mcp/package-lock.json",
    "mcp/tsconfig.json", "mcp/src/server.ts", "deploy/docker-compose.yml",
    "deploy/attestations/bootstrap-project-v3.4.json", "adapters/README.md", "adapters/config.example.json",
    "docs/CODE_LANGUAGE_POLICY.md", "docs/FALLOW_SECURITY_REVIEW.md", "docs/GITHUB_MOBILE_IMPORT.md",
    "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/PRE_DEPLOYMENT_VALIDATION_2026-08-15.md", "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/PR_BODY.md",
    "docs/DETERMINISTIC_ENGINE.md", "docs/PRODUCTION_CEREMONY.md", "docs/PORTABILITY_MATRIX.md",
    "docs/GRCH38_COMPUTE_STRATEGY.md", "docs/audits/GENOMA_V0.8_PREIMPLEMENTATION_AUDIT_2026-08-16.md",
)
EXPECTED_ARTIFACTS = {
    "Homo_sapiens_assembly38.fasta", "Homo_sapiens_assembly38.fasta.fai", "Homo_sapiens_assembly38.dict",
    "gencode.v50.primary_assembly.annotation.gtf.gz", "Homo_sapiens_assembly38.dbsnp138.vcf.gz",
    "Homo_sapiens_assembly38.dbsnp138.vcf.gz.tbi", "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz",
    "Mills_and_1000G_gold_standard.indels.hg38.vcf.gz.tbi", "hg38-blacklist.v2.bed.gz",
}
EXPECTED_EVIDENCE_ADAPTERS = {"clinvar", "clingen", "cpic", "clinpgx", "gnomad", "pgs_catalog"}
FORBIDDEN_SUFFIXES = (".fastq", ".fq", ".bam", ".bai", ".cram", ".crai", ".vcf", ".tbi")
SKIP_PARTS = {".git", "node_modules", "dist", "__pycache__", ".pytest_cache"}
TEXT_IDENTITY_SUFFIXES = {
    ".json", ".md", ".nf", ".py", ".rego", ".sh", ".toml", ".ts", ".txt", ".yaml", ".yml",
}
SUPERSEDED_IDENTITY_TEST_FIXTURES = frozenset(
    {
        "policy_engine/tests/test_policy_engine.py",
        "tests/test_v34_activation_contract.py",
        "tests/test_validate_repo_static_fstrings.py",
        "tests/test_superseded_identity_scanner.py",
    }
)
MISSING_PATH_HINTS = {
    "manifests/GRCh38.sources.tsv": "restore the tracked GRCh38 source manifest before running the Runtime/Resource Gate",
    "manifests/RULESET_V3.4.sha256": "restore the tracked canonical SHA manifest; do not add an active plaintext ruleset to the repository",
    "normative/sealed/MANIFEST.json": "restore the sealed transport manifest; materialization is runtime-only after the transport is valid",
}
ACTIVE_IDENTITY_SURFACES = (
    "scripts/run_live_post_deployment_smoke.py", "scripts/verify_ruleset.sh", "scripts/genoma_audit.py",
    "scripts/run_snp_array.py", "scripts/annotate_partial_genome.py", "scripts/build_wgs_curated_manifest.py",
    "scripts/build_array_case_manifest.py", "scripts/generate_report.py", "scripts/generate_all_reports.py",
    "array_pipeline/qc.py", "array_pipeline/annotation.py", "workflows/wgs.nf", "workflows/array.nf",
    "main.nf", "nextflow.config", "Dockerfile", "deploy/docker-compose.yml", "mcp/src/server.ts",
    "reporting/engine.py", "reporting/editorial_v3_hifi.py", "reporting/template_v3.py",
    "policy_engine/Dockerfile", "policy_engine/docker-compose.yml",
    "policy_engine/pyproject.toml", "policy_engine/README_GENOMA_POLICY.md", "policy_engine/tests/test_server.py",
    "policy_engine/genoma_policy/__init__.py", "policy_engine/genoma_policy/cli.py",
    "policy_engine/genoma_policy/engine.py", "policy_engine/genoma_policy/gates_core.py",
    "policy_engine/genoma_policy/gates_audit.py", "policy_engine/genoma_policy/models.py",
    "policy_engine/genoma_policy/paths.py", "policy_engine/genoma_policy/ruleset.py",
    "policy_engine/genoma_policy/smoke.py", "policy_engine/policy/rego/genoma.rego",
    "policy_engine/policy/rego/genoma_test.rego", "policy_engine/policy/schema/execution-manifest.schema.json",
    "locks/runtime-lock.json", ".github/workflows/genoma-policy-engine.yml",
    ".github/workflows/genoma-production-ceremony.yml", ".github/workflows/genoma-production-witness.yml",
    ".github/workflows/genoma-ngs-runtime-gate.yml", ".github/workflows/genoma-snp-array.yml",
    "docs/DETERMINISTIC_ENGINE.md", "docs/PRODUCTION_CEREMONY.md", "docs/MAGALU_PRIVATE_MCP_SETUP.md",
    "docs/RECOVERY_AND_ACTIVATION_RUNBOOK.md", "docs/SNP_ARRAY_PARTIAL_GENOME.md", "docs/PR_BODY.md",
)


# A superseded identity is only dangerous when something can activate it. These keys
# name an obsolete ruleset uniquely, so any occurrence outside declared history is an
# error wherever it appears.
SUPERSEDED_STRONG_KEYS = ("canonical_filename", "manifest_filename", "rule_id_prefix", "raw_sha256")
# These keys are bare version numbers and dates. They occur legitimately in prose,
# changelogs, dated filenames, unrelated timestamps and negative regression fixtures,
# so they are errors only inside an active normative declaration.
SUPERSEDED_WEAK_KEYS = ("version", "effective_date", "iso_date")


def _load_superseded_contract() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Read the superseded-identity registry from every archived ruleset version.

    Refuses when no registry is present rather than scanning for nothing: a check with an
    empty pattern list passes every repository, including one that has reintroduced an
    identity a previous version retired.
    """
    fixtures = sorted((ROOT / "docs" / "history").glob("*/superseded-identities.json"))
    if not fixtures:
        raise RuntimeError("superseded identity registry is missing from docs/history")
    strong: list[str] = []
    weak: list[str] = []
    forbidden_paths: list[str] = []
    for fixture in fixtures:
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        if payload.get("schema") != "genoma-superseded-identity-v1" or payload.get("status") != "HISTORICAL":
            raise RuntimeError(f"invalid superseded identity registry: {fixture}")
        required = (*SUPERSEDED_STRONG_KEYS, *SUPERSEDED_WEAK_KEYS, "forbidden_active_paths")
        missing = [key for key in required if not payload.get(key)]
        if missing:
            raise RuntimeError(f"incomplete superseded identity registry {fixture}: {missing}")
        strong.extend(str(payload[key]) for key in SUPERSEDED_STRONG_KEYS)
        weak.extend(str(payload[key]) for key in SUPERSEDED_WEAK_KEYS)
        forbidden = payload["forbidden_active_paths"]
        if not isinstance(forbidden, list) or not all(isinstance(item, str) and item for item in forbidden):
            raise RuntimeError(f"invalid forbidden_active_paths in {fixture}")
        forbidden_paths.extend(forbidden)
    return tuple(dict.fromkeys(strong)), tuple(dict.fromkeys(weak)), tuple(dict.fromkeys(forbidden_paths))


SUPERSEDED_STRONG_TOKENS, SUPERSEDED_WEAK_TOKENS, FORBIDDEN_ACTIVE_PATHS = _load_superseded_contract()
# Declared active surfaces stay strict: any superseded token at all is an error there.
OLD_ACTIVE_TOKENS = SUPERSEDED_STRONG_TOKENS + SUPERSEDED_WEAK_TOKENS

# Names that make a Python string constant an identity definition rather than a mention.
IDENTITY_BINDING_PATTERN = re.compile(
    r"RULESET|CANONICAL|NORMATIV|VIGENTE|IDENTITY|IDENTIDADE|RULE_ID|EFFECTIVE|CURRENT|VERS(AO|ÃO|ION)",
    re.IGNORECASE,
)
# Markers that turn a line of non-Python text into an active normative declaration.
ACTIVE_DECLARATION_MARKERS = (
    "STATUS NORMATIVO", "VERSÃO NORMATIVA", "VERSAO NORMATIVA", "ARQUIVO CANÔNICO", "ARQUIVO CANONICO",
    "VIGENTE", "ruleset_version", "RULESET_VERSION", "CURRENT_RULESET", "canonical_filename",
    "effective_date", "DATA FORMAL DE EMISSÃO", "DATA FORMAL DE EMISSAO",
)


def validate_sealed_ruleset(root: Path, errors: list[str]) -> None:
    """Record an error unless the sealed transport decodes to the canonical ruleset."""
    try:
        verify_transport(root / "normative" / "sealed")
    except (OSError, UnicodeError, ValueError, SealedRulesetError) as exc:
        errors.append(f"sealed normative transport invalid: {type(exc).__name__}: {exc}")


def validate_active_identity_text(text: str, relative: str, errors: list[str]) -> None:
    """Reject each superseded active-identity token independently."""
    for token in OLD_ACTIVE_TOKENS:
        if token in text:
            errors.append(f"active ruleset surface still references superseded identity: {relative}: {token}")


def _constant_value(node: ast.AST) -> str | int | float | bool | None:
    """The literal behind an AST node, or None when it is computed at runtime.

    Only literals can be checked statically; a value assembled at runtime is deliberately
    not guessed at, because guessing wrong would either pass a violation or fail a legal file.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool)):
        return node.value
    return None


def _formatted_constant(value: ast.FormattedValue) -> str | None:
    """The literal text an f-string placeholder expands to, when it is a constant.

    Lets an identity spelled through an f-string be checked like a plain string, so the
    superseded-identity scan cannot be evaded by interpolating a constant.
    """
    constant = _constant_value(value.value)
    if constant is None:
        return None
    if value.conversion == -1:
        converted: object = constant
    elif value.conversion == 115:  # !s
        converted = str(constant)
    elif value.conversion == 114:  # !r
        converted = repr(constant)
    elif value.conversion == 97:  # !a
        converted = ascii(constant)
    else:
        return None
    if value.format_spec is None:
        return str(converted)
    format_spec = _constant_string(value.format_spec)
    if format_spec is None:
        return None
    try:
        return format(converted, format_spec)
    except (TypeError, ValueError):
        return None


def _constant_string(node: ast.AST) -> str | None:
    """Fold static string expressions without executing repository code."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _constant_string(node.left)
        right = _constant_string(node.right)
        if left is not None and right is not None:
            return left + right
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
                continue
            if isinstance(value, ast.FormattedValue):
                rendered = _formatted_constant(value)
                if rendered is None:
                    return None
                parts.append(rendered)
                continue
            return None
        return "".join(parts)
    return None


def _binding_names(node: ast.AST) -> list[str]:
    """Names a value is bound to: assignment targets, dict keys and keyword arguments."""
    names: list[str] = []
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, (ast.Name, ast.Attribute)):
        names.append(node.target.id if isinstance(node.target, ast.Name) else node.target.attr)
    elif isinstance(node, ast.keyword) and node.arg:
        names.append(node.arg)
    return names


def _python_constant_strings(text: str) -> tuple[str, ...]:
    """Every statically foldable string in a module, including split literals.

    Constant folding is what stops a superseded identity from being smuggled past a
    raw-text scan as ``"GENOMA-V3." + "3"`` or ``f"GENOMA-V3.{3}"``.
    """
    tree = ast.parse(text)
    values = (_constant_string(node) for node in ast.walk(tree))
    return tuple(dict.fromkeys(value for value in values if value is not None))


def _identity_declaration_strings(text: str) -> tuple[str, ...]:
    """Python string constants that actually define a normative identity.

    Only values bound to an identity-shaped name are returned — an assignment target,
    a dict key or a keyword argument. Comments, docstrings, prose and unrelated
    literals such as test timestamps are excluded by construction, so a historical
    mention can never be mistaken for an active normative source.
    """
    tree = ast.parse(text)
    declarations: list[str] = []
    for node in ast.walk(tree):
        values: list[ast.AST] = []
        if any(IDENTITY_BINDING_PATTERN.search(name) for name in _binding_names(node)):
            # A bare annotation (``NAME: str``) binds no value.
            if getattr(node, "value", None) is not None:
                values.append(node.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                key_text = _constant_value(key) if key is not None else None
                if isinstance(key_text, str) and IDENTITY_BINDING_PATTERN.search(key_text):
                    values.append(value)
        for value in values:
            declarations.extend(
                constant
                for constant in (_constant_string(child) for child in ast.walk(value))
                if constant is not None
            )
    return tuple(dict.fromkeys(declarations))


def _active_declaration_context(path: Path, text: str) -> tuple[str, ...]:
    """Fragments of a file that assert an active normative identity."""
    if path.suffix.lower() == ".py":
        return _identity_declaration_strings(text)
    return tuple(line for line in text.splitlines() if any(marker in line for marker in ACTIVE_DECLARATION_MARKERS))


def _historical_roots(root: Path) -> tuple[Path, ...]:
    """Directories holding archived ruleset versions, which are exempt from identity checks.

    A superseded identity is *expected* inside its own archive: that is the record of what it
    was. The scan refuses it everywhere else.
    """
    history = root / "docs" / "history"
    return tuple(
        fixture.parent.relative_to(root)
        for fixture in sorted(history.glob("*/superseded-identities.json"))
    )


def _is_historical_path(relative: Path, history_roots: tuple[Path, ...]) -> bool:
    """Whether a path sits inside an archived ruleset version."""
    return any(relative == historical or historical in relative.parents for historical in history_roots)


def validate_superseded_identity_locations(root: Path, errors: list[str]) -> None:
    """Reject superseded normative identities outside declared history.

    Two rules, deliberately separate, so that historical evidence is never confused
    with an active normative source:

    * Strong tokens (canonical filename, manifest filename, rule-id prefix, raw
      SHA-256) uniquely name an obsolete ruleset. They are rejected anywhere outside
      declared history — nothing can activate v3.3 without one of them.
    * Weak tokens (a bare version or date) are rejected only where they actually
      declare an identity: an identity-bound Python constant, or a line carrying an
      active-declaration marker. Prose, dated filenames, unrelated timestamps and
      negative regression fixtures are therefore allowed to mention them.

    Declared active surfaces are validated separately and remain strict about both.
    """
    history_roots = _historical_roots(root)
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root)
        if _is_historical_path(relative, history_roots):
            continue

        relative_text = relative.as_posix()
        if relative_text in SUPERSEDED_IDENTITY_TEST_FIXTURES:
            continue
        errors.extend(
            f"superseded identity path outside explicit history: {relative}: {token}"
            for token in SUPERSEDED_STRONG_TOKENS
            if token in relative_text
        )

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(
                f"unreadable identity surface cannot be scanned: {relative}: {type(exc).__name__}: {exc}"
            )
            continue
        except UnicodeDecodeError:
            continue
        # Strong tokens are scanned in the raw text and, for Python, in every folded
        # constant as well, so a split or interpolated literal cannot hide one. This scan
        # runs on every readable file: a checksum manifest, a lock or a data file carries a
        # superseded identity just as effectively as a .py or .md, so the suffix guard
        # below applies only to the weak, declaration-scoped tokens.
        strong_surfaces = [text]
        python_declarations: tuple[str, ...] | None = None
        if path.suffix.lower() == ".py":
            try:
                strong_surfaces.extend(_python_constant_strings(text))
                python_declarations = _identity_declaration_strings(text)
            except SyntaxError as exc:
                errors.append(
                    f"unparseable Python surface cannot be identity-scanned: {relative}: "
                    f"{exc.msg} (line {exc.lineno})"
                )
                continue
        errors.extend(
            f"superseded identity outside explicit history: {relative}: {token}"
            for token in SUPERSEDED_STRONG_TOKENS
            if any(token in surface for surface in strong_surfaces)
        )

        if path.suffix.lower() not in TEXT_IDENTITY_SUFFIXES and path.name not in {"Dockerfile", "AGENTS.md"}:
            continue
        declarations = python_declarations if python_declarations is not None else _active_declaration_context(path, text)
        if not declarations:
            continue
        errors.extend(
            f"superseded identity declared as active: {relative}: {token}"
            for token in SUPERSEDED_WEAK_TOKENS
            if any(token in declaration for declaration in declarations)
        )


def _missing_path_error(relative: str) -> str:
    """The error for a required path that is absent, with the hint for fixing it if there is one."""
    hint = MISSING_PATH_HINTS.get(relative)
    if hint:
        return f"missing required path: {relative} — {hint}"
    return f"missing required path: {relative}"


#: The surfaces the "core has no external runtime dependency" claim is about. `reporting` and
#: `scripts` deliberately carry pinned renderer dependencies (python-docx, reportlab, pypdf,
#: PyMuPDF); the scientific core does not, and that is the property checked below.
CORE_PACKAGES = ("array_pipeline", "normative")

#: Packages that live in this repository but are optional by contract — `.coderabbit.yaml`
#: declares `evidence_adapters/**` an optional Evidence Plane component. The core must import
#: without them, so they are excluded from the "local, therefore fine" allowance below.
OPTIONAL_LOCAL_PACKAGES = frozenset({"evidence_adapters", "adapters", "mcp"})


#: The only errors an optional-adapter guard may catch. `ModuleNotFoundError` is a subclass of
#: `ImportError`, so naming either is enough; naming anything else is not a guard.
_IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Does this `except` clause catch import errors and *nothing else*?

    A bare `except:` and `except Exception:` do catch it, and are deliberately not accepted:
    the contract is that an absent adapter degrades to a *stated* refusal, and a handler that
    also swallows a corrupt install or a failing module-level side effect cannot tell the
    caller which of those happened. Naming the error is what makes the guard a declaration
    that the dependency is optional rather than a blanket suppression.

    The same argument applies to a tuple, which an earlier version of this check missed by
    accepting any handler *containing* ImportError: under
    ``except (ImportError, AttributeError)`` an `AttributeError` raised while the dependency
    runs its own import-time code binds the fallback and reports a missing optional adapter
    where there is a broken installed one. Every name in the clause has to be an import error.
    """
    if handler.type is None:
        return False
    candidates = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    named = set()
    for candidate in candidates:
        if isinstance(candidate, ast.Name):
            named.add(candidate.id)
        elif isinstance(candidate, ast.Attribute):
            named.add(candidate.attr)
        else:
            # A computed exception class — a name this walk cannot resolve is not a
            # declaration it can act on, so it does not qualify as a guard.
            return False
    return bool(named) and named <= _IMPORT_ERRORS


def _import_time_statements(body: list[ast.stmt]) -> Iterator[ast.stmt]:
    """Yield the statements that run when the module is imported, minus the guarded ones.

    The first version of the caller walked `tree.body` alone, reasoning that "an import
    nested in a `try` is guarded by construction". `tree.body` holds the `ast.Try` node and
    not the `ast.Import` inside it, so *every* `try` hid its imports from the walk —
    ``try: import numpy`` / ``except ValueError:`` reported clean and still raised
    `ModuleNotFoundError` at import time. What makes an import optional is the handler, so
    the handler is read: the body of a `try` that catches ImportError is skipped, and
    everything else that executes at import time is yielded, however deeply nested.

    Function and class bodies are not import-time and are not descended into: a lazy import
    inside a function is the pattern this contract exists to permit — `array_pipeline/
    annotation.py` loads `evidence_adapters` that way so the core imports without it.

    `ast.TryStar` (`try`/`except*`, Python 3.11) is a distinct node from `ast.Try`, and
    `ast.Match` is another, so imports inside either were invisible to this walk in exactly
    the way every import was before the handler started being read. Both are traversed, and
    `except*` follows the same guard rule: an `except* ImportError` group does catch the
    plain `ModuleNotFoundError` the import raises.
    """
    #: The `try` forms this walk understands. Both carry body/handlers/orelse/finalbody, so
    #: the same reasoning applies; only the node class differs.
    try_nodes: tuple[type[ast.stmt], ...] = (ast.Try,)
    if hasattr(ast, "TryStar"):  # pragma: no branch - present from Python 3.11
        try_nodes += (ast.TryStar,)

    for node in body:
        yield node
        if isinstance(node, try_nodes):
            if not any(_catches_import_error(handler) for handler in node.handlers):
                yield from _import_time_statements(node.body)
            for handler in node.handlers:
                yield from _import_time_statements(handler.body)
            # `else` runs only when the body did not raise and `finally` runs regardless;
            # neither is covered by the handler that protects the body.
            yield from _import_time_statements(node.orelse)
            yield from _import_time_statements(node.finalbody)
        elif isinstance(node, (ast.If, ast.For, ast.While)):
            yield from _import_time_statements(node.body)
            yield from _import_time_statements(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from _import_time_statements(node.body)
        elif isinstance(node, ast.Match):
            for case in node.cases:
                yield from _import_time_statements(case.body)


def validate_core_runtime_dependencies(root: Path, errors: list[str]) -> None:
    """Check the claim `main()` used to simply print.

    `PASS optional_adapters core has no external runtime dependency` was a literal print with
    nothing behind it, and `array_pipeline/ancestry.py` imported NumPy at module scope —
    unpinned, absent from environment.yml, reporting/requirements.txt and the runtime lock —
    for as long as that line claimed otherwise. A validator that asserts a property it never
    evaluates is worse than one that stays quiet: every run of it published the assurance.

    An import inside `try`/`except ImportError` is an optional adapter and passes; one at
    module scope makes the package unimportable without the library and does not.
    """
    local_modules = {p.stem for p in root.glob("*.py")}
    local_modules |= {p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}
    local_modules |= {"array_pipeline", "reporting", "scripts", "normative", "tests"}
    allowed = set(sys.stdlib_module_names) | local_modules
    # Present in this repository, yet declared optional by contract, so "is it local?" is
    # the wrong question for these. `array_pipeline/annotation.py` imported
    # `evidence_adapters` at module scope and `completeness.py` imported *annotation* for a
    # single constant, which made an optional Evidence Plane adapter a hard requirement for
    # importing the core — the same defect as the NumPy one, hidden because the package sits
    # inside the repository and so counted as local.
    allowed -= OPTIONAL_LOCAL_PACKAGES

    def module_paths(module: str) -> list[Path]:
        """Files Python executes while importing one absolute local module."""
        parts = module.split(".")
        found: list[Path] = []
        for index in range(1, len(parts) + 1):
            package_init = root.joinpath(*parts[:index], "__init__.py")
            if package_init.is_file():
                found.append(package_init)
        module_file = root.joinpath(*parts).with_suffix(".py")
        if module_file.is_file():
            found.append(module_file)
        return found

    pending = [
        path
        for package in CORE_PACKAGES
        for path in sorted((root / package).rglob("*.py"))
    ]
    visited: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            errors.append(f"core module could not be parsed: {path.relative_to(root)}: {exc}")
            continue
        for node in _import_time_statements(tree.body):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    modules = [node.module]
                    modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
                elif node.level > 0:
                    relative = path.relative_to(root).with_suffix("").parts[:-1]
                    keep = max(len(relative) - node.level + 1, 0)
                    base_parts = (*relative[:keep], *((node.module,) if node.module else ()))
                    base = ".".join(base_parts)
                    modules = [base] if base else []
                    modules.extend(f"{base}.{alias.name}" for alias in node.names)
            for module in modules:
                name = module.split(".")[0]
                if name in OPTIONAL_LOCAL_PACKAGES:
                    errors.append(
                        f"core module {path.relative_to(root)} imports {name!r} at module "
                        "scope; optional local packages must be lazy and fail closed"
                    )
                elif name in local_modules:
                    pending.extend(module_paths(module))
                elif name not in allowed:
                    errors.append(
                        f"core module {path.relative_to(root)} imports {name!r} at module "
                        "scope; the scientific core must have no external runtime "
                        "dependency. Guard it with try/except ImportError and refuse "
                        "NÃO DISPONÍVEL, or declare and pin it and change this contract."
                    )


def validate_language_policy(root: Path, errors: list[str]) -> None:
    try:
        validate_code_language(root, errors)
    except LanguagePolicyError as exc:
        errors.append(f"code language policy unavailable: {exc}")


def validate_production_witness_contract(root: Path, errors: list[str]) -> None:
    witness = root / ".github/workflows/genoma-production-witness.yml"
    if not witness.is_file():
        return
    text = witness.read_text(encoding="utf-8")
    if "--output-dir evidence/live-section-260" in text:
        errors.append("Production Witness still uses obsolete live smoke --output-dir contract")
    for token in ("--deployment-id", "--output evidence/live-section-260/summary.json"):
        if token not in text:
            errors.append(f"Production Witness missing current live smoke contract: {token}")
    marker = "\n  witness:\n"
    publisher_marker = "\n  publish-witness:\n"
    if marker not in text or publisher_marker not in text:
        errors.append("Production Witness capability guard is not attached to the witness job boundary")
        return
    job = text.split(marker, 1)[1].split(publisher_marker, 1)[0]
    conditions = [line.removeprefix("    if: ").strip() for line in job.splitlines() if line.startswith("    if: ")]
    if conditions != [PRODUCTION_WITNESS_CAPABILITY_GUARD]:
        errors.append("Production Witness capability guard must use the exact job-level repository-variable predicate")


def _presentation_labels(locale_tree: ast.Module, errors: list[str]) -> dict[str, str] | None:
    """Read unique literal strings without importing the presentation module."""
    labels: dict[str, str] = {}
    for index, statement in enumerate(locale_tree.body):
        if (
            index == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue
        if (
            not isinstance(statement, ast.Assign)
            or len(statement.targets) != 1
            or not isinstance(statement.targets[0], ast.Name)
            or not isinstance(statement.value, ast.Constant)
            or not isinstance(statement.value.value, str)
            or statement.targets[0].id in labels
        ):
            errors.append("reporting presentation labels must be unique literal string assignments")
            return None
        labels[statement.targets[0].id] = statement.value.value
    return labels


def _presentation_reads(tree: ast.AST) -> set[str]:
    """Collect loaded names from the statically bound locale, including nested code."""
    return {
        item.attr
        for item in ast.walk(tree)
        if isinstance(item, ast.Attribute)
        and isinstance(item.value, ast.Name)
        and item.value.id == "pt_br"
        and isinstance(item.ctx, ast.Load)
    }


def _presentation_imports(tree: ast.AST) -> list[tuple[str | None, str, str | None, int]]:
    """Describe every import that claims the pt_br binding without executing it."""
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name) == "pt_br":
                    imports.append(
                        (
                            getattr(node, "module", None),
                            alias.name,
                            alias.asname,
                            getattr(node, "level", 0),
                        )
                    )
    return imports


def _presentation_shadowed(node: ast.AST) -> bool:
    """Recognize the same assignment, deletion and argument shadows as the original gate."""
    return (
        isinstance(node, ast.Name)
        and node.id == "pt_br"
        and isinstance(node.ctx, (ast.Store, ast.Del))
    ) or (isinstance(node, ast.arg) and node.arg == "pt_br")


def _validate_presentation_binding(
    relative: str, tree: ast.Module, labels: dict[str, str], errors: list[str]
) -> None:
    """Check missing constants before the import binding, preserving diagnostic order."""
    for name in sorted(_presentation_reads(tree) - labels.keys()):
        errors.append(f"reporting presentation attribute missing: {relative}: {name}")
    if _presentation_imports(tree) != [("reporting", "locale_pt_br", "pt_br", 0)] or any(
        _presentation_shadowed(node) for node in ast.walk(tree)
    ):
        errors.append(
            f"reporting renderer {relative} must bind pt_br only to reporting.locale_pt_br"
        )


def _validate_result_caption(renderer_tree: ast.Module, errors: list[str]) -> None:
    """Keep the PDF and DOCX result-caption checks independent of literal ownership."""
    for name in ("_pdf", "_docx"):
        functions = [
            node
            for node in renderer_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        ]
        if len(functions) != 1 or "GENOMIC_RESULT" not in _presentation_reads(functions[0]):
            errors.append(f"editorial v3 renderer {name} must use pt_br.GENOMIC_RESULT")


def validate_report_presentation(root: Path, errors: list[str]) -> None:
    """Validate source, literal ownership, both bindings and both required result captions."""
    try:
        locale_tree = ast.parse((root / "reporting/locale_pt_br.py").read_text(encoding="utf-8"))
        engine_tree = ast.parse((root / "reporting/engine.py").read_text(encoding="utf-8"))
        renderer_tree = ast.parse(
            (root / "reporting/editorial_v3_hifi.py").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append(f"reporting presentation source invalid: {type(exc).__name__}: {exc}")
        return
    labels = _presentation_labels(locale_tree, errors)
    if labels is None:
        return
    for name, expected in (("GENOMIC_RESULT", "RESULTADO GENÔMICO"), ("LANGUAGE_TAG", "pt-BR")):
        if labels.get(name) != expected:
            errors.append(f"reporting presentation contract mismatch: {name}")
    for relative, tree in (
        ("reporting/engine.py", engine_tree),
        ("reporting/editorial_v3_hifi.py", renderer_tree),
    ):
        _validate_presentation_binding(relative, tree, labels, errors)
    _validate_result_caption(renderer_tree, errors)


def validate(root: Path) -> list[str]:
    """Run every static repository check and return the accumulated errors.

    Errors accumulate rather than raising, so one run reports everything wrong instead of
    stopping at the first problem. `main` prints its PASS banner only when this returns
    empty — those printed lines are a summary of this function's verdict, not twelve
    independent checks, and should not be quoted as if they were.
    """
    errors: list[str] = []
    errors.extend(
        _missing_path_error(relative)
        for relative in REQUIRED_PATHS
        if not (root / relative).is_file()
    )
    errors.extend(
        f"superseded active ruleset path must be archived outside executable surfaces: {relative}"
        for relative in FORBIDDEN_ACTIVE_PATHS
        if (root / relative).exists()
    )
    validate_superseded_identity_locations(root, errors)
    validate_core_runtime_dependencies(root, errors)

    active = []
    for candidate in root.rglob("REGRAS_PROJETO_GENOMA*.txt"):
        if any(part in SKIP_PARTS for part in candidate.parts):
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if re.search(r"^STATUS NORMATIVO:\s*VIGENTE\s*$", text, re.MULTILINE):
            active.append(candidate.relative_to(root))
    if active:
        errors.append(f"active normative ruleset must be materialized at runtime, not duplicated in repo; found {active}")

    validate_sealed_ruleset(root, errors)

    ruleset_manifest = root / "manifests/RULESET_V3.4.sha256"
    if ruleset_manifest.is_file():
        try:
            manifest_text = ruleset_manifest.read_text(encoding="ascii")
        except (OSError, UnicodeDecodeError):
            # A manifest that is not plain ASCII cannot pin the canonical artifact; report
            # it as a mismatch instead of aborting the whole validation run.
            manifest_text = ""
        if manifest_text.strip().split() != [CANONICAL_RULESET_SHA256, CANONICAL_RULESET]:
            errors.append("ruleset external manifest does not match the verified v3.4 artifact")

    for relative in ACTIVE_IDENTITY_SURFACES:
        path = root / relative
        if path.is_file():
            validate_active_identity_text(path.read_text(encoding="utf-8", errors="replace"), relative, errors)

    manifest = root / "manifests/GRCh38.sources.tsv"
    if manifest.is_file():
        with manifest.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle, delimiter="\t"))
        targets = {row.get("target", "") for row in rows}
        if len(rows) != 9 or targets != EXPECTED_ARTIFACTS:
            errors.append(f"GRCh38 manifest must contain exactly the required 9 artifacts; found {len(rows)}")
        if any(not row.get("url", "").startswith(("https://", "generated-from:")) for row in rows):
            errors.append("GRCh38 manifest contains a non-HTTPS/non-generated source")

    package = root / "mcp/package.json"
    if package.is_file() and json.loads(package.read_text()).get("devDependencies", {}).get("fallow") != "3.16.0":
        errors.append("mcp/package.json must pin fallow 3.16.0 exactly")

    fw = root / ".github/workflows/fallow.yml"
    if fw.is_file():
        text = fw.read_text(encoding="utf-8")
        if f"fallow-rs/fallow@{FALLOW_ACTION_SHA}" not in text or "version: 3.16.0" not in text:
            errors.append("Fallow workflow must pin wrapper SHA and CLI 3.16.0")

    runbook = root / "docs/MAGALU_PRIVATE_MCP_SETUP.md"
    if runbook.is_file() and "--entrypoint /bin/bash" in runbook.read_text(encoding="utf-8"):
        errors.append("runbook must not bypass the micromamba container entrypoint")

    main_nf = root / "main.nf"
    if main_nf.is_file():
        text = main_nf.read_text(encoding="utf-8")
        for token in ("params.mode", "WGS_PRODUCTION", "ARRAY_PRODUCTION", "CANARY", "array_input", "array_build_evidence", "array_strand_evidence"):
            if token not in text:
                errors.append(f"main.nf missing dispatcher contract token: {token}")

    wgs_nf = root / "workflows/wgs.nf"
    if wgs_nf.is_file():
        text = wgs_nf.read_text(encoding="utf-8")
        for token in ("VERIFY_RUNTIME_GATE", "REFRESH_FRESHNESS_GATE", "VERIFY_CONSENT_PROVENANCE", "ready_for_first_dna_read", "INGEST_AND_QC", "ALIGN_OR_STAGE", "RERUN_SAMPLE_RUNTIME_GATE", "CALL_SHORT_VARIANTS", "NORMALIZE_VARIANTS", "ANNOTATE_EVIDENCE", "BUILD_CURATED_MANIFEST", "POLICY_EVALUATE", "GENERATE_REPORTS", "unsupported_variant_classes", "NÃO DISPONÍVEL", "CYP2D6", "CNV", "SV"):
            if token not in text:
                errors.append(f"WGS workflow missing fail-closed contract token: {token}")

    array_nf = root / "workflows/array.nf"
    if array_nf.is_file():
        text = array_nf.read_text(encoding="utf-8")
        for token in ("ARRAY_QC", "ARRAY_ANNOTATE", "ARRAY_BUILD_MANIFEST", "ARRAY_POLICY_EVALUATE", "ARRAY_GENERATE_REPORTS", "LIMITED_INTERPRETATION_GATE", "plan-only", "live"):
            if token not in text:
                errors.append(f"SNP-array workflow missing fail-closed contract token: {token}")

    validate_production_witness_contract(root, errors)

    ngs_gate = root / ".github/workflows/genoma-ngs-runtime-gate.yml"
    if ngs_gate.is_file():
        text = ngs_gate.read_text(encoding="utf-8")
        if "bash -lc './scripts/run_canary.sh" in text:
            errors.append("NGS gate must not bypass micromamba environment with a login-shell canary")
        for token in ("freshness_gate.py", "GRCh38.lock.sha256.approved", "[self-hosted, linux, x64, genoma-production, highmem]", "nextflow run /opt/codework/main.nf --mode canary", "validate_bwa_mem2_functional.sh", "verify_supply_chain_lock.py"):
            if token not in text:
                errors.append(f"NGS gate missing current-session readiness contract: {token}")

    nextflow_cfg = root / "nextflow.config"
    if nextflow_cfg.is_file() and "nextflowVersion = '!>=26.04.6'" not in nextflow_cfg.read_text(encoding="utf-8"):
        errors.append("Nextflow manifest must permit tested forward versions while enforcing minimum 26.04.6")

    adapters = root / "evidence_adapters/__init__.py"
    if adapters.is_file():
        text = adapters.read_text(encoding="utf-8")
        for key in EXPECTED_EVIDENCE_ADAPTERS:
            if f'"{key}"' not in text:
                errors.append(f"missing evidence adapter: {key}")
        if "api.pharmgkb.org" in text:
            errors.append("retired PharmGKB API hostname must not be used; use ClinPGx")
        for token in ("result_digest", "checked_at", "locator", "NÃO DISPONÍVEL", "VERIFICADO"):
            if token not in text:
                errors.append(f"evidence adapter contract missing: {token}")

    renderer = root / "reporting/editorial_v3_hifi.py"
    if renderer.is_file():
        text = renderer.read_text(encoding="utf-8")
        for token in (
            "0B1F33", "0F766E", "A16207", "F2F4F7", "write_editorial_bundle", "DejaVu Sans"
        ):
            if token not in text:
                errors.append(f"editorial v3 high-fidelity renderer contract missing: {token}")

    validate_report_presentation(root, errors)

    catalog = root / "reporting/catalog.json"
    if catalog.is_file():
        models = json.loads(catalog.read_text(encoding="utf-8"))
        expected_accents = {"01": "0F766E", "02": "2563EB", "03": "7C3AED", "04": "166534", "05": "475467", "06": "B42318", "07": "A16207", "08": "0F766E", "09": "475467", "10": "0B1F33", "11": "0B1F33"}
        for report_id, accent in expected_accents.items():
            if models.get(report_id, {}).get("accent") != accent:
                errors.append(f"report {report_id} v3 accent mismatch")

    requirements = root / "reporting/requirements.txt"
    if requirements.is_file():
        req = requirements.read_text(encoding="utf-8")
        if "python-docx==" not in req or "reportlab==" not in req:
            errors.append("editorial renderer dependencies must be exact-pinned")

    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root)
        name = path.name.lower()
        if name.endswith(FORBIDDEN_SUFFIXES) or name.endswith((".fastq.gz", ".fq.gz", ".vcf.gz")):
            errors.append(f"genomic/reference payload must not be committed: {relative}")
        if name == "grch38.lock.sha256.approved":
            errors.append("externally approved GRCh38 lock must not be committed")
        if path.suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(f"invalid JSON: {relative}: {exc}")
    validate_language_policy(root, errors)
    return errors


def main() -> None:
    """Run every repository check and print the verdict.

    The twelve `PASS` lines are a fixed banner printed once `validate()` returns no errors —
    not twelve independent verdicts. What exit 0 supports is "`validate()` found no errors";
    see `validate()` for what that does and does not cover.
    """
    errors = validate(ROOT)
    if errors:
        for error in errors:
            print(f"FAIL\t{error}")
        raise SystemExit(1)
    print("PASS\trepository_contract")
    print("PASS\truleset_manifest_contract\tv3.4 raw SHA-256 pinned")
    print("PASS\trepository_active_rulesets\t0")
    print("PASS\tsealed_normative_transport\tshared decoder")
    print("PASS\tgrch38_manifest\t9/9")
    print("PASS\tpre_dna_readiness_contract\tlatest-tested candidate + canaries + freshness + runtime/resource gate")
    print("PASS\twgs_scientific_data_plane_contract\treal SNV/indel path + explicit unsupported classes")
    print("PASS\tarray_scientific_data_plane_contract\tQC + target-first evidence + policy/report handoff")
    print("PASS\tevidence_adapter_contract\tClinVar/ClinGen/CPIC/ClinPGx/gnomAD/PGS Catalog")
    print("PASS\tsupply_chain_contract\tworkflow/action/container lock paths present")
    print("PASS\treporting_contract\t11-model deterministic renderer and reference identities")
    print("PASS\toptional_adapters\tcore has no external runtime dependency")


if __name__ == "__main__":
    main()
