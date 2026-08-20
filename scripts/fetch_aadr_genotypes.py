#!/usr/bin/env python3
"""Pull selected individuals' genotypes out of the AADR Human Origins release.

The report 02 reference panel had no Amazonian population and said so as a limitation:
Nahua, Maya, Quechua and Aymara are Mesoamerican and Andean, so the indigenous component of
a Brazilian genome was being measured against related but not local peoples. The Allen
Ancient DNA Resource carries present-day Human Origins genotypes for **Karitiana** and
**Surui** — Tupí peoples of Rondônia, in the Brazilian Amazon — and for **Piapoco** of the
Orinoco–Amazon basin, under CC0.

**Why fetching, not downloading.** The Human Origins genotype file is 3.8 GB and holds 27,594
individuals, of whom this panel needs about a hundred. The format is `packedancestrymap` in
its *transposed* variant, whose header reads ``TGENO nind nsnp``: one fixed-length row per
**individual**, not per SNP. That makes each individual a single contiguous range of
``ceil(nsnp/4)`` bytes, and Harvard Dataverse answers HTTP range requests, so a hundred
individuals cost about 14 MB rather than 3.8 GB.

**Why the allele orientation is measured and not assumed.** The two bits per genotype count
copies of one of the two alleles named in the `.snp` file, and which one is a convention this
script refuses to take on faith: reading it backwards inverts every genotype silently, and a
panel built on inverted genotypes still produces confident-looking coordinates. The
orientation is settled by ``scripts/build_ancestry_panel.py`` against 1000 Genomes allele
frequencies at shared markers, where an inversion shows up as a strongly negative
correlation. This script only reports what it read.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATAVERSE_DOI = "doi:10.7910/DVN/FFIDCW"
DATAVERSE_FILE = "https://dataverse.harvard.edu/api/access/datafile/{file_id}?format=original"
AADR_CITATION = (
    "Mallick S, Micco A, Mah M, Ringbauer H, Lazaridis I, Olalde I, Patterson N, Reich D. "
    "The Allen Ancient DNA Resource (AADR): A curated compendium of ancient human genomes. "
    "Harvard Dataverse, doi:10.7910/DVN/FFIDCW, licença CC0 1.0."
)

#: Population groups taken as reference, and the group each belongs to in the panel. The
#: split is the point: "indígena americano" as one bucket is what made an Amazonian genome
#: get measured against Andean and Mesoamerican peoples.
GROUPS: dict[str, tuple[str, ...]] = {
    "AMR-NAT-AMAZONIA": ("Karitiana", "Surui", "Piapoco"),
    "AMR-NAT-ANDES": ("Quechua", "Bolivian"),
    "AMR-NAT-MESOAMERICA": ("Mayan", "Mixe", "Mixtec", "Pima", "Zapotec"),
}
#: Fetched only so the allele orientation can be checked against 1000 Genomes frequencies.
#: These are never used as reference groups — the continental references come from the
#: 1000 Genomes release, whose sample labels this project already relies on.
ORIENTATION_CONTROLS: dict[str, tuple[str, ...]] = {
    "CHECK-EUR": ("French",),
    "CHECK-EAS": ("Han",),
    "CHECK-AFR": ("Yoruba",),
}

#: Reich-lab suffixes marking a sample the curators themselves set aside. Including one
#: would put an individual the source flagged as an outlier into a reference centroid.
EXCLUDED_SUFFIXES = ("-Discovery", "-QCremove", "-o", "-oEurope", "-oPCA", "-2")

MISSING = 3


class AadrError(RuntimeError):
    pass


def _get(url: str, *, byte_range: tuple[int, int] | None = None, attempts: int = 4) -> bytes:
    headers = {"User-Agent": "genoma-ancestry-panel/1.0"}
    if byte_range is not None:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    request = urllib.request.Request(url, headers=headers)
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                if byte_range is not None and response.status != 206:
                    raise AadrError(
                        "o servidor ignorou o pedido de intervalo e devolveu o arquivo "
                        f"inteiro (HTTP {response.status}); abortando em vez de baixar 3,8 GB"
                    )
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise AadrError(f"falha ao ler {url}: {last}")


def read_annotation(path: Path) -> dict[str, dict[str, str]]:
    """Genetic ID -> group, country, date, for the present-day Human Origins samples."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    if not rows:
        raise AadrError(f"anotação vazia: {path}")
    out: dict[str, dict[str, str]] = {}
    for row in rows[1:]:
        if len(row) <= 16:
            continue
        gid, date, group, country = row[0], row[10].strip(), row[14], row[16]
        # Present-day only. A date of anything but zero is an ancient individual, and an
        # ancient genome in a modern reference centroid moves it somewhere nobody lives.
        if date not in ("0", ""):
            continue
        # `.HO` is the Affymetrix Human Origins genotype representation. The other suffixes
        # are shotgun or capture data on a different ascertainment, and mixing them changes
        # which markers are missing in a way that tracks the assay rather than the person.
        if not gid.endswith(".HO"):
            continue
        out[gid] = {"group": group, "country": country, "date": date}
    return out


def read_ind(path: Path) -> list[tuple[str, str, str]]:
    """The `.ind` file, in file order — the order the genotype rows are stored in."""
    out: list[tuple[str, str, str]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 3:
            out.append((fields[0], fields[1], fields[2]))
    return out


def read_snp(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) < 6:
            continue
        out.append(
            {
                "rsid": fields[0],
                "chromosome": fields[1],
                "position": int(fields[3]),
                "allele_a": fields[4].upper(),
                "allele_b": fields[5].upper(),
            }
        )
    return out


def _content_length(url: str) -> int:
    """The file's true size, from a one-byte range response's Content-Range.

    Needed because the row offsets are derived from it rather than assumed — see
    `resolve_layout`. A HEAD request is not used: it returns no Content-Range and the
    Content-Length it does return describes the redirect, not the file.
    """
    request = urllib.request.Request(
        url, headers={"Range": "bytes=0-0", "User-Agent": "genoma-ancestry-panel/1.0"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        content_range = response.headers.get("Content-Range") or ""
    _, _, total = content_range.partition("/")
    if not total.strip().isdigit():
        raise AadrError(
            f"o servidor não informou o tamanho total do arquivo ({content_range!r}); sem ele "
            "o deslocamento das linhas não pode ser verificado"
        )
    return int(total.strip())


def resolve_layout(nind: int, nsnp: int, file_size: int) -> tuple[int, int]:
    """Return (header_bytes, row_bytes), decided by arithmetic on the real file size.

    packedancestrymap is documented as padding its header to a full row, and this file does
    not: its 3.8 GB are exactly ``48 + row_bytes * nind``, 145,985 bytes short of the padded
    layout. Assuming the documented convention shifted every read by almost one whole row, so
    each individual was served a scrambled mixture of two people's genotypes — data that
    unpacks cleanly, has a believable call rate, and is wrong.

    Nothing here is inferred from the convention: both candidate layouts are checked against
    the byte count, and a size matching neither is refused rather than rounded to the closer
    one.
    """
    row_bytes = max(48, (nsnp + 3) // 4)
    if file_size == 48 + row_bytes * nind:
        return 48, row_bytes
    if file_size == row_bytes * (nind + 1):
        return row_bytes, row_bytes
    raise AadrError(
        f"o arquivo tem {file_size} bytes, que não corresponde nem a "
        f"{48 + row_bytes * nind} (cabeçalho de 48 bytes) nem a {row_bytes * (nind + 1)} "
        f"(cabeçalho preenchido até uma linha) para {nind} indivíduos e {nsnp} marcadores. "
        "Ler com um deslocamento errado produz genótipos que descompactam sem erro e "
        "pertencem a outra pessoa."
    )


def parse_header(raw: bytes) -> tuple[int, int]:
    text = raw[:48].split(b"\x00")[0].decode("ascii", errors="replace")
    parts = text.split()
    if not parts or parts[0] != "TGENO":
        raise AadrError(
            f"esperado cabeçalho TGENO (uma linha por indivíduo), encontrado {parts[:1]}. "
            "Um arquivo GENO tem uma linha por SNP e cada indivíduo estaria espalhado por "
            "todo o arquivo, o que torna a leitura por intervalo inútil."
        )
    return int(parts[1]), int(parts[2])


def unpack_row(row: bytes, nsnp: int) -> bytearray:
    """Two bits per genotype, four per byte, most significant pair first."""
    out = bytearray(nsnp)
    index = 0
    for byte in row:
        for shift in (6, 4, 2, 0):
            if index >= nsnp:
                return out
            out[index] = (byte >> shift) & 0b11
            index += 1
    return out


def select(annotation: dict[str, dict[str, str]]) -> dict[str, str]:
    """Genetic ID -> panel group, for every individual this panel takes as reference."""
    wanted: dict[str, str] = {}
    for panel_group, populations in {**GROUPS, **ORIENTATION_CONTROLS}.items():
        for gid, meta in annotation.items():
            group = meta["group"]
            if group not in populations:
                continue
            if any(group.endswith(suffix) for suffix in EXCLUDED_SUFFIXES):
                continue
            wanted[gid] = panel_group
    return wanted


def fetch(
    *,
    ind_path: Path,
    anno_path: Path,
    snp_path: Path,
    geno_file_id: str,
    limit_per_population: int | None = None,
) -> dict[str, Any]:
    annotation = read_annotation(anno_path)
    individuals = read_ind(ind_path)
    snps = read_snp(snp_path)
    url = DATAVERSE_FILE.format(file_id=geno_file_id)

    nind, nsnp = parse_header(_get(url, byte_range=(0, 47)))
    if nind != len(individuals):
        raise AadrError(
            f"o cabeçalho declara {nind} indivíduos e o arquivo .ind lista {len(individuals)}; "
            "os dois têm de descrever a mesma coorte ou cada linha lida é de outra pessoa"
        )
    if nsnp != len(snps):
        raise AadrError(
            f"o cabeçalho declara {nsnp} SNPs e o arquivo .snp lista {len(snps)}; "
            "sem essa igualdade cada genótipo lido pertence a outro marcador"
        )
    header_bytes, row_length = resolve_layout(nind, nsnp, _content_length(url))

    wanted = select(annotation)
    if not wanted:
        raise AadrError(
            "nenhum indivíduo selecionado. Um painel de referência vazio não é um painel "
            "menor, é um painel que nomeia populações e não as contém."
        )

    per_population: dict[str, int] = defaultdict(int)
    samples: list[dict[str, Any]] = []
    genotypes: list[bytes] = []
    for index, (gid, _sex, group) in enumerate(individuals):
        panel_group = wanted.get(gid)
        if panel_group is None:
            continue
        if limit_per_population is not None and per_population[group] >= limit_per_population:
            continue
        per_population[group] += 1
        start = header_bytes + row_length * index
        raw = _get(url, byte_range=(start, start + row_length - 1))
        if len(raw) != row_length:
            raise AadrError(
                f"{gid}: lidos {len(raw)} bytes de {row_length}; uma linha truncada desloca "
                "todos os genótipos seguintes"
            )
        calls = unpack_row(raw, nsnp)
        called = sum(1 for value in calls if value != MISSING)
        if called == 0:
            raise AadrError(
                f"{gid}: nenhuma chamada em {nsnp} marcadores. Um indivíduo inteiramente "
                "ausente entraria no centróide como um vetor de zeros e o puxaria para a "
                "origem — o deslocamento é silencioso e parece estrutura populacional."
            )
        samples.append(
            {
                "id": gid,
                "population": group,
                "panel_group": panel_group,
                "country": annotation[gid]["country"],
                "call_rate": called / nsnp if nsnp else 0.0,
            }
        )
        # Stored as the raw packed row, not as one byte per marker: the unpacked form is
        # four times larger and every consumer has to unpack anyway.
        genotypes.append(raw)
        print(
            f"  {gid:<28} {group:<16} {panel_group:<22} chamadas {called/nsnp:6.1%}",
            flush=True,
        )

    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": "genoma-aadr-genotypes-v1",
        "fetched_at": generated,
        "source": {
            "dataset": "Allen Ancient DNA Resource, Human Origins present-day genotypes",
            "doi": DATAVERSE_DOI,
            "license": "CC0 1.0",
            "citation": AADR_CITATION,
            "geno_file_id": geno_file_id,
            "access": "requisições HTTP Range sobre o arquivo packedancestrymap transposto",
        },
        "assembly": "GRCh37",
        "layout": {
            "format": "TGENO",
            "individuals": nind,
            "snps": nsnp,
            "row_bytes": row_length,
            "header_bytes": header_bytes,
            "file_bytes": _content_length(url),
            "basis": (
                "cabeçalho e comprimento de linha derivados do tamanho real do arquivo, não "
                "da convenção do formato: este arquivo usa cabeçalho de 48 bytes onde o "
                "packedancestrymap documenta preenchimento até uma linha inteira, e ler pela "
                "convenção desloca cada leitura em quase uma linha"
            ),
        },
        "selection": {
            "present_day_only": True,
            "human_origins_only": True,
            "excluded_suffixes": list(EXCLUDED_SUFFIXES),
            "groups": {k: list(v) for k, v in GROUPS.items()},
            "orientation_controls": {k: list(v) for k, v in ORIENTATION_CONTROLS.items()},
        },
        "allele_encoding": (
            "Dois bits por genótipo contam cópias de um dos dois alelos do arquivo .snp; qual "
            "deles é convenção e não é assumida aqui. A orientação é resolvida em "
            "scripts/build_ancestry_panel.py contra as frequências do 1000 Genomes nos "
            "marcadores em comum, onde uma inversão aparece como correlação fortemente "
            f"negativa. O valor {MISSING} é ausência de chamada."
        ),
        "populations": {
            population: count for population, count in sorted(per_population.items())
        },
        "samples": samples,
        "snps": snps,
        "genotypes_packed": [base64.b64encode(row).decode("ascii") for row in genotypes],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ind", required=True, help="v66.p1_HO.aadr.patch.PUB.ind")
    parser.add_argument("--anno", required=True, help="v66.p1_HO.aadr.PUB.anno")
    parser.add_argument("--snp", required=True, help="v66.p1_HO.aadr.patch.PUB.snp")
    parser.add_argument(
        "--geno-file-id",
        default="13994808",
        help="Dataverse file id of v66.p1_HO.aadr.patch.PUB.geno",
    )
    parser.add_argument("--limit-per-population", type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = fetch(
        ind_path=Path(args.ind),
        anno_path=Path(args.anno),
        snp_path=Path(args.snp),
        geno_file_id=args.geno_file_id,
        limit_per_population=args.limit_per_population,
    )
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False)
    if out.suffix == ".gz":
        out.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
    else:
        out.write_text(text, encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(out),
                "bytes": out.stat().st_size,
                "samples": len(payload["samples"]),
                "populations": payload["populations"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
