# Painel de referência populacional (relatório 02)

## O que faltava

O relatório 02 recusava estimar ancestralidade, e a recusa estava certa: frequência alélica
separa populações no agregado mas não posiciona um indivíduo. Faltava um painel de
**genótipos**, com populações nomeadas, que pudesse ser citado.

## O que foi encontrado

| fonte | amostras | papel |
|---|---:|---|
| 1000 Genomes, chip **Affymetrix 6.0** | 3.450 | AFR, EUR, EAS, SAS, AMR |
| **AADR** v66.p1, genótipos Human Origins atuais | 97 | AMR-NAT-AMAZONIA, AMR-NAT-ANDES, AMR-NAT-MESOAMERICA |

O painel ameríndio de Mao et al. (43 indivíduos) foi **substituído** pelo AADR, e por duas
razões que apontam na mesma direção — ver "Por que o AADR substituiu Mao et al." abaixo.

Karitiana e Surui são povos **Tupí de Rondônia, na Amazônia brasileira**; Piapoco são da
bacia do Orinoco-Amazonas. É a referência local que faltava: a limitação declarada na versão
anterior deste documento era exatamente que Nahua, Maya, Quechua e Aymara são mesoamericanos e
andinos, e o componente indígena de um genoma brasileiro estava sendo estimado contra povos
aparentados mas não locais.

Sem alguma referência ameríndia, a única disponível seria o AMR do 1000 Genomes, que **é ele
mesmo miscigenado**: estimar o componente indígena de um brasileiro contra o PEL seria
medi-lo com uma régua feita em parte da coisa medida.

## Por que o AADR substituiu Mao et al.

As duas referências são alternativas, não somáveis: Mao et al. está em Affymetrix 6.0 e o
AADR em Human Origins, e exigir as duas interseta três plataformas.

| interseção com o release Affy 6.0 do 1000 Genomes | coordenadas |
|---|---:|
| Mao et al. (Affy 6.0) | 51.263 |
| **AADR (Human Origins)** | **162.289** |
| as três juntas | 12.889 |

O AADR ganha nos dois critérios ao mesmo tempo: **três vezes mais marcadores** e povos
amazônicos brasileiros onde Mao et al. só oferece grupos mesoamericanos e andinos. Manter as
duas custaria 92% dos marcadores.

Os três grupos ameríndios entram **separados**, não como um balde "AMR-NAT". Juntá-los é
precisamente o que fazia um genoma amazônico ser medido contra referências andinas.

| grupo | n | povos |
|---|---:|---|
| AMR-NAT-AMAZONIA | 24 | Karitiana, Surui (Brasil), Piapoco (Colômbia) |
| AMR-NAT-ANDES | 11 | Quechua (Peru), Bolivian |
| AMR-NAT-MESOAMERICA | 62 | Mayan, Mixe, Mixtec, Pima, Zapotec (México) |

Só indivíduos **atuais** com genótipo Human Origins entram, e os que os próprios curadores
marcaram como *discovery*, *outlier* ou *QC-remove* ficam de fora — incluir um indivíduo que a
fonte sinalizou colocaria um outlier dentro de um centróide de referência.

## Dois defeitos que a leitura do AADR expôs

**O deslocamento das linhas.** O `packedancestrymap` é documentado como preenchendo o
cabeçalho até uma linha inteira; este arquivo não o faz — seus 3,8 GB são exatamente
`48 + linha × indivíduos`, 145.985 bytes a menos que o layout documentado. Ler pela convenção
deslocava cada leitura em quase uma linha inteira, servindo a cada indivíduo uma mistura
embaralhada de duas pessoas — dados que descompactam sem erro, com taxa de chamada
plausível, e errados. O layout agora é **derivado do tamanho real do arquivo**, e um tamanho
que não corresponda a nenhum dos dois layouts candidatos é recusado em vez de arredondado
para o mais próximo.

**A orientação dos alelos.** Os dois bits por genótipo contam cópias de um dos dois alelos do
`.snp`, e qual deles é convenção. O script não a presume: mede-a comparando a frequência
alélica dos franceses, han e iorubás do AADR com as superpopulações EUR, EAS e AFR do 1000
Genomes nos mesmos marcadores. Uma inversão aparece como correlação próxima de −1.

```
correlações medidas: −0,985 (EUR)  −0,989 (EAS)  −0,966 (AFR)  →  INVERTIDO
```

Foi essa mesma verificação que pegou o deslocamento: com o cabeçalho errado as correlações
eram −0,002, −0,004 e −0,000. Correlação perto de zero não é orientação a corrigir, é junção
errada, e o painel é recusado sobre ela.

## Construção

```
584.131 marcadores Human Origins (AADR v66.p1, GRCh37)
→ 579.720  autossomos
→ 162.289  interseção por coordenada com o release Affy 6.0 do 1000 Genomes
→ 162.286  após excluir palindrômicos (1) e alelos divergentes (2)
→ 149.753  após MAF >= 0,05 e faltantes <= 2%
→  80.801  após poda de LD (janela 50, passo 5, r² < 0,2)
→  60.000  após afinamento determinístico, uniforme ao longo do genoma
```

Contra 12.914 marcadores do painel anterior: **4,6× mais**.

**Junção por coordenada, não pela coluna ID.** Só 29% dos IDs do release do 1000 Genomes são
rsid; o resto são identificadores de sonda (`SNP1-524110`). Uma junção por rsid descartaria
sete marcadores em dez.

**Palindrômicos excluídos.** A/T e C/G não carregam informação de fita. Ambos os painéis
ameríndios já vêm com **zero** marcadores palindrômicos — seus autores os removeram — e o
script remove de novo em vez de confiar. Por isso a contagem de excluídos é 1, e não os ~15%
que o release Affy 6.0 traz sozinho.

**Os 188 controles de orientação saem do painel** depois de responderem à sua pergunta.
Franceses, han e iorubás do AADR entram só para medir a codificação dos alelos; mantê-los
poria as mesmas populações duas vezes, em duas plataformas, o que desloca esses centróides e
convida um componente principal que descreve o ensaio em vez das pessoas.

## O painel separa populações

| população | n | PC1 | PC2 |
|---|---:|---:|---:|
| AFR | 655 | +117,1 | +7,3 |
| AMR | 347 | −37,2 | −16,2 |
| **AMR-NAT-AMAZONIA** | **24** | **−67,1** | **+47,9** |
| AMR-NAT-ANDES | 11 | −63,4 | +37,4 |
| AMR-NAT-MESOAMERICA | 62 | −64,2 | +43,0 |
| EAS | 501 | −59,4 | +82,2 |
| EUR | 502 | −41,0 | −65,2 |
| SAS | 487 | −41,6 | −14,4 |

Os três grupos ameríndios ficam próximos entre si, como deviam — são populações aparentadas —
e o PC9 é o que os separa: a Amazônia sai em +76,0 contra −12,8 dos Andes e −5,2 da
Mesoamérica.

## Validação: onze indivíduos conhecidos, e o que ela publica

`scripts/validate_ancestry_panel.py` projeta pessoas de origem conhecida pelo mesmo caminho
que um caso percorre e grava o resultado em `docs/evidence/ANCESTRY_PANEL_VALIDATION.json` —
**incluindo o que o painel erra**, porque um relatório de validação que lista só os casos que
deram certo é peça de marketing.

| amostra | é | mais próximo | resíduo | composição |
|---|---|---|---:|---|
| NA19625 | Iorubá, Nigéria | AFR ✓ | 7% | AFR 67%; **AMR-NAT-MESOAMERICA 20%**; EUR 9% |
| NA12878 | CEU, Utah | EUR ✓ | 12% | EUR 99% |
| NA18525 | Han, Pequim | EAS ✓ | 8% | EAS 97% |
| HG01565 | Peruano, Lima | AMR-NAT-ANDES ✓ | 6% | AMR-NAT-ANDES 65%; EUR 26%; AMR-NAT-AMAZONIA 4% |
| NA20502 | Toscano, Itália | EUR ✓ | 23% | EUR 94%; SAS 5% |
| HG02461 | Gâmbia | AFR ✓ | 27% | AFR 100% |
| HGDP00995 | **Karitiana, Brasil** | AMR-NAT-AMAZONIA ✓ | 16% | AMR-NAT-AMAZONIA 100% |
| HGDP00832 | **Surui, Brasil** | AMR-NAT-AMAZONIA ✓ | 6% | AMR-NAT-AMAZONIA 100% |
| HGDP00702 | Piapoco, Colômbia | AMR-NAT-ANDES ✓ | 7% | ANDES 48%; AMAZONIA 28%; MESOAMERICA 24% |
| NA11200 | Quechua, Peru | AMR-NAT-ANDES ✓ | 11% | AMR-NAT-ANDES 100% |
| HGDP00854 | Mayan, México | AMR-NAT-MESOAMERICA ✓ | 3% | MESOAMERICA 60%; ANDES 32% |

Onze de onze caem na família populacional certa. Karitiana e Surui saem 100% amazônicos, que
é o teste que importa para um genoma brasileiro. O peruano de Lima sai 65% andino e 26%
europeu — o perfil real de Lima, e **não** artefato: populações do AMR do 1000 Genomes são
miscigenadas por definição, e contar essa ancestralidade verdadeira como erro inflaria a
única cifra que este arquivo existe para declarar honestamente.

## O artefato honesto: 19,8%

**NA19625 é iorubá e recebe 20% de componente ameríndio mesoamericano.** Isso não é
ancestralidade: é o ajuste distribuindo peso por direções que a base de referência não separa
bem nessa região do espaço. É o maior componente espúrio medido, e é o número que o
relatório 02 cita.

O painel anterior produzia 17,5% no mesmo indivíduo com resíduo de 28%, e o aviso do sistema
estava amarrado ao resíduo: acima de 15%, "componentes pequenos podem ser artefato". **Esse
aviso deixou de funcionar.** Com 60.000 marcadores o mesmo iorubá ajusta com resíduo de 7% —
qualidade "boa" — e continua recebendo 20% espúrios. Resíduo e artefato não viajam juntos, e
uma guarda presa ao resíduo perde exatamente o caso para o qual foi escrita.

A correção: a ressalva sobre componentes minoritários passou a ser **incondicional**, e o
tamanho que ela cita é **medido, não estipulado** — vem do artefato de validação, carimbado
dentro do próprio painel. Se um painel não trouxer validação, o texto diz que o tamanho
típico de um componente espúrio não foi medido, em vez de citar um número herdado de outra
construção.

> Componentes abaixo de 20% não são estabelecidos por esta projeção.

**Nenhum destes indivíduos é externo ao painel.** Todos contribuíram para os loadings, então
as projeções são otimistas. Isto mede consistência interna e detecção de artefato, não
acurácia fora da amostra, e o artefato diz isso em `held_out: false`.

## Guardas na projeção

| guarda | o que faz |
|---|---|
| build | caso em GRCh38 contra painel GRCh37 **recusa**; a junção é por rsid e rodaria em silêncio |
| mínimo de marcadores | abaixo de 2.000 não emite nada — a projeção cai onde o ruído puser |
| sobreposição | abaixo de 7.500 marcadores em comum emite afinidade mas **retém proporções**: encolhimento cresce quando a sobreposição cai |
| fita | par de alelos que não bate nem com o painel nem com o complemento é descartado e contado |
| resíduo | quanto a pessoa se afasta da mistura que os pesos descrevem, com aviso acima de 15% |
| componente minoritário | ressalva **incondicional**, citando o maior componente espúrio medido no painel (19,8%) |

O limiar de proporções é **absoluto, com a fração como piso secundário**, e isso é correção
de um defeito que a própria reconstrução criou: 60% de um painel de 12.914 marcadores são
7.748, mas 60% de um painel de 60.000 são 36.000 — um array que ganhava proporções contra o
painel pequeno seria recusado pelo painel melhor, carregando estritamente mais informação. O
encolhimento depende de quantos marcadores foram usados, não de quantos o painel tem.

## O que isto não é

**Não são proporções de ADMIXTURE.** É mínimos quadrados restritos da posição projetada sobre
os centróides das populações de referência — afirmação geométrica sobre componentes
principais, não estimativa de verossimilhança de mistura, e não decompõe o genoma em segmentos
de ancestralidade local.

## Limitações que permanecem

- **A sobreposição com um array de consumo nunca foi medida.** O painel vem da interseção
  Affy 6.0 × Human Origins; quanto dela um chip Illumina de consumo carrega é desconhecido até
  que um caso real seja projetado. A guarda existe e recusa proporções abaixo de 7.500
  marcadores em comum, mas recusar não é o mesmo que funcionar, e nenhuma projeção de um array
  de consumo real foi executada contra este painel nem contra o anterior.
- A referência amazônica são **24 indivíduos** de três povos. Karitiana e Surui são de
  Rondônia; não há referência de povos do Nordeste, do Sul, do Xingu nem da costa atlântica, e
  a diversidade indígena brasileira não é representável por três povos.
- Os 97 indivíduos ameríndios vêm todos do Human Origins, uma plataforma com **ascertainment
  próprio**: os marcadores foram escolhidos por critérios que não são neutros entre populações,
  o que afeta distâncias absolutas mais do que a ordem de afinidade.
- O grupo AFR do 1000 Genomes mistura africanos continentais com afro-americanos e
  afro-caribenhos, que são miscigenados; o centróide AFR não é âncora africana pura.
- 958 amostras do release não têm rótulo no arquivo de populações. Entram no PCA, melhorando
  os eixos, e ficam fora dos centróides.
- Coordenadas em GRCh37.
- Ancestralidade genética não é identidade, cultura, nacionalidade nem história familiar.

## Reprodutibilidade

O resultado pinado está em `docs/evidence/ANCESTRY_PANEL_VALIDATION.json`; o campo
`cases[].closest_matches_expected` é verdadeiro nos 11 casos e sustenta “onze de onze”.
O checkout atual **não inclui** os antigos scripts
`fetch_aadr_genotypes.py`, `build_ancestry_panel.py` e
`validate_ancestry_panel.py`. Por isso, os comandos históricos que os citavam foram
removidos: o artefato é um snapshot de evidência inspecionável, mas sua regeneração não é
reproduzível a partir deste repositório e não deve ser apresentada como tal.

O painel comprometido contém os loadings, amostras de referência, centróides, orientação e
resumo de validação que os consumidores atuais validam estruturalmente antes da projeção.
