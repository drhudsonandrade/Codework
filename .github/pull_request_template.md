## Escopo

Descreva uma única mudança e por que ela é necessária.

## Contratos/arquitetura afetados

- [ ] Policy Control Plane
- [ ] Scientific Data Plane
- [ ] Evidence Plane
- [ ] Audit Plane
- [ ] Ruleset/manifest/hash
- [ ] MCP/adapters
- [ ] Nenhum dos anteriores

## Arquivos alterados intencionalmente

Liste os caminhos principais e justifique alterações amplas.

## Evidência local

Comandos realmente executados e resultados:

```text
<cole apenas resultados reais; não escreva PASS se não executou>
```

- [ ] `python3 scripts/validate_repo.py`
- [ ] `python3 scripts/verify_supply_chain_lock.py`
- [ ] `python3 -m unittest discover -s tests -v`
- [ ] testes específicos do componente alterado
- [ ] CodeRabbit CLI pré-PR, se disponível/autenticado

## CodeRabbit

- [ ] Nenhum finding bloqueante conhecido no review pré-PR, quando executado
- [ ] Aguardar review automático do CodeRabbit GitHub App após abrir o PR
- [ ] Findings bloqueantes serão corrigidos nesta branch e re-revisados

## CI / GitHub Actions

- [ ] Aguardar todos os checks obrigatórios do GitHub Actions
- [ ] Não usar resultado de CI inexistente como evidência

## Mudança canônica

Este PR altera versão/data/hash/nome do ruleset, manifest, sealed transport,
attestation ou contrato de evidência?

**Resposta:** Sim / Não

Se sim, descreva a migração coordenada e todos os consumidores atualizados.

## Limitações conhecidas

Liste validações que não puderam ser executadas e por quê.

## Merge

- [ ] Sem auto-merge
- [ ] Merge somente após CodeRabbit + CI + aprovação humana
