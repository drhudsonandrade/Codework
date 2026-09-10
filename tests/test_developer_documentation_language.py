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
LOCAL_PORTUGUESE_PROSE_TERMS = frozenset({
    "apenas", "ainda", "alem", "antes", "apos", "arquivo", "arquivos",
    "cada", "como", "com", "dados", "deve", "devem", "durante", "entre",
    "essa", "esse", "esta", "este", "execucao", "fica", "ficam", "foi",
    "foram", "marcador", "marcadores", "mesmo", "nao", "onde", "painel",
    "para", "pode", "podem", "por", "quando", "que", "registro", "resultado",
    "resultados", "revisao", "sem", "sobre", "somente", "tambem", "todos",
    "todas", "uma", "versao",
})
_POLICY_PAYLOAD = json.loads(
    (ROOT / "config/code_language_policy.json").read_text(encoding="utf-8")
)
POLICY_TECHNICAL_TERMS = frozenset(_POLICY_PAYLOAD["technical_terms"])
PORTUGUESE_PROSE_TERMS = LOCAL_PORTUGUESE_PROSE_TERMS | POLICY_TECHNICAL_TERMS
PORTUGUESE_LOWERCASE_ACCENT = re.compile(r"[áéíóúâêôãõçà]")
PORTUGUESE_ASCII_COMMON_WORDS = frozenset({
    "agora", "ainda", "aqui", "assim", "cada", "como", "depois", "desde",
    "esse", "essa", "este", "esta", "isso", "isto", "mais", "menos", "mesmo",
    "muito", "muitos", "nao", "onde", "ontem", "outro", "outros", "outra",
    "outras", "para", "pela", "pelas", "pelo", "pelos", "pois", "porque",
    "quando", "sem", "somente", "tambem", "talvez", "toda", "todas", "todo",
    "todos", "uma", "umas", "uns",
})
PORTUGUESE_ASCII_VERB_ENDINGS = (
    "ando", "endo", "indo", "amos", "emos", "imos", "aram", "eram", "iram",
    "avam", "aria", "ariam", "eria", "eriam", "iria", "iriam", "asse", "assem",
    "esse", "essem", "isse", "issem", "ou", "eu", "iu",
)
PORTUGUESE_ASCII_NOMINAL_ENDINGS = (
    "cao", "coes", "dade", "dades", "mente", "amento", "amentos", "imento",
    "imentos", "avel", "aveis", "ivel", "iveis",
)
PRESERVED_LITERALS = (
    "NÃO DISPONÍVEL", "NÃO DETECTADO", "NÃO TESTADO", "NÃO REPORTÁVEL",
    "EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO",
    "MODELO", "RESULTADO", "DATA", "VERSÃO",
    "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO", "TRANSFERIBILIDADE INCERTA",
    "PARCIALMENTE TRANSFERÍVEL",
)
RETIRED_BASE_COMMANDS = frozenset({"python3 scripts/curate_panelapp.py"})
PRESERVED_PORTUGUESE_REASONS = frozenset({"historical_quote", "localized_example"})
EXPECTED_PRESERVED_PORTUGUESE_COUNTS = {
    "docs/ANCESTRY_REFERENCE_PANEL.md": 1,
    "docs/EDITORIAL_V3_PIXEL_QA.md": 1,
    "docs/PGX_ALLELE_DISCRIMINATION.md": 7,
    "docs/SNP_ARRAY_PARTIAL_GENOME.md": 4,
    "docs/TARGET_REGISTRY_EXPANSION.md": 16,
}


def _normalize(value: str) -> str:
    """Normalize Unicode text for bounded Portuguese-token matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _ascii_portuguese_hints(words: set[str]) -> set[str]:
    """Return multi-signal Portuguese hints for otherwise ambiguous ASCII prose."""
    hints = words & PORTUGUESE_ASCII_COMMON_WORDS
    for word in words:
        if len(word) >= 5 and word.endswith(PORTUGUESE_ASCII_VERB_ENDINGS):
            hints.add(word)
        if len(word) >= 6 and word.endswith(PORTUGUESE_ASCII_NOMINAL_ENDINGS):
            hints.add(word)
    return hints if len(hints) >= 2 else set()


def _prose_tokens(line: str) -> set[str]:
    """Return policy, diacritic, and multi-signal ASCII Portuguese prose tokens."""
    line = re.sub(r"`[^`]*`", " ", line)
    line = re.sub(r"https?://\S+", " ", line)
    for literal in PRESERVED_LITERALS:
        line = line.replace(literal, " ")
    parts = re.findall(r"[^\W_]+", line, flags=re.UNICODE)
    words = {_normalize(word) for word in parts}
    matches = words & PORTUGUESE_PROSE_TERMS
    matches.update(
        _normalize(word)
        for word in parts
        if word[:1].islower() and PORTUGUESE_LOWERCASE_ACCENT.search(word)
    )
    if not matches:
        matches.update(_ascii_portuguese_hints(words))
    return matches


def _preserved_portuguese_lines(path: Path) -> frozenset[str]:
    """Load exact reviewed historical/localized Portuguese lines for a tracked document."""
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return frozenset()
    fixture_path = ROOT / "tests/fixtures/developer_documentation_contract.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture.get("preserved_portuguese_lines", {}).get(relative, [])
    return frozenset(item["line"] for item in values)


def _find_portuguese_prose(path: Path) -> list[tuple[int, tuple[str, ...]]]:
    """Scan every Markdown line except exact reviewed historical/localized exceptions."""
    findings: list[tuple[int, tuple[str, ...]]] = []
    preserved = _preserved_portuguese_lines(path)
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw in preserved or raw.lstrip().startswith("```"):
            continue
        tokens = tuple(sorted(_prose_tokens(raw)))
        if tokens:
            findings.append((lineno, tokens))
    return findings


def _executable_lines(text: str) -> list[str]:
    """Extract executable lines from shell and Python code fences."""
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
    """Pin stable commands/tokens while evidence references follow live artifacts."""
    evidence_free = re.sub(r"`docs/evidence/[^`\n]+`", " ", text)
    inline_code = [
        value
        for value in re.findall(r"`([^`\n]+)`", text)
        if not value.startswith("docs/evidence/") and value not in PRESERVED_LITERALS
    ]
    return {
        "sha256_literals": sorted(
            re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", text)
        ),
        "urls": sorted(re.findall(r"https?://[^\s)`]+", text)),
        "inline_code": sorted(inline_code),
        "executable_lines": [
            line for line in _executable_lines(text) if line not in RETIRED_BASE_COMMANDS
        ],
        "digit_groups": sorted(re.findall(r"\d+", evidence_free)),
    }


class DeveloperDocumentationLanguageTest(unittest.TestCase):
    """Bound stage-seven English documentation without rewriting contracts/history."""

    def test_active_technical_docs_have_no_detected_portuguese_prose(self) -> None:
        """Selected active technical docs must contain no detected Portuguese prose."""
        for relative in ACTIVE_TECHNICAL_DOCS:
            with self.subTest(path=relative):
                self.assertEqual(_find_portuguese_prose(ROOT / relative), [])

    def test_scanner_detects_portuguese_prose_but_ignores_contract_literals(self) -> None:
        """The bounded scanner must detect prose while ignoring exact contract labels."""
        self.assertEqual(_prose_tokens("Este painel deve usar dados somente após revisão."),
                         {"este", "painel", "deve", "dados", "somente", "apos", "revisao"})
        self.assertEqual(_prose_tokens("status = `NÃO DISPONÍVEL`; `EXECUTADO`"), set())

    def test_scanner_rejects_a_short_line_with_one_portuguese_term(self) -> None:
        """A one-token Portuguese heading must not escape the language gate."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "short.md"
            path.write_text("## Como execute\n", encoding="utf-8")
            self.assertEqual(_find_portuguese_prose(path), [(1, ("como",))])

    def test_scanner_detects_portuguese_beyond_the_local_word_list(self) -> None:
        """Repository policy terms and accented prose must extend the local token vocabulary."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text("Falha crítica detectada imediatamente.\n", encoding="utf-8")
            self.assertTrue(_find_portuguese_prose(path))

    def test_scanner_detects_ascii_portuguese_without_known_vocabulary(self) -> None:
        """Common all-ASCII Portuguese must not depend only on enumerated vocabulary."""
        examples = (
            "Isso ocorreu ontem.",
            "Precisamos corrigir outros problemas.",
            "Aquilo aconteceu ontem.",
            "Talvez possamos melhorar depois.",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            for index, example in enumerate(examples):
                with self.subTest(example=example):
                    path.write_text(example + "\n", encoding="utf-8")
                    self.assertTrue(_find_portuguese_prose(path), index)

    def test_ascii_heuristic_does_not_reject_plain_english_prose(self) -> None:
        """Broad Portuguese detection must retain negative controls for English prose."""
        examples = (
            "This panel validates files and reports current results.",
            "The runner checks reproducible artifacts before publication.",
            "We need to correct other problems before release.",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            for example in examples:
                with self.subTest(example=example):
                    path.write_text(example + "\n", encoding="utf-8")
                    self.assertEqual(_find_portuguese_prose(path), [])

    def test_markdown_syntax_does_not_create_a_portuguese_bypass(self) -> None:
        """Arbitrary blockquotes and fenced comments must remain subject to language checks."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text(
                "> Este painel deve usar dados somente após revisão.\n"
                "```bash\n"
                "# Este painel deve usar dados somente após revisão.\n"
                "```\n",
                encoding="utf-8",
            )
            findings = _find_portuguese_prose(path)
            self.assertEqual([line for line, _ in findings], [1, 3])

    def test_preserved_portuguese_exceptions_are_exact_and_justified(self) -> None:
        """Only enumerated historical/localized lines may bypass the language detector."""
        fixture = json.loads(
            (ROOT / "tests/fixtures/developer_documentation_contract.json").read_text(
                encoding="utf-8"
            )
        )
        preserved = fixture["preserved_portuguese_lines"]
        self.assertEqual(set(preserved), set(EXPECTED_PRESERVED_PORTUGUESE_COUNTS))
        for relative, expected_count in EXPECTED_PRESERVED_PORTUGUESE_COUNTS.items():
            entries = preserved[relative]
            self.assertEqual(len(entries), expected_count)
            self.assertEqual(len({item["line"] for item in entries}), expected_count)
            source_lines = (ROOT / relative).read_text(encoding="utf-8").splitlines()
            for item in entries:
                self.assertEqual(set(item), {"line", "reason"})
                self.assertIn(item["reason"], PRESERVED_PORTUGUESE_REASONS)
                self.assertEqual(source_lines.count(item["line"]), 1)
                self.assertTrue(_prose_tokens(item["line"]))

    def test_inventory_does_not_document_a_retired_markdown_bypass(self) -> None:
        """The inventory must describe the current Markdown scanning boundary."""
        inventory = (
            ROOT / "docs/DEVELOPER_DOCUMENTATION_LANGUAGE_INVENTORY.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("outside fenced code and blockquotes", inventory)
        self.assertIn("Markdown syntax is not an exemption", inventory)

    def test_documented_repo_script_entrypoints_exist(self) -> None:
        """Executable doc commands must not call repository scripts absent from HEAD."""
        missing = []
        for relative in ACTIVE_TECHNICAL_DOCS:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for line in _executable_lines(text):
                for script_path in re.findall(
                    r"(?:python3?|bash)\s+(scripts/[A-Za-z0-9_./-]+)", line
                ):
                    if not (ROOT / script_path).is_file():
                        missing.append((relative, script_path))
        self.assertEqual(missing, [])

    def test_documented_evidence_references_exist(self) -> None:
        """Active technical docs must not cite missing versioned evidence artifacts."""
        missing = []
        for relative in ACTIVE_TECHNICAL_DOCS:
            text = (ROOT / relative).read_text(encoding="utf-8")
            for evidence_path in re.findall(r"`(docs/evidence/[^`\n]+)`", text):
                if not (ROOT / evidence_path).is_file():
                    missing.append((relative, evidence_path))
        self.assertEqual(missing, [])

    def test_editorial_qa_claims_match_versioned_evidence(self) -> None:
        """Editorial QA prose must not overstate evidence present in the repository."""
        document = (ROOT / "docs/EDITORIAL_V3_PIXEL_QA.md").read_text(encoding="utf-8")
        static_path = "docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI_2026-08-16.json"
        docx_path = "docs/evidence/EDITORIAL_V3_DOCX_PARITY_150DPI_2026-08-20.json"
        static = json.loads((ROOT / static_path).read_text(encoding="utf-8"))
        docx = json.loads((ROOT / docx_path).read_text(encoding="utf-8"))
        self.assertEqual(static["status"], "VERIFICADO")
        self.assertEqual(docx["status"], "NÃO DISPONÍVEL")
        self.assertIn(f"`{static_path}`", document)
        self.assertIn(f"`{docx_path}`", document)
        self.assertNotIn("Poppler/pdftoppm confirmation: 11/11 `VERIFICADO`", document)
        self.assertIn("current reproducible DOCX QA status is `NÃO DISPONÍVEL`", document)

    def test_migrated_docs_preserve_base_contract_tokens_and_commands(self) -> None:
        """Stable base commands/tokens remain pinned while evidence paths may advance."""
        fixture = json.loads(
            (ROOT / "tests/fixtures/developer_documentation_contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(fixture["schema"], "genoma-developer-documentation-contract-v4")
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
        """Normative and localized Portuguese labels must remain available unchanged."""
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
