"""Keep active developer documentation English while preserving explicit exceptions."""
from __future__ import annotations

import json
import re
import unicodedata
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
ACTIVE_TECHNICAL_DOCS = (
    "docs/ANCESTRY_REFERENCE_PANEL.md",
    "docs/EDITORIAL_V3_PIXEL_QA.md",
    "docs/HIGHMEM_GRCH38_RUNNER.md",
    "docs/PGX_ALLELE_DISCRIMINATION.md",
    "docs/SNP_ARRAY_PARTIAL_GENOME.md",
    "docs/TARGET_REGISTRY_EXPANSION.md",
)
PORTUGUESE_PROSE_TERMS = frozenset({
    "apenas", "ainda", "alem", "antes", "apos", "arquivo", "arquivos",
    "cada", "como", "com", "dados", "deve", "devem", "durante", "entre",
    "essa", "esse", "esta", "este", "execucao", "fica", "ficam", "foi",
    "foram", "marcador", "marcadores", "mesmo", "nao", "onde", "painel",
    "para", "pode", "podem", "por", "quando", "que", "registro", "resultado",
    "resultados", "revisao", "sem", "sobre", "somente", "tambem", "todos",
    "todas", "uma", "versao",
})
PRESERVED_LITERALS = (
    "NÃO DISPONÍVEL", "NÃO DETECTADO", "NÃO TESTADO", "NÃO REPORTÁVEL",
    "EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO",
    "MODELO", "RESULTADO", "DATA", "VERSÃO",
    "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO", "TRANSFERIBILIDADE INCERTA",
    "PARCIALMENTE TRANSFERÍVEL",
)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _prose_tokens(line: str) -> set[str]:
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"https?://\S+", " ", line)
    for literal in PRESERVED_LITERALS:
        line = line.replace(literal, " ")
    words = {_normalize(word) for word in re.findall(r"[^\W_]+", line, flags=re.UNICODE)}
    return words & PORTUGUESE_PROSE_TERMS


def _find_portuguese_prose(path: Path) -> list[tuple[int, tuple[str, ...]]]:
    findings: list[tuple[int, tuple[str, ...]]] = []
    fenced = False
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced or stripped.startswith(">"):
            continue
        tokens = tuple(sorted(_prose_tokens(raw)))
        if tokens:
            findings.append((lineno, tokens))
    return findings


def _executable_lines(text: str) -> list[str]:
    lines: list[str] = []
    fenced = False
    language = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            if not fenced:
                language = stripped[3:].strip().lower()
                fenced = True
            else:
                fenced = False
                language = ""
            continue
        if not fenced or language not in {"bash", "sh", "shell", "python", "py"}:
            continue
        value = raw.rstrip()
        if not value.strip() or value.lstrip().startswith("#"):
            continue
        if language in {"bash", "sh", "shell"} and " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        lines.append(value)
    return lines


def _protected_contract(text: str) -> dict[str, list[str]]:
    return {
        "sha256_literals": sorted(
            re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", text)
        ),
        "urls": sorted(re.findall(r"https?://[^\s)`]+", text)),
        "inline_code": sorted(re.findall(r"`([^`\n]+)`", text)),
        "executable_lines": _executable_lines(text),
        "digit_groups": sorted(re.findall(r"\d+", text)),
    }


class DeveloperDocumentationLanguageTest(unittest.TestCase):
    """Bound stage-seven English documentation without rewriting contracts/history."""

    def test_active_technical_docs_have_no_detected_portuguese_prose(self) -> None:
        for relative in ACTIVE_TECHNICAL_DOCS:
            with self.subTest(path=relative):
                self.assertEqual(_find_portuguese_prose(ROOT / relative), [])

    def test_scanner_detects_portuguese_prose_but_ignores_contract_literals(self) -> None:
        self.assertEqual(_prose_tokens("Este painel deve usar dados somente após revisão."),
                         {"este", "painel", "deve", "dados", "somente", "apos", "revisao"})
        self.assertEqual(_prose_tokens("status = `NÃO DISPONÍVEL`; `EXECUTADO`"), set())

    def test_scanner_rejects_a_short_line_with_one_portuguese_term(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "short.md"
            path.write_text("## Como execute\n", encoding="utf-8")
            self.assertEqual(_find_portuguese_prose(path), [(1, ("como",))])

    def test_migrated_docs_preserve_base_contract_tokens_and_commands(self) -> None:
        fixture = json.loads(
            (ROOT / "tests/fixtures/developer_documentation_contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fixture["schema"], "genoma-developer-documentation-contract-v1")
        self.assertEqual(
            fixture["base_sha"], "185996841b55669e42aa641896e2947748e04704"
        )
        self.assertEqual(set(fixture["documents"]), set(ACTIVE_TECHNICAL_DOCS))
        for relative in ACTIVE_TECHNICAL_DOCS:
            with self.subTest(path=relative):
                current = (ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    _protected_contract(current), fixture["documents"][relative]
                )

    def test_intentional_portuguese_contract_values_are_still_present(self) -> None:
        matrix = (ROOT / "docs/GENOME_COMPLETENESS_MATRIX.md").read_text(encoding="utf-8")
        for literal in ("NÃO DETECTADO", "NÃO TESTADO", "NÃO REPORTÁVEL"):
            self.assertIn(literal, matrix)
        projection = (ROOT / "adapters/supabase/optional_projection.sql").read_text(
            encoding="utf-8"
        )
        for literal in (
            "EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL"
        ):
            self.assertIn(literal, projection)
        editorial = (ROOT / "docs/EDITORIAL_V3_PIXEL_QA.md").read_text(encoding="utf-8")
        for literal in ("MODELO", "RESULTADO", "DATA", "VERSÃO"):
            self.assertIn(literal, editorial)
        target_registry = (ROOT / "docs/TARGET_REGISTRY_EXPANSION.md").read_text(
            encoding="utf-8"
        )
        for literal in (
            "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO", "TRANSFERIBILIDADE INCERTA",
            "PARCIALMENTE TRANSFERÍVEL",
        ):
            self.assertIn(literal, target_registry)


if __name__ == "__main__":
    unittest.main()
