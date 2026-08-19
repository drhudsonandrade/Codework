# Guia editorial da suíte de relatórios

Gerado por `scripts/build_editorial_guide.py` em 19/08/2026. **Não editar à mão**: 
o conteúdo é derivado de `reporting/catalog.json`, do manifesto de coordenadas dos 
templates selados, das tabelas de resolvers de `reporting/template_fill.py` e do 
contrato de `reporting/case_dossier.py`. Editar aqui cria uma segunda cópia que 
envelhece na primeira mudança de resolver.

Nenhum dado de genótipo é lido para gerar este arquivo.

## Como ler a contagem de campos

Um template com 200 campos preenchíveis dos quais 55 são deriváveis **não** é um 
documento 27% pronto. É um documento que imprimirá NÃO DISPONÍVEL 145 vezes se o 
dossiê do caso não for preenchido. Cerca de 60% de todo template v3.0 é administrativo 
— quem é a pessoa, quem pediu, sob qual consentimento, assinado por quem — e nada disso 
sai de um arquivo de genótipos. As três colunas abaixo separam:

* **resolver** — o pipeline responde a partir de artefato medido;
* **dossiê** — só o operador responde, via `--dossier`;
* **ninguém** — nem o pipeline nem o dossiê respondem; imprime NÃO DISPONÍVEL sempre.

## Panorama

| # | Código | Relatório | Campos | Resolver | Dossiê | Ninguém | Produtor de dados |
|---|--------|-----------|-------:|---------:|-------:|--------:|-------------------|
| 01 | GCL | Relatório de Genoma Clínico | 129 | 31 | 11 | 62 | `scripts/build_clinical_report.py` |
| 02 | ANG | Ancestralidade e Genealogia Genética | 116 | 25 | 11 | 55 | `scripts/build_ancestry_report.py` |
| 03 | REP | Relatório Genômico Reprodutivo | 135 | 29 | 11 | 45 | `scripts/build_reproductive_report.py` |
| 04 | NUT | Nutrigenética e Nutrição de Precisão | 112 | 23 | 11 | 57 | `scripts/build_association_report.py --report 04` |
| 05 | TEC | Relatório Técnico de Métodos, QC e Limitações | 200 | 17 | 11 | 72 | `scripts/build_technical_report.py` |
| 06 | PGX | Farmacogenômica e Cartão Genômico de Anestesia | 91 | 28 | 12 | 25 | `scripts/build_pharmacogenomic_report.py` |
| 07 | LON | Longevidade, Proteção e Prevenção | 90 | 23 | 11 | 34 | `scripts/build_association_report.py --report 07` |
| 08 | ATL | Atlas de Traços e Curiosidades | 81 | 25 | 11 | 23 | `scripts/build_association_report.py --report 08` |
| 09 | GCM | Genome Completeness & Blind Spots | 83 | 25 | 11 | 25 | `scripts/build_completeness_report.py` |
| 10 | R1P | Resumo Clínico Genômico — Uma Página | 26 | 12 | 0 | 11 | `scripts/build_one_page_summary.py` |
| 11 | GED | Guia Editorial e Matriz de Preenchimento | 75 | 21 | 12 | 20 | `scripts/build_editorial_guide.py` |

Total: 1138 campos preenchíveis na suíte; 259 tokens distintos por relatório têm resolver, 112 vêm do dossiê, 429 não têm origem declarada.

## Por relatório

### 01 — Relatório de Genoma Clínico (GCL)

*Público:* Pessoa avaliada, médico assistente, geneticista e equipe multiprofissional

*Produtor de dados:* `scripts/build_clinical_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Resumo clínico executivo
3. Pergunta clínica, fenótipo e heredograma
4. Achados clínicos e diagnósticos
5. Predisposições, risco e achados negativos
6. Confirmação, pontos cegos e reanálise
7. Fontes e Execution Manifest

*Tokens com resolver (31):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ACHADO_OU_NENHUM`, `CLINICO_OU_PREDISPOSICAO`, `CONFIRMACAO`, `CURADORIA_GENE_DOENCA_E_VARIANTE`, `DATA`, `DATA_EMISSAO`, `ESCOPO_EXATO`, `GENES_E_CLASSES`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENE_VARIANTE_CONDICAO`, `IDENTIFICACAO`, `INTERPRETACAO_CURTA`, `LABORATORIO_E_PLATAFORMA`, `LIMITACOES_RESIDUAIS`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO`, `NIVEL_E_FONTES`, `NOME_OU_ID_PSEUDONIMIZADO`, `N_ACHADOS_P1_P2`, `N_CONFIRMACOES`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `RESULTADO_NEGATIVO`, `STATUS`, `STATUS_OPERACIONAL`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (62):* `ACAO`, `ACAO_CONFIRMATORIA_OU_CLINICA`, `AUTORIZA_ACHADOS_DE_INICIO_ADULTO_EM_MENORES`, `AUTORIZA_ACHADOS_SECUNDARIOS_ACMG`, `AUTORIZA_FARMACOGENOMICA`, `AUTORIZA_RECONTATO_E_REANALISE`, `AUTORIZA_STATUS_DE_PORTADOR`, `CALIBRACAO_ANCESTRALIDADE`, `CANAL_CONSENTIDO`, `CASCATA_POTENCIAL`, `CLASSE_E_CRITERIOS`, `COBERTURA_BALANCO_ALELICO_QUALIDADE`, `CONDUTA_POTENCIAL_E_DIRETRIZ`, `CONFIRMACAO_OU_CONSULTA`, `CONFLITOS_LACUNAS_E_DATA_LIMITE`, `COSEGREGACAO`, `CRITERIO`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DATA_OU_GATILHO`, `DESFECHO`, `DOENCA_MONDO_OMIM_E_HERANCA`, `DOMINIO`, `FAMILIARES_DISPONIVEIS`, `FIT_FENOTIPICO` (+38)

### 02 — Ancestralidade e Genealogia Genética (ANG)

*Público:* Pessoa avaliada, familiares, genealogistas e consultores de ancestralidade

*Produtor de dados:* `scripts/build_ancestry_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Retrato das origens
3. Qualidade, painel e sensibilidade
4. Linhagens materna e paterna
5. Parentesco genético e triangulação
6. DNA antigo e contexto histórico
7. Limitações e fontes

*Tokens com resolver (25):* `ARVORE_VERSAO`, `DATA`, `DATA_EMISSAO`, `HAPLOGRUPO_HAPLOTIPO_IBD_AFINIDADE`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LACUNAS`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO_VERSAO_QUALIDADE`, `METRICAS_E_LIMIARES`, `MODELO_VERSAO_REFERENCIA`, `NOME_OU_ID_PSEUDONIMIZADO`, `NOME_VERSAO_N_AMOSTRAS`, `N_SNP_POS_QC`, `PLATAFORMA`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `STATUS`, `SUBCLADO_MT`, `SUBCLADO_Y_OU_NA`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (55):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `AFINIDADE_OU_LINHAGEM`, `AJUSTE`, `ALTA_MEDIA_BAIXA`, `AMOSTRA_OU_FIGURA`, `ARQUIVO_REGISTRO_FAMILIAR`, `ASSOCIACAO_HIPOTESE`, `BOOTSTRAP_SEEDS_CENARIOS`, `BUILD`, `CHR`, `CLASSE_IBD`, `CLUSTER_LADO`, `CM_E_SNPS`, `CM_MAIOR`, `CM_TOTAL`, `COMPARACAO`, `CONFIANCA`, `CONTEXTO`, `COORDENADAS`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DATA_LOCAL`, `DELTA`, `DOI_REPOSITORIO_E_COBERTURA`, `ESTAVEL_OU_SENSIVEL` (+31)

### 03 — Relatório Genômico Reprodutivo (REP)

*Público:* Pessoa/casal, geneticista, obstetra, reprodução assistida e aconselhamento genético

*Produtor de dados:* `scripts/build_reproductive_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Resumo para o casal
3. Escopo individual e comparabilidade
4. Achados de portador por pessoa
5. Risco combinado e fase
6. Opções, confirmação e aconselhamento
7. Limitações e fontes

*Tokens com resolver (29):* `ACONSELHAMENTO`, `AR_XL_AD_MT_OUTRO`, `COBERTURA_A`, `CONDICAO_GENE`, `CONFIRMACAO_VARIANTES`, `DATA`, `DATA_EMISSAO`, `ENCAMINHAMENTO`, `ESCOPO_A`, `FAIXA_RESIDUAL`, `GENOTIPO`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LACUNAS`, `LIMITES`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO`, `NOME_OU_ID_PSEUDONIMIZADO`, `N_PORTADOR_A`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `RESIDUAL`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`, `ZIGOSIDADE`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (45):* `ACAO`, `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ALVO_DIAGNOSTICO`, `ALVO_FAMILIAR`, `AMBOS_PORTADORES_E_FASE`, `ASPECTOS`, `A_B_CASAL_FAMILIAR`, `CENARIO`, `CLASSE_CRITERIOS`, `COBERTURA_B`, `COMPLEMENTAR`, `CONDICAO`, `CONTEXTO_CONSENTIDO`, `CONTEXTO_SE_VALIDO`, `DADO_E_METODO`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DEPENDENCIA`, `DESENHO_E_VALIDACAO`, `ESCOPO_B`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENE_MANE`, `GESTACOES_PERDAS_DIAGNOSTICOS`, `HGVS`, `LAUDO_OU_NAO_DISPONIVEL` (+21)

### 04 — Nutrigenética e Nutrição de Precisão (NUT)

*Público:* Pessoa avaliada, nutricionista, médico e equipe de saúde

*Produtor de dados:* `scripts/build_association_report.py --report 04`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Resumo nutricional acionável
3. Contexto clínico e nutricional
4. Matriz gene–nutriente–fenótipo
5. Módulos de interpretação
6. Experimentos e monitorização
7. Limitações e fontes

*Tokens com resolver (23):* `BETA_OR_RR_IC`, `COORTE_ANCESTRALIDADE`, `DATA`, `DATA_EMISSAO`, `EVIDENCIA_E_EFEITO`, `FATO_ASSOCIACAO_HIPOTESE`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENETICA_FENOTIPO`, `GENE_RS_HGVS`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `NIVEL_EVIDENCIA`, `NOME_OU_ID_PSEUDONIMIZADO`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `RISCO_E_RESPOSTA`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (57):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `BIOMARCADOR`, `COMO_MEDIR`, `CONDUTA_PROFISSIONAL`, `CONTEXTO`, `CONTEXTO_CLINICO`, `CRITERIO_SEGURANCA`, `DADOS_ATUAIS`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DESFECHO`, `DOSE_OU_META`, `EVENTO`, `GENETICA_CONSUMO_SINTOMA`, `GENETICA_EXAME_DIETA`, `GENOTIPO`, `HIPOTESE`, `INTERPRETACAO`, `INTERVENCAO`, `INTERVENCAO_PADRAO`, `JEJUM_MEDICACAO_OUTRO`, `LACTOSE_CELIACA_OUTRAS`, `LAUDO_OU_NAO_DISPONIVEL`, `LIMITE_INDIVIDUAL`, `MANTER_AJUSTAR_PARAR` (+33)

### 05 — Relatório Técnico de Métodos, QC e Limitações (TEC)

*Público:* Laboratório, bioinformática, geneticista, auditor e leitor leigo interessado

*Produtor de dados:* `scripts/build_technical_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Resumo leigo do exame
3. Contrato de entrada e cadeia de custódia
4. Plataforma e desempenho analítico
5. Pipeline reproduzível
6. Genome Completeness Matrix
7. Runtime/Resource Gate
8. Limitações e fontes

*Tokens com resolver (17):* `DATA`, `DATA_EMISSAO`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO`, `NOME_OU_ID_PSEUDONIMIZADO`, `PERCENTUAL`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (72):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ADEQUACAO`, `AMOSTRA_E_TECNOLOGIA`, `ARQUIVO_OU_AMOSTRA`, `BYTES`, `CALLABILITY_E_COBERTURA`, `CAMINHO_HASH`, `CASE_RUN_BATCH_ID`, `CHECK`, `CLASSE`, `CLASSES_EXECUTADAS`, `CLINVAR_GNOMAD_CLINGEN_OUTRO`, `CONCORDANCIA`, `CONFIGURACAO`, `CONSULTA`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DOMINIO_VALIDADO`, `DUPLA_REVISAO`, `ESCOPO_E_VERSAO`, `ESTIMATIVA`, `ESTIMATIVA_IC`, `ESTUDO`, `ETAPA`, `EVENTOS_E_RESPONSAVEIS` (+48)

### 06 — Farmacogenômica e Cartão Genômico de Anestesia (PGX)

*Público:* Pessoa avaliada, prescritores, farmacêuticos, anestesiologistas e emergência

*Produtor de dados:* `scripts/build_pharmacogenomic_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Resumo farmacogenômico
3. Medicações e fenoconversão
4. Camada técnica por gene
5. Cartão genômico de anestesia
6. Plano de atualização
7. Limitações e fontes

*Tokens com resolver (28):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `DATA`, `DATA_EMISSAO`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DIPLOTIPO`, `ESCOPO`, `FENOCONVERSAO`, `FENOTIPO_PADRONIZADO`, `FONTE_VERSAO`, `GENE`, `GUIDELINE_ALELO_CARTAO`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LIMITACAO`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO`, `NOME_OU_ID_PSEUDONIMIZADO`, `PROFISSIONAIS_E_DECISOES_FORA_DO_ESCOPO`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `RELATORIO_QC`, `STAR_ALLELES`, `STATUS`, `TERMOS_CPIC`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_DATA`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (12):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `NOME_OU_ID_E_DATA_NASCIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (25):* `ACTIVITY_SCORE`, `CONSIDERAR_ACAO`, `DOSE`, `FARMACO`, `FUNCAO`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENE_CONDICAO_FENOTIPO_CONFIRMADO`, `IMPLICACAO`, `INDICACAO`, `INTERACAO`, `LAB_DATA_METODO`, `LAUDO_OU_NAO_DISPONIVEL`, `MUDANCA`, `NIVEL`, `NOVA_VERSAO_NOVO_FARMACO`, `N_ALERTAS`, `N_INCOMPLETOS`, `N_MEDICACOES`, `N_PARES`, `ORIENTACAO_CURTA_COM_FONTE`, `REGISTRO_DE_CONSULTAS`, `SECOES_RESULTADOS_AFETADOS`, `SERVICO_TELEFONE`, `URL_COM_CONTROLE_DE_ACESSO` (+1)

### 07 — Longevidade, Proteção e Prevenção (LON)

*Público:* Pessoa avaliada e equipe clínica preventiva

*Produtor de dados:* `scripts/build_association_report.py --report 07`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Mapa preventivo
3. Linha de base
4. Matriz de predisposição
5. Variantes e fatores protetores
6. Plano preventivo longitudinal
7. Limitações e fontes

*Tokens com resolver (23):* `COORTES`, `DATA`, `DATA_EMISSAO`, `EFEITO`, `EFEITO_IC`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENE_VARIANTE`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `MONOGENICO_PRS_ASSOCIACAO`, `NOME_OU_ID_PSEUDONIMIZADO`, `N_PROTETORES`, `PROTETOR`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `RISCO_IC`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (34):* `ACAO`, `ACHADO`, `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ASSOCIACAO_OU_FATO`, `CARDIOMETABOLICO_NEURO_OUTRO`, `CONDICOES`, `CRONOGRAMA`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DECISAO`, `DESFECHO`, `DIRETRIZ_E_GENETICA`, `EFEITOS_CONTRARIOS`, `EVENTOS_IDADES_GRAU`, `EXPOSICOES`, `FATORES`, `GATILHO`, `IDENTIFICADOR`, `LAUDO_OU_NAO_DISPONIVEL`, `MARCADOR`, `META`, `METRICAS`, `MUDANCA`, `NIVEL`, `N_LACUNAS` (+10)

### 08 — Atlas de Traços e Curiosidades (ATL)

*Público:* Pessoa avaliada, família e educadores

*Produtor de dados:* `scripts/build_association_report.py --report 08`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Visão geral
3. Cartões de traços
4. Sentidos, fisiologia e preferências
5. Evidência e reprodutibilidade
6. Salvaguardas éticas
7. Limitações e fontes

*Tokens com resolver (25):* `AMOSTRA`, `ASSOCIACAO`, `DATA`, `DATA_EMISSAO`, `EFEITO`, `EFEITO_ESCALA`, `FISIOLOGIA`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `MODELO_VALIDADO`, `NOME_OU_ID_PSEUDONIMIZADO`, `N_ASSOCIACOES`, `PERCEPCAO`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `REPLICADO`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `TRACO`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (23):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ALTA_MEDIA_BAIXA`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DOI_MODELO`, `FATORES`, `HORARIO`, `LAUDO_OU_NAO_DISPONIVEL`, `MODELO_E_FENOTIPO`, `MUDANCA`, `N_CURIOSIDADES`, `N_NAO_DISP`, `N_ROBUSTOS`, `PIGMENTACAO`, `PROBABILIDADE`, `PROFISSIONAIS_E_DECISOES_FORA_DO_ESCOPO`, `PRS_O_VARIANTES`, `R2_OU_NA`, `SECOES_RESULTADOS_AFETADOS`, `TENDENCIA`, `TRACO_FICTICIO`, `VARIANTES_MODELO`, `VARIANTE_VALIDADA`, `VUS_CONFLITOS_PENETRANCIA_E_LIMITES_DE_MODELO`

### 09 — Genome Completeness & Blind Spots (GCM)

*Público:* Pessoa avaliada, clínicos, laboratórios, analistas e auditores

*Produtor de dados:* `scripts/build_completeness_report.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Painel de completude
3. Matriz por classe
4. Matriz por gene/região
5. Evidência negativa
6. Plano para fechar lacunas
7. Limitações e fontes

*Tokens com resolver (25):* `AMOSTRA`, `CALLER_ENSAIO`, `CONCLUSAO_LIMITADA`, `DATA`, `DATA_EMISSAO`, `ENSAIO_COMPLEMENTAR`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `GENE_REGIAO`, `IDENTIFICACAO`, `LABORATORIO_E_PLATAFORMA`, `LACUNA`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `METODO`, `NEGATIVO`, `NOME_OU_ID_PSEUDONIMIZADO`, `N_CEGOS`, `N_CLASSES`, `REGIOES`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `RELATORIO_QC`, `STATUS`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (11):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (25):* `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `CLASSES`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DESEMPENHO_IC`, `DETECTADO_NAO_DETECTADO`, `DOMINIO`, `EXONS_COORDENADAS`, `GC_MAPEAMENTO_OUTRO`, `IMPACTO`, `LAUDO_OU_NAO_DISPONIVEL`, `MUDANCA`, `N_BASES`, `N_GENES_COMPLETOS`, `N_GENES_PARCIAIS`, `P1_A_P5`, `PERCENTUAL`, `PROFISSIONAIS_E_DECISOES_FORA_DO_ESCOPO`, `QUESTAO`, `REGISTRO_DE_CONSULTAS`, `RESIDUAL`, `SECOES_RESULTADOS_AFETADOS`, `SIM_NAO_PARCIAL`, `SNV_INDEL_CNV_SV_STR_MT_OUTRO`, `TRANSCRITO` (+1)

### 10 — Resumo Clínico Genômico — Uma Página (R1P)

*Público:* Pessoa avaliada e equipe assistencial

*Produtor de dados:* `scripts/build_one_page_summary.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Situação atual
2. Prioridade e confirmação
3. Achados essenciais
4. Alertas e pontos cegos
5. Uso seguro e vínculos

*Tokens com resolver (12):* `ACHADO`, `ACHADO_OU_NENHUM`, `ALERTA_OU_LACUNA`, `DATA`, `IDS_E_VERSOES`, `METODO`, `RESUMO_EM_ATE_60_PALAVRAS_SEM_JARGAO`, `SIGNIFICADO`, `SIGNIFICADO_CURTO`, `STATUS`, `TEMA`, `VERSAO`

*Tokens que só o dossiê responde (0):* nenhum

*Tokens sem origem declarada (11):* `ACAO`, `ACAO_CURTA`, `CLINICO_PREDISPOSICAO_PGX_REPRO`, `CONFIRMACAO_OU_TESTE`, `DATA_GATILHO`, `DOMINIO`, `IMPACTO`, `MOTIVO`, `P1_A_P5`, `PESSOA_OU_ID`, `RESPONSAVEL_PRAZO`

### 11 — Guia Editorial e Matriz de Preenchimento (GED)

*Público:* Autores, revisores, geneticistas, analistas, designers e desenvolvedores

*Produtor de dados:* `scripts/build_editorial_guide.py`

*Seções, na ordem do catálogo (o motor imprime por título; parafrasear aqui renderiza seção vazia):*

1. Identificação e controle
2. Matriz de seleção
3. Dicionário de campos
4. Taxonomias obrigatórias
5. Arquitetura de uma afirmação
6. Linguagem e estilo
7. Consentimento e privacidade
8. QA antes da publicação
9. Versionamento e manutenção

*Tokens com resolver (21):* `ARTEFATO`, `CONTROLE`, `DATA`, `DATA_EMISSAO`, `DETALHE`, `ESCALA_DEFINIDA_POR_MODULO`, `FONTE_VERSAO_DATA`, `IDENTIFICACAO`, `LOGS_WORKFLOW_VERSOES`, `MANIFESTO_DE_ENTRADAS`, `MUDANCA`, `NOME_OU_ID_PSEUDONIMIZADO`, `PROCESSO`, `REGISTRO_DE_CONSULTAS`, `RELATORIO_QC`, `SEMVER`, `STATUS`, `STATUS_OPERACIONAL`, `TIPO_AMOSTRA_E_IDENTIFICADOR`, `VERSAO`, `VERSAO_RELATORIO`

*Tokens que só o dossiê responde (12):* `ASSINATURAS`, `DATA_COLETA`, `DATA_NASCIMENTO_OU_NAO_INFORMADA`, `FINALIDADE_E_RELATORIOS_AUTORIZADOS`, `ID_VERSAO_DATA_CONSENTIMENTO`, `LABORATORIO_E_PLATAFORMA`, `PESSOAS_SERVICOS_AUTORIZADOS`, `POLITICA_E_PRAZO`, `PREFERENCIA_CANAL_PRAZO`, `PREFERENCIA_GRANULAR`, `PROFISSIONAL_OU_SERVICO_SOLICITANTE`, `RESPONSAVEL`

*Tokens sem origem declarada (20):* `ACAO`, `ACHADOS_QUE_EXIGEM_METODO_ORTOGONAL_E_SEGREGACAO`, `ALTERACAO`, `CRITICA_ALTA_MEDIA_BAIXA`, `DATA_LIMITE_DE_BANCOS_GUIDELINES_E_REANALISE`, `DESTINATARIOS`, `GATILHO`, `GENES_REGIOES_CLASSES_E_POPULACAO_COBERTOS`, `HGVS_G_C_P_E_GRCH`, `LAUDO_OU_NAO_DISPONIVEL`, `NC_ID`, `NOMES`, `PROFISSIONAIS_E_DECISOES_FORA_DO_ESCOPO`, `REGIOES_CLASSES_VAF_FASE_E_MECANISMOS_NAO_AVALIADOS`, `RESULTADOS_AFETADOS`, `RISCO_E_IC`, `SECOES_RESULTADOS_AFETADOS`, `SECUNDARIOS_PORTADOR_PARENTESCO_TRAÇOS_DADOS`, `SIM_NAO_DEPOIS`, `VUS_CONFLITOS_PENETRANCIA_E_LIMITES_DE_MODELO`

## Regras editoriais que o código já impõe

Não são recomendações; são recusas implementadas, com teste e controle negativo.

1. **Nenhum valor entra num relatório sem estar ancorado a um artefato.** `reporting/provenance.py` religa cada valor ao locator de onde saiu e o `PROVENANCE_GATE` reconfere no momento de renderizar. Não existe flag de bypass.
2. **Renderização estrita recusa publicar o modelo em branco.** Se nenhum campo foi substituído, `render_pdf_from_template` levanta erro em vez de emitir as páginas vazias como se fossem o relatório.
3. **Placeholder é apagado, não coberto.** A redação usa `apply_redactions` do PyMuPDF: um retângulo opaco por cima deixaria o token extraível do PDF.
4. **Ausência é um resultado e é ancorada como tal.** NÃO DISPONÍVEL nunca é campo vazio; carrega a razão pela qual está ausente.
5. **Conflito nunca é arbitrado.** Registro cross-platform divergente, modo de herança divergente entre fontes e duplicata com genótipos diferentes viram NÃO REPORTÁVEL.
6. **Consentimento é tudo-ou-nada.** Um bloco pela metade lê na página como consentimento documentado, então é rejeitado no carregamento.

## Vocabulário de status (seção 261 do ruleset)

| status | significa |
|---|---|
| EXECUTADO | a operação rodou e o resultado é dela |
| VERIFICADO | foi medido e conferido contra evidência |
| INFERIDO | deduzido de medição, sob suposição declarada |
| PROPOSTO | desenhado, não executado |
| NÃO DISPONÍVEL | não existe; a razão acompanha |

Manifesto de coordenadas: `genoma-editorial-v3-reference-manifest-v2`, 11 relatórios descritos.

