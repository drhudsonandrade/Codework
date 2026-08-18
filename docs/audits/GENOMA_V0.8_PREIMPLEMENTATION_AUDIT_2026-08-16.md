# GENOMA v0.8 - Auditoria pré-implementação

> **HISTÓRICO — SUPERSEDED.** Auditoria executada sob o ruleset **v3.3 (14/08/2026)**. O repositório passou a ser governado pela **v3.4 (17/08/2026)** e estes controles **não** foram reexecutados sob a v3.4. Preservada sem alteração como proveniência; nenhum PASS abaixo é uma afirmação atual.


Data da auditoria: 2026-08-16

## Identidade normativa

- Status operacional da verificação: **VERIFICADO**
- STATUS NORMATIVO: `VIGENTE`
- VERSÃO NORMATIVA: `v3.3`
- DATA FORMAL DE EMISSÃO E VIGÊNCIA: `14/08/2026`
- SHA-256 canônico: `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`

## Baseline após PR #12

- PR #12 incorporado à `main`: **EXECUTADO**
- Commit de merge: `ff0f918afbfcdf00e3dfb559a5778b7d26c87431`
- Production Witness agora cobre toda alteração em `main`, com escrita separada para `audit-evidence`: **VERIFICADO** por CI do PR #12; requer novo witness no commit final após todas as mudanças v0.8.
- Scientific Data Plane WGS curto (SNV/small-indel) já existe: **EXECUTADO** como código; `full-grch38` permanece **NÃO DISPONÍVEL** sem infraestrutura/bundle aprovado.
- SNP-array QC/harmonização existe como executor separado: **EXECUTADO**, porém integração como modo Nextflow de primeira classe ainda **NÃO DISPONÍVEL**.
- Evidence adapters ClinVar, ClinGen, CPIC, ClinPGx, gnomAD e PGS Catalog existem: **EXECUTADO**, porém annotation/query planning por loci interrogados de SNP-array ainda **NÃO DISPONÍVEL**.
- 11 templates v3.0 possuem SHA/page-count/placeholder-count fixados no manifesto: **VERIFICADO**; os PDFs ainda são declarados `EXTERNAL_PRIVATE_TEMPLATE_PACK`, então a independência da conversa/anexo ainda é **NÃO DISPONÍVEL**.
- QA estático de referência dos templates: **VERIFICADO** para a evidência existente; o workflow precisa acompanhar a `main` final.
- GitHub Actions ainda usam várias tags mutáveis (`@v4`, `@v5`, etc.): endurecimento por SHA **NÃO DISPONÍVEL**.

## Riscos/achados

1. **Scientific Data Plane dividido** - WGS usa Nextflow, SNP-array usa CLI separada; isso aumenta risco de caminhos de auditoria divergentes.
2. **Annotation fan-out** - consultar centenas de milhares de SNPs diretamente em APIs externas seria não determinístico, lento e potencialmente abusivo; é necessário planner com orçamento e alvos explícitos.
3. **Templates externos** - depender dos anexos/conversa compromete reprodutibilidade de longo prazo mesmo com hashes conhecidos.
4. **Supply chain** - tags de Actions e imagens por tag podem mover; identidades críticas devem ser content-addressed.
5. **GRCh38/BWA-MEM2** - construir o índice humano é um passo monolítico de alta memória; múltiplos runners pequenos não somam memória compartilhada para esse processo. A alternativa segura é construir uma vez em compute high-memory efêmero ou usar índice prebuilt independente, desde que ele seja hash-locked ao FASTA aprovado e passe canário funcional antes de promoção.
6. **POST-DEPLOYMENT** - qualquer PASS anterior deixa de ser prova suficiente depois das mudanças v0.8; o estado permanece **PENDENTE** até o witness live do SHA final da `main`.

## Critérios de aceitação v0.8

- `main.nf --mode array` existe e é fail-closed.
- SNP-array passa por QC -> observações alvo -> annotation/evidence -> manifest auditável, sem tratar ausência como negativo.
- Evidence Plane limita consultas, registra `locator`, `query`, `checked_at`, versão e `result_digest`, e falha como `NÃO DISPONÍVEL` quando a fonte não pode ser verificada.
- 11 PDFs v3.0 exatos são armazenados em caminhos content-addressed dentro do repositório privado e validados contra os hashes já aprovados.
- Actions críticas são pinadas por commit SHA e existe `actions-lock.json` verificável.
- Existe `runtime-lock.json` com hashes dos arquivos/contratos críticos e versões do runtime.
- Scanner de segredos executa um canário sintético antes de confiar em um PASS do repositório.
- GRCh38 admite dois caminhos sem relaxar gates: build high-memory ou índice prebuilt verificado.
- Auditoria final produz JSON + relatório humano, mas não concede POST-DEPLOYMENT.
- Após merge final, `GENOMA Production Witness` executa no SHA exato da `main`; somente 15/15, zero falha crítica e `post_deployment_status=PASS` autorizam `POST-DEPLOYMENT PASS`.
