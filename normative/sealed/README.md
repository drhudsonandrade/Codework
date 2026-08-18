# Sealed normative transport

This directory contains an **inactive, byte-exact transport** of the canonical GENOMA v3.4 ruleset. It is deliberately not stored as an active plaintext `VIGENTE` TXT in Git.

Activation is explicit: `scripts/materialize_ruleset.py` verifies the transport hash, gzip hash, canonical raw SHA-256, normative header and sequential sections `0–262`, then atomically materializes exactly one canonical TXT with mode `0444`. Production mounts that materialized file read-only.

This mechanism is about integrity and single-source activation, not secrecy. The canonical SHA-256 is `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.

## Reading and writing

- `scripts/sealed_ruleset.py` is the only reader; `scripts/seal_ruleset.py` is the only writer.
- Both take the expected identity from `normative/__init__.py`, so a version migration is a single edit there followed by a re-seal.
- Sealing refuses to run unless the supplied TXT matches that declared identity byte for byte.

## Version history

v3.4 (17/08/2026) supersedes v3.3 (14/08/2026, SHA-256 `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`). Per the REGRA DE UNICIDADE only one source may remain `VIGENTE`; the v3.3 integrity manifest is retained as archived provenance under `manifests/archive/` and marked `OBSOLETA`.
