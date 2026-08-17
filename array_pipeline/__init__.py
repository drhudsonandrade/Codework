"""SNP-array public API bound to the active GENOMA ruleset identity."""

from . import qc as _qc

_ACTIVE_RULESET = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}

def _bind_active_ruleset(module) -> None:
    ruleset = getattr(module, "RULESET", None)
    if isinstance(ruleset, dict):
        ruleset.clear()
        ruleset.update(_ACTIVE_RULESET)

_bind_active_ruleset(_qc)
# Import annotation after qc so direct imports of array_pipeline.annotation also pass
# through this package initializer and receive the same canonical runtime identity.
from . import annotation as _annotation
_bind_active_ruleset(_annotation)

inspect_array = _qc.inspect_array
write_outputs = _qc.write_outputs
annotate_partial_genome = _annotation.annotate_partial_genome
write_annotation = _annotation.write_annotation
RULESET = _qc.RULESET

__all__ = [
    "inspect_array", "write_outputs", "annotate_partial_genome", "write_annotation", "RULESET"
]
