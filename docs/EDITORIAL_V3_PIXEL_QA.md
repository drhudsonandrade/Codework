# GENOMA v3.0 — editorial renderer and visual regression contract

## Objective

The final result must preserve the geometry and visual system of the 11 v3.0 models without freezing model values, placeholders, or obsolete normative identity. PDF is the authoritative visual artifact. DOCX is the high-fidelity editable artifact and is explicitly treated as renderer-dependent.

## External private template pack

The 11 reference PDFs are not copied into the repository. `reporting/reference_v3_manifest.json` records filename, page count, SHA-256, dynamic fields, and controlled regions. `scripts/install_report_templates.py` installs only a pack that passes all 11/11 hashes and page counts.

Configure at runtime:

```bash
export GENOMA_REPORT_TEMPLATE_DIR=/srv/genoma/templates/v3.0
python3 scripts/install_report_templates.py \
  --source-dir /caminho/pack-aprovado \
  --target-dir "$GENOMA_REPORT_TEMPLATE_DIR" \
  --evidence results/editorial/template-install.json
```

## Pixel-by-pixel rule

Comparing the reference PDF with the entire result and requiring zero changed pixels globally would be semantically wrong: case data, placeholders, and some model text must change. The contract is therefore:

> **zero changed pixels outside the dynamic/controlled regions declared in the manifest**.

The dynamic region includes the placeholder box and the bounded area intended for the replacement value. The controlled region includes only text that must change from MODELO to RESULTADO or correct normative identity. Everything else on the page is the reference PDF itself and must remain visually invariant.

QA executed on 2026-08-16:

- 11/11 reports generated in `template-v3` strict mode with no unresolved fields;
- page counts: 10,10,10,10,11,9,9,9,9,1,12 — exactly the models;
- local comparison at 200 DPI: 11/11 `VERIFICADO`, 0 changed pixels outside allowed regions;
- independent Poppler/pdftoppm confirmation: 11/11 `VERIFICADO` in the rasterization smoke test;
- report 10: 1 page, DATA and VERSÃO peer-bounded, with no visual collision.

Versioned evidence:

- `docs/evidence/EDITORIAL_V3_PDF_PIXEL_QA_200DPI_2026-08-16.json`
- `docs/evidence/EDITORIAL_V3_PDF_PIXEL_QA_POPPLER_72DPI_2026-08-16.json`
- `docs/evidence/EDITORIAL_V3_DOCX_VISUAL_QA_2026-08-16.json`

## DOCX

DOCX uses the reference page converted to SVG as a static visual plate, with PNG fallback, and case values in editable VML text boxes. During QA the file was re-rendered through LibreOffice for every page of all 11 reports, with page counts preserved and no clipping/overlap observed in the synthetic fixture.

**Do not describe DOCX as renderer-independent pixel-identical.** Word, LibreOffice, and other engines rasterize and antialias differently. The correct contract is:

- PDF: `VERIFICADO` static pixel-by-pixel parity outside dynamic/controlled regions;
- DOCX: high visual fidelity + editable fields + `VERIFICADO` rendering QA;
- PDF remains the authoritative final publication artifact.

## Fail closed

`template_fields_complete=true` activates strict mode. If any required field lacks an explicit value (including `NÃO DISPONÍVEL` where appropriate), the renderer refuses the final PDF/DOCX. An incorrect hash or missing pack also blocks publication.
