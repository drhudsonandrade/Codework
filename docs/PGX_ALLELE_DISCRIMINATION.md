# Discriminação de alelos, risco residual e requisição de sequenciamento

## O problema, como estava enunciado

> A array cobre 1 a 4 das 40 a 80 posições definidoras por gene do CPIC. Nenhum diplótipo
> farmacogenético sairá dela além do VKORC1. Isso pede sequenciamento dirigido dos genes de
> interesse, não mais código.

Duas afirmações estavam embutidas nessa frase. Uma era um artefato deste pipeline. A outra era
real, mas admitia uma resposta muito melhor do que "não dá".

## Primeira causa: a cobertura media a lista de alvos, não o array

`config/partial_genome_annotation_targets.json` lista 29 loci escolhidos à mão. A matriz de
completude classifica exatamente esses 29. O passaporte então cruzava as posições definidoras
do CPIC contra essa matriz — de modo que **toda posição do CPIC fora dos 29 voltava
`NÃO TESTADO` por construção**, o array a carregando ou não.

O CPIC publica 342 posições definidoras únicas para os dez genes do registro. Um array de
consumo ensaia centenas de milhares de posições. Quantas das 342 ele carrega nunca havia sido
medido — apenas suposto.

`scripts/build_pgx_panel.py` deriva um segundo manifesto de alvos com **todas** as 342, com
coordenada GRCh38 e acesso de referência. Rodando a matriz de completude sobre ele, a pergunta
vira medição:

```bash
python3 scripts/build_pgx_panel.py
python3 scripts/build_pharmacogenomic_report.py \
    --input DNA.csv.gz --qc array-qc.json \
    --targets config/partial_genome_annotation_targets.json \
    --pgx-registry config/pgx_allele_definitions.json \
    --pgx-panel config/pgx_panel_targets.json \
    --matrix-out matrix.json --panel-matrix-out panel-matrix.json \
    --passport-out passport.json --payload-out payload-06.json
```

Sem `--pgx-panel` o passaporte continua funcionando e **declara na própria face** que a
cobertura mede só os alvos curados (`panel_matrix.status = NÃO DISPONÍVEL`). A ausência do
painel nunca equivale à cobertura completa.

## Segunda causa: a recusa era binária onde o dado é quantitativo

`_diplotype_for` recusa se *qualquer* posição definidora do gene não for interpretável. A
recusa é correta — `*1` afirma a base de referência em todas as posições, inclusive as que o
chip nunca leu — mas é tudo-ou-nada. Ela dispara igualmente para um gene a que falta um alelo
raríssimo e para um gene a que faltam quarenta alelos comuns, e o leitor não tem como
distinguir os dois casos.

`array_pipeline/allele_discrimination.py` substitui o binário por uma medição.

### 1. Partição

Para cada gene, os alelos do CPIC são separados em **discrimináveis** (toda posição
definidora interpretável nesta amostra) e **não discrimináveis** (ao menos uma não). Um alelo
sem nenhuma posição definidora no registro nunca conta como discriminável: `all()` sobre um
requisito vazio é verdadeiro, e essa é exatamente a verdade vácua que este projeto passa o
tempo encontrando.

### 2. Risco residual

Os alelos não discrimináveis são precificados pela tabela de frequência do próprio CPIC, por
grupo biogeográfico:

```text
residual = P(um cromossomo carrega alelo de função alterada que este painel não vê)
```

Como a ancestralidade da amostra não está estabelecida, reporta-se o **grupo de maior risco**,
não a média — a média subestimaria o risco para a população a que a pessoa de fato pertence.

Dois sinalizadores carregam a honestidade do número:

| campo | significado |
|---|---|
| `computable` | o CPIC publica frequência para ao menos um dos alelos não excluídos |
| `bounded` | o CPIC publica frequência para **todos** eles, logo o número é o residual e não um limite inferior |

Um residual zero porque tudo foi excluído e um residual zero porque nada pôde ser precificado
são coisas opostas. Os dois sinalizadores existem para que nunca se pareçam.

Função clínica fora do vocabulário publicado pelo CPIC — inclusive nula — conta como
**incerta**, nunca como normal. Se o CPIC renomear um status, o residual cresce; ele não
encolhe em silêncio.

### 3. Diplótipo condicional

Emitido em campo próprio (`discrimination.conditional_diplotype`), **nunca** em
`diplotype.value`. Nada que já lia um diplótipo estabelecido passa a ler um condicional.

O segundo elemento não é `*1`. É `[NÃO DETECTADO]` — vocabulário do relatório 09, que afirma
"interrogado e ausente", que é o que de fato se sabe:

```text
CYP2C19*2/[NÃO DETECTADO]
  "*2 detectado em um cromossomo; o outro cromossomo não carrega nenhum dos 15 alelos
   discrimináveis, e permanece indistinguível de 30 alelos não interrogados"
  conditional_on: nenhum dos 30 alelos do catálogo CPIC não interrogados está presente
  residual: 0,0321 (Sub-Saharan African), limite inferior
```

Todas as precondições do diplótipo incondicional continuam valendo — gene não estrutural,
haplótipo de referência nomeado, no máximo um alelo detectado, no máximo uma posição
definidora heterozigota. A única substituída é a completude do painel, trocada por uma
suposição de mundo fechado **explícita e quantificada**. Status sempre `INFERIDO`.

Conjunto discriminável vazio não produz chamada: um "referência/referência" a partir de zero
posições interrogadas é precisamente a troca de NÃO TESTADO por NÃO DETECTADO que o relatório
09 existe para impedir.

### 4. Fenótipo condicional

Consultado na tabela do CPIC, nunca composto. Exige residual `computable`; boundedness **não**
é exigida — punhados de alelos do CPIC não têm frequência publicada em nenhuma população, o
que bloquearia todos os genes — mas nunca é escondida. O registro do fenótipo carrega
`residual_bounded`, `residual_worst_altered`, `residual_unpriced_alleles` e um `caveat` em
texto corrido, de modo que o rótulo não possa ser citado separado da suposição que o sustenta.

### 5. Requisição de sequenciamento dirigido

"Precisa de sequenciamento dirigido" é uma conclusão, não uma instrução. `sequencing_requisition`
transforma em instrução: seleção gulosa sobre as posições não cobertas, ordenada pela massa de
frequência que cada uma recupera, com coordenada GRCh38 e o residual após cada passo.

Exemplo **ilustrativo, não verificado** (não há artefato de saída, SHA-256 da entrada nem
comando pinado em `docs/evidence/` que sustente estes números; eles não são evidência de
release):

| gene | posições faltantes | 1ª posição | massa recuperada |
|---|---|---|---|
| NAT2 | 31 | rs1208 (chr8:18400806) | 0,684 |
| SLCO1B1 | 26 | rs2306283 (chr12:21176804) | 0,150 |
| CYP3A5 | 5 | rs10264272 (chr7:99665212) | 0,193 |

No exemplo, a linha do CYP3A5 ilustra o argumento: `rs10264272` é o `*6`, comum em
populações africanas, e é a razão pela qual um CYP3A5 chamado só a partir de `rs776746` é
inseguro para esse grupo. O algoritmo foi desenhado para derivar essa priorização da tabela do CPIC; a tabela acima
permanece apenas ilustrativa até que uma execução materialize e pine os artefatos.

## O que continua verdadeiro

Sequenciar as posições listadas **não** resolve alelos estruturais (duplicações, híbridos,
deleções), **não** estabelece fase, e um alelo que o CPIC não cataloga permanece
indistinguível do haplótipo de referência mesmo com cobertura completa. `scope_note` diz isso
em toda requisição.

O CYP2D6 segue sem diplótipo em qualquer cenário: sua variação clinicamente relevante é
estrutural.

## Onde está cada coisa

| arquivo | papel |
|---|---|
| `scripts/build_pgx_registry.py` | busca no CPIC as definições, funções clínicas, **frequências por população** e **coordenadas GRCh38** |
| `scripts/build_pgx_panel.py` | deriva o manifesto de alvos com as 342 posições definidoras |
| `array_pipeline/allele_discrimination.py` | partição, residual, diplótipo/fenótipo condicional, requisição |
| `array_pipeline/pharmacogenomics.py` | integra por gene; totais condicionais separados dos estabelecidos |
| `tests/test_allele_discrimination.py` | cada guarda com seu controle negativo |
