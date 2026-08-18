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

QA executado em 16/08/2026, com artefato versionado:

- comparação estática a 200 DPI: `VERIFICADO`, 11 relatórios, 100 páginas de referência,
  **0 pixels alterados** fora das regiões dinâmicas/controladas declaradas;
- page counts: 10,10,10,10,11,9,9,9,9,1,12 — exatamente os modelos.

Evidência versionada — a única:

- `docs/evidence/EDITORIAL_V3_STATIC_PIXEL_QA_200DPI_2026-08-16.json`

Cada execução verificada nesse arquivo é reconferida no CI por
`.github/workflows/genoma-visual-qa-candidates.yml`, que liga os SHA-256 dos PDFs de
referência, as contagens de página e de placeholders ao `reporting/reference_v3_manifest.json`.

### Controles sem artefato — NÃO DISPONÍVEL

Não existe evidência versionada para os itens abaixo. Pelo Capability Gate, eles não podem
ser declarados executados até que o artefato correspondente seja produzido e commitado:

| ITEM | STATUS | MOTIVO | PRÓXIMO PASSO |
|---|---|---|---|
| Rasterização independente Poppler/pdftoppm | NÃO DISPONÍVEL | nenhum artefato de execução no repositório | rodar o smoke e commitar a evidência em `docs/evidence/` |
| QA visual de renderização DOCX | NÃO DISPONÍVEL | nenhum artefato de execução no repositório | re-renderizar via LibreOffice e commitar a evidência |
| Relatório 10 sem colisão visual (DATA/VERSÃO peer-bounded) | NÃO DISPONÍVEL | inspeção não registrada em artefato | registrar a verificação no JSON de QA |

## DOCX

O DOCX usa a página de referência convertida para SVG como placa visual estática, com PNG fallback, e valores do caso em textboxes VML editáveis. A re-renderização via LibreOffice para todas as páginas dos 11 relatórios está `NÃO DISPONÍVEL`: não há artefato dessa execução no repositório. `tests/test_editorial_renderers.py` cobre apenas a estrutura do DOCX (é um pacote OOXML válido, editável, com os campos e o SVG esperados), o que não é o mesmo que QA de renderização.

**Não declarar DOCX como pixel-idêntico de forma renderer-independent.** Word, LibreOffice e outros engines fazem rasterização/antialiasing diferentes. O contrato correto é:

- PDF: paridade estática pixel-a-pixel `VERIFICADO` fora das regiões dinâmicas/controladas;
- DOCX: alta fidelidade visual + campos editáveis; QA de renderização `NÃO DISPONÍVEL`;
- PDF continua sendo o artefato final autoritativo para publicação.

## Fail closed

`template_fields_complete=true` ativa strict mode. Se qualquer campo obrigatório não tiver valor explícito (inclusive `NÃO DISPONÍVEL` quando apropriado), o renderer recusa o PDF/DOCX final. Hash incorreto ou pack ausente também bloqueia a publicação.
