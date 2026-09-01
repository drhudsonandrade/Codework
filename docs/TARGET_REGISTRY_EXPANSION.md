# Expansão do registro de alvos

## O que mudou

| registro | alvos | fonte |
|---|---:|---|
| `partial_genome_annotation_targets.json` | 29 | curadoria manual (ClinVar + CPIC + dbSNP) |
| `pgx_panel_targets.json` | 342 | posições definidoras do CPIC |
| `targets_clinvar_plp.json.gz` | **54.845** | release em massa do ClinVar, P/LP, 2★+ |
| `targets_clinvar_plp_1star.json.gz` | **123.551** | o mesmo, admitindo também o nível de uma estrela |
| `targets_gwas_traits.json` | **733** | GWAS Catalog, termos declarados |
| `targets_merged_panel.json.gz` | 55.916 | união com o corte de 2★ |
| **`targets_merged_panel_1star.json.gz`** | **124.621** | união com o corte de 1★ — **o padrão** |

O padrão passou a ser o registro de 1★ porque a interpretação classifica por nível de
revisão, não por pertencimento: o nível fica visível no laudo em vez de diluído nele. Numa
execução de demonstração o resultado saiu 93 ACHADO PRELIMINAR contra 20 ACHADO ACIONÁVEL —
número **ilustrativo, não verificado**, sem artefato de saída, SHA-256 de entrada ou comando
pinado em `docs/evidence/` que o sustente. O par de 2★ continua selecionável com `--targets`/`--evidence` para uma execução
que só deva ver consenso curado.

No corte de 1★: **4.408 genes**, dos quais **3.895** com relação gene-doença estabelecida —
2.535 recessivos, 1.602 dominantes, 163 ligados ao X.

Com o corte de 2★, que era o padrão anterior, o artefato de alvos versionado
`config/targets_clinvar_plp.json.gz` permite reproduzir **54.845 rsids e 3.082 genes**.
Esse é o limite do que o HEAD atual sustenta para esse corte.

> **Medição histórica não verificada — validade gene-doença no corte 2★.** Uma revisão
> anterior deste documento publicou **2.965 genes estabelecidos**, **117 sem relação
> estabelecida** e uma decomposição por ClinGen/GenCC/PanelApp/ClinGen Dosage/gnomAD. O
> repositório atual não contém um artefato de validade gene-doença para o mesmo universo de
> 3.082 genes que permita reproduzir essas contagens. `docs/evidence/GENE_DISEASE_VALIDITY.json`
> contém apenas **16 genes (7 estabelecidos, 9 não estabelecidos)** e, portanto, não é o
> denominador correspondente ao painel 2★. As contagens 2.965/117 e sua antiga tabela por
> fonte ficam preservadas apenas como histórico de uma execução não reproduzível e **não são
> evidência de release**. Elas só podem voltar como verificadas quando um artefato versionado,
> com SHA-256 e comando reproduzível, materializar esse mesmo corte.

No artefato **1★** que está efetivamente versionado, as contagens de validade são
reproduzíveis: **4.408 genes**, **3.895 com validade estabelecida**, **540 estabelecidos
apenas pelo PanelApp**, **3 apenas pelo GenCC**, **0 apenas por ClinGen Dosage**, **3.249**
com sobreposição PanelApp/GenCC, **1.289** com curadoria de dosagem, **3.990** com métrica de
restrição do gnomAD e **1.004** com pLI ≥ 0,90. Esses números vêm de
`docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz`; PanelApp sobreposto ao GenCC continua
marcado como uma única base de curadoria, e gnomAD continua sem poder estabelecer relação
gene-doença.

## Os registros curados que decidem o que vira achado

Nenhum deles é o ClinVar. O ClinVar diz o que uma **variante** é; estes dizem se o **gene**
tem relação estabelecida com doença — e sem isso o sistema não converte variante em achado
clínico.

| registro | o que afirma | conta como estabelecido quando |
|---|---|---|
| ClinGen Gene-Disease Validity | painel de especialistas curou a relação | classificação Definitive ou Strong |
| GenCC | vários curadores submeteram a mesma relação | ≥2 submetentes independentes em Definitive/Strong |
| **PanelApp** (Genomics England + Austrália) | um serviço de saúde testa o gene na prática | gene **verde** em ao menos um painel diagnóstico |
| **ClinGen Dosage Sensitivity** | perder ou ganhar uma cópia é o mecanismo | escore 3 de haploinsuficiência ou triplossensibilidade |
| gnomAD v4.1 constraint | quão intolerante o gene é a perda de função | **nunca** — restrição não é relação gene-doença |

Cada gene registra qual deles o sustentou em `established_by`. "Definitivo por painel de
especialistas do ClinGen" e "verde num painel do NHS" são afirmações de pesos diferentes, e
achatá-las num booleano esconderia qual foi.

**PanelApp não é independente do GenCC.** O export do GenCC já agrega as submissões das duas
instâncias do PanelApp. Onde os dois estabelecem o mesmo gene, é um corpo de curadoria
aparecendo duas vezes, não duas fontes concordando: `panelapp_overlaps_gencc` marca esses
genes e o relatório 01 escreve a ressalva na seção de incertezas.

**A varredura, medida.** 68.991 entradas gene-painel nas duas instâncias, cobrindo **657
painéis** — 414 do Genomics England e 243 do PanelApp Australia — dos quais 652 carregam ao
menos um gene verde. São 7.239 genes indexados e **5.004 verdes**. O PanelApp é vivo: entre
duas varreduras com poucas horas de intervalo, as contagens da Austrália foram de 36.485 para
36.491 entradas, e por isso a data e as contagens ficam gravadas no artefato em vez de serem
citadas de memória. Uma leitura curta é recusada, não publicada: um varrimento parcial não é
um registro menor, é um registro que omite em silêncio os painéis que ordenam por último.

**Verde, e só verde.** Âmbar é evidência insuficiente para reportar e vermelho é gene
considerado e rejeitado pelos próprios curadores. Ler âmbar como evidência colocaria num
laudo um gene que o painel explicitamente recusou endossar. Os dois são retidos no artefato;
apenas verde estabelece.

**Os escores de dosagem não são uma escala.** 30 e 40 são maiores que 3 como número e não
como evidência: 3 é "evidência suficiente para patogenicidade por dosagem", 30 é o curador
escrevendo "gene associado a fenótipo autossômico recessivo" *em vez* de pontuar, e 40 é
"dosagem improvável de ser sensível". Tratar 30 como acima de 3 estabeleceria 599 genes que o
ClinGen nunca afirmou. Aqui 3 estabelece, 30 contribui o modo de herança AR sem estabelecer, e
40 não contribui nada.

**Restrição populacional é carregada e nunca estabelece.** Um gene pode ser exigentemente
intolerante a perda de função sem doença curada, e um gene Definitivo pode ser irrestrito — o
pLI do CFTR é ~0 porque portadores são comuns e saudáveis. Ela entra no laudo para que uma
linha "sem validade estabelecida" possa acrescentar se o gene é ainda assim restrito, e por
nenhum outro motivo.

## PGS Catalog: 6.972 escores, e as duas coisas que decidem se algum pode ser usado

O PGS Catalog publica 6.972 escores poligênicos em 807 traços mapeados — muito mais traços do
que a rota do GWAS Catalog alcança. O que ele **não** publica é permissão para aplicar
qualquer um deles a uma pessoa específica, e dois campos decidem isso. Os dois são
computados, não estimados.

**A ancestralidade das coortes em que o escore foi construído.** Um escore poligênico é um
conjunto de pesos ajustado numa população, e sua acurácia cai — muitas vezes pela metade —
ao ser levado para outra, com frequências alélicas e desequilíbrio de ligação diferentes.
Para um genoma brasileiro miscigenado isso não é nota de rodapé, é a fonte dominante de erro:

| classe | escores |
|---|---:|
| **NÃO TRANSFERÍVEL SEM CALIBRAÇÃO** (coortes ≥90% europeias) | **4.361** |
| TRANSFERIBILIDADE INCERTA | 2.393 |
| **PARCIALMENTE TRANSFERÍVEL** (≥20% hispânica/latina, africana ou nativa) | **202** |
| ancestralidade não declarada pelo catálogo | 16 |

**O número de variantes, contra quantas um array consegue ler.** O escore mediano tem 123.613
variantes e o maior tem 10,3 milhões; um array de consumo carrega ~700.000 posições no genoma
inteiro. Somar os pesos das variantes presentes e tratar as ausentes como dose zero é a falha
por verdade vácua na forma mais pura: produz um número finito, plausível e errado, e nada na
saída diz que faltava a maior parte do escore. Abaixo de **95%** de cobertura o sistema recusa
em vez de emitir.

Nenhum peso é copiado para este repositório. Cada escore é citado pela URL do arquivo
harmonizado e pela **própria licença**, que não é uniforme: 6.879 são de citação, mas 31 são
CC BY-NC-ND, 7 são só para uso acadêmico e 1 é restrito a pesquisa. Um registro que achatasse
isso autorizaria um uso que o autor proibiu.

## O nível de revisão do ClinVar viaja com o alvo

O registro pode ser construído a partir de 2★ (consenso curado) ou de 1★ (submetente único),
e cada alvo declara o próprio `clinvar_review_stars`. Isso é o que torna o segundo seguro:

| corte | rsids | genes | genes só alcançáveis nesse corte |
|---|---:|---:|---:|
| 2★+ | 54.845 | 3.082 | — |
| só 1★ | 68.706 | — | 1.326 |
| união | **123.551** | **4.408** | |

Estes números são **derivados dos artefatos versionados**, não transcritos: saem de
`config/targets_clinvar_plp.json.gz` e `config/targets_clinvar_plp_1star.json.gz`, cujos
SHA-256 estão publicados abaixo. Reproduza com:

```bash
python3 - <<'PY'
import json, gzip
from pathlib import Path
def load(p):
    raw = Path(p).read_bytes()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
two = load("config/targets_clinvar_plp.json.gz")
one = load("config/targets_clinvar_plp_1star.json.gz")
genes = lambda d: {t[k] for t in d["targets"] for k in ("gene",) if isinstance(t.get(k), str) and t[k]}
r2 = {t["rsid"] for t in two["targets"]}; r1 = {t["rsid"] for t in one["targets"]}
print(len(r2), len(genes(two)))
print(len(r1 - r2), len(genes(one) - genes(two)))
print(len(r1), len(genes(one)))
PY
```

A tabela anterior publicava 54.801 / 74.161 / 123.541 e contagens de genes que não
correspondiam a nenhum campo dos artefatos. `só 1★` é a faixa exclusiva de uma estrela
(`target_statistics.tier_1_star`), não o total do arquivo de 1★ — e 54.845 + 68.706 = 123.551
fecha exatamente com o total publicado.

Um locus de uma estrela **nunca** vira achado acionável nem estado de portador: a
interpretação o rebaixa a `ACHADO PRELIMINAR`, com o texto dizendo que uma asserção de
submetente único é a opinião de um laboratório e não consenso curado. Sem esse rebaixamento,
baixar o corte reportaria dezenas de milhares de opiniões únicas como achados — que é
exatamente o motivo de o nível viajar com cada alvo. O painel de aplicação padrão é a união
de 1★ declarada no início deste documento; o gerador conserva 2★ como default fail-closed e
exige `--min-review-stars 1` para materializar explicitamente a alternativa ampliada.

## Por que o release em massa, e não a API

Curar 3.137 genes via E-utilities são ~10 mil requisições, uma hora de tráfego limitado, e
um rate limit de distância de um registro pela metade que *parece* completo.
`variant_summary.txt.gz` é o mesmo dado num download versionado: ou o arquivo está lá ou não
está. O mesmo vale para o GenCC e para o GWAS Catalog.

## Filtros do ClinVar, e por que cada um é recusa e não conveniência

> **Medição histórica não verificada:** a cadeia de contagens publicada anteriormente não
> fechava aritmeticamente entre 62.367 linhas e 54.845 alvos e não citava um artefato de
> saída com SHA-256. Os números intermediários foram removidos. O filtro reproduzível é:
> GRCh38, SNV, classificação P/LP exata, limiar explícito de estrelas, rsid presente e
> alelos A/C/G/T; as contagens devem ser lidas de `scan_statistics`,
> `target_statistics` e `totals` nos artefatos gerados pela execução.



Dos 54.845, **50.515** têm alelo avaliado único e **4.330** não: o ClinVar assere mais de uma
base alternativa na mesma coordenada, e escolher uma seria arbitrar. Esses loci só chegam a
OBSERVADO, nunca a NÃO DETECTADO.

## A junção por coordenada, nas duas rotas

A rota da API acha registros por **busca textual** de rsid, que devolve variantes não
relacionadas — em `rs4244285` devolveu doze. Esses registros não trazem coordenada própria e
só entram se o acesso constar do conjunto já verificado na coordenada do alvo.

A rota em massa lê acesso, classificação e coordenada da **mesma linha** do release. Não há
junção entre fontes a errar, e o registro carrega a coordenada — então ele entra quando ela
bate com a do locus. Isso é conferência feita no código, não um sinalizador que o arquivo de
evidência possa levantar para se isentar: registro sem coordenada volta para a lista de
acessos, seja qual for a proveniência que o arquivo declara.

## Escopo de traços: a única parte que é julgamento

O GWAS Catalog rotula cada associação com um termo de ontologia mas **não publica
categorização temática** — nada nele diz que intolerância à lactose é nutricional. Essa
decisão está em `config/trait_scopes.json`, com o ID de ontologia de cada termo e a
justificativa escrita. Tudo abaixo da lista — quais loci, qual alelo de risco, qual tamanho
de efeito, qual coorte de descoberta — vem do catálogo.

`scripts/build_trait_targets.py` **recusa** um termo declarado que não tenha nenhuma
associação de significância genômica no release. Dois termos caíram nessa guarda:

| termo | motivo |
|---|---|
| `GO_0050916` percepção de sabor doce | 56 associações, a mais forte p = 4e-07 — abaixo da significância genômica. Traço popular em relatório de consumo, sem locus estabelecido. |
| `MONDO_0100345` intolerância à lactose | zero associações mapeadas no release anotado. A persistência da lactase entra por `EFO_0801753` (rs4988235) e `OBA_VT0015043`, ambos verificados. |

## O conflito que a fusão encontrou

`rs3918290` é **multialélico** em chr1:97450058 (GRCh38, referência C):

* **C>T** = `c.1905+1G>A` = **DPYD\*2A**, classificado pelo ClinVar como *drug response* — é o
  alelo que o CPIC define;
* **C>G** = `c.1905+1G>C`, variante **diferente** na mesma posição, essa sim P/LP.

O filtro P/LP pegou o G; o CPIC declara o T. As duas fontes estão certas sobre variantes
distintas. Um rsid **não identifica uma variante** num sítio multialélico, e arbitrar teria
pontuado o genótipo contra a base errada num locus de toxicidade a fluoropirimidina. A fusão
remove o alelo avaliado e registra a divergência.

O custo é pequeno e correto: o passaporte farmacogenômico não é afetado, porque testa contra
o alelo do **seu** registro (CPIC), não contra o `assessed_allele` do alvo. Só a classe
NÃO DETECTADO da matriz de completude é retida naquele locus — que é o certo, já que "não
detectado" é ambíguo quando duas variantes clinicamente distintas ocupam uma posição.

## Escala observada numa execução de demonstração

**Ilustrativo, não verificado.** Os números abaixo vieram de uma execução local que não está
versionada: não há artefato de saída, SHA-256 de entrada, comando pinado nem versões de
ambiente em `docs/evidence/` que os sustentem, e nenhum teste ou gate os valida. Não são
evidência de release, e não devem ser citados como desempenho garantido. O que a seção
documenta são os três defeitos que a escala expôs. **Só um dos três é verificável neste
repositório neste SHA**, e a distinção está marcada em cada um abaixo — a afirmação anterior
de que as três correções "entraram no código, essas sim com teste" não se sustentava: nenhum
caminho de teste era citado, e ao procurá-los duas das três correções não foram localizadas
aqui.

Cadeia completa — QC, matriz de completude, passaporte PGx, junção clínica e os dez payloads
— sobre um array de 700.000 SNPs contra o painel de 55.916 alvos, com o registro expandido
como padrão:

```text
14 de 14 etapas OK, nenhuma bloqueada      (observação não verificada)
tempo: 20,5 s   |   pico de memória: 676 MB
matriz de completude: 23 MB   |   junção clínica: 59 MB
```

Chegar aí exigiu três correções que só a escala expôs, e as três eram defeitos reais:

**O arquivo de evidência não era legível.** *(VERIFICÁVEL AQUI.)* `build_clinical_findings`
lia a evidência com `read_text`, e o arquivo em massa tem 88 MB e viaja comprimido. O erro
era um `UnicodeDecodeError` sobre o byte `0x8b` — que não diz nada sobre a causa, e é a razão
de o registro expandido nunca ter sido o padrão. Agora passa pelo mesmo leitor que decide
compressão pelo número mágico do próprio arquivo:
`array_pipeline/clinical_findings.py`, chamada a `read_manifest_bytes`.

O teste que sustenta esta correção é
`tests/test_clinical_findings_regressions.py::test_the_gene_disease_evidence_may_arrive_compressed`,
adicionado ao registrar esta errata — antes dela **não havia teste algum** exercitando o
caminho comprimido, e a alegação de cobertura estava errada. Execute com:

```bash
python3 -m unittest discover -s tests -p test_clinical_findings_regressions.py
```

**O relatório 05 estava bloqueado em toda execução orquestrada.** *(NÃO VERIFICÁVEL AQUI.)*
`probe_path` seria posicional em `build_payload` e o orquestrador não o passava: um
`TypeError` na chamada, lido como recusa do relatório. Procurado neste SHA, o identificador
`probe_path` não ocorre em nenhum arquivo do repositório, e não há construtor para o
relatório 05 em `scripts/` — os únicos presentes são `build_one_page_summary.py` (relatório
10) e `build_pharmacogenomic_report.py` (relatório 06). O parágrafo permanece como narrativa
de uma execução de demonstração, sem código ou teste aqui que o sustente.

**Relatório 09 — observação histórica não verificável.** Como acima, não há construtor do
relatório 09 neste repositório nem implementação localizável, em `array_pipeline/` ou
`reporting/`, do comportamento de agregação descrito pela execução de demonstração. Sem
artefato de saída, SHA-256 de entrada, comando pinado e teste versionado, essa narrativa não
é atribuída ao HEAD atual. As contagens, limites de enumeração e reduções de tamanho antes
publicados foram removidos; só podem voltar como resultado quando houver evidência
reproduzível ligada ao SHA que os produz.

A primeira versão da junção clínica custava **391 MB e 2,8 GB de pico**, porque o bloco de
validade de cada gene era copiado em cada locus e loci nunca interrogados carregavam detalhe
que não têm. Normalizar — validade uma vez por gene em `gene_validity`, e para locus não
interrogado só identidade e motivo — trouxe para 40 MB sem perder informação: o detalhe está
no arquivo de evidência, citado por SHA-256, e a omissão é declarada em cada achado.

## Taxa de detecção, que era o objetivo

O relatório 03 citava um denominador sem poder interrogá-lo. Agora consegue, e emite a taxa
a cada execução. A citação abaixo é a saída de uma execução de demonstração —
**ilustrativa, não verificada**, sem artefato, SHA-256 ou comando pinado em `docs/evidence/`
por trás dela. O que é contratual é o formato e o denominador serem interrogáveis, não estes
valores:

> 2.236 de 162.943 variantes classificadas P/LP no ClinVar foram interrogadas, em 732 genes
> recessivos curados. Genes mais cobertos: ATM 58/3864; BRCA1 48/4302; BRCA2 44/5744;
> PAH 32/900; CFTR 24/1496.

É contagem de **variantes**, não de frequência alélica — variantes raras dominam a contagem e
comuns dominam a frequência, então isso limita quanto do catálogo foi coberto e nada diz
sobre quanto do risco foi. O texto do relatório diz isso em toda emissão.

## Reproduzir

```bash
curl -O https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
curl -O https://ftp.clinicalgenome.org/ClinGen_gene_curation_list_GRCh38.tsv
curl -O https://storage.googleapis.com/gcp-public-data--gnomad/release/4.1/constraint/gnomad.v4.1.constraint_metrics.tsv
python3 scripts/curate_panelapp.py            # varre as duas instâncias; recusa leitura curta
python3 scripts/expand_clinvar_targets.py \
    --clinvar-bulk variant_summary.txt.gz \
    --panelapp docs/evidence/PANELAPP_CURATION.json.gz \
    --clingen-dosage ClinGen_gene_curation_list_GRCh38.tsv \
    --gnomad-constraint gnomad.v4.1.constraint_metrics.tsv \
    --min-review-stars 1 \
    --targets-out config/targets_clinvar_plp_1star.json.gz \
    --evidence-out docs/evidence/GENE_DISEASE_VALIDITY_BULK_1STAR.json.gz
python3 scripts/build_trait_targets.py \
    --associations gwas-catalog-associations_ontology-annotated-full.zip \
    --ancestries gwas-catalog-download-ancestries-v1.0.3.1.txt
python3 scripts/merge_target_manifests.py \
    config/partial_genome_annotation_targets.json \
    config/pgx_panel_targets.json \
    config/targets_clinvar_plp_1star.json.gz \
    config/targets_gwas_traits.json \
    --output config/targets_merged_panel_1star.json.gz
```

## Procedência das contagens publicadas

As URLs acima **não fixam release nem digest**. ClinVar, ClinGen, gnomAD e PanelApp são fontes
mutáveis: executar o bloco em outra data produz registros e contagens diferentes das
publicadas aqui, e isso não é um defeito da reprodução — é a natureza das fontes.

O que fica fixo é o outro lado. Toda contagem deste documento foi lida dos artefatos abaixo,
como versionados neste commit. Recontar a partir deles é determinístico; recoletar das fontes
não é.

| Artefato | SHA-256 |
| --- | --- |
| `config/targets_clinvar_plp.json.gz` | `8afcfa91ffe98407ca16685a2d85a2794bf54984c9120aa46c38307b462e97fd` |
| `config/targets_clinvar_plp_1star.json.gz` | `dfee157e673bad8611076ea5d3f57037fc7cc38b8dc4731f8be918e1d2b852f8` |
| `config/targets_merged_panel.json.gz` | `955cfe674d02c85eb9b5f18a726f1a60f392caf4f26f138d9d218699d903dbc9` |
| `config/targets_merged_panel_1star.json.gz` | `d9d57f109c212c5248bd680e5044e093dee352a13fa11c0731cf731e35e2c40a` |
| `config/targets_gwas_traits.json` | `920ee4ad18ca5c17546a240ba89b1e226d20d18ee280352d37ee1879c6cd18e9` |
| `docs/evidence/PANELAPP_CURATION.json.gz` | `ed5d495c68ec50782848873f5c7960d8532db30cd3045605157aea4c9449d54c` |
| `docs/evidence/GENE_DISEASE_VALIDITY_1STAR.json.gz` | `39aedaa763db55812ee4bf230e8c02068da012b034ffa7d78d23fff64c42a925` |
| `docs/evidence/PGS_CATALOG_REGISTRY.json.gz` | `a3f4c61c672850e0f18d915d6e4460d7731ca859e2e2f3de25aa9d959f024cbd` |

Os SHA-256 da tabela são dos **bytes dos arquivos versionados**. Alguns JSON também carregam
um campo interno `sha256` para o payload lógico; esse digest interno tem outro escopo e não
substitui o hash do arquivo `.json`/`.json.gz` armazenado no repositório. Os dois novos hashes
foram reexecutados neste HEAD com `sha256sum`.

Para comparar uma nova coleta com o publicado, gere os artefatos, confira o SHA-256 contra a
tabela e trate qualquer divergência como fonte atualizada, não como erro de reprodução.
