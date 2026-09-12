"""Guard stage-six integration language without changing external contracts."""
from __future__ import annotations

import json
import re
import unicodedata
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = ROOT / "scripts" / "codex" / "setup-coderabbit.sh"
SERVER_SOURCE = ROOT / "mcp" / "src" / "server.ts"
GOVERNANCE = ROOT / ".github" / "governance" / "main-ruleset.json"

PORTUGUESE_TOOLING_TERMS = frozenset({
    "obrigatorio", "validar", "estado", "encontrado", "ambiente", "baixar",
    "instalar", "manifesto", "versao", "ausente", "reconhecido", "diverge",
    "origem", "plataforma", "suportada", "invalido", "configurados", "precisa",
    "autenticacao", "interativa", "nao", "proveniencia", "esperados", "confirmacao",
    "habilitado", "preso", "disponivel", "instalado", "perdeu", "reinicie",
    "sessao", "binario", "extraido", "verificado", "reporta",
})
EXPECTED_MCP_ENV = {
    "PROJECT_ROOT", "REF_ROOT", "RESULTS_ROOT", "AUDIT_ROOT", "PORT", "MCP_BIND_HOST"
}
EXPECTED_REQUIRED_CHECKS = {
    "static",
    "container-canary",
    "Canonical policy + 263-rule contract",
    "OPA/Rego parity",
    "Real Docker + canonical read-only mount",
    "CodeRabbit",
    "Greptile Review",
    "GitGuardian Security Checks",
    "DeepSource: Python",
    "DeepSource: JavaScript",
    "DeepSource: Shell",
    "DeepSource: Docker",
    "DeepSource: SQL",
    "semgrep-cloud-platform/scan",
}


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _tooling_terms(text: str) -> set[str]:
    words = {_normalize(word) for word in re.findall(r"[^\W_]+", text, flags=re.UNICODE)}
    return words & PORTUGUESE_TOOLING_TERMS


def _setup_diagnostics(source: str) -> tuple[str, ...]:
    """Extract only quoted messages passed to executable fail/echo commands."""
    command = re.compile(
        r'(?:^|\|\||;|\))\s*(?:fail|echo)\s+"((?:[^"\\]|\\.)*)"',
        re.MULTILINE,
    )
    return tuple(command.findall(source))


class IntegrationCodeLanguageTest(unittest.TestCase):
    """Keep developer tooling English while preserving integration contracts."""

    def test_coderabbit_setup_diagnostics_are_english(self) -> None:
        """The stage-six inventoried developer diagnostics must not return in Portuguese."""
        diagnostics = _setup_diagnostics(SETUP_SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(len(diagnostics), 37)
        self.assertEqual(_tooling_terms("\n".join(diagnostics)), set())

    def test_diagnostic_extraction_ignores_comments_and_contract_values(self) -> None:
        """Portuguese outside executable fail/echo messages is not tooling-language debt."""
        source = (
            '# fail "versão ausente"\n'
            'CONTRACT="plataforma não suportada"\n'
            'fail "version is missing"\n'
            'echo "ERROR: unsupported platform" >&2\n'
        )
        self.assertEqual(
            _setup_diagnostics(source),
            ("version is missing", "ERROR: unsupported platform"),
        )

    def test_tooling_scanner_detects_portuguese_fixture(self) -> None:
        """The bounded scanner must reject representative translated diagnostics."""
        self.assertEqual(
            _tooling_terms("versão ausente; plataforma não suportada; reinicie a sessão"),
            {"versao", "ausente", "plataforma", "nao", "suportada", "reinicie", "sessao"},
        )

    def test_mcp_environment_variable_contract_is_unchanged(self) -> None:
        """Stage six cannot rename deployment-admin environment variables."""
        source = SERVER_SOURCE.read_text(encoding="utf-8")
        found = set(re.findall(r"process\.env\.([A-Z][A-Z0-9_]*)", source))
        self.assertEqual(found, EXPECTED_MCP_ENV)

    def test_required_status_check_contexts_are_unchanged(self) -> None:
        """Workflow display cleanup cannot rename protected-main check identities."""
        payload = json.loads(GOVERNANCE.read_text(encoding="utf-8"))
        status_rules = [
            rule for rule in payload["rules"] if rule["type"] == "required_status_checks"
        ]
        self.assertEqual(len(status_rules), 1)
        status_rule = status_rules[0]
        checks = status_rule["parameters"]["required_status_checks"]
        contexts = {item["context"] for item in checks if "context" in item}
        fingerprints = [item["context_fingerprint"] for item in checks if "context_fingerprint" in item]
        self.assertEqual(contexts, EXPECTED_REQUIRED_CHECKS)
        self.assertEqual(len(fingerprints), 1)
        self.assertEqual(fingerprints[0]["digest"], "13148c18c6ce9155ee89d2c0de0435a9ff86e658bc56851d2a8ec24062134bf7 ".strip())
        self.assertEqual(fingerprints[0]["provider_family"], "dependency-security")

    def test_intentional_portuguese_integration_values_remain_contractual(self) -> None:
        """Normative values, localized fixtures and safety filename patterns remain untouched."""
        projection = (ROOT / "adapters/supabase/optional_projection.sql").read_text(
            encoding="utf-8"
        )
        for status in (
            "EXECUTADO", "VERIFICADO", "INFERIDO", "PROPOSTO", "NÃO DISPONÍVEL"
        ):
            self.assertIn(status, projection)
        runtime_gate = (ROOT / ".github/workflows/genoma-ngs-runtime-gate.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("NÃO DISPONÍVEL: approved GRCh38 lock missing", runtime_gate)
        array_gate = (ROOT / ".github/workflows/genoma-snp-array.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("dados[ _-]*dna", array_gate)
        visual = (ROOT / ".github/workflows/genoma-visual-qa-candidates.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("Conteúdo rastreável para teste editorial de regressão visual.", visual)
        self.assertIn("Fixture editorial; não representa paciente.", visual)


if __name__ == "__main__":
    unittest.main()
