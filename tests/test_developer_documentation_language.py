"""Keep active developer documentation English while preserving explicit exceptions."""
from __future__ import annotations

import json
import re
import unicodedata
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MIGRATED_TECHNICAL_DOCS = (
    "docs/ANCESTRY_REFERENCE_PANEL.md",
    "docs/EDITORIAL_V3_PIXEL_QA.md",
    "docs/HIGHMEM_GRCH38_RUNNER.md",
    "docs/PGX_ALLELE_DISCRIMINATION.md",
    "docs/SNP_ARRAY_PARTIAL_GENOME.md",
    "docs/TARGET_REGISTRY_EXPANSION.md",
)
ACTIVE_DOCUMENTATION_EXCLUDED_PREFIXES = (
    "docs/evidence/",
    "docs/audits/",
    "docs/history/",
    "docs/superpowers/plans/",
    "docs/superpowers/checkpoints/",
    "docs/superpowers/evidence/",
    "normative/",
    "template_store/",
    "vendor/",
)
ACTIVE_DOCUMENTATION_EXCLUDED_PARTS = frozenset({
    ".git", "node_modules", "dist", "build", "generated", ".venv", "__pycache__"
})


def _discover_active_developer_docs(root: Path) -> tuple[str, ...]:
    """Discover active Markdown developer docs while excluding evidence/history surfaces."""
    relative = []
    for path in root.rglob("*.md"):
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if any(part in ACTIVE_DOCUMENTATION_EXCLUDED_PARTS for part in path.parts):
            continue
        if name.startswith(ACTIVE_DOCUMENTATION_EXCLUDED_PREFIXES):
            continue
        relative.append(name)
    return tuple(sorted(relative))


ACTIVE_TECHNICAL_DOCS = _discover_active_developer_docs(ROOT)
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
PORTUGUESE_ACCENT = re.compile(r"[áéíóúâêôãõçà]", re.IGNORECASE)
EMAIL_ADDRESS = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b"
)
DOMAIN_COM_SUFFIX = re.compile(r"(?<=\.)com\b", re.IGNORECASE)
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
PRESERVED_LITERALS = tuple(dict.fromkeys((
    *_POLICY_PAYLOAD["contract_literals"],
    "NÃO DETECTADO", "NÃO TESTADO", "NÃO REPORTÁVEL",
    "MODELO", "RESULTADO", "DATA", "VERSÃO",
    "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO", "TRANSFERIBILIDADE INCERTA",
    "PARCIALMENTE TRANSFERÍVEL",
    "ACHADO PRELIMINAR", "ACHADO ACIONÁVEL",
    "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt",
    "REGRAS_..._v3.4_2026-08-17.txt",
    "NAO_DISPONIVEL", "NAO_TESTADO", "NAO_REPORTAVEL", "NAO_DETECTADO",
    "NAO_INTERROGADO",
)))
PRESERVED_PROPER_NOUNS = ("Tupí", "Rondônia")
COMPATIBILITY_INLINE_EXCLUSIONS = frozenset({
    "NÃO DISPONÍVEL", "NÃO DETECTADO", "NÃO TESTADO", "NÃO REPORTÁVEL",
    "EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO",
    "MODELO", "RESULTADO", "DATA", "VERSÃO",
    "NÃO TRANSFERÍVEL SEM CALIBRAÇÃO", "TRANSFERIBILIDADE INCERTA",
    "PARCIALMENTE TRANSFERÍVEL",
    "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt",
    "REGRAS_..._v3.4_2026-08-17.txt",
    "NAO_DISPONIVEL", "NAO_TESTADO", "NAO_REPORTAVEL", "NAO_DETECTADO",
    "NAO_INTERROGADO",
})
RETIRED_BASE_COMMANDS = frozenset({"python3 scripts/curate_panelapp.py"})
PRESERVED_PORTUGUESE_REASONS = frozenset({
    "historical_quote", "localized_example", "safety_pattern"
})
EXPECTED_PRESERVED_PORTUGUESE_COUNTS = {
    "docs/ANCESTRY_REFERENCE_PANEL.md": 1,
    "docs/EDITORIAL_V3_PIXEL_QA.md": 1,
    "docs/PGX_ALLELE_DISCRIMINATION.md": 7,
    "docs/SNP_ARRAY_PARTIAL_GENOME.md": 4,
    "docs/TARGET_REGISTRY_EXPANSION.md": 16,
    "docs/ARRAY_PROVENANCE_PROBE.md": 2,
    "docs/GENOME_COMPLETENESS_MATRIX.md": 2,
    "docs/PHARMACOGENOMIC_PASSPORT.md": 12,
}
EXPECTED_PRESERVED_INLINE_COUNTS = {
    "docs/ANCESTRY_REFERENCE_PANEL.md": 1,
    "docs/TARGET_REGISTRY_EXPANSION.md": 1,
    "docs/INTEGRATION_CODE_LANGUAGE_INVENTORY.md": 3,
}


def _normalize(value: str) -> str:
    """Normalize Unicode text for bounded Portuguese-token matching."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _known_portuguese_inflection_hints(words: set[str]) -> set[str]:
    """Map common plural/gender inflections back to known Portuguese policy terms."""
    matches = set()
    for word in words:
        candidates = set()
        if len(word) > 3 and word.endswith("s"):
            candidates.add(word[:-1])
        if len(word) > 4 and word.endswith("oes"):
            candidates.add(word[:-3] + "ao")
        if len(word) > 4 and word.endswith("ais"):
            candidates.add(word[:-3] + "al")
        if len(word) > 4 and word.endswith("eis"):
            candidates.add(word[:-3] + "el")
        if len(word) > 4 and word.endswith("is"):
            candidates.add(word[:-2] + "il")
        for candidate in tuple(candidates):
            if candidate.endswith("a"):
                candidates.add(candidate[:-1] + "o")
        if candidates & PORTUGUESE_PROSE_TERMS:
            matches.add(word)
    return matches


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
    line = re.sub(r"https?://\S+", " ", line)
    for literal in sorted(PRESERVED_LITERALS, key=len, reverse=True):
        line = line.replace(literal, " ")
    line = EMAIL_ADDRESS.sub(" ", line)
    line = DOMAIN_COM_SUFFIX.sub(" ", line)
    parts = re.findall(r"[^\W_]+", line, flags=re.UNICODE)
    analysis_parts = [word for word in parts if word not in PRESERVED_PROPER_NOUNS]
    words = {_normalize(word) for word in analysis_parts}
    matches = words & PORTUGUESE_PROSE_TERMS
    matches.update(_known_portuguese_inflection_hints(words))
    matches.update(
        _normalize(word)
        for word in analysis_parts
        if PORTUGUESE_ACCENT.search(word)
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


def _preserved_inline_portuguese_literals(path: Path) -> frozenset[str]:
    """Load exact reviewed Portuguese literals allowed only inside backticks."""
    try:
        relative = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return frozenset()
    fixture_path = ROOT / "tests/fixtures/developer_documentation_contract.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    values = fixture.get("preserved_inline_portuguese_literals", {}).get(relative, [])
    return frozenset(item["literal"] for item in values)


def _find_portuguese_prose(path: Path) -> list[tuple[int, tuple[str, ...]]]:
    """Scan every Markdown line except exact reviewed historical/localized exceptions."""
    findings: list[tuple[int, tuple[str, ...]]] = []
    preserved = _preserved_portuguese_lines(path)
    preserved_inline = _preserved_inline_portuguese_literals(path)
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw in preserved or raw.lstrip().startswith("```"):
            continue
        scanned = raw
        for literal in preserved_inline:
            scanned = scanned.replace(f"`{literal}`", " ")
        tokens = tuple(sorted(_prose_tokens(scanned)))
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
        if (
            not value.startswith("docs/evidence/")
            and value not in COMPATIBILITY_INLINE_EXCLUSIONS
        )
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

    def test_active_scope_covers_repository_developer_documentation(self) -> None:
        """Stage seven must guard the active developer-documentation surface, not six files."""
        active = set(ACTIVE_TECHNICAL_DOCS)
        required = {
            "README.md",
            "AGENTS.md",
            ".github/pull_request_template.md",
            "mcp/README.md",
            "policy_engine/README_GENOMA_POLICY.md",
            "docs/DETERMINISTIC_ENGINE.md",
            "docs/DEVELOPER_DOCUMENTATION_LANGUAGE_INVENTORY.md",
            "docs/superpowers/specs/2026-09-03-english-codebase-refactor-design.md",
            "adapters/README.md",
            "policy_engine/docs/TRANSLATION_MATRIX.md",
            "policy_engine/docs/GENOMA_EXECUTABLE_ARCHITECTURE.md",
            "policy_engine/docs/REMAINING_GAPS.md",
        }
        required.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "adapters").glob("*/README.md")
        )
        self.assertTrue(required <= active, sorted(required - active))
        self.assertFalse(any(path.startswith("docs/evidence/") for path in active))
        self.assertFalse(any(path.startswith("docs/audits/") for path in active))
        self.assertFalse(any(path.startswith("docs/history/") for path in active))
        self.assertFalse(any(path.startswith("docs/superpowers/plans/") for path in active))
        self.assertFalse(any(path.startswith("docs/superpowers/checkpoints/") for path in active))
        self.assertFalse(any(path.startswith("docs/superpowers/evidence/") for path in active))

    def test_active_scope_discovery_includes_new_docs_and_excludes_records(self) -> None:
        """Discovery must include new developer Markdown and exclude record/evidence surfaces."""
        with TemporaryDirectory() as directory:
            temp = Path(directory)
            included = (
                "README.md",
                "CONTRIBUTING.md",
                ".github/pull_request_template.md",
                "docs/ACTIVE.md",
                "docs/superpowers/specs/DESIGN.md",
                "mcp/README.md",
                "policy_engine/README_EXTRA.md",
                "adapters/README.md",
                "adapters/example/README.md",
                "policy_engine/docs/ACTIVE.md",
            )
            excluded = (
                "docs/evidence/EVIDENCE.md",
                "docs/audits/AUDIT.md",
                "docs/history/HISTORY.md",
                "docs/superpowers/plans/PLAN.md",
                "docs/superpowers/checkpoints/CHECKPOINT.md",
                "docs/superpowers/evidence/PROOF.md",
                "normative/sealed/README.md",
                "template_store/v3.0/report-01/README.md",
                "vendor/example/README.md",
                "generated/output/README.md",
            )
            for relative in included + excluded:
                path = temp / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Document\n", encoding="utf-8")
            discovered = set(_discover_active_developer_docs(temp))
            self.assertEqual(discovered, set(included))

    def test_translated_contribution_and_policy_docs_preserve_key_contracts(self) -> None:
        """Stage-seven translations must preserve validation and policy identifiers."""
        template = (ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")
        for command in (
            "python3 scripts/validate_repo.py",
            "python3 scripts/verify_supply_chain_lock.py",
            "python3 -m unittest discover -s tests -v",
        ):
            self.assertIn(f"`{command}`", template)
        self.assertIn("No auto-merge", template)
        self.assertIn(
            "Manual merge only after CodeRabbit + CI + all other required checks", template
        )
        matrix = (ROOT / "policy_engine/docs/TRANSLATION_MATRIX.md").read_text(
            encoding="utf-8"
        )
        for literal in ("`0–262`", "`GENOMA-V3.4-S000`", "`GENOMA-V3.4-S262`"):
            self.assertIn(literal, matrix)
        self.assertIn("PASS", matrix)

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

    def test_policy_contract_literals_are_excluded_by_exact_identity(self) -> None:
        """Every repository policy contract literal must remain outside prose detection."""
        for literal in _POLICY_PAYLOAD["contract_literals"]:
            with self.subTest(literal=literal):
                self.assertEqual(_prose_tokens(f"status = `{literal}`"), set())
        self.assertEqual(
            _prose_tokens("REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"), set()
        )

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

    def test_scanner_detects_inflected_ascii_portuguese_with_one_strong_signal(self) -> None:
        """Common Portuguese inflections must not require two unrelated weak hints."""
        examples = (
            "Falhas graves surgiram hoje.",
            "Mudancas importantes apareceram ontem.",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            for example in examples:
                with self.subTest(example=example):
                    path.write_text(example + "\n", encoding="utf-8")
                    self.assertTrue(_find_portuguese_prose(path))

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

    def test_email_and_bare_domain_syntax_do_not_create_portuguese_false_positives(self) -> None:
        """Email and domain suffixes must not be tokenized as Portuguese prose."""
        examples = (
            "Contact support@example.com for assistance.",
            "See docs.example.com for the current guide.",
            "Mail security-team@sub.example.org before release.",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            for example in examples:
                with self.subTest(example=example):
                    path.write_text(example + "\n", encoding="utf-8")
                    self.assertEqual(_find_portuguese_prose(path), [])

    def test_dotted_portuguese_identifier_is_not_discarded_as_a_domain(self) -> None:
        """Dotted implementation identifiers must remain visible to the language guard."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text("Use `arquivo.configuracao` here.\n", encoding="utf-8")
            self.assertTrue(_find_portuguese_prose(path))

    def test_uppercase_accented_portuguese_is_detected(self) -> None:
        """Uppercase accented prose must not bypass diacritic detection."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text("DOCUMENTAÇÃO TÉCNICA APROVADA.\n", encoding="utf-8")
            self.assertTrue(_find_portuguese_prose(path))

    def test_titlecase_accented_portuguese_is_detected(self) -> None:
        """Title-case accented Portuguese must not bypass diacritic detection."""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text("Ótimo.\n", encoding="utf-8")
            self.assertTrue(_find_portuguese_prose(path))

    def test_accented_proper_nouns_are_explicitly_preserved(self) -> None:
        """Only exact reviewed proper-name tokens bypass the diacritic detector."""
        self.assertEqual(_prose_tokens("Tupí peoples from Rondônia."), set())
        for attached in ("Tupíagem", "preTupí", "RondôniaExtra", "xRondônia"):
            with self.subTest(attached=attached):
                self.assertTrue(_prose_tokens(attached))
        self.assertTrue(_prose_tokens("Ótimo."))

    def test_inline_code_does_not_create_a_portuguese_bypass(self) -> None:
        """Backticks must not hide developer prose that is not an explicit contract literal."""
        examples = (
            "`Este painel deve usar dados somente após revisão.`",
            "Prefix `Isso ocorreu ontem.` suffix",
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            for example in examples:
                with self.subTest(example=example):
                    path.write_text(example + "\n", encoding="utf-8")
                    self.assertTrue(_find_portuguese_prose(path))

    def test_inline_code_identifiers_and_contract_literals_remain_allowed(self) -> None:
        """Scanning inline prose must not reject ordinary identifiers or exact contracts."""
        examples = (
            "Use `result_path` and `panel_matrix.status` for the current artifact.",
            "Status remains `NÃO DISPONÍVEL` until evidence exists.",
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

    def test_preserved_inline_portuguese_literals_are_exact_and_justified(self) -> None:
        """Only enumerated Portuguese backtick literals may bypass inline scanning."""
        fixture = json.loads(
            (ROOT / "tests/fixtures/developer_documentation_contract.json").read_text(
                encoding="utf-8"
            )
        )
        preserved = fixture["preserved_inline_portuguese_literals"]
        self.assertEqual(set(preserved), set(EXPECTED_PRESERVED_INLINE_COUNTS))
        for relative, expected_count in EXPECTED_PRESERVED_INLINE_COUNTS.items():
            entries = preserved[relative]
            self.assertEqual(len(entries), expected_count)
            self.assertEqual(len({item["literal"] for item in entries}), expected_count)
            source = (ROOT / relative).read_text(encoding="utf-8")
            for item in entries:
                self.assertEqual(set(item), {"literal", "reason"})
                self.assertIn(item["reason"], PRESERVED_PORTUGUESE_REASONS)
                self.assertEqual(source.count(f"`{item['literal']}`"), 1)
                self.assertTrue(_prose_tokens(item["literal"]))

    def test_inventory_does_not_document_a_retired_markdown_bypass(self) -> None:
        """The inventory must describe the current Markdown scanning boundary."""
        inventory = (
            ROOT / "docs/DEVELOPER_DOCUMENTATION_LANGUAGE_INVENTORY.md"
        ).read_text(encoding="utf-8")
        self.assertNotIn("outside fenced code and blockquotes", inventory)
        self.assertIn("Markdown syntax is not an exemption", inventory)
        for boundary in ("`normative/**`", "`template_store/**`", "`vendor/**`"):
            self.assertIn(boundary, inventory)

    def test_documented_repo_script_entrypoints_exist(self) -> None:
        """Executable doc commands must not call repository scripts absent from HEAD."""
        missing = []
        for relative in MIGRATED_TECHNICAL_DOCS:
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
        for relative in MIGRATED_TECHNICAL_DOCS:
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
        self.assertEqual(fixture["schema"], "genoma-developer-documentation-contract-v6")
        self.assertEqual(
            fixture["base_sha"], "185996841b55669e42aa641896e2947748e04704"
        )
        self.assertEqual(set(fixture["documents"]), set(MIGRATED_TECHNICAL_DOCS))
        for relative in MIGRATED_TECHNICAL_DOCS:
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
        policy_readme = (ROOT / "policy_engine/README_GENOMA_POLICY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt", policy_readme
        )
        policy_inventory = (ROOT / "docs/POLICY_CODE_LANGUAGE_INVENTORY.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("NAO_DISPONIVEL", policy_inventory)
        scientific_inventory = (
            ROOT / "docs/SCIENTIFIC_CODE_LANGUAGE_INVENTORY.md"
        ).read_text(encoding="utf-8")
        for literal in ("NAO_TESTADO", "NAO_REPORTAVEL", "NAO_DETECTADO", "NAO_INTERROGADO"):
            self.assertIn(literal, scientific_inventory)
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
