# Expansão do registro de alvos

## O que mudou

| registro | alvos | fonte |
|---|---:|---|
| `partial_genome_annotation_targets.json` | 29 | curadoria manual (ClinVar + CPIC + dbSNP) |
| `pgx_panel_targets.json` | 342 | posições definidoras do CPIC |
| `targets_clinvar_plp.json.gz` | **54.845** | release em massa do ClinVar, P/LP, 2★+ |
| `targets_gwas_traits.json` | **733** | GWAS Catalog, termos declarados |
| `targets_merged_panel.json.gz` | **55.916** | união dos quatro |

Genes cobertos: de 16 para **3.082**, dos quais **2.776** têm relação gene-doença
estabelecida em nível Definitivo ou Forte por ClinGen ou GenCC.

## Por que o release em massa, e não a API

Curar 3.137 genes via E-utilities são ~10 mil requisições, uma hora de tráfego limitado, e
um rate limit de distância de um registro pela metade que *parece* completo.
`variant_summary.txt.gz` é o mesmo dado num download versionado: ou o arquivo está lá ou não
está. O mesmo vale para o GenCC e para o GWAS Catalog.

## Filtros do ClinVar, e por que cada um é recusa e não conveniência

```
9.044.810 linhas
→ 4.488.630  Assembly = GRCh38        (misturar builds põe a variante na coordenada errada)
→ 4.161.194  single nucleotide        (sonda de array lê substituição de base; indel não é interrogável)
→   190.191  P/LP exato               ("Conflicting classifications of pathogenicity" contém a
                                       palavra e assere o oposto — comparação é por string inteira)
→    62.367  2★ ou mais               (127.824 P/LP têm um submetente só; opinião única não é
                                       asserção curada)
→    62.367  com rsid e bialélico ACGT
→    54.845  alvos únicos             (13 descartados por rsid em duas coordenadas)
```

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

## Escala medida

Cadeia completa sobre um array de 700.000 SNPs contra o painel de 55.916 alvos:

```
tempo: 11 s   |   pico de memória: 803 MB
matriz de completude: 25 MB   |   junção clínica: 68 MB
```

A primeira versão da junção clínica custava **391 MB e 2,8 GB de pico**, porque o bloco de
validade de cada gene era copiado em cada locus e loci nunca interrogados carregavam detalhe
que não têm. Normalizar — validade uma vez por gene em `gene_validity`, e para locus não
interrogado só identidade e motivo — trouxe para 40 MB sem perder informação: o detalhe está
no arquivo de evidência, citado por SHA-256, e a omissão é declarada em cada achado.

## Taxa de detecção, que era o objetivo

O relatório 03 citava um denominador sem poder interrogá-lo. Agora:

> 2.236 de 162.943 variantes classificadas P/LP no ClinVar foram interrogadas, em 732 genes
> recessivos curados. Genes mais cobertos: ATM 58/3864; BRCA1 48/4302; BRCA2 44/5744;
> PAH 32/900; CFTR 24/1496.

É contagem de **variantes**, não de frequência alélica — variantes raras dominam a contagem e
comuns dominam a frequência, então isso limita quanto do catálogo foi coberto e nada diz
sobre quanto do risco foi. O texto do relatório diz isso em toda emissão.

## Reproduzir

```bash
curl -O https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
python3 scripts/expand_clinvar_targets.py --clinvar-bulk variant_summary.txt.gz
python3 scripts/build_trait_targets.py \
    --associations gwas-catalog-associations_ontology-annotated-full.zip \
    --ancestries gwas-catalog-download-ancestries-v1.0.3.1.txt
python3 scripts/merge_target_manifests.py \
    config/partial_genome_annotation_targets.json \
    config/pgx_panel_targets.json \
    config/targets_clinvar_plp.json.gz \
    config/targets_gwas_traits.json \
    --output config/targets_merged_panel.json.gz
```
