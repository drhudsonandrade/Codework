"""What a SNP array cannot answer, stated once and imported by everything that says it.

This list lived in `array_pipeline/annotation.py`, which imports `evidence_adapters` at
module scope. `completeness.py` needed only the list, so importing it from `annotation`
dragged the Evidence Plane adapter package into the import graph of modules that never
retrieve any evidence — making an adapter the repository declares optional a hard
requirement for importing the core. The constant has no dependencies of its own, so it
belongs somewhere with none.

Every entry is a class of question the assay is physically unable to answer, not one this
pipeline merely declines to implement. Reports print them so a reader learns what was never
looked at, rather than reading silence as absence.
"""
from __future__ import annotations

UNSUPPORTED_ARRAY_CLAIMS = [
    "genome-wide negative/exclusion claims",
    "CNV",
    "SV",
    "repeat expansions",
    "HLA typing",
    "CYP2D6 structural/hybrid/copy-number diplotyping",
    "mosaicism from read-level evidence",
    "deep intronic/non-assayed variation",
]
