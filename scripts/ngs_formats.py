#!/usr/bin/env python3
"""Read the NGS container formats well enough to refuse a file that is not one.

The WGS input gate checked BAM and CRAM by asking `is_file()` and `size > 0`, then recorded a
SHA-256. A 32-byte text file renamed `fake.bam` passed with `status: VERIFICADO`, no errors,
and a digest beside it — the gate certified as a verified alignment input a file containing
one line of prose. Verified by doing it. `count_vcf_records` had the same shape: it counted
every line not starting with `#`, so three lines of prose in a file named `.vcf` came back as
"3 variant records".

Both are the recurring defect of this project in a new place: a gate trusting a self-declared
field — here the filename extension — instead of reading the thing.

So these probes read the actual bytes. They are deliberately pure Python: a gate must not
depend on the toolchain it is gating, and this one runs in the same minimal environment as
`validate_repo.py`, before any conda environment or container exists. They are not a
replacement for `samtools quickcheck` on a full file; they establish that the container is
what it claims to be, which is the question the gate was failing to ask at all.

Format is decided by **content**, never by extension — `.vcf` holding gzip, or `.bam` holding
SAM text, is exactly the confusion the extension check could not see.
"""
from __future__ import annotations

import gzip
import struct
import zlib
from pathlib import Path
from typing import Any, BinaryIO, TextIO

GZIP_MAGIC = b"\x1f\x8b"
BAM_MAGIC = b"BAM\x01"
CRAM_MAGIC = b"CRAM"
SAM_HEADER_PREFIX = b"@HD\t"

#: The BGZF extra subfield: SI1='B', SI2='C', SLEN=2, then the block size minus one. A BAM
#: that is plain gzip rather than BGZF decompresses fine and cannot be indexed or sliced, so
#: the framing is checked separately from the header.
BGZF_SUBFIELD_ID = (66, 67)

#: Ceilings on what a probe will decompress or walk. Without them a crafted header claiming
#: four billion references, or a gzip bomb, turns a validation step into the denial of
#: service it exists to prevent. Chosen well above any real genome: GRCh38 with alt contigs
#: has ~3.4k references and a header text in the low megabytes.
MAX_HEADER_BYTES = 64 * 1024 * 1024
MAX_REFERENCES = 1_000_000
MAX_VCF_HEADER_LINES = 100_000


class FormatError(Exception):
    """The file is not the format it is being read as, and the message says how it differs."""


def _read_prefix(path: Path, count: int = 64) -> bytes:
    with Path(path).open("rb") as handle:
        return handle.read(count)


def detect_container(path: Path) -> str:
    """Name the container from its magic bytes: BAM, CRAM, SAM, GZIP, VCF or UNKNOWN.

    Returned rather than raised because the callers want to say *what* they found when they
    refuse — "this is a SAM" is a far more useful refusal than "not a BAM".
    """
    prefix = _read_prefix(path)
    if not prefix:
        return "EMPTY"
    if prefix.startswith(CRAM_MAGIC):
        return "CRAM"
    if prefix.startswith(GZIP_MAGIC):
        # A BAM is BGZF, which is gzip; only decompressing tells the two apart.
        try:
            with gzip.open(path, "rb") as handle:
                head = handle.read(16)
        except (OSError, EOFError, zlib.error):
            return "GZIP"
        if head.startswith(BAM_MAGIC):
            return "BAM"
        if head.startswith(b"##fileformat=VCF"):
            return "VCF"
        return "GZIP"
    if prefix.startswith(BAM_MAGIC):
        # Uncompressed BAM: legal, and unusable as an indexed alignment.
        return "BAM_UNCOMPRESSED"
    if prefix.startswith(b"##fileformat=VCF"):
        return "VCF"
    if prefix.startswith(SAM_HEADER_PREFIX) or prefix.startswith(b"@SQ\t") or prefix.startswith(b"@RG\t"):
        return "SAM"
    return "UNKNOWN"


# ---------------------------------------------------------------------------------
# BGZF / BAM
# ---------------------------------------------------------------------------------


def _bgzf_first_block_size(handle: BinaryIO) -> int:
    """The size of the first BGZF block, or raise if the file is not BGZF-framed."""
    handle.seek(0)
    header = handle.read(12)
    if len(header) < 12 or header[:2] != GZIP_MAGIC or header[2] != 8:
        raise FormatError("não é um fluxo gzip; BAM é BGZF, que é gzip com campo extra BC")
    if not header[3] & 0x04:
        raise FormatError("gzip sem campo FEXTRA; um BAM real é BGZF e sempre o traz")
    extra_length = struct.unpack("<H", header[10:12])[0]
    extra = handle.read(extra_length)
    if len(extra) != extra_length:
        raise FormatError("cabeçalho gzip truncado no campo extra")
    offset = 0
    while offset + 4 <= extra_length:
        si1, si2, slen = struct.unpack_from("<BBH", extra, offset)
        if (si1, si2) == BGZF_SUBFIELD_ID:
            if slen != 2:
                raise FormatError(f"subcampo BGZF BC com tamanho {slen}, esperado 2")
            return struct.unpack_from("<H", extra, offset + 4)[0] + 1
        offset += 4 + slen
    raise FormatError(
        "gzip sem o subcampo BGZF 'BC': o arquivo descomprime, mas não é BGZF e não pode ser "
        "indexado nem fatiado por região"
    )


def _bounded_decompress(path: Path, limit: int) -> bytes:
    """Decompress at most `limit` bytes, refusing a payload that wants more."""
    produced = bytearray()
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            while chunk:
                produced.extend(decompressor.decompress(chunk, limit - len(produced)))
                if len(produced) >= limit:
                    raise FormatError(
                        f"cabeçalho excede {limit} bytes descomprimidos; recusado em vez de "
                        "carregado"
                    )
                chunk = decompressor.unconsumed_tail
                if decompressor.eof:
                    return bytes(produced)
    return bytes(produced)


def probe_bam(path: Path) -> dict[str, Any]:
    """Parse a BAM header: BGZF framing, magic, SAM text and the reference list.

    Returns what was actually read — reference count, read groups, the sort order the header
    declares — so a caller can compare it against what the manifest claims rather than take
    the manifest's word.
    """
    path = Path(path)
    with path.open("rb") as handle:
        block_size = _bgzf_first_block_size(handle)
    payload = _bounded_decompress(path, MAX_HEADER_BYTES)
    if not payload.startswith(BAM_MAGIC):
        raise FormatError(f"bytes iniciais {payload[:4]!r} não são o magic BAM {BAM_MAGIC!r}")
    if len(payload) < 8:
        raise FormatError("BAM truncado antes do comprimento do cabeçalho")
    (text_length,) = struct.unpack_from("<i", payload, 4)
    if text_length < 0 or 8 + text_length > len(payload):
        raise FormatError(f"l_text={text_length} inconsistente com o tamanho do cabeçalho lido")
    header_text = payload[8 : 8 + text_length].decode("utf-8", errors="replace")
    offset = 8 + text_length
    references: list[dict[str, Any]] = []
    reference_count = None
    if offset + 4 <= len(payload):
        (reference_count,) = struct.unpack_from("<i", payload, offset)
        if reference_count < 0 or reference_count > MAX_REFERENCES:
            raise FormatError(f"n_ref={reference_count} fora de qualquer faixa plausível")
        offset += 4
        for _ in range(min(reference_count, 8)):  # a sample is enough to prove the structure
            if offset + 4 > len(payload):
                break
            (name_length,) = struct.unpack_from("<i", payload, offset)
            offset += 4
            if name_length < 0 or offset + name_length + 4 > len(payload):
                break
            name = payload[offset : offset + name_length - 1].decode("ascii", errors="replace")
            offset += name_length
            (length,) = struct.unpack_from("<i", payload, offset)
            offset += 4
            references.append({"name": name, "length": length})

    read_groups = []
    sort_order = None
    for line in header_text.splitlines():
        if line.startswith("@RG\t"):
            fields = dict(
                part.split(":", 1) for part in line.split("\t")[1:] if ":" in part
            )
            read_groups.append({"id": fields.get("ID"), "sample": fields.get("SM"), "platform": fields.get("PL")})
        elif line.startswith("@HD\t"):
            for part in line.split("\t")[1:]:
                if part.startswith("SO:"):
                    sort_order = part[3:]
    return {
        "format": "BAM",
        "bgzf": True,
        "first_block_bytes": block_size,
        "header_text_bytes": text_length,
        "reference_count": reference_count,
        "references_sampled": references,
        "read_groups": read_groups,
        "sort_order": sort_order,
    }


def probe_cram(path: Path) -> dict[str, Any]:
    """Read the CRAM file definition: magic, version and file id."""
    prefix = _read_prefix(Path(path), 26)
    if not prefix.startswith(CRAM_MAGIC):
        raise FormatError(f"bytes iniciais {prefix[:4]!r} não são o magic CRAM")
    if len(prefix) < 6:
        raise FormatError("CRAM truncado antes dos bytes de versão")
    major, minor = prefix[4], prefix[5]
    if major not in (2, 3, 4):
        raise FormatError(f"versão CRAM {major}.{minor} não reconhecida")
    file_id = prefix[6:26].split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return {"format": "CRAM", "version": f"{major}.{minor}", "file_id": file_id}


def probe_alignment(path: Path) -> dict[str, Any]:
    """Probe an alignment by content, refusing anything that is not BAM or CRAM."""
    container = detect_container(Path(path))
    if container == "BAM":
        return probe_bam(path)
    if container == "CRAM":
        return probe_cram(path)
    if container == "BAM_UNCOMPRESSED":
        raise FormatError(
            "BAM sem compressão BGZF: descomprime, mas não pode ser indexado nem fatiado por "
            "região; recomprimir com bgzip"
        )
    if container == "SAM":
        raise FormatError("o arquivo é SAM (texto); converter para BAM antes de submeter")
    if container == "VCF":
        raise FormatError("o arquivo é um VCF, não um alinhamento")
    if container == "EMPTY":
        raise FormatError("arquivo vazio")
    raise FormatError(
        f"conteúdo não reconhecido como BAM nem CRAM (detectado: {container}); a extensão do "
        "arquivo não é evidência do seu formato"
    )


# ---------------------------------------------------------------------------------
# VCF
# ---------------------------------------------------------------------------------

#: The eight columns every VCF must carry, in this order, on the #CHROM line.
VCF_FIXED_COLUMNS = ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")


def open_vcf_text(path: Path) -> TextIO:
    """Open a VCF as text, choosing the decompressor by magic bytes rather than by suffix.

    `path.suffix == ".gz"` was the test in three places. A VCF named `.vcf` that is in fact
    bgzipped — the usual result of a careless copy — was read as though the compressed bytes
    were its content, and every line failed to parse as a record, silently, yielding zero
    variants.
    """
    path = Path(path)
    if _read_prefix(path, 2) == GZIP_MAGIC:
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("r", encoding="utf-8", errors="strict")


def probe_vcf(path: Path, *, count_records: bool = True) -> dict[str, Any]:
    """Validate a VCF's header and structure, and count its records.

    The record count is the whole reason this exists: counting lines that do not start with
    `#` calls any text file a variant set. A line is counted here only when it has the eight
    mandatory columns and an integer position.
    """
    path = Path(path)
    compression = "bgzf/gzip" if _read_prefix(path, 2) == GZIP_MAGIC else "plain"
    version = None
    samples: list[str] = []
    header_seen = False
    records = 0
    malformed: list[str] = []
    contigs: set[str] = set()

    try:
        with open_vcf_text(path) as handle:
            for index, line in enumerate(handle):
                line = line.rstrip("\n").rstrip("\r")
                if index == 0:
                    if not line.startswith("##fileformat=VCF"):
                        raise FormatError(
                            "a primeira linha não é `##fileformat=VCF`; um VCF a exige, e sem "
                            "ela o arquivo é texto qualquer"
                        )
                    version = line.split("=", 1)[1]
                    continue
                if line.startswith("##"):
                    if index > MAX_VCF_HEADER_LINES:
                        raise FormatError(f"cabeçalho com mais de {MAX_VCF_HEADER_LINES} linhas")
                    continue
                if line.startswith("#CHROM"):
                    columns = line.split("\t")
                    if tuple(columns[:8]) != VCF_FIXED_COLUMNS:
                        raise FormatError(
                            f"linha #CHROM com colunas {columns[:8]}, esperadas "
                            f"{list(VCF_FIXED_COLUMNS)}"
                        )
                    samples = columns[9:] if len(columns) > 9 else []
                    header_seen = True
                    continue
                if not header_seen:
                    raise FormatError("registro de dados antes da linha #CHROM")
                if not count_records:
                    break
                fields = line.split("\t")
                if len(fields) < 8:
                    malformed.append(f"linha {index + 1}: {len(fields)} colunas, mínimo 8")
                    continue
                try:
                    int(fields[1])
                except ValueError:
                    malformed.append(f"linha {index + 1}: POS {fields[1]!r} não é inteiro")
                    continue
                contigs.add(fields[0])
                records += 1
    except UnicodeDecodeError as exc:
        raise FormatError(
            f"não é UTF-8 válido ({exc}); uma contagem lida sobre bytes substituídos "
            "descreveria um arquivo que não existe"
        ) from exc
    except (OSError, EOFError, zlib.error) as exc:
        raise FormatError(f"falha ao ler o fluxo comprimido: {type(exc).__name__}: {exc}") from exc

    if not header_seen:
        raise FormatError("VCF sem linha #CHROM; não há como saber onde começam os registros")
    if malformed:
        raise FormatError(
            f"{len(malformed)} registros malformados, os primeiros: {malformed[:3]}"
        )
    return {
        "format": "VCF",
        "version": version,
        "compression": compression,
        "sample_count": len(samples),
        "samples": samples[:8],
        "record_count": records,
        "distinct_contigs": len(contigs),
    }


# ---------------------------------------------------------------------------------
# FASTQ
# ---------------------------------------------------------------------------------


def probe_fastq(path: Path, *, records: int = 128) -> dict[str, Any]:
    """Structurally probe the first `records` FASTQ records.

    Moved here from the gate unchanged in what it verifies, except that the decompressor is
    now chosen by magic bytes rather than by suffix, for the same reason as the VCF reader.
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise FormatError("ausente ou vazio")
    opener = (
        (lambda p: gzip.open(p, "rt", encoding="utf-8", errors="strict"))
        if _read_prefix(path, 2) == GZIP_MAGIC
        else (lambda p: p.open("r", encoding="utf-8", errors="strict"))
    )
    try:
        with opener(path) as handle:
            seen = 0
            for _ in range(records):
                row = [handle.readline() for __ in range(4)]
                if row[0] == "":
                    break
                if any(part == "" for part in row):
                    raise FormatError(f"registro {seen + 1} truncado")
                if not row[0].startswith("@"):
                    raise FormatError(f"registro {seen + 1}: cabeçalho não começa com '@'")
                if not row[2].startswith("+"):
                    raise FormatError(f"registro {seen + 1}: terceira linha não começa com '+'")
                if len(row[1].strip()) != len(row[3].strip()):
                    raise FormatError(
                        f"registro {seen + 1}: sequência e qualidade têm comprimentos diferentes"
                    )
                seen += 1
    except UnicodeDecodeError as exc:
        raise FormatError(f"não é UTF-8 válido ({exc})") from exc
    except (OSError, EOFError, zlib.error) as exc:
        raise FormatError(f"falha de leitura: {type(exc).__name__}: {exc}") from exc
    if not seen:
        raise FormatError("nenhum registro")
    return {
        "format": "FASTQ",
        "compression": "gzip" if _read_prefix(path, 2) == GZIP_MAGIC else "plain",
        "probe_records": seen,
    }
