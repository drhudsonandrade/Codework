# GENOMA v0.8 — auditoria final de implementação

Data-base: 2026-08-16  
Norma: **STATUS NORMATIVO VIGENTE · v3.3 · 14/08/2026**  
SHA-256 canônico: `187f28a9d9195ee02aa3a3d308549ee804e44ef6043cf9d0bfbfe931ca68810a`

> Esta auditoria não concede POST-DEPLOYMENT PASS. O status formal só pode vir do `GENOMA Production Witness` executado depois do merge no SHA exato da `main`, com 15/15 da seção 260 e zero falhas críticas.

## Resultado por plano

### Policy Control Plane — EXECUTADO / VERIFICADO

- parser/engine determinístico permanece separado de ChatGPT e de qualquer fornecedor;
- Actions críticas são identificadas por SHA de commit e verificadas por `locks/actions-lock.json`;
- base OCI e Gitleaks são identificados por digest em `locks/runtime-lock.json`;
- `scripts/verify_supply_chain_lock.py` falha fechado se uma Action retornar a tag mutável ou se os pins críticos divergirem;
- ruleset canônico continua materializado byte-exact em runtime e não é duplicado como segunda fonte `VIGENTE` no repositório.

### Scientific Data Plane — EXECUTADO

- WGS permanece em `workflows/wgs.nf` com Runtime/Resource Gate imediatamente antes de calling real;
- SNP-array agora é lane de primeira classe em `main.nf --mode array` e `workflows/array.nf`;
- pipeline array: QC → annotation plan/snapshot → case manifest → policy → reports;
- build/strand/proveniência são parâmetros bloqueadores;
- ausência de marcador nunca é tratada como negativo genômico;
- CNV/SV/repetições/HLA/CYP2D6 estrutural/fase complexa continuam fora do escopo do chip.

### Evidence/Annotation Plane — EXECUTADO

- planner target-first limita fan-out e impede consulta ingênua de centenas de milhares de SNPs;
- registry suporta ClinVar, ClinGen, CPIC, ClinPGx, gnomAD e PGS Catalog;
- uma recuperação `VERIFICADO` exige locator, query, timestamp e digest do resultado;
- falha/indisponibilidade de fonte permanece `NÃO DISPONÍVEL`;
- evidência externa não é automaticamente convertida em diagnóstico, causalidade ou conduta.

### Audit Plane — EXECUTADO

- `scripts/genoma_audit.py` produz auditoria machine-readable dos quatro planos;
- CI dedicada `GENOMA v0.8 four-plane audit` executa contratos e testes arquiteturais;
- Production Witness continua independente da auditoria estática e é o único componente que pode testemunhar o pós-deployment formal.

## Templates v3.0

- **VERIFICADO** — identidades SHA-256, tamanho e page count dos 11 PDFs anexos foram selados em `template_store/v3.0/MANIFEST.json` e cruzados com `reporting/reference_v3_manifest.json`.
- **EXECUTADO** — política de imutabilidade: um ID v3.0 não pode trocar bytes sob a mesma versão.
- **NÃO DISPONÍVEL** — transporte binário dos 11 PDFs dentro do GitHub ainda depende da materialização dos chunks selados. O conector de escrita utilizado nesta sessão aceita texto/blobs fornecidos no payload, mas não expõe upload binário direto a partir do arquivo local; por isso os bytes não são falsamente declarados presentes.
- **NÃO DISPONÍVEL / HISTÓRICO NÃO VERIFICÁVEL** — este registro histórico afirma que um source pack determinístico exato foi produzido fora do repositório, mas não preserva locator imutável nem SHA-256 do artefato. Portanto sua existência e identidade não podem ser verificadas a partir desta evidência e ele não deve ser usado como prova até que um locator recuperável e o digest correspondente sejam registrados.

## GRCh38 / high memory

- **EXECUTADO** — verificador fail-closed para BWA-MEM2 prebuilt checksum-locked.
- **EXECUTADO** — arquitetura eliminou a necessidade de máquina high-memory permanente: construção, quando necessária, pode ser one-shot/ephemeral e o bundle passa a ser distribuído por digest.
- **VERIFICADO (fonte externa atual)** — GitHub documenta 8 GB RAM/14 GB SSD para runner Linux padrão de repositório privado, insuficiente para construir o índice BWA-MEM2 humano; GitHub também documenta que o Container Registry atualmente tem armazenamento/banda gratuitos.
- **PROPOSTO** — alternativa zero-build: validar uma lane classic BWA usando os índices GRCh38 prebuilt publicados pelo Broad/GATK; não promover sem benchmark porque muda o aligner.
- **NÃO DISPONÍVEL** — ainda não existe nesta auditoria um bundle BWA-MEM2 GRCh38 aprovado e funcionalmente validado por digest, portanto `full-grch38` não pode ser declarado pronto.

## Privacy / capability honesty

- Dados genéticos pessoais não são commitados no GitHub nem usados como fixture de CI.
- SNP-array real e WGS real permanecem separados de fixtures sintéticas.
- Etapas não executadas têm status PROPOSTO ou NÃO DISPONÍVEL.

## Gate final

A branch só pode ser mesclada após todos os checks aplicáveis ficarem verdes. Depois do merge, deve-se observar o `GENOMA Production Witness` do **SHA exato da main**. O documento de auditoria permanece aberto quanto a dois itens externos: materialização binária do cofre dos templates e full-grch38 real. Esses itens não podem ser convertidos em PASS apenas para encerrar a auditoria.
