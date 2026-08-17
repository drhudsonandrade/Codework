"""SNP-array QC public API bound to the active GENOMA ruleset identity."""

from . import qc as _qc

_ACTIVE_RULESET = {
    "status": "VIGENTE",
    "version": "v3.4",
    "effective_date": "17/08/2026",
    "sha256": "ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580",
}
# qc.py is retained as the stable implementation module. Bind its emitted metadata to
# the canonical active identity at package import so every supported import path
# (including ``from array_pipeline.qc import inspect_array``) returns v3.4 metadata.
_qc.RULESET.clear()
_qc.RULESET.update(_ACTIVE_RULESET)

inspect_array = _qc.inspect_array
write_outputs = _qc.write_outputs
RULESET = _qc.RULESET

__all__ = ["inspect_array", "write_outputs", "RULESET"]
