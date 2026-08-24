from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import normative
from array_pipeline import assembly

RULESET = normative.ruleset_block()

HARMONIZED_COLUMNS = [
    "RSID", "CHROMOSOME", "POSITION", "CONSENSUS_RESULT", "STATUS",
    "GENERA_RESULT", "MYHERITAGE_RESULT", "SOURCES",
]
RAW_COLUMNS = ["RSID", "CHROMOSOME", "POSITION", "RESULT"]
#: The table `scripts/vcf_projection.py` writes from a WGS VCF. It is deliberately not
#: `RAW_COLUMNS`: those four columns would make this QC name the schema
#: `raw_snp_array_v1`, and every report prints the method — calling a WGS-derived
#: genotype a SNP-array reading is a false statement about how it was obtained. The three
#: extra columns are what an array never had: the per-call depth and genotype quality
#: section 119 asks for, and the basis of each call or refusal.
VCF_PROJECTION_COLUMNS = [
    "RSID", "CHROMOSOME", "POSITION", "RESULT", "DEPTH", "GENOTYPE_QUALITY", "CALL_BASIS",
]
ALLOWED_CHROMS = {str(i) for i in range(1, 23)} | {"X", "Y", "MT", "M"}
MISSING_GENOTYPES = {"", "--", "NA", "N/A", "NULL", "."}

#: The strand every registry in this project is expressed on. A file reported on the other
#: strand is not merely unverified: every allele comparison made against it is inverted.
FORWARD_STRANDS = frozenset({"forward", "plus", "+"})
COMPLEMENT = {"A": "T", "T": "A", "C": "G", "G": "C"}
#: Markers that must agree before the file's own content is allowed to contradict a declared
#: strand. One marker is a coincidence; this is the same threshold the probe uses.
MIN_STRAND_CONTRADICTION_MARKERS = 3
#: Spellings of the determinate opposite. These are the *knowledge* that a file is flipped,
#: which is never permission to interpret it as though it were not.
REVERSE_STRANDS = frozenset({"reverse", "minus", "-"})
DIPLOID_SNP = re.compile(r"^[ACGT]{2}$")
HAPLOID_SNP = re.compile(r"^[ACGT]$")
INDEL = re.compile(r"^(?:II|DD|ID|DI)$")

# Harmonized records whose cross-platform overlap was never resolved. Ruleset section 4
# requires conflicts to stay recorded and never be arbitrarily resolved, and section 7
# forbids assuming either platform is correct, so these loci must never be presented as
# consensus. They are excluded from interpretation rather than blocking the whole array.
#
# `genera_ambiguous_duplicate` was added after a real harmonized export was found to emit
# it 261 times: the same rsid appearing twice in one vendor's file with different values
# (`II|DD`). It is an unresolved ambiguity exactly like the others.
UNRESOLVED_OVERLAP_STATUSES = frozenset({
    "coordinate_conflict",
    "ambiguous_overlap",
    "genotype_conflict",
    "genera_ambiguous_duplicate",
})

# Statuses under which a harmonized record may be interpreted. This is an allowlist, not
# the complement of the denylist above, because a denylist fails *open*: a harmonizer
# emitting a status neither list anticipated would have been treated as clean. Real data
# proved that risk is not theoretical — this file carries ten distinct STATUS values, and
# one of them was unknown to this module.
INTERPRETABLE_OVERLAP_STATUSES = frozenset({
    "consensus",
    "genera_only",
    "myheritage_only",
    "genera_only_call",
    "myheritage_only_call",
    "observed",
    "",
})

BASELINE_RSIDS = [
    "rs1799807", "rs1803274", "rs17580", "rs28929474", "rs738409",
    "rs1799853", "rs1057910", "rs9923231", "rs4149056", "rs776746",
    "rs1799930", "rs4307059", "rs429358", "rs7412",
]


#: The pinned, verified two-assembly marker table. Loaded lazily so this module keeps no
#: import-time dependency on `provenance_probe`, which imports from here.
STRAND_MARKERS_PATH = Path(__file__).resolve().parents[1] / "config/array_provenance_markers.json"


def _strand_marker_alleles() -> dict[str, set[str]]:
    """rsid → plus-strand allele set, for the non-palindromic markers only.

    Returns an empty mapping when the table is unreadable: the check this feeds can only
    ever *contradict* a declared strand, so having no table means having no contradiction,
    never a licence. Palindromic markers are excluded because they read identically on both
    strands and would vote for whatever they were asked.
    """
    try:
        payload = json.loads(STRAND_MARKERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, set[str]] = {}
    for marker in payload.get("markers") or []:
        if not isinstance(marker, dict) or marker.get("palindromic"):
            continue
        alleles = marker.get("plus_alleles")
        rsid = str(marker.get("rsid") or "").strip().lower()
        if rsid and isinstance(alleles, list) and len(alleles) == 2:
            out[rsid] = {str(a).strip().upper() for a in alleles}
    return out


@dataclass(frozen=True)
class SourceInfo:
    kind: str
    member_name: str | None
    metadata: dict[str, str]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


#: Largest uncompressed size a member of an input ZIP may declare. A 700k-marker consumer
#: array is about 30 MB of text; this leaves two orders of magnitude of room and still bounds
#: what a declared size can ask the runner to read.
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024

#: Largest compression ratio a member may declare. Measured genotype CSVs run about 5:1, so
#: this is twenty times the real figure; a zip bomb runs three orders of magnitude higher.
#: The member count was checked before this and the sizes were not, so one member declaring
#: fifty gigabytes passed as "exactly one data file".
MAX_COMPRESSION_RATIO = 100.0


def _check_zip_member(member: zipfile.ZipInfo) -> None:
    """Refuse a member whose declared sizes are outside what a genotype export can be.

    Checked before `open`, because the point is not to discover the problem while the
    decompressor is already writing it into memory.
    """
    if member.file_size > MAX_UNCOMPRESSED_BYTES:
        raise ValueError(
            f"ZIP member {member.filename!r} declares {member.file_size:,} uncompressed bytes, "
            f"above the {MAX_UNCOMPRESSED_BYTES:,}-byte ceiling for an array export"
        )
    if member.compress_size > 0:
        ratio = member.file_size / member.compress_size
        if ratio > MAX_COMPRESSION_RATIO:
            raise ValueError(
                f"ZIP member {member.filename!r} declares a {ratio:,.0f}:1 compression ratio, "
                f"above the {MAX_COMPRESSION_RATIO:,.0f}:1 ceiling; measured genotype exports "
                "run about 5:1 and this shape is a decompression bomb"
            )


class _ZipBackedTextStream(io.TextIOWrapper):
    """A ZIP member stream that releases its archive when the caller closes it.

    `zf.open()` keeps the whole `ZipFile` alive behind the member stream, so closing only
    the text wrapper leaks the archive's file descriptor. Binding the archive to the
    stream means one `close()` from the caller releases both, in the right order.
    """

    def __init__(self, raw, archive: zipfile.ZipFile, **kwargs: Any) -> None:
        super().__init__(raw, **kwargs)
        self._genoma_zipfile = archive

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._genoma_zipfile.close()


def _text_stream(path: Path) -> tuple[TextIO, SourceInfo]:
    """Open plain/gzip/zip CSV text. ZIP must contain exactly one regular data file.

    Decoding is strict. With `errors="replace"` an undecodable byte became U+FFFD and was
    parsed as data: a mangled rsid or chromosome still joined, just against the wrong key,
    and nothing anywhere reported that the file had not been read as written. A caller
    cannot tell a repaired file from an intact one, so the repair is not offered — the
    refusal names the file and the byte instead.
    """
    lower = path.name.lower()
    if lower.endswith(".gz"):
        fh = gzip.open(path, "rt", encoding="utf-8-sig", errors="strict", newline="")
        return fh, SourceInfo("gzip", None, {})
    if lower.endswith(".zip"):
        zf = zipfile.ZipFile(path)
        members = [x for x in zf.infolist() if not x.is_dir()]
        if len(members) != 1:
            zf.close()
            raise ValueError(f"ZIP must contain exactly one data file; found {len(members)}")
        try:
            _check_zip_member(members[0])
        except ValueError:
            zf.close()
            raise
        raw = zf.open(members[0], "r")
        try:
            text = _ZipBackedTextStream(
                raw,
                zf,
                encoding="utf-8-sig",
                errors="strict",
                newline="",
            )
        except Exception:
            raw.close()
            zf.close()
            raise
        return text, SourceInfo("zip", members[0].filename, {})
    return path.open("rt", encoding="utf-8-sig", errors="strict", newline=""), SourceInfo("plain", None, {})


def _read_header_and_metadata(fh: TextIO) -> tuple[list[str], dict[str, str]]:
    metadata: dict[str, str] = {}
    while True:
        line = fh.readline()
        if line == "":
            raise ValueError("empty data file")
        stripped = line.rstrip("\r\n")
        if stripped.startswith("##") and "=" in stripped[2:]:
            k, v = stripped[2:].split("=", 1)
            metadata[k.strip().lower()] = v.strip()
            continue
        if stripped.startswith("#"):
            lower = stripped.lower()
            if "forward (+) strand" in lower or "forward strand" in lower:
                metadata["strand"] = "forward"
                metadata["strand_evidence"] = stripped.lstrip("#").strip()
            continue
        if stripped.strip() == "":
            continue
        header = [x.strip().upper() for x in next(csv.reader([stripped]))]
        return header, metadata


def detect_schema(header: list[str]) -> str:
    """Name the genotype table's schema from its header, or refuse it.

    Four modules carried their own copy of this three-branch check — qc, annotation,
    completeness and the provenance probe. A schema added to one and forgotten in another is
    the kind of drift that ends with a file accepted by the gate and unreadable by the
    matrix, so the branches live here once and the four call it.
    """
    if header == HARMONIZED_COLUMNS:
        return "harmonized_genera_myheritage_v1"
    if header == RAW_COLUMNS:
        return "raw_snp_array_v1"
    if header == VCF_PROJECTION_COLUMNS:
        return "wgs_vcf_projection_v1"
    raise ValueError(f"unsupported genotype table header: {header}")


def _is_called(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().upper() not in MISSING_GENOTYPES


def _is_valid_consensus(value: str | None) -> bool:
    if not _is_called(value):
        return False
    v = value.strip().upper()
    return bool(DIPLOID_SNP.fullmatch(v) or HAPLOID_SNP.fullmatch(v) or INDEL.fullmatch(v))


def _canonical_gt(value: str | None) -> str | None:
    if not _is_called(value):
        return None
    v = value.strip().upper()
    if DIPLOID_SNP.fullmatch(v):
        return "".join(sorted(v))
    if v in {"ID", "DI"}:
        return "DI"
    return v


def _gate(state: str, reasons: list[str], **extra: Any) -> dict[str, Any]:
    return {"state": state, "reasons": reasons, **extra}


def _metadata_attestation(kind: str, text: str, input_sha: str, asserted_value: str) -> str:
    payload = {
        "status": "VERIFICADO",
        "decision": "SATISFIED",
        # Which value this attestation establishes, in machine-readable form. Without it the
        # gate can only check that *an* attestation exists, never that it agrees with the
        # value being declared — see `_verified_provenance`.
        "asserted_value": asserted_value,
        "justification": f"The source file explicitly declares {kind}: {text}",
        "evidence_refs": [f"input-metadata:{kind}"],
        "trace": {
            "attestation_id": f"input-metadata-{kind}-{input_sha[:16]}",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "actor_type": "SOFTWARE",
            "actor_id": "array_pipeline.qc",
            "method": "source-file metadata parsing",
            "run_id": f"input-{input_sha[:16]}",
            "input_sha256": [input_sha],
            "output_sha256": [],
            "tool_versions": {"array_pipeline": "v0.8"},
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _normalised_assertion(kind: str, value: Any) -> str | None:
    """Canonical spelling of a build or strand value, for comparing two of them."""
    text = str(value or "").strip()
    if not text:
        return None
    if kind == "strand":
        lower = text.lower()
        if lower in FORWARD_STRANDS:
            return "forward"
        if lower in REVERSE_STRANDS:
            return "reverse"
        return lower
    return text.upper()


def _verified_provenance(
    value: str | None,
    input_sha: str,
    *,
    kind: str | None = None,
    expected_value: Any = None,
) -> bool:
    """True when the attestation is structurally sound, bound to this file, and says so.

    `kind`/`expected_value` close the hole that made the whole gate ornamental. The
    attestation was checked for shape, status and SHA-256 binding but never for *content*,
    so it could not contradict the value it was supposed to support. The probe in
    `array_pipeline.provenance_probe` will honestly determine that a file is on the reverse
    strand and, before this check existed, that determination — a real VERIFICADO/SATISFIED
    attestation, correctly bound to the input — was accepted as the evidence certifying the
    same file as forward. BUILD_STRAND_GATE passed, `operational_status` came out VERIFICADO,
    and every allele comparison downstream ran inverted: a Factor V Leiden carrier reads
    NÃO DETECTADO, and a palindromic locus can read OBSERVADO in someone who carries nothing.

    An attestation that does not name what it asserts cannot be checked against the declared
    value, so it no longer verifies one. That is fail-closed by design: the missing field is
    not "no disagreement", it is "no way to disagree".
    """
    if not value:
        return False
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("status") != "VERIFICADO" or payload.get("decision") != "SATISFIED":
        return False
    if not isinstance(payload.get("justification"), str) or not payload["justification"].strip():
        return False
    refs = payload.get("evidence_refs")
    if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x.strip() for x in refs):
        return False
    trace = payload.get("trace")
    if not isinstance(trace, dict):
        return False
    for field in ("attestation_id", "created_at", "actor_type", "actor_id", "method", "run_id"):
        if not isinstance(trace.get(field), str) or not trace[field].strip():
            return False
    if trace.get("actor_type") not in {"HUMAN", "SOFTWARE", "SERVICE"}:
        return False
    try:
        datetime.fromisoformat(trace["created_at"].replace("Z", "+00:00"))
    except ValueError:
        return False
    hashes = trace.get("input_sha256")
    if not isinstance(hashes, list) or input_sha.lower() not in {str(x).lower() for x in hashes}:
        return False
    tools = trace.get("tool_versions")
    if not isinstance(tools, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in tools.items()):
        return False
    if kind is not None:
        declared = _normalised_assertion(kind, expected_value)
        asserted = _normalised_assertion(kind, payload.get("asserted_value"))
        if declared is None or asserted is None or declared != asserted:
            return False
    return True


def inspect_array(
    path: Path,
    *,
    case_id: str,
    build: str | None = None,
    strand: str | None = None,
    platform: str | None = None,
    build_evidence: str | None = None,
    strand_evidence: str | None = None,
    min_call_rate: float = 0.95,
    max_overlap_conflict_rate: float = 0.005,
) -> dict[str, Any]:
    """QC a raw or harmonized SNP-array file without pretending it is WGS.

    This gate intentionally owns only array-level structure/callability/provenance and
    direct cross-platform concordance. It does not infer CNV/SV/phase, does not turn
    missing assayed loci into negative clinical evidence, and does not promote a marker
    to a clinical result. Provenance evidence must be a structured VERIFICADO/SATISFIED
    attestation bound to this exact input SHA-256; plain prose never unlocks the gate.
    """
    path = path.resolve()
    input_sha = sha256_file(path)
    input_size = path.stat().st_size

    fh, src = _text_stream(path)
    try:
        header, metadata = _read_header_and_metadata(fh)
        schema = detect_schema(header)

        if build is None:
            ref = metadata.get("reference", "")
            if ref.lower() in {"build37", "grch37", "hg19"}:
                build = "GRCh37"
            elif ref.lower() in {"build38", "grch38", "hg38"}:
                build = "GRCh38"
        if strand is None and metadata.get("strand"):
            strand = metadata.get("strand")
        if build_evidence is None and metadata.get("reference") and build:
            build_evidence = _metadata_attestation(
                "reference_build", metadata.get("reference", ""), input_sha, build
            )
        if strand_evidence is None and metadata.get("strand_evidence"):
            strand_evidence = _metadata_attestation(
                "strand", metadata.get("strand_evidence", ""), input_sha, metadata.get("strand", "")
            )
        if platform is None:
            platform = metadata.get("chip")

        # The declared value is passed in, so an attestation that establishes a different
        # one stops counting as verification of this one.
        build_evidence_verified = _verified_provenance(
            build_evidence, input_sha, kind="reference_build", expected_value=build
        )
        strand_evidence_verified = _verified_provenance(
            strand_evidence, input_sha, kind="strand", expected_value=strand
        )

        reader = csv.DictReader(fh, fieldnames=header)
        total = 0
        unique_rsids: set[str] = set()
        duplicate_rsids = 0
        invalid_positions = 0
        invalid_chromosomes = 0
        # A position past the end of its own chromosome is not a rare value, it is an
        # impossible one, and it means the coordinate column cannot be trusted for the join
        # every downstream report performs. The worst offender is kept so the reason can
        # point at a row instead of only counting them.
        off_assembly_positions = 0
        off_assembly_example: tuple[str, int] | None = None
        assembly_lengths, assembly_basis = assembly.lengths_for(build)
        chromosome_counts: Counter[str] = Counter()
        status_counts: Counter[str] = Counter()
        source_counts: Counter[str] = Counter()
        valid_calls = 0
        invalid_called_genotypes = 0
        autosomal_diploid = 0
        autosomal_het = 0
        g_present = g_calls = m_present = m_calls = 0
        overlap_consensus = overlap_conflict = 0
        marker_hits: dict[str, dict[str, Any]] = {}
        coordinate_seen: set[tuple[str, str]] = set()
        duplicate_coordinate_rows = 0

        # The file's own vote on its orientation. An attestation is a claim; these markers
        # are the data, and the data is allowed to contradict the claim.
        strand_markers = _strand_marker_alleles()
        strand_votes_plus = 0
        strand_votes_minus = 0

        for row in reader:
            total += 1
            rsid = (row.get("RSID") or "").strip()
            chrom = (row.get("CHROMOSOME") or "").strip().upper()
            pos = (row.get("POSITION") or "").strip()
            if rsid in unique_rsids:
                duplicate_rsids += 1
            else:
                unique_rsids.add(rsid)
            try:
                position = int(pos)
                if position <= 0:
                    invalid_positions += 1
                elif assembly.is_beyond_end(chrom, position, assembly_lengths):
                    off_assembly_positions += 1
                    if off_assembly_example is None or position > off_assembly_example[1]:
                        off_assembly_example = (chrom, position)
            except (TypeError, ValueError):
                # Only what `int()` raises on a malformed position. `except Exception` also
                # swallowed anything `is_beyond_end` could throw, so a defect in the assembly
                # bounds check would have been counted as one more invalid coordinate in the
                # patient's file — a real bug reported as bad input, at QC, where the count
                # decides whether the run proceeds.
                invalid_positions += 1
            if chrom not in ALLOWED_CHROMS:
                invalid_chromosomes += 1
            chromosome_counts[chrom] += 1
            coord = (chrom, pos)
            if coord in coordinate_seen:
                duplicate_coordinate_rows += 1
            else:
                coordinate_seen.add(coord)

            if schema.startswith("harmonized"):
                gt = row.get("CONSENSUS_RESULT")
                status = (row.get("STATUS") or "").strip()
                sources = (row.get("SOURCES") or "").strip()
                status_counts[status] += 1
                source_counts[sources] += 1
                if "G" in sources:
                    g_present += 1
                    if _is_called(row.get("GENERA_RESULT")):
                        g_calls += 1
                if "M" in sources:
                    m_present += 1
                    if _is_called(row.get("MYHERITAGE_RESULT")):
                        m_calls += 1
                if status == "consensus":
                    overlap_consensus += 1
                elif status == "genotype_conflict":
                    overlap_conflict += 1
            else:
                gt = row.get("RESULT")

            if _is_valid_consensus(gt):
                valid_calls += 1
            elif _is_called(gt):
                invalid_called_genotypes += 1

            v = (gt or "").strip().upper()
            if chrom in {str(i) for i in range(1, 23)} and DIPLOID_SNP.fullmatch(v):
                autosomal_diploid += 1
                if v[0] != v[1]:
                    autosomal_het += 1

            plus_alleles = strand_markers.get(rsid.lower())
            if plus_alleles and v and set(v) <= set("ACGT"):
                letters = set(v)
                minus_alleles = {COMPLEMENT[a] for a in plus_alleles}
                if letters <= plus_alleles and not letters <= minus_alleles:
                    strand_votes_plus += 1
                elif letters <= minus_alleles and not letters <= plus_alleles:
                    strand_votes_minus += 1

            if rsid in BASELINE_RSIDS:
                reverse_strand = str(strand or "").strip().lower() in REVERSE_STRANDS
                if reverse_strand:
                    # Checked before the source-specific branches, because none of their
                    # arguments survive a known flip. Cross-platform consensus in particular
                    # establishes that the two vendors agree with each other — and when the
                    # file is reverse, what they agree on is the complement.
                    orientation_status = "NÃO DISPONÍVEL"
                    orientation_basis = (
                        f"fita determinada como reversa ({strand}); o alelo relatado é o "
                        "complementar do que os registros esperam"
                    )
                elif schema.startswith("harmonized"):
                    marker_sources = (row.get("SOURCES") or "").strip()
                    if marker_sources == "GM":
                        # Cross-platform agreement proves the two vendors used the SAME
                        # strand convention; it does not prove which one. If both reported
                        # the reverse strand, an AG call would read TC in both files and
                        # they would agree perfectly while both being flipped. Consensus is
                        # therefore mutual consistency (INFERIDO), and only documented
                        # strand provenance can raise it to VERIFICADO.
                        if strand in {"forward", "plus", "+"} and strand_evidence_verified:
                            orientation_status = "VERIFICADO"
                            orientation_basis = "cross-platform consensus with documented forward-strand provenance"
                        else:
                            orientation_status = "INFERIDO"
                            orientation_basis = (
                                "cross-platform consensus establishes mutual consistency between "
                                "vendors, not absolute strand orientation"
                            )
                    elif marker_sources == "M" and strand == "forward" and strand_evidence_verified:
                        orientation_status = "VERIFICADO"
                        orientation_basis = "MyHeritage forward-strand source metadata"
                    elif marker_sources == "G":
                        orientation_status = "INFERIDO"
                        orientation_basis = "Genera-only marker; orientation inferred from harmonization context, not independently verified"
                    else:
                        orientation_status = "NÃO DISPONÍVEL"
                        orientation_basis = "source-specific orientation not independently verified"
                else:
                    orientation_status = "VERIFICADO" if strand in {"forward", "plus", "+"} and strand_evidence_verified else "NÃO DISPONÍVEL"
                    orientation_basis = strand_evidence or "source-specific orientation evidence absent"
                marker_hits[rsid] = {
                    "rsid": rsid,
                    "chromosome": chrom,
                    "position": int(pos) if pos.isdigit() else pos,
                    "genotype": _canonical_gt(gt),
                    "status": row.get("STATUS") if schema.startswith("harmonized") else "observed",
                    "sources": row.get("SOURCES") if schema.startswith("harmonized") else "single_source",
                    "genera_result": _canonical_gt(row.get("GENERA_RESULT")) if schema.startswith("harmonized") else None,
                    "myheritage_result": _canonical_gt(row.get("MYHERITAGE_RESULT")) if schema.startswith("harmonized") else None,
                    "orientation_operational_status": orientation_status,
                    "orientation_basis": orientation_basis,
                }
    except UnicodeDecodeError as exc:
        # Named, with the file and the offending byte, instead of the bare codec error the
        # strict decoder raises. The operator has to know which file to re-export.
        raise ValueError(
            f"{path.name} is not valid UTF-8: byte {exc.object[exc.start:exc.start + 1]!r} at "
            f"position {exc.start}. Genotype rows are read strictly, because a replaced byte "
            "in an rsid or a chromosome still joins — against the wrong key — and nothing "
            "downstream can tell a repaired file from an intact one. Re-export the file or "
            "convert it to UTF-8 before running QC."
        ) from exc
    finally:
        fh.close()

    call_rate = valid_calls / total if total else 0.0
    overlap_denom = overlap_consensus + overlap_conflict
    overlap_concordance = overlap_consensus / overlap_denom if overlap_denom else None
    overlap_conflict_rate = overlap_conflict / overlap_denom if overlap_denom else None
    het_rate = autosomal_het / autosomal_diploid if autosomal_diploid else None

    structure_reasons: list[str] = []
    structure_notes: list[str] = []
    # A subset of `structure_reasons`: the ones that mean this is not a usable array at all,
    # as opposed to a usable array with a defect the per-locus classification absorbs.
    # Duplicate RSID rows are the clear case of the latter — a real harmonized export was
    # found emitting them 261 times, and the completeness matrix resolves them locus by
    # locus rather than arbitrating a winner. Consumers that must refuse read this list, so
    # the severity is a property of the gate instead of something each caller re-derives by
    # matching on reason text.
    structure_blocking: list[str] = []

    def _structural(reason: str, *, blocking: bool) -> None:
        structure_reasons.append(reason)
        if blocking:
            structure_blocking.append(reason)

    if total == 0:
        _structural("no rows", blocking=True)
    if duplicate_rsids:
        if schema.startswith("harmonized"):
            _structural(f"duplicate RSID rows={duplicate_rsids}", blocking=False)
        else:
            structure_notes.append(
                f"raw source contains duplicate RSID rows={duplicate_rsids}; retained as vendor provenance and must be disambiguated during harmonization"
            )
    if invalid_positions:
        _structural(f"invalid positions={invalid_positions}", blocking=True)
    if invalid_chromosomes:
        _structural(f"invalid chromosomes={invalid_chromosomes}", blocking=True)
    if off_assembly_positions:
        # Any count blocks, with no tolerance: under the declared build these bases do not
        # exist, so there is no fraction of them that is still a measurement. A file with a
        # handful is on the wrong assembly just as surely as one with half a million, and
        # letting a small count through would leave the coordinate join silently wrong for
        # exactly the loci nobody looked at.
        chromosome, position = off_assembly_example or ("?", 0)
        limit = assembly_lengths.get(chromosome, 0)
        _structural(
            f"positions beyond the end of their own chromosome={off_assembly_positions} "
            f"(worst chr{chromosome}:{position:,} against a limit of {limit:,} bp under "
            f"{assembly_basis}); the file is annotated on another assembly or the coordinate "
            "column is corrupt, and every position-keyed join would be wrong",
            blocking=True,
        )
    structure_state = "PASS" if not structure_reasons else "FAIL"

    build_reasons: list[str] = []
    if build not in {"GRCh37", "GRCh38"}:
        build_reasons.append("reference build not explicitly verified")
    elif not build_evidence_verified:
        build_reasons.append("reference build provenance is not a structured VERIFICADO/SATISFIED attestation bound to input SHA-256")
    if str(strand or "").strip().lower() in REVERSE_STRANDS:
        # Distinguished from "not verified" on purpose: this is not a missing answer, it is
        # the wrong one, determined. Every registry this project compares against is written
        # on the plus strand, so the file's alleles are the complements of the ones the
        # comparison expects. Complementing it here would be a silent repair of data whose
        # provenance nobody can re-derive afterwards, so the file is refused instead.
        build_reasons.append(
            f"o arquivo está na fita reversa ({strand}); toda comparação de alelo contra "
            "os registros (escritos na fita plus) sairia invertida, e a inversão não é "
            "corrigida em silêncio"
        )
    elif strand not in FORWARD_STRANDS:
        build_reasons.append("strand convention not explicitly verified")
    elif not strand_evidence_verified:
        build_reasons.append("strand provenance is not a structured VERIFICADO/SATISFIED attestation bound to input SHA-256")
    elif strand_votes_minus >= MIN_STRAND_CONTRADICTION_MARKERS and strand_votes_plus == 0:
        # An attestation is a claim about the file; the file is the evidence. A well-formed,
        # correctly bound, human-signed attestation asserting `forward` used to be the end of
        # the matter even when the file's own markers said otherwise — which is the one
        # remaining way to certify a flipped file, and the one with no automated check
        # against it. Only a *contradiction* blocks: agreement is not treated as proof, and
        # a file with too few informative markers is neither confirmed nor refused here.
        build_reasons.append(
            f"a atestação declara fita forward, mas o conteúdo do próprio arquivo a "
            f"contradiz: {strand_votes_minus} marcadores não palindrômicos compatíveis "
            f"apenas com a fita minus e {strand_votes_plus} apenas com a plus"
        )
        strand_evidence_verified = False
        # The per-locus orientation was decided inside the row loop, before this vote could
        # be counted. Leaving those entries VERIFICADO would publish the contradiction in
        # one field of the same file that resolves it in another.
        for hit in marker_hits.values():
            hit["orientation_operational_status"] = "NÃO DISPONÍVEL"
            hit["orientation_basis"] = (
                f"conteúdo do arquivo contradiz a fita declarada ({strand_votes_minus} "
                f"marcadores apenas minus, {strand_votes_plus} apenas plus)"
            )
    build_state = "PASS" if not build_reasons else "BLOCKED"

    call_reasons: list[str] = []
    if call_rate < min_call_rate:
        call_reasons.append(f"call_rate {call_rate:.6f} < operational threshold {min_call_rate:.6f}")
    if invalid_called_genotypes:
        call_reasons.append(f"invalid called consensus genotypes={invalid_called_genotypes}")
    call_state = "PASS" if not call_reasons else "FAIL"

    cross_reasons: list[str] = []
    cross_state = "NOT_APPLICABLE"
    if schema.startswith("harmonized"):
        cross_state = "PASS"
        if overlap_conflict_rate is not None and overlap_conflict_rate > max_overlap_conflict_rate:
            cross_reasons.append(
                f"overlap conflict rate {overlap_conflict_rate:.6f} > operational threshold {max_overlap_conflict_rate:.6f}"
            )
            cross_state = "FAIL"
    # Unresolved records are reported in their own field, never as gate `reasons`: a gate
    # that answers PASS while listing failure reasons is self-contradictory. They do not
    # block the array — they are excluded from interpretation downstream instead.
    unresolved_records = {
        status: status_counts.get(status, 0)
        for status in sorted(UNRESOLVED_OVERLAP_STATUSES)
        if status_counts.get(status, 0)
    }

    ready_for_limited_interpretation = all(
        x == "PASS" for x in (structure_state, build_state, call_state)
    ) and cross_state in {"PASS", "NOT_APPLICABLE"}

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema": "genoma-snp-array-qc-v1",
        "operational_status": "VERIFICADO" if ready_for_limited_interpretation else "NÃO DISPONÍVEL",
        "evaluated_at": now,
        "ruleset": normative.attested_ruleset_block(),
        "case_id": case_id,
        "input": {
            "path_name": path.name,
            "sha256": input_sha,
            "size_bytes": input_size,
            "container": src.kind,
            "member_name": src.member_name,
            "schema": schema,
            "metadata": metadata,
            "build": build or "NÃO DISPONÍVEL",
            "build_evidence": build_evidence or "NÃO DISPONÍVEL",
            # The verification verdict is published, not left for each consumer to
            # re-derive. Downstream code was testing `strand_evidence != "NÃO DISPONÍVEL"`,
            # which is true for any non-empty string — including one that failed
            # `_verified_provenance`.
            "build_evidence_verified": build_evidence_verified,
            "strand": strand or "NÃO DISPONÍVEL",
            "strand_evidence": strand_evidence or "NÃO DISPONÍVEL",
            "strand_evidence_verified": strand_evidence_verified,
            "platform": platform or "NÃO DISPONÍVEL",
        },
        "metrics": {
            "rows": total,
            "unique_rsids": len(unique_rsids),
            "duplicate_rsid_rows": duplicate_rsids,
            "unique_coordinates": len(coordinate_seen),
            "duplicate_coordinate_rows": duplicate_coordinate_rows,
            # Reported whether or not it blocked, so a clean file states the zero rather
            # than leaving the reader to infer it from the gate's silence.
            "positions_beyond_chromosome_end": off_assembly_positions,
            "assembly_bounds_basis": assembly_basis,
            "valid_calls": valid_calls,
            "call_rate": call_rate,
            "invalid_called_consensus_genotypes": invalid_called_genotypes,
            "autosomal_diploid_snp_calls": autosomal_diploid,
            "autosomal_heterozygous_calls": autosomal_het,
            "autosomal_heterozygosity_rate": het_rate,
            # The file's own orientation vote, recorded whether or not it contradicted
            # anything, so a reader can recompute the verdict instead of trusting it. Zero on
            # both sides means the file carried too few informative markers to say — which is
            # neither confirmation nor refusal.
            "strand_markers_plus_only": strand_votes_plus,
            "strand_markers_minus_only": strand_votes_minus,
            "strand_contradiction_threshold": MIN_STRAND_CONTRADICTION_MARKERS,
            "chromosome_counts": dict(sorted(chromosome_counts.items())),
            "status_counts": dict(status_counts),
            "source_counts": dict(source_counts),
            "genera_present_markers": g_present,
            "genera_called_markers": g_calls,
            "genera_call_rate": g_calls / g_present if g_present else None,
            "myheritage_present_markers": m_present,
            "myheritage_called_markers": m_calls,
            "myheritage_call_rate": m_calls / m_present if m_present else None,
            "direct_overlap_consensus": overlap_consensus,
            "direct_overlap_genotype_conflicts": overlap_conflict,
            "direct_overlap_concordance": overlap_concordance,
            "direct_overlap_conflict_rate": overlap_conflict_rate,
        },
        "gates": {
            "STRUCTURE_GATE": _gate(
                structure_state,
                structure_reasons,
                notes=structure_notes,
                blocking_reasons=structure_blocking,
            ),
            "BUILD_STRAND_GATE": _gate(build_state, build_reasons),
            "CALLABILITY_GATE": _gate(call_state, call_reasons, threshold=min_call_rate),
            "CROSS_PLATFORM_GATE": _gate(
                cross_state,
                cross_reasons,
                max_conflict_rate=max_overlap_conflict_rate,
                unresolved_records=unresolved_records,
                unresolved_record_policy="excluded from interpretation; conflicts are never auto-resolved",
            ),
            "LIMITED_INTERPRETATION_GATE": _gate(
                "PASS" if ready_for_limited_interpretation else "BLOCKED",
                [] if ready_for_limited_interpretation else ["one or more prerequisite gates are not PASS"],
                scope="SNP-array loci only; no WGS-only classes, no diagnostic exclusion, no phase/CNV/SV inference",
            ),
        },
        "baseline_marker_observations": [marker_hits[x] for x in BASELINE_RSIDS if x in marker_hits],
        "baseline_markers_not_present": [x for x in BASELINE_RSIDS if x not in marker_hits],
        "limitations": [
            "SNP-array data interrogate only assayed loci and cannot establish genome-wide absence of variants.",
            "No DP/GQ/allele-balance/read-level evidence exists for array genotype calls.",
            "CNV, SV, repeat expansions, HLA, CYP2D6 structural alleles, mosaicism and deep intronic variation are not resolved by this QC module.",
            "Operational call/conflict thresholds are project QC gates, not clinical assay validation claims.",
            "Clinically actionable observations require current evidence review and appropriate confirmation before changing conduct.",
        ],
    }


def write_outputs(result: dict[str, Any], outdir: Path) -> dict[str, str]:
    outdir.mkdir(parents=True, exist_ok=True)
    qc = outdir / "array-qc.json"
    qc.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markers = outdir / "baseline-marker-observations.tsv"
    cols = [
        "rsid", "chromosome", "position", "genotype", "status", "sources",
        "genera_result", "myheritage_result", "orientation_operational_status", "orientation_basis",
    ]
    with markers.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(result["baseline_marker_observations"])
    sums = outdir / "SHA256SUMS"
    lines = [f"{sha256_file(p)}  {p.name}" for p in (qc, markers)]
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"qc": str(qc), "markers": str(markers), "sha256sums": str(sums)}
