from __future__ import annotations

from datetime import datetime, date
from typing import Any, Iterable

from .models import GateResult, GateState, OperationalStatus

ALLOWED_OPERATIONAL = {s.value for s in OperationalStatus}
ALLOWED_NATURE = {"FATO CONFIRMADO", "INFERÊNCIA", "ASSOCIAÇÃO", "HIPÓTESE", "DESCONHECIDO"}
ALLOWED_DOMAIN = {"CLÍNICO", "PREDISPOSIÇÃO", "PESQUISA", "CURIOSIDADE"}
ALLOWED_PRIORITY = {"P1", "P2", "P3", "P4", "P5"}

CRITICAL_FINAL_AUDIT_KEYS = (
    "numbering_integrity", "no_accidental_empty_sections", "critical_sources_versioned",
    "critical_databases_current", "variant_class_coverage_explicit", "qc_documented",
    "lod_described", "complex_regions_flagged", "ancestry_reference_considered",
    "absolute_vs_relative_risk_separated", "domains_separated",
    "report_has_technical_and_lay_layers", "master_database_query_manifest",
    "scientific_novelty_radar", "remaining_gaps_listed",
)

RUNTIME_REQUIRED_KEYS = (
    "executables_and_versions", "reference_build_and_contigs", "fasta_fai_dictionary",
    "aligner_indexes", "required_resources_checksums", "sample_read_group_integrity",
    "fastq_bam_cram_integrity", "caller_model_reference_compatibility",
)

def _gate(name: str, ok: bool, reasons: Iterable[str] = (), *, blocking: bool = True, pending: bool = False) -> GateResult:
    state = GateState.PENDING if pending else (GateState.PASS if ok else GateState.FAIL)
    return GateResult(name, state, tuple(reasons), (), blocking)

def _as_bool(value: Any) -> bool:
    return value is True

def _get_list(obj: dict[str, Any], key: str) -> list[Any]:
    value = obj.get(key, [])
    return value if isinstance(value, list) else []

def _parse_iso_date(value: str) -> date | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
