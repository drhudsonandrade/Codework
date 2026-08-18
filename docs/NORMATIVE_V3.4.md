# Norma vigente — GENOMA v3.4

```
STATUS NORMATIVO: VIGENTE
VERSÃO NORMATIVA: v3.4
DATA FORMAL DE EMISSÃO E VIGÊNCIA: 17/08/2026
IDENTIFICADOR NORMATIVO: GENOMA-RULESET-v3.4
ARQUIVO CANÔNICO: REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt
SHA-256: ab7a5f0ba9709e2f92a11ae4630f82ebae70385eab877ad3464fac6bd44a3580
```

Estrutura: 263 seções principais, numeração `0–262` sequencial. O hash é externo por
construção — um arquivo não pode conter, sem circularidade, o hash final de si próprio —
e vive em `manifests/RULESET_V3.4.sha256`.

## REGRA DE UNICIDADE

Somente a v3.4 pode permanecer marcada como `VIGENTE`. Duas fontes ativas simultâneas
tornam o gate normativo **FAIL**, não um aviso. O repositório aplica isso em dois pontos
independentes:

- `scripts/validate_repo.py` recusa qualquer `manifests/RULESET_V*.sha256` que não seja o
  da versão corrente, e recusa qualquer TXT `VIGENTE` em texto puro no repositório;
- o `RULESET_GATE` da auditoria four-plane recusa um segundo manifesto ativo e bloqueia o
  plano de controle.

Quando o gate falha, a resposta obrigatória é `RULESET NÃO DISPONÍVEL/CONFLITANTE` e a
tarefa para. Não existe caminho degradado.

## O que a v3.4 mudou em relação à anterior (seção 262)

A revisão é normativa e editorial: preserva integralmente o conteúdo científico e
operacional herdado, e altera identidade, coerência de implantação e neutralidade de
plataforma.

1. Atualiza status, versão, data formal, identificador normativo e nome canônico.
2. Atualiza o BOOTSTRAP CURTO para nome, versão e data da v3.4.
3. Neutraliza referências a fornecedor/plataforma específica na REGRA DE DEPLOYMENT e na
   seção 253, substituindo-as por linguagem genérica de ambiente de projeto.
4. Mantém inalteradas DATA-FIRST, QC-FIRST, EVIDENCE-FIRST, RECENCY-FIRST, NO FALSE
   CERTAINTY, CONFIRMATION e CAPABILITY HONESTY.
5. Mantém a exigência de Runtime/Resource Gate antes de calling NGS real, sem presumir
   persistência de instalações, referências, índices ou recursos.
6. Preserva os 15 casos do Deployment Smoke Test, atualizando o alvo normativo esperado.
7. **Separa explicitamente evidência histórica de runtime/benchmark da execução atual**,
   evitando promover resultado de auditoria anterior como se tivesse sido reexecutado.
8. Mantém POST-DEPLOYMENT PENDENTE até substituição real da fonte, instalação do BOOTSTRAP
   CURTO v3.4 e smoke ao vivo 15/15 sem falha crítica.

O item 7 é o que governa este repositório na prática: nenhum PASS anterior sobrevive à
troca de versão por inércia. Foi por isso que os relatórios datados da revisão anterior
foram retirados da árvore em vez de reescritos — reescrever medições que nunca foram
reexecutadas seria fabricar evidência. O histórico permanece recuperável no Git.

## Gates da seção 258 e como este repositório responde

| Gate normativo | Situação declarada na v3.4 | Onde é exercido aqui |
|---|---|---|
| FORMAL VERSION / VIGENTE | EXECUTADO — PASS no artefato | `RULESET_GATE`, `validate_repo.py`, `verify_ruleset.sh` |
| STATIC LINT (263 seções, 0–262) | EXECUTADO — PASS no artefato | `sealed_ruleset.py` valida a sequência ao decodificar |
| SCIENTIFIC FRESHNESS | VERIFICADO — snapshot histórico | `scripts/refresh_evidence_sources.py`, `freshness_gate.py` |
| BEHAVIORAL ACCEPTANCE | VERIFICADO — histórico, não reexecutado | não promovido a atual |
| DEPLOYMENT-SMOKE FIXTURE | VERIFICADO — histórico | `genoma_policy smoke` (15/15, fixture controlado) |
| NGS RUNTIME GATE | **histórico, não reexecutado** | `runtime_resource_gate.py` por sessão |
| GRCh38 RESOURCE GATE | **histórico, não reexecutado** | `validate_grch38.sh` + checksums por sessão |
| REAL VARIANT-CALLING BENCHMARK | histórico | canário sintético, não validação clínica |
| DEEPVARIANT | NÃO DISPONÍVEL até novo teste | não declarado executado |
| CAPABILITY GATE | EXECUTADO — PASS no texto | contrato de status operacional |
| POST-DEPLOYMENT | **PROPOSTO / PENDENTE** | nunca concedido por CI |

## Runtime/Resource Lock (seção 259)

Antes de calling real, verificar e marcar cada item como `EXECUTADO` ou `NÃO DISPONÍVEL`:
executáveis e versões; build e convenção de contig; FASTA/FAI/dictionary; índices do
alinhador; known-sites/annotation quando exigidos; checksums; sample/read group;
integridade FASTQ/BAM/CRAM; compatibilidade caller–modelo–referência.

A regra termina com **"Não herdar o PASS de outra sessão."** Um artefato que apenas declara
`inherited_from_previous_session: false` não satisfaz isso, porque o produtor escreve essa
flag incondicionalmente. Por isso a atestação é vinculada ao `boot_id` do kernel e
reverificada no consumo — ver `docs/DETERMINISTIC_ENGINE.md`.

## Contrato de status operacional (seção 261)

`EXECUTADO` (feito nesta sessão) · `VERIFICADO` (conferido em fonte acessível) · `INFERIDO`
(derivado, com base e incerteza explícitas) · `PROPOSTO` (recomendado, não realizado) ·
`NÃO DISPONÍVEL` (ausente).

Nunca escrever "analisei", "processei", "confirmei" ou "rodei" para um item `PROPOSTO`.
Toda análise grande fecha com um Execution Manifest que permita auditoria independente;
os relatórios finais carimbam a identidade normativa verificada no próprio manifesto.

## POST-DEPLOYMENT — critério único

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE` é o estado corrente e correto.

Para chegar a PASS, e somente assim:

1. manter apenas a v3.4 como fonte normativa VIGENTE;
2. instalar o BOOTSTRAP CURTO v3.4 nas instruções operacionais do ambiente;
3. atualizar `deploy/attestations/bootstrap-project-v3.4.json` para `VERIFICADO` após
   inspeção humana direta das instruções ao vivo;
4. executar ao vivo os 15 casos da seção 260, exigindo **15/15 sem falha crítica** e
   confirmação de que a execução recuperou v3.4/VIGENTE/17/08/2026.

Enquanto a atestação de bootstrap estiver `PROPOSTO`, a cerimônia de produção recusa
POST-DEPLOYMENT PASS por construção. Isso é intencional: entregar o arquivo não é implantar.

## Migração para uma versão futura

1. Editar a identidade em `normative/__init__.py` (versão, data, nome canônico,
   identificador, SHA-256, tamanho, contagem de seções).
2. Rodar `python3 scripts/seal_ruleset.py --input <TXT canônico>`; a selagem recusa
   qualquer arquivo que não bata byte a byte com a identidade declarada.
3. Atualizar as constantes espelhadas em `policy_engine/genoma_policy/` — o pacote é
   instalável de forma autônoma e não importa a raiz. `tests/test_normative_identity.py`
   falha fechado se as duas cópias divergirem.
4. Rodar a suíte completa e a auditoria four-plane; reabrir POST-DEPLOYMENT como PENDENTE.
