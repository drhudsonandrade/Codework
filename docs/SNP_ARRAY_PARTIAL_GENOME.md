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

O CI usa exclusivamente fixtures sintéticas. DNA pessoal não é enviado para GitHub Actions, para nenhum adaptador opcional de ingresso, projeção, orquestração ou interface, nem para qualquer outro serviço. Os padrões de `.gitignore` bloqueiam nomes usuais dos arquivos genéticos pessoais; o workflow também rejeita fixtures com nomes de dados reais.

## Relação com WGS

O Runtime/Resource Gate de WGS continua independente e deve ser reexecutado na sessão de calling real. `full-grch38` e o runner high-memory não são pré-requisitos para o QC de SNP-array parcial, mas continuam obrigatórios antes da via WGS correspondente.


## Homozigose em tratos longos (F_ROH)

A triagem de portadores responde "esta pessoa é portadora"; não responde "qual a chance de dois
portadores carregarem a mesma variante na mesma família". Consanguinidade muda isso, e muda por
um fator grande: para uma condição rara, a maior parte do aumento de risco vem de identidade
por descendência, não de dois eventos independentes de portador.

Isso é mensurável no próprio array, sem ensaio adicional, porque ancestralidade compartilhada
recente deixa tratos homozigotos longos. `array_pipeline/homozygosity.py` calcula **F_ROH** — a
fração do genoma autossômico dentro de tratos — pelo estimador de McQuillan et al. (*Am J Hum
Genet* 83:359-372, 2008), preferido aos estimadores por frequência alélica porque estes exigem
uma população de referência pareada que um genoma brasileiro miscigenado não tem. O resultado
entra na seção "Risco combinado e fase" do relatório 03.

Parâmetros: trato ≥ 1.500 kb, ≥ 50 marcadores chamados, no máximo 1 heterozigoto tolerado,
nenhum vão acima de 1.000 kb. Denominador de 2.875.001 kb.

**O que é recusado, e por quê.** O estimador devolve um número em qualquer circunstância, então
cada modo de falha é uma recusa explícita:

| guarda | motivo |
|---|---|
| < 100.000 marcadores chamados | em densidade baixa a fração descreve onde os marcadores caíram, não o genoma |
| taxa de chamada < 95% | genótipo ausente não interrompe um trato e por isso é lido como homozigose |
| coordenada além do fim do cromossomo | o arquivo não está na montagem assumida; todo comprimento derivado é ficção |
| soma dos tratos > autossomo | uma fração do genoma não pode exceder o genoma — recusa, nunca truncamento para 1,0 |

A última apareceu na primeira execução real: uma fixture com coordenadas aleatórias produziu
F_ROH de 1,91 e o código o reportou. Truncar para 1,0 teria escondido a mesma falha atrás de um
número plausível.

**O que não é afirmado.** F_ROH não é pedigree e não identifica grau de parentesco. Isolamento
populacional e efeito fundador produzem tratos longos sem parentesco próximo entre os pais, e
este exame não distingue as causas. O laudo dá a fração medida, o inventário de tratos e os
valores esperados para algumas relações de referência — para escala, não como limiar — e para
por aí.
