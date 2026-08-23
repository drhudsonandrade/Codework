# GENOMA v3.4 — Scientific Data Plane para SNP-array parcial

## Objetivo

Esta via existe para dados de genotipagem parcial (por exemplo, chips comerciais) e é deliberadamente separada do pipeline WGS/FASTQ/BAM/CRAM. Ela executa QC, proveniência, callability e concordância entre fontes sem fingir cobertura de genoma inteiro.

## Gate antes de interpretação

```bash
python3 scripts/run_snp_array.py \
  --input /caminho/privado/arquivo.csv.gz \
  --case-id CASE-PSEUDONIMIZADO \
  --build GRCh37 \
  --strand forward \
  --build-evidence 'fonte rastreável' \
  --strand-evidence 'fonte rastreável' \
  --output-dir /caminho/privado/resultados
```

A execução falha fechada quando build/strand não têm evidência explícita, quando a estrutura harmonizada contém rsID duplicado, quando há genótipos chamados inválidos ou quando os gates configurados de callability/concordância falham.

Arquivos brutos de fornecedor podem conter mais de uma sonda/registro para o mesmo rsID. Esses registros não são colapsados silenciosamente: permanecem na proveniência e precisam ser resolvidos na harmonização. Depois da harmonização, rsID duplicado é bloqueador.

## Saída

- `array-qc.json`: hashes, metadados, métricas, gates, limitações e observações de baseline.
- `baseline-marker-observations.tsv`: observações dos marcadores definidos no ruleset; **não é laudo clínico**.
- `SHA256SUMS`: hashes dos artefatos de saída.

## Escopo honesto

`LIMITED_INTERPRETATION_GATE=PASS` autoriza somente interpretação dos loci efetivamente interrogados e aprovados em QC. Não autoriza:

- exclusão de doença por ausência no chip;
- inferência de CNV/SV, expansões, mosaicismo ou variantes intrônicas profundas;
- diplótipos complexos em CYP2D6/HLA e outros loci que exigem CNV/fase/método especializado;
- uso de SNP-array como substituto de WGS ou confirmação clínica/ortogonal.

Marcadores presentes nas duas plataformas e concordantes recebem maior garantia de orientação. Marcadores MyHeritage-only podem usar a declaração forward (+) do próprio arquivo quando presente. Marcadores Genera-only permanecem `INFERIDO` quanto à orientação até confirmação por referência/alelo/build ou outra evidência rastreável.

## Privacidade

O CI usa exclusivamente fixtures sintéticas. DNA pessoal não é enviado para GitHub Actions, Cloudflare, Supabase, microfn ou qualquer serviço opcional. Os padrões de `.gitignore` bloqueiam nomes usuais dos arquivos genéticos pessoais; o workflow também rejeita fixtures com nomes de dados reais.

## Relação com WGS

O Runtime/Resource Gate de WGS continua independente e deve ser reexecutado na sessão de calling real. `full-grch38` e o runner high-memory não são pré-requisitos para o QC de SNP-array parcial, mas continuam obrigatórios antes da via WGS correspondente.
