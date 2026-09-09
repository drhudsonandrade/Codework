"""Verify the bounded reporting migration against fixed Git and content references."""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
import subprocess
import tokenize
from pathlib import Path

BASE = "0a643128f3ac3e99a51428644c3012a2d638ab8b"
REFERENCE_COMMIT = "c87b336a292f6c9f2fb490a51d2853b74ab72749"
REFERENCE_DIGESTS = {
    "tests/fixtures/reporting_language_baseline.json": (
        "9cc84c09512dc0c0bea15ef4dc4da1fa41efb387eda61fc4eb727146fe66c2c8"
    ),
    "tests/reporting_language_fixtures.py": (
        "58316c45089f8354cc8ce7007237fa27544185b7f0b550147591ad0eb7318fd0"
    ),
}
EXPECTED_COMPARISON_SHA256 = "cd81d90e1d03d2d645ce286973d3673779a04a9393a644f7334d37a46e6aaa92"
INVENTORY_PATHS = (
    "reporting/__init__.py",
    "reporting/assay.py",
    "reporting/case_dossier.py",
    "reporting/catalog.py",
    "reporting/consent.py",
    "reporting/deployment_target.py",
    "reporting/editorial_v3.py",
    "reporting/editorial_v3_hifi.py",
    "reporting/engine.py",
    "reporting/policy_control.py",
    "reporting/post_render_provenance.py",
    "reporting/provenance.py",
    "reporting/section_attestations.py",
    "reporting/template_fill.py",
    "reporting/template_v3.py",
    "reporting/wgs_qc_record.py",
    "scripts/build_pharmacogenomic_report.py",
    "scripts/build_report_coordinate_pack.py",
    "scripts/generate_all_reports.py",
    "scripts/generate_report.py",
    "scripts/install_report_templates.py",
    "scripts/prepare_report_release.py",
    "scripts/verify_template_store.py",
    "tests/test_editorial_renderers.py",
    "tests/test_rendered_text_matches_the_document.py",
    "tests/test_report_coordinate_pack_ruleset_markers.py",
    "tests/test_report_engine.py",
    "tests/test_report_release_assembly.py",
    "tests/test_reporting_provenance_regressions.py",
    "tests/test_template_fill_regressions.py",
    "tests/test_template_store.py",
    "tests/test_template_v3_contract.py",
    "tests/test_template_v3_page_size_regression.py",
)
IDENTIFIER_TOKENS = (
    "ainda",
    "amostra",
    "arquivo",
    "associacao",
    "caminho",
    "clinico",
    "com",
    "confirmado",
    "curiosidade",
    "dados",
    "desconhecido",
    "executado",
    "hipotese",
    "inferencia",
    "inferido",
    "nao",
    "para",
    "pesquisa",
    "predisposicao",
    "proposto",
    "retorna",
    "sem",
    "somente",
    "verificado",
)
ACCENT_PATTERN = r"[áéíóúãõçÁÉÍÓÚÃÕÇ]"
MIGRATED = ("reporting/engine.py", "reporting/editorial_v3_hifi.py")
EXPECTED_CHANGES = set(MIGRATED) | {
    "reporting/locale_pt_br.py",
    "scripts/validate_repo.py",
    "scripts/verify_reporting_language_migration.py",
    "tests/test_reporting_presentation_gate.py",
    "tests/test_reporting_migration_verifier.py",
    "tests/reporting_language_fixtures.py",
    "tests/test_reporting_language_compatibility.py",
    "tests/fixtures/reporting_language_baseline.json",
    "docs/REPORTING_CODE_LANGUAGE_INVENTORY.md",
    "docs/superpowers/plans/2026-09-09-reporting-english-locale.md",
    "docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md",
}
DESIGN_FIELDS = {
    name: "str"
    for name in (
        "navy",
        "teal",
        "amber",
        "cream",
        "light_gray",
        "border",
        "text",
        "slate",
        "pale_blue",
        "white",
    )
}
DESIGN_FIELDS.update(a4_mm="tuple[int, int]", cover_left_mm="float", content_width_mm="float")


def require(condition: bool, message: str) -> None:
    """Keep proof failures active even when Python assertions are optimized away."""
    if not condition:
        raise ValueError(message)


def git(root: Path, *arguments: str) -> bytes:
    """Read the local Git object database without network or source execution."""
    return subprocess.check_output(["git", "-C", str(root), *arguments])


def require_digest(raw: bytes, digest: str, label: str) -> None:
    """Reject a changed reference rather than learning expectations from it."""
    require(hashlib.sha256(raw).hexdigest() == digest, f"reference digest mismatch: {label}")


def read_reference(root: Path, relative: str) -> bytes:
    """Load the first published reference bytes through an immutable commit anchor."""
    raw = git(root, "show", f"{REFERENCE_COMMIT}:{relative}")
    require_digest(raw, REFERENCE_DIGESTS[relative], relative)
    return raw


def validate_path_scope(base: set[str], candidate: set[str], allowed: set[str]) -> None:
    """Inspect both sides so new tracked files cannot escape baseline-only iteration."""
    unexpected = (base ^ candidate) - allowed
    require(not unexpected, f"out-of-scope added/deleted paths: {sorted(unexpected)}")


class RestorePresentation(ast.NodeTransformer):
    """Reverse only the enumerated presentation, documentation and typing changes."""

    def __init__(self, texts: dict[str, str]) -> None:
        """Use text read from the pinned reference, never the candidate golden."""
        self.texts = texts

    def visit_ImportFrom(self, node):
        """Remove the documented locale import and the precise typing-only import."""
        aliases = [(item.name, item.asname) for item in node.names]
        if node.module == "reporting" and aliases == [("locale_pt_br", "pt_br")]:
            require(node.level == 0, "unexpected relative presentation import")
            return None
        if node.module == "typing" and any(item.name == "TypedDict" for item in node.names):
            require(
                node.level == 0 and aliases == [("Any", None), ("TypedDict", None)],
                "unexpected typing import change",
            )
            node.names = [ast.alias(name="Any")]
        return node

    def visit_AnnAssign(self, node):
        """Normalize the exact DESIGN annotation without altering its dictionary value."""
        if isinstance(node.target, ast.Name) and node.target.id == "DESIGN":
            require(
                isinstance(node.annotation, ast.Name)
                and node.annotation.id == "_DesignTokens"
                and node.simple == 1,
                "unexpected DESIGN annotation",
            )
            require(isinstance(node.value, ast.Dict), "DESIGN must remain a dictionary literal")
            return ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node)
        return self.generic_visit(node)

    def visit_ClassDef(self, node):
        """Ignore only the exact private TypedDict declaration, not arbitrary classes."""
        if node.name != "_DesignTokens":
            return self._without_docstring(node)
        require(
            [ast.unparse(base) for base in node.bases] == ["TypedDict"]
            and not node.keywords
            and not node.decorator_list,
            "unexpected design type declaration",
        )
        fields = node.body[1:] if ast.get_docstring(node) is not None else node.body
        require(
            all(
                isinstance(item, ast.AnnAssign)
                and isinstance(item.target, ast.Name)
                and item.value is None
                and item.simple == 1
                for item in fields
            ),
            "design type must contain only field declarations",
        )
        actual = {item.target.id: ast.unparse(item.annotation) for item in fields}
        require(
            len(fields) == len(DESIGN_FIELDS) and actual == DESIGN_FIELDS,
            "design type fields differ from their exact contract",
        )
        return None

    def visit_Attribute(self, node):
        """Restore each locale read from the independently pinned original value."""
        if isinstance(node.value, ast.Name) and node.value.id == "pt_br":
            require(node.attr in self.texts, f"unrecorded presentation name: {node.attr}")
            require(isinstance(node.ctx, ast.Load), "presentation reference must remain a read")
            return ast.copy_location(ast.Constant(self.texts[node.attr]), node)
        return self.generic_visit(node)

    def visit_JoinedStr(self, node):
        """Fold only plain interpolated constants introduced by label extraction."""
        self.generic_visit(node)
        merged = []
        for item in node.values:
            if (
                isinstance(item, ast.FormattedValue)
                and item.conversion == -1
                and item.format_spec is None
                and isinstance(item.value, ast.Constant)
                and isinstance(item.value.value, str)
            ):
                item = item.value
            if merged and isinstance(item, ast.Constant) and isinstance(merged[-1], ast.Constant):
                merged[-1].value += item.value
            else:
                merged.append(item)
        node.values = merged
        return node

    def _without_docstring(self, node):
        """Remove explanatory docstrings while preserving every executable statement."""
        if isinstance(node, ast.Module):
            node.body = [
                item
                for item in node.body
                if not (
                    isinstance(item, ast.Import)
                    and [(alias.name, alias.asname) for alias in item.names] == [("os", None)]
                )
            ]
        self.generic_visit(node)
        if (
            node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
        return node

    visit_Module = _without_docstring
    visit_FunctionDef = _without_docstring


def comparison_digest(result: dict[str, object]) -> str:
    """Bind the complete proof record to the fixed reviewed comparison digest."""
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == EXPECTED_COMPARISON_SHA256, "comparison digest mismatch")
    return digest


def verify(root: Path) -> dict[str, object]:
    """Check reference integrity, allowed paths, renderer ASTs and protected file bytes."""
    references = {name: read_reference(root, name) for name in REFERENCE_DIGESTS}
    for relative, expected in references.items():
        require(
            (root / relative).read_bytes() == expected, f"candidate changed reference: {relative}"
        )
    record = json.loads(references["tests/fixtures/reporting_language_baseline.json"])
    require(record["base_sha"] == BASE, "wrong baseline identity")
    texts = record["presentation_text"]
    locale = ast.parse((root / "reporting/locale_pt_br.py").read_bytes())
    actual = {}
    for index, statement in enumerate(locale.body):
        if index == 0 and isinstance(statement, ast.Expr) and ast.get_docstring(locale) is not None:
            continue
        if not (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            raise ValueError("nonliteral locale definition")
        name = statement.targets[0].id
        require(name not in actual, f"duplicate locale name: {name}")
        actual[name] = statement.value.value
    require(actual == texts, "locale differs from the pinned pre-migration values")
    base_paths = {
        p.decode() for p in git(root, "ls-tree", "-rz", "--name-only", BASE).split(b"\0") if p
    }
    candidate_paths = {p.decode() for p in git(root, "ls-files", "-z").split(b"\0") if p}
    validate_path_scope(base_paths, candidate_paths, EXPECTED_CHANGES)
    matched = []
    for relative in MIGRATED:
        before = RestorePresentation(texts).visit(
            ast.parse(git(root, "show", f"{BASE}:{relative}"))
        )
        after = RestorePresentation(texts).visit(ast.parse((root / relative).read_bytes()))
        require(ast.dump(before) == ast.dump(after), f"executable AST differs: {relative}")
        matched.append(relative)
    protected = []
    for relative in sorted(base_paths - EXPECTED_CHANGES):
        original = git(root, "show", f"{BASE}:{relative}")
        require(
            (root / relative).read_bytes() == original, f"out-of-scope bytes differ: {relative}"
        )
        protected.append({"path": relative, "sha256": hashlib.sha256(original).hexdigest()})
    result: dict[str, object] = {"base": BASE, "ast_matches": matched, "protected_files": protected}
    comparison_sha256 = comparison_digest(result)
    return {
        "base": BASE,
        "reference_commit": REFERENCE_COMMIT,
        "ast_matches": len(matched),
        "protected_files": len(protected),
        "comparison_sha256": comparison_sha256,
    }


def lexical_inventory(root: Path) -> dict[str, object]:
    """Reproduce the bounded source inventory using only fixed-base Git objects."""
    identifiers = []
    prose = []
    accents = re.compile(ACCENT_PATTERN)
    terms = set(IDENTIFIER_TOKENS)
    for relative in INVENTORY_PATHS:
        source = git(root, "show", f"{BASE}:{relative}").decode("utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            name = None
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = node.name
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.arg):
                name = node.arg
            if name and terms.intersection(name.lower().split("_")):
                identifiers.append(
                    {"path": relative, "line": getattr(node, "lineno", 1), "text": name}
                )
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    for index, line in enumerate(doc.splitlines()):
                        if accents.search(line):
                            prose.append(
                                {
                                    "path": relative,
                                    "line": node.body[0].lineno + index,
                                    "kind": "docstring",
                                    "text": line,
                                }
                            )
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and accents.search(token.string):
                prose.append(
                    {
                        "path": relative,
                        "line": token.start[0],
                        "kind": "comment",
                        "text": token.string,
                    }
                )
    return {
        "base": BASE,
        "paths": list(INVENTORY_PATHS),
        "identifier_tokens": list(IDENTIFIER_TOKENS),
        "accent_pattern": ACCENT_PATTERN,
        "identifier_candidates": identifiers,
        "prose_candidates": prose,
    }


def main() -> int:
    """Print a reproducible proof result; any unmet invariant exits unsuccessfully."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--inventory", action="store_true", help="Report the fixed-base lexical inventory"
    )
    args = parser.parse_args()
    operation = lexical_inventory if args.inventory else verify
    print(json.dumps(operation(args.root.resolve()), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
