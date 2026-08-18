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

### Controles ainda sem artefato — NÃO DISPONÍVEL

| ITEM | STATUS | MOTIVO | PRÓXIMO PASSO |
|---|---|---|---|
| QA visual de renderização DOCX | NÃO DISPONÍVEL | paridade DOCX depende do engine (Word/LibreOffice); nenhuma medição registrada | re-renderizar via LibreOffice e commitar a evidência |
| Relatório 10 sem colisão visual (DATA/VERSÃO peer-bounded) | NÃO DISPONÍVEL | inspeção visual não registrada em artefato | registrar a verificação no JSON de QA |

## DOCX

O DOCX usa a página de referência convertida para SVG como placa visual estática, com PNG fallback, e valores do caso em textboxes VML editáveis. A geração pelo caminho template-v3 está exercitada e coberta (`tests/test_template_v3_contract.py` produz o relatório 10 em modo strict e confirma um pacote OOXML editável com campos `GENOMA_FIELD_` e `svgBlip`), o que exige `poppler-utils` na sessão.

A **paridade visual de renderização** do DOCX continua `NÃO DISPONÍVEL`: Word, LibreOffice e outros engines rasterizam de forma diferente, e não há medição registrada. Estrutura verificada não é o mesmo que paridade medida.

**Não declarar DOCX como pixel-idêntico de forma renderer-independent.** Word, LibreOffice e outros engines fazem rasterização/antialiasing diferentes. O contrato correto é:

- PDF: paridade estática pixel-a-pixel `VERIFICADO` fora das regiões dinâmicas/controladas;
- DOCX: alta fidelidade visual + campos editáveis; QA de renderização `NÃO DISPONÍVEL`;
- PDF continua sendo o artefato final autoritativo para publicação.

## Fail closed

`template_fields_complete=true` ativa strict mode. Se qualquer campo obrigatório não tiver valor explícito (inclusive `NÃO DISPONÍVEL` quando apropriado), o renderer recusa o PDF/DOCX final. Hash incorreto ou pack ausente também bloqueia a publicação.
