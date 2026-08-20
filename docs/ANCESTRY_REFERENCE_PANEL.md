# Painel de referência populacional (relatório 02)

## O que faltava

O relatório 02 recusava estimar ancestralidade, e a recusa estava certa: frequência alélica
separa populações no agregado mas não posiciona um indivíduo. Faltava um painel de
**genótipos**, com populações nomeadas, que pudesse ser citado.

## O que foi encontrado

| fonte | amostras | papel |
|---|---:|---|
| 1000 Genomes, chip **Affymetrix 6.0** | 3.450 | AFR, EUR, EAS, SAS, AMR |
| **Mao et al. 2007**, painel ameríndio | 43 | AMR-NAT (Nahua, Maya, Quechua, Aymara) |

O segundo é o que torna o resultado significativo para um genoma brasileiro. São os 43
indivíduos que o **próprio 1000 Genomes** usou para deconvoluir suas populações americanas
miscigenadas — retidos porque o ADMIXTURE em K=3 os colocou em 99% ou mais de ancestralidade
nativa, filtrados e controlados por Kenny, Moreno, Maples e Gignoux (Stanford/UCSF).

Sem ele a única referência ameríndia disponível seria o AMR do 1000 Genomes, que **é ele
mesmo miscigenado**: estimar o componente indígena de um brasileiro contra o PEL seria medi-lo
com uma régua feita em parte da coisa medida.

## Por que Affymetrix 6.0 e não Omni 2.5M

Construí o painel primeiro com o chip Omni. Deu **23.377 coordenadas em comum** — os dois
arrays se sobrepõem mal. O painel ameríndio é Affy 6.0; usar o release Affy 6.0 do 1000
Genomes dobra a interseção:

| release | coordenadas em comum | após filtros | após poda de LD |
|---|---:|---:|---:|
| Omni 2.5M | 23.377 | 19.431 | 9.237 |
| **Affy 6.0** | **51.263** | **43.466** | **12.914** |

## Construção

```
616.568 marcadores do painel ameríndio (autossomos, GRCh37)
→  51.263  interseção por coordenada com o release do 1000 Genomes
→  51.228  após excluir palindrômicos (23) e alelos divergentes (12)
→  43.466  após MAF >= 0,05 e faltantes <= 2%
→  12.914  após poda de LD (janela 50, passo 5, r² < 0,2)
```

**Junção por coordenada, não pela coluna ID.** Só 29% dos IDs do release são rsid; o resto são
identificadores de sonda (`SNP1-524110`). Uma junção por rsid descartaria sete marcadores em
dez e chamaria o resto de painel.

**Palindrômicos excluídos.** A/T e C/G não carregam informação de fita — um flip mapeia A↔T e
C↔G, então o erro é indetectável e inverte o genótipo em silêncio. Os autores do painel
ameríndio já os removeram; o script remove de novo em vez de confiar.

**Poda de LD antes do PCA.** Sem ela os primeiros componentes descrevem alguns blocos
haplotípicos longos em vez de estrutura populacional.

## O painel separa populações

| população | n | PC1 | PC2 |
|---|---:|---:|---:|
| AFR | 655 | +55,3 ± 8,5 | −2,4 ± 3,1 |
| AMR | 347 | −17,9 ± 9,8 | +7,0 ± 13,5 |
| **AMR-NAT** | 43 | **−30,2 ± 0,9** | **−20,5 ± 2,1** |
| EAS | 501 | −27,4 ± 0,9 | −39,4 ± 1,6 |
| EUR | 502 | −21,1 ± 1,6 | +29,2 ± 2,2 |
| SAS | 487 | −20,6 ± 1,0 | +6,3 ± 4,0 |

PC1 separa África de tudo; PC2 separa Leste Asiático de Europa, com AMR-NAT do lado asiático,
como esperado da ancestralidade compartilhada. Todo par nomeado tem razão distância/dispersão
acima de 7, a maioria acima de 20. **AMR é o mais disperso** (±9,8 e ±13,5) — que é exatamente
a razão de ele não servir de referência.

## Validação: quatro indivíduos conhecidos

Extraí quatro amostras do próprio release como se fossem casos e projetei:

| amostra | é | mais próximo | resíduo | composição |
|---|---|---|---:|---|
| NA19625 | Iorubá, Nigéria | AFR ✓ | 28% | AFR 83%; AMR-NAT 17% |
| NA12878 | CEU, Utah | EUR ✓ | 11% | EUR 97%; AMR-NAT 3% |
| NA18525 | Han, Pequim | EAS ✓ | 5% | EAS 97%; AMR-NAT 2% |
| HG01565 | Peruano, Lima | AMR ✓ | 13% | **AMR-NAT 56%; EUR 41%** |

Zero flips de fita, zero incompatibilidades de alelo, 99,8–100% de sobreposição. O peruano sai
com o perfil correto de Lima.

O iorubá com **17% de componente ameríndio é artefato**, não ancestralidade, e o sistema o
sinaliza: resíduo de 28% classifica o ajuste como *moderado* e dispara um aviso explícito de
que componentes abaixo de ~20% podem ser artefato. Os limiares de qualidade (15% e 30%) foram
calibrados nesses quatro casos, não escolhidos como números redondos.

## Duas correções que a validação forçou

**AMR fora da base do ajuste.** Usar AMR como vetor-base é erro conceitual: AMR *é* uma mistura
das outras populações, o que torna a base linearmente dependente e faz o ajuste distribuir
peso por direções redundantes. Com AMR na base, o peruano saía 40% AMR + 40% AMR-NAT + 18%
EUR; sem ela, 56% AMR-NAT + 41% EUR — o perfil real. AMR permanece na lista de afinidade,
porque "mais próximo de AMR" é verdadeiro e útil.

**Citação derivada do arquivo.** O primeiro painel publicado citava o release Omni nas fontes
tendo sido construído a partir do Affy 6.0 — erro de proveniência produzido por uma citação
escrita à mão que nada conferia. Agora o nome e o SHA-256 do arquivo efetivamente lido entram
no artefato.

## Guardas na projeção

| guarda | o que faz |
|---|---|
| build | caso em GRCh38 contra painel GRCh37 **recusa**; a junção é por rsid e rodaria em silêncio |
| mínimo de marcadores | abaixo de 2.000 não emite nada — a projeção cai onde o ruído puser |
| sobreposição | abaixo de 60% emite afinidade mas **retém proporções**: encolhimento cresce quando a sobreposição cai |
| fita | par de alelos que não bate nem com o painel nem com o complemento é descartado e contado |
| resíduo | quanto a pessoa se afasta da mistura que os pesos descrevem, com aviso acima de 15% |

## O que isto não é

**Não são proporções de ADMIXTURE.** É mínimos quadrados restritos da posição projetada sobre
os centróides das populações de referência — afirmação geométrica sobre componentes
principais, não estimativa de verossimilhança de mistura, e não decompõe o genoma em segmentos
de ancestralidade local.

## Limitações que permanecem

- Nahua, Maya, Quechua e Aymara são mesoamericanas e andinas. **Não há referência amazônica
  nem de povos originários do Brasil** neste painel, então o componente ameríndio de um genoma
  brasileiro é estimado contra populações aparentadas mas não locais.
- O grupo AFR do 1000 Genomes mistura africanos continentais com afro-americanos e
  afro-caribenhos, que são miscigenados; o centróide AFR não é âncora africana pura.
- 958 amostras do release não têm rótulo no arquivo de populações. Entram no PCA, melhorando
  os eixos, e ficam fora dos centróides.
- Coordenadas em GRCh37.
- Ancestralidade genética não é identidade, cultura, nacionalidade nem história familiar.

## Reproduzir

```bash
B=https://ftp.1000genomes.ebi.ac.uk/vol1/ftp
curl -O $B/release/20130502/supporting/hd_genotype_chip/ALL.wgs.nhgri_coriell_affy_6.20140825.genotypes_has_ped.vcf.gz
curl -O $B/release/20130502/integrated_call_samples_v3.20130502.ALL.panel
for e in bed bim fam; do
  curl -O $B/technical/working/20130711_native_american_admix_train/native_amr_train_20130711.$e
done
python3 scripts/build_ancestry_panel.py \
    --vcf ALL.wgs.nhgri_coriell_affy_6.20140825.genotypes_has_ped.vcf.gz \
    --panel integrated_call_samples_v3.20130502.ALL.panel \
    --native native_amr_train_20130711
```

O artefato tem 766 KB comprimido: 12.914 marcadores com loadings, 3.493 amostras de
referência com coordenadas, e os centróides por população.
