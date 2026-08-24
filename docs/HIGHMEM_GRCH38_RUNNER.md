# GENOMA - high-memory runner e full-grch38

## Contrato

`full-grch38` só roda em um runner GitHub Actions com labels:

`self-hosted, linux, x64, genoma-production, highmem`

O workflow exige pelo menos ~96 GiB de RAM, espaço persistente para o bundle, Docker, e um `GRCh38.lock.sha256.approved` externo em `REF_ROOT`.

## Provisionamento

1. Provisionar ou ligar um host Linux x86_64 com >=96 GiB RAM e armazenamento persistente suficiente.
2. Registrar GitHub Actions Runner no repositório/organização e aplicar exatamente `genoma-production` e `highmem` além dos labels padrão.
3. Criar `REF_ROOT` (padrão `/srv/genoma/refs/GRCh38`).
4. Obter os 9 artefatos definidos por `manifests/GRCh38.sources.tsv` usando `scripts/fetch_grch38.sh` ou uma cópia aprovada equivalente.
5. Gerar o lock pendente no host. Revisar independentemente proveniência e todos os SHA-256. **Somente após essa revisão**, instalar o lock como `GRCh38.lock.sha256.approved`. O arquivo example não é aprovação.
6. Executar o workflow `GENOMA NGS Runtime Resource Gate` com `mode=full-grch38`.

## O que o workflow faz

- resolve uma candidata atual compatível sem alterar o ambiente pinado;
- roda canário funcional direto, incluindo caller e runtime editorial;
- roda o mesmo canário via Nextflow;
- promoção de sessão só ocorre quando **os dois** canários são PASS e o inventário está completo;
- atualiza e valida freshness das fontes oficiais críticas;
- valida 9/9 recursos, checksums, FASTA/FAI/dict e contigs;
- constrói índices BWA-MEM2 somente se faltarem;
- revalida os cinco arquivos do índice e executa canário funcional do BWA-MEM2;
- reexecuta o Runtime/Resource Gate na sessão atual.

A existência deste runbook não significa que o runner esteja ligado nem que `full-grch38` tenha sido executado. O status só pode mudar após evidência de execução do workflow.
