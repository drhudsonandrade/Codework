# Sealed normative transport

This directory contains an **inactive, byte-exact transport** of the canonical GENOMA v3.4 ruleset. It is deliberately not stored as an active plaintext `VIGENTE` TXT in Git.

Activation is explicit: `scripts/materialize_ruleset.py` verifies the transport hash, gzip hash, canonical raw SHA-256, normative header and sequential sections `0–262`, then atomically materializes exactly one canonical TXT with mode `0444`. Production mounts that materialized file read-only.

This mechanism is about integrity and single-source activation, not secrecy. The canonical SHA-256 is `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.
