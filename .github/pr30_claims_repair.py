from __future__ import annotations

import gzip
import json
import subprocess
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"expected snippet not found: {label}")
    return text.replace(old, new, 1)


def repair_document() -> None:
    path = Path("docs/TARGET_REGISTRY_EXPANSION.md")
    text = path.read_text(encoding="utf-8")

    text = replace_once(
        text,
        'genes = lambda d: {t[k] for t in d["targets"] for k in ("gene",) if isinstance(t.get(k), str) and t[k]}\nr2 = {t["rsid"] for t in two["targets"]}; r1 = {t["rsid"] for t in one["targets"]}\nprint(len(r2), len(genes(two)))\nprint(len(r1 - r2), len(genes(one) - genes(two)))\nprint(len(r1), len(genes(one)))',
        'def genes(document):\n    values = set()\n    for target in document["targets"]:\n        target_genes = target.get("genes", [])\n        if isinstance(target_genes, str):\n            target_genes = [target_genes]\n        if isinstance(target_genes, list):\n            values.update(gene for gene in target_genes if isinstance(gene, str) and gene)\n    return values\nr2 = {t["rsid"] for t in two["targets"]}; r1 = {t["rsid"] for t in one["targets"]}\nprint(len(r2), len(genes(two)))\nprint(len(r1 - r2), len(genes(one) - genes(two)))\nprint(len(r1), len(genes(one)))',
        "target-count reproducer",
    )

    start = text.index("## Escala observada numa execução de demonstração")
    end = text.index("## Taxa de detecção, que era o objetivo", start)
    scale = """## Escala observada numa execução de demonstração

Os benchmarks quantitativos da execução histórica foram removidos deste documento porque o
repositório não contém o artefato de saída, SHA-256 das entradas, versões do ambiente e
comando pinado necessários para reproduzi-los. Eles não são evidência do HEAD atual e não
podem ser usados como alegação de desempenho.

O comportamento reproduzível preservado dessa investigação é o suporte a evidência
comprimida: `build_clinical_findings` lê o manifesto por `read_manifest_bytes`, que detecta
compressão pelo conteúdo do arquivo. O contrato é exercitado por
`tests/test_clinical_findings_regressions.py::test_the_gene_disease_evidence_may_arrive_compressed`.
Execute apenas esse conjunto com:

```bash
python3 -m unittest discover -s tests -p test_clinical_findings_regressions.py
```

As antigas narrativas de execução referentes aos relatórios 05 e 09 também permanecem fora
do conjunto verificável deste HEAD: não há aqui artefato versionado e reproducer correspondente
que autorize atribuir resultados quantitativos a esses caminhos.

"""
    text = text[:start] + scale + text[end:]

    start = text.index("## Taxa de detecção, que era o objetivo")
    end = text.index("## Reproduzir", start)
    detection = """## Taxa de detecção, que era o objetivo

O relatório 03 emite, em cada execução, o numerador de variantes interrogadas e o denominador
do catálogo aplicável. Os valores históricos de uma execução local foram removidos porque
não há artefato de saída, SHA-256 de entrada e comando pinado que permitam reproduzi-los neste
HEAD. O contrato verificável é que numerador e denominador sejam derivados dos artefatos da
própria execução e que a saída os descreva como contagem de variantes, não como frequência
alélica.

"""
    text = text[:start] + detection + text[end:]

    text = replace_once(
        text,
        "Curar 3.137 genes via E-utilities são ~10 mil requisições, uma hora de tráfego limitado, e\num rate limit de distância de um registro pela metade que *parece* completo.\n`variant_summary.txt.gz` é o mesmo dado num download versionado: ou o arquivo está lá ou não\nestá. O mesmo vale para o GenCC e para o GWAS Catalog.",
        "A rota por E-utilities exige muitas requisições e pode terminar parcialmente sob limites de\ntráfego sem produzir um artefato único que materialize o release consultado.\n`variant_summary.txt.gz` oferece o mesmo tipo de dado em um download materializável: ou o\narquivo completo está disponível ou a execução deve recusar. O mesmo princípio vale para os\nartefatos usados do GenCC e do GWAS Catalog.",
        "E-utilities benchmark",
    )
    text = replace_once(
        text,
        "A rota da API acha registros por **busca textual** de rsid, que devolve variantes não\nrelacionadas — em `rs4244285` devolveu doze. Esses registros não trazem coordenada própria e",
        "A rota da API acha registros por **busca textual** de rsid, que pode devolver variantes não\nrelacionadas ao locus pretendido. Esses registros não trazem coordenada própria e",
        "API-count anecdote",
    )
    path.write_text(text, encoding="utf-8")


def repair_code_comments() -> None:
    path = Path("array_pipeline/homozygosity.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "#:\n#: Measured on the first real array: the two longest tracts averaged 98.7 and 70.1 kb between\n#: markers against a sample median of 2.11 kb — 47x and 33x — and together they were 68% of\n#: the reported F_ROH. Both sat on chromosome 9, over the pericentromeric heterochromatin\n#: that arrays barely tile. They were coverage holes counted as homozygous genome.\n#:\n#: The bound is relative to the sample rather than absolute because array densities differ by",
        "#:\n#: This is a policy bound, not an empirical benchmark. A tract whose average marker spacing\n#: is far above the sample's own median is treated as insufficiently measured instead of\n#: letting a low-density coverage hole dominate the reported homozygous fraction.\n#:\n#: The bound is relative to the sample rather than absolute because array densities differ by",
        "homozygosity benchmark",
    )
    path.write_text(text, encoding="utf-8")

    path = Path("array_pipeline/clinical_findings.py")
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    # Validity is computed once per gene and stored once. Copying it into every finding cost\n    # 391 MB and 2.8 GB of peak memory on the 54,845-locus registry, because a gene with\n    # hundreds of catalogued variants carried hundreds of identical copies of its ClinGen and\n    # GenCC curations. Normalising loses nothing: every finding names its gene.",
        "    # Validity is computed once per gene and stored once. Repeating the same validity block\n    # at every locus duplicates evidence and makes resource use grow with repeated records.\n    # Normalising loses nothing: every finding names its gene and the evidence remains\n    # addressable from the shared gene-level block.",
        "clinical memory benchmark",
    )
    path.write_text(text, encoding="utf-8")


def load(path: str) -> dict[str, object]:
    raw = Path(path).read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def genes(document: dict[str, object]) -> set[str]:
    values: set[str] = set()
    for target in document["targets"]:  # type: ignore[index]
        target_genes = target.get("genes", [])
        if isinstance(target_genes, str):
            target_genes = [target_genes]
        if isinstance(target_genes, list):
            values.update(gene for gene in target_genes if isinstance(gene, str) and gene)
    return values


def verify() -> None:
    two = load("config/targets_clinvar_plp.json.gz")
    one = load("config/targets_clinvar_plp_1star.json.gz")
    two_targets = two["targets"]  # type: ignore[index]
    one_targets = one["targets"]  # type: ignore[index]
    r2 = {target["rsid"] for target in two_targets}
    r1 = {target["rsid"] for target in one_targets}
    observed = (
        (len(r2), len(genes(two))),
        (len(r1 - r2), len(genes(one) - genes(two))),
        (len(r1), len(genes(one))),
    )
    expected = ((54845, 3082), (68706, 1326), (123551, 4408))
    print("target-count reproducer:", observed)
    if observed != expected:
        raise SystemExit(f"target-count mismatch: expected {expected}, observed {observed}")

    forbidden = (
        "98.7 and 70.1",
        "391 MB",
        "2.8 GB",
        "40 MB",
        "20,5 s",
        "676 MB",
        "23 MB",
        "59 MB",
        "2.236 de 162.943",
        "3.137 genes",
        "devolveu doze",
    )
    for file_name in (
        "array_pipeline/homozygosity.py",
        "array_pipeline/clinical_findings.py",
        "docs/TARGET_REGISTRY_EXPANSION.md",
    ):
        text = Path(file_name).read_text(encoding="utf-8")
        hits = [claim for claim in forbidden if claim in text]
        if hits:
            raise SystemExit(f"unsupported historical claims remain in {file_name}: {hits}")

    subprocess.run(["git", "diff", "--check"], check=True)
    subprocess.run(["python3", "scripts/validate_repo.py"], check=True)
    subprocess.run(
        [
            "python3",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_clinical_findings_regressions.py",
            "-v",
        ],
        check=True,
    )


if __name__ == "__main__":
    repair_document()
    repair_code_comments()
    verify()
