# GENOMA v0.8 Array/Evidence/Template Hardening — historical plan pointer

O plano original foi preservado em [`docs/history/v3.3/superpowers/plans/2026-08-16-genoma-array-evidence-template-lock-v0.8.md`](../../history/v3.3/superpowers/plans/2026-08-16-genoma-array-evidence-template-lock-v0.8.md) porque descreve uma baseline normativa substituída. Ele permanece disponível para proveniência, mas não é uma fonte operacional ativa.

## Contrato vigente

- Policy Control Plane → Scientific Data Plane → Evidence Plane → Audit Plane permanece a arquitetura exigida.
- Ruleset ativo: `VIGENTE / v3.4 / 17/08/2026`.
- SHA-256 canônico: `ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580`.
- Evidência normativa verificável: `manifests/RULESET_V3.4.sha256` e `normative/sealed/MANIFEST.json`.
- SNP-array continua sendo genoma parcial; ausência de marcador não equivale a resultado negativo.
- `POST-DEPLOYMENT PASS` só pode ser registrado depois do merge e do Production Witness no SHA exato de `main`, com `passed == 15`, `total == 15`, `critical_failures == 0` e `post_deployment_status == "PASS"`.

Consulte a documentação operacional atual e os workflows vigentes para execução.
