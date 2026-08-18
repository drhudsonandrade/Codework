# GENOMA v3.0 - renderer editorial e contrato de regressão visual

## Objetivo

O resultado final deve preservar a geometria e o sistema visual dos 11 modelos v3.0 sem congelar valores de modelo, placeholders ou identidade normativa obsoleta. O PDF é o artefato visual autoritativo. O DOCX é o artefato editável de alta fidelidade e é explicitamente tratado como dependente do renderer.

## Template pack externo e privado

Os 11 PDFs de referência não são copiados para o repositório. `reporting/reference_v3_manifest.json` registra filename, número de páginas, SHA-256, campos dinâmicos e regiões controladas. `scripts/install_report_templates.py` só instala um pack que passe 11/11 hashes e page counts.

Configure em runtime:

```bash
export GENOMA_REPORT_TEMPLATE_DIR=/srv/genoma/templates/v3.0
python3 scripts/install_report_templates.py \
  --source-dir /caminho/pack-aprovado \
  --target-dir "$GENOMA_REPORT_TEMPLATE_DIR" \
  --evidence results/editorial/template-install.json
```

## Regra pixel-a-pixel

Comparar o PDF de referência com o resultado inteiro e exigir zero pixels alterados globalmente seria semanticamente incorreto: dados do caso, placeholders e alguns textos de modelo precisam mudar. Por isso o contrato é:

> **zero pixels alterados fora das regiões dinâmicas/controladas declaradas no manifest**.

A região dinâmica inclui a caixa do placeholder e a área limitada destinada ao valor substituto. A região controlada inclui somente textos que precisam mudar de MODELO para RESULTADO ou corrigir identidade normativa. Todo o restante da página é o próprio PDF de referência e deve permanecer visualmente invariável.

## Produtor e evidência

`scripts/run_editorial_pixel_qa.py` é o **produtor** da evidência: ele instala o pacote
aprovado, renderiza cada relatório pelo caminho template-v3 real e compara o raster contra
o PDF de referência, contando apenas pixels fora das máscaras compiladas.

Antes existia o arquivo de evidência mas nenhum código capaz de gerá-lo — o PASS não podia
ser reproduzido nem contestado. Agora pode:

```bash
python3 scripts/verify_template_store.py --materialize /srv/genoma/templates/raw
python3 scripts/install_report_templates.py \
  --source-dir /srv/genoma/templates/raw --target-dir /srv/genoma/templates/v3.0
python3 scripts/run_editorial_pixel_qa.py \
  --template-dir /srv/genoma/templates/v3.0 \
  --output docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI.json
```

Execução medida em 18/08/2026 — `docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI_2026-08-18.json`:

- `VERIFICADO`, 11 relatórios, 100 páginas, **0 pixels alterados** fora das máscaras;
- page counts 10,10,10,10,11,9,9,9,9,1,12 — exatamente os modelos;
- reproduz o agregado registrado em 16/08/2026, agora por medição própria.

O `.github/workflows/genoma-visual-qa-candidates.yml` **executa** o QA a cada corrida, em
vez de apenas reler evidência armazenada.

### Por que o PASS não é vazio

`tests/test_editorial_pixel_qa.py` fixa a sensibilidade da comparação: diferença dentro de
máscara é ignorada, diferença fora é detectada — inclusive uma alteração menor que um glifo
— e rasters de tamanhos distintos nunca são reportados como aprovados. Sem isso, um "0
pixels alterados" poderia significar apenas que a comparação não olha nada.

As máscaras são dilatadas em `mask_padding_pt` (1,0 pt) para absorver antialiasing na borda;
o valor é declarado na evidência e coberto por teste para não crescer a ponto de esconder
deriva real.

### Defeito encontrado ao exercitar o caminho real

Com o pacote instalado, o compilador de coordenadas revelou um defeito sério. A extração de
texto do PDF parte um placeholder onde o tipógrafo quebrou a linha, e o compilador junta os
spans com `\n`. Quando o par de fechamento caía nessa quebra (`...ANCESTRALIDADE]` + `\n` +
`]`), a regex não fechava ali e **corria até o `]]` do próximo token**, produzindo um
placeholder falso de 470×106 pt sobre o corpo da página.

Duas consequências, ambas piores que cosméticas:

- os tokens engolidos sumiam do inventário — **18 placeholders em 6 relatórios** nunca
  seriam preenchidos;
- o retângulo falso virava **máscara**, e o QA de pixel exclui regiões mascaradas por
  construção. O QA jamais poderia ter detectado o estrago que ele mesmo escondia.

Corrigido tolerando espaço entre os colchetes (`\[\s*\[.*?\]\s*\]`) e recusando, com erro,
qualquer token que contenha outro par de colchetes. As contagens fixadas eram sintoma e
foram recorrigidas: 1131 → **1149** placeholders. Colisões de bbox caíram de 12 para **0** e
a maior máscara de 49.700 para 4.387 pt². O QA de pixel continua em 0 pixels alterados —
agora medindo uma área bem maior.

### Paridade DOCX — medida

`scripts/run_docx_parity_qa.py` converte cada DOCX via LibreOffice Writer headless e separa
duas coisas que não podem ser confundidas:

- **Paridade estrutural (gate):** contagem de páginas e geometria devem bater com o modelo.
  Medido: 11 relatórios, 100 páginas, geometria preservada em todas.
- **Similaridade visual (observada, não gated em igualdade):** fração de pixels diferentes e
  RMSE. Medido: pior caso 11,1% e RMSE 32,8.

O envelope (25% / RMSE 60) foi **derivado da medição**, não escolhido a priori, e existe só
para pegar regressão catastrófica — plate perdido, página em branco. Ele **não** é alegação
de paridade de pixel: DOCX é dependente de engine, e Word renderizará diferente.

Evidência: `docs/evidence/EDITORIAL_V3_DOCX_PARITY_150DPI_2026-08-18.json`.

### Controles ainda sem artefato — NÃO DISPONÍVEL

| ITEM | STATUS | MOTIVO | PRÓXIMO PASSO |
|---|---|---|---|
| Paridade DOCX em Microsoft Word | NÃO DISPONÍVEL | medido apenas em LibreOffice Writer; Word não está disponível nesta sessão | medir em Word e commitar a evidência |

## DOCX

O DOCX usa a página de referência convertida para SVG como placa visual estática, com PNG fallback, e valores do caso em textboxes VML editáveis. A geração pelo caminho template-v3 está exercitada e coberta (`tests/test_template_v3_contract.py` produz o relatório 10 em modo strict e confirma um pacote OOXML editável com campos `GENOMA_FIELD_` e `svgBlip`), o que exige `poppler-utils` na sessão.

A **paridade estrutural** está medida (páginas e geometria idênticas em 100 páginas). A **paridade de pixel** continua fora do escopo do que este projeto pode alegar para DOCX: o resultado depende do engine, e a diferença residual medida em LibreOffice (até 11,1% dos pixels) é esperada, não é defeito.

**Não declarar DOCX como pixel-idêntico de forma renderer-independent.** Word, LibreOffice e outros engines fazem rasterização/antialiasing diferentes. O contrato correto é:

- PDF: paridade estática pixel-a-pixel `VERIFICADO` fora das regiões dinâmicas/controladas;
- DOCX: paridade estrutural `VERIFICADO` (páginas + geometria) e similaridade visual medida e registrada; paridade de pixel nunca é alegada;
- PDF continua sendo o artefato final autoritativo para publicação.

## Fail closed

`template_fields_complete=true` ativa strict mode. Se qualquer campo obrigatório não tiver valor explícito (inclusive `NÃO DISPONÍVEL` quando apropriado), o renderer recusa o PDF/DOCX final. Hash incorreto ou pack ausente também bloqueia a publicação.
