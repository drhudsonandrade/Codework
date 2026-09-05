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

Durante a implementação, mantenha a PR como Draft e execute as correções e validações
localmente. Para evitar consumo iterativo de runners, não aguarde os checks obrigatórios do GitHub Actions enquanto a PR estiver em Draft.

- [ ] Confirmar que o HEAD exato está validado localmente antes da rodada final
- [ ] Marcar a PR como Ready for Review somente quando o HEAD estiver pronto para validação final
- [ ] Após Ready for Review, aguardar todos os checks obrigatórios do GitHub Actions no HEAD exato
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
- [ ] Merge manual somente após CodeRabbit + CI + todos os demais required checks
- [ ] Se necessário, usar o bypass PR-only do owner somente na approval layer; nunca contornar Security & CI
