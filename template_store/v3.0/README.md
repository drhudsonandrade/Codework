# GENOMA v3.0 — private immutable template store

This directory defines the immutable source identities for the 11 user-approved GENOMA v3.0 PDF models.

## Contract

- Repository visibility must remain **private**.
- `MANIFEST.json` is the content-addressed identity contract.
- Report IDs `01`..`11` may not change filename, SHA-256, byte size or page count under version `v3.0`.
- Any byte-level template change requires a new suite version and new immutable manifest.

> **Esta regra foi quebrada uma vez, e o registro fica aqui.** Em 2026-08-20 o relatório 11
> teve seus bytes alterados e a identidade foi *repinada sob v3.0* (`d68fce73…` →
> `169fe6c0…`) em vez de originar uma nova suíte, porque `scripts/seal_template_store.py`
> estava fixo em `v3.0` e só oferecia `--amend`. Durante esse período dois conjuntos de bytes
> distintos chamavam-se ambos "GENOMA v3.0" e nada os distinguia.
>
> O pacote em uso está agora selado como **`template_store/v3.1/`**, cuja `lineage` registra
> a alteração herdada e nomeia o relatório que difere do v3.0 originalmente aprovado. O
> selador recusa repinagem sob uma suíte já selada: uma mudança de bytes tem de virar suíte
> nova. O que permanece sob `v3.0/` é o transporte tal como ficou após a emenda — não os
> bytes originalmente anexados, que este repositório não guarda.
- No case, patient or genotype data may be stored here.
- The renderer must use only a template whose bytes verify against the manifest.

## Sealed source transport

The approved storage design uses a deterministic `tar.xz` encoded as fixed base64 parts under `sealed/parts/`. `scripts/verify_template_store.py` validates every part, reconstructs the archive, checks the archive hash and then checks all 11 PDF hashes before optional materialization.

The `--allow-sealed-only` mode is intentionally honest: when the source parts are absent from a checkout it returns `NÃO DISPONÍVEL` for binary materialization while still verifying the manifest-to-reference identity contract. It must never silently manufacture or substitute a PDF.

## Operational status

The template identities are **VERIFICADO** against the exact attached v3.0 model sources. Binary source transport is promoted to **VERIFICADO** only when every sealed part is present and passes the reconstruction check.
