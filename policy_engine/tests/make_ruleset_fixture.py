from __future__ import annotations

import hashlib
import sys
from pathlib import Path

CANONICAL = "REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt"


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    out.mkdir(parents=True, exist_ok=True)
    ruleset = out / CANONICAL
    lines = [
        "REGRAS PROJETO GENOMA",
        "STATUS NORMATIVO: VIGENTE",
        "VERSÃO NORMATIVA: v3.4",
        "DATA FORMAL DE EMISSÃO E VIGÊNCIA: 17/08/2026",
        "IDENTIFICADOR NORMATIVO: GENOMA-RULESET-v3.4",
        f"ARQUIVO CANÔNICO: {CANONICAL}",
        "FIXTURE DE TESTE: NÃO É O ARTEFATO NORMATIVO; USO EXCLUSIVO EM CI DE INFRAESTRUTURA.",
        "",
    ]
    for index in range(263):
        lines.extend([f"{index}. Fixture section {index}", "CI-only synthetic section body.", ""])

    payload = ("\n".join(lines) + "\n").encode("utf-8")
    ruleset.write_bytes(payload)
    manifests = out / "manifests"
    manifests.mkdir(exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    manifest = manifests / "RULESET_V3.4.sha256"
    manifest.write_text(f"{digest}  {CANONICAL}\n", encoding="ascii")
    print(ruleset)
    print(manifest)


if __name__ == "__main__":
    main()
