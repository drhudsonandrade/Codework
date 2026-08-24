"""Chromosome lengths for the two supported builds, held in one place.

A coordinate past the end of its own chromosome is not a borderline value: under the
declared build there is no such base. It means the file is annotated on an assembly nobody
told this pipeline about, or the coordinate column is corrupt — and every downstream join
keyed on position is then joining on nothing.

`homozygosity` already refused on exactly this, using its own private copy of the table.
Array QC did not check at all, so a file where 47% of markers sat beyond their chromosome
passed all five gates and only fell over later, in one analysis, while the clinical join and
the completeness matrix consumed the same coordinates without comment. Two copies of a fact
also drift; this module is the single copy both read.

Lengths are the GRCh37 (hg19) and GRCh38 primary-assembly totals. M and MT are accepted
aliases for the rCRS at 16,569 bases in both.
"""
from __future__ import annotations

GRCH37: dict[str, int] = {
    "1": 249_250_621, "2": 243_199_373, "3": 198_022_430, "4": 191_154_276,
    "5": 180_915_260, "6": 171_115_067, "7": 159_138_663, "8": 146_364_022,
    "9": 141_213_431, "10": 135_534_747, "11": 135_006_516, "12": 133_851_895,
    "13": 115_169_878, "14": 107_349_540, "15": 102_531_392, "16": 90_354_753,
    "17": 81_195_210, "18": 78_077_248, "19": 59_128_983, "20": 63_025_520,
    "21": 48_129_895, "22": 51_304_566,
    "X": 155_270_560, "Y": 59_373_566, "MT": 16_569, "M": 16_569,
}

GRCH38: dict[str, int] = {
    "1": 248_956_422, "2": 242_193_529, "3": 198_295_559, "4": 190_214_555,
    "5": 181_538_259, "6": 170_805_979, "7": 159_345_973, "8": 145_138_636,
    "9": 138_394_717, "10": 133_797_422, "11": 135_086_622, "12": 133_275_309,
    "13": 114_364_328, "14": 107_043_718, "15": 101_991_189, "16": 90_338_345,
    "17": 83_257_441, "18": 80_373_285, "19": 58_617_616, "20": 64_444_167,
    "21": 46_709_983, "22": 50_818_468,
    "X": 156_040_895, "Y": 57_227_415, "MT": 16_569, "M": 16_569,
}

CHROMOSOME_LENGTHS: dict[str, dict[str, int]] = {"GRCh37": GRCH37, "GRCh38": GRCH38}

AUTOSOMES = tuple(str(i) for i in range(1, 23))

# Used when the build was never verified. A position beyond the longer of the two builds is
# impossible under either, so this is the only bound that can be asserted without knowing
# which assembly the file is on. It is deliberately the lenient choice: an unverified build
# should not manufacture violations, only report the ones that hold regardless.
EITHER_BUILD = {
    chromosome: max(GRCH37[chromosome], GRCH38[chromosome]) for chromosome in GRCH37
}


def lengths_for(build: str | None) -> tuple[dict[str, int], str]:
    """Return the length table to check against, plus the basis for saying so."""
    table = CHROMOSOME_LENGTHS.get(str(build or "").strip())
    if table is None:
        return EITHER_BUILD, "maior comprimento entre GRCh37 e GRCh38 (build não verificado)"
    return table, str(build).strip()


def is_beyond_end(chromosome: str, position: int, lengths: dict[str, int]) -> bool:
    """True when the position cannot exist on that chromosome under `lengths`.

    An unknown contig is not judged here: `ALLOWED_CHROMS` in QC decides which names are
    acceptable, and answering "beyond the end" for a chromosome with no declared end would
    be an assertion with nothing behind it.
    """
    limit = lengths.get(chromosome)
    return limit is not None and position > limit


# `homozygosity` measures tract lengths in kilobases and divides by the autosomal total, so
# it reads the same numbers in its own unit rather than keeping a second table. Rounding up
# keeps the guard from flagging a marker that sits in the final partial kilobase.
AUTOSOME_KB_BY_CHROMOSOME: dict[str, int] = {
    chromosome: -(-GRCH37[chromosome] // 1000) for chromosome in AUTOSOMES
}

AUTOSOME_TOTAL_KB: float = float(sum(AUTOSOME_KB_BY_CHROMOSOME.values()))


#: Ceilings for decompressing a curated registry or panel. The QC gate applies the same two
#: to an array export inside a ZIP; the registry loaders applied neither, so a path handed to
#: `--targets` or `--panel` was expanded with no bound at all. The shipped files decompress at
#: 5x to 17x and reach 168 MB, so these admit them with room while refusing a bomb, which
#: reaches a thousandfold and beyond.
MAX_REGISTRY_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_REGISTRY_COMPRESSION_RATIO = 200.0


def bounded_gunzip(raw: bytes, *, name: str) -> bytes:
    """Decompress a gzip payload, refusing one that expands beyond the declared ceilings.

    Decompression is incremental so the refusal happens while expanding rather than after: a
    ratio check on the finished output has already spent the memory it was meant to protect.
    """
    import zlib

    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    chunks: list[bytes] = []
    produced = 0
    view = memoryview(raw)
    step = 1 << 20
    for start in range(0, len(view), step):
        chunk = decompressor.decompress(bytes(view[start : start + step]), step * 64)
        while True:
            produced += len(chunk)
            if produced > MAX_REGISTRY_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"{name}: gzip payload expands past "
                    f"{MAX_REGISTRY_UNCOMPRESSED_BYTES:,} bytes and was refused before "
                    "the rest was read"
                )
            chunks.append(chunk)
            if not decompressor.unconsumed_tail:
                break
            chunk = decompressor.decompress(decompressor.unconsumed_tail, step * 64)
    chunks.append(decompressor.flush())
    produced += len(chunks[-1])
    if not decompressor.eof:
        raise ValueError(f"{name}: gzip payload is truncated or incomplete")
    if decompressor.unused_data:
        raise ValueError(f"{name}: gzip payload contains trailing data or multiple members")
    if raw and produced / len(raw) > MAX_REGISTRY_COMPRESSION_RATIO:
        raise ValueError(
            f"{name}: gzip payload expands {produced / len(raw):.0f}x, above the "
            f"{MAX_REGISTRY_COMPRESSION_RATIO:.0f}x ceiling for a curated registry"
        )
    return b"".join(chunks)
