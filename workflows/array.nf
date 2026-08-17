nextflow.enable.dsl = 2

/*
 * GENOMA Scientific Data Plane for partial SNP-array genomes.
 *
 * This workflow is intentionally separate from WGS calling. It never converts
 * non-assayed loci into negative evidence and never promotes CNV/SV/repeats/HLA/
 * CYP2D6-structural claims from a consumer SNP chip.
 */

process ARRAY_QC {
    tag "array-qc:${case_id}"

    input:
    path array_input
    val case_id
    val build
    val strand
    val build_evidence
    val strand_evidence

    output:
    path 'array-qc/array-qc.json', emit: qc_json
    path 'array-qc/baseline-marker-observations.tsv', emit: baseline_observations
    path 'array-qc/SHA256SUMS', emit: qc_hashes

    script:
    """
    mkdir -p array-qc
    python3 '${workflow.projectDir}/scripts/run_snp_array.py' \
      --input '${array_input}' \
      --case-id '${case_id}' \
      --build '${build}' \
      --strand '${strand}' \
      --build-evidence '${build_evidence}' \
      --strand-evidence '${strand_evidence}' \
      --output-dir array-qc
    jq -e '.operational_status == "VERIFICADO" and .gates.LIMITED_INTERPRETATION_GATE.state == "PASS"' array-qc/array-qc.json >/dev/null
    """
}

process ARRAY_ANNOTATE {
    tag "array-evidence:${case_id}"

    input:
    path array_input
    path qc_json
    path target_manifest
    val case_id
    val evidence_mode

    output:
    path 'annotation/partial-genome-annotation.json', emit: annotation_json

    script:
    """
    mkdir -p annotation
    python3 '${workflow.projectDir}/scripts/annotate_partial_genome.py' \
      --input '${array_input}' \
      --qc '${qc_json}' \
      --targets '${target_manifest}' \
      --mode '${evidence_mode}' \
      --output annotation/partial-genome-annotation.json
    if [ '${evidence_mode}' = 'live' ]; then
      jq -e '.operational_status == "VERIFICADO" and .evidence_gate.state == "PASS"' annotation/partial-genome-annotation.json >/dev/null
    else
      jq -e '.operational_status == "PROPOSTO" and .mode == "plan-only"' annotation/partial-genome-annotation.json >/dev/null
    fi
    """
}

process ARRAY_BUILD_MANIFEST {
    tag "array-manifest:${case_id}"

    input:
    path qc_json
    path annotation_json
    val case_id

    output:
    path 'curation/analysis-manifest.json', emit: curation_manifest

    script:
    """
    mkdir -p curation
    python3 '${workflow.projectDir}/scripts/build_array_case_manifest.py' \
      --qc '${qc_json}' \
      --annotation '${annotation_json}' \
      --output curation/analysis-manifest.json
    jq -e '.schema == "genoma-array-curation-manifest-v1" and .case_id == "${case_id}" and .publication_gate.passed == false' curation/analysis-manifest.json >/dev/null
    """
}

process ARRAY_POLICY_EVALUATE {
    tag "array-policy:${case_id}"

    input:
    path curation_manifest
    val case_id

    output:
    path 'policy/evaluation.json', emit: policy_evaluation

    script:
    """
    mkdir -p policy/normative
    python3 '${workflow.projectDir}/scripts/materialize_ruleset.py' \
      --output-dir policy/normative \
      --evidence policy/ruleset-materialization.json
    canonical='policy/normative/REGRAS_PROJETO_GENOMA_VIGENTE_v3.3_2026-08-14.txt'
    set +e
    GENOMA_RULESET_PATH="\$canonical" \
    GENOMA_RULESET_SHA_MANIFEST='${workflow.projectDir}/manifests/RULESET_V3.3.sha256' \
    PYTHONPATH='${workflow.projectDir}/policy_engine' \
      python3 -m genoma_policy evaluate '${curation_manifest}' --output policy/evaluation.json
    code=\$?
    set -e
    test -s policy/evaluation.json
    printf '%s\n' "\$code" > policy/evaluation.exit-code
    """
}

process ARRAY_GENERATE_REPORTS {
    tag "array-report-gate:${case_id}"

    input:
    path curation_manifest
    path policy_evaluation
    val case_id

    output:
    path 'reports', emit: reports

    script:
    """
    mkdir -p reports
    python3 '${workflow.projectDir}/scripts/generate_all_reports.py' \
      --input '${curation_manifest}' \
      --policy '${policy_evaluation}' \
      --output-dir reports
    """
}

workflow ARRAY_PRODUCTION {
    take:
    array_input
    case_id
    build
    strand
    build_evidence
    strand_evidence
    evidence_mode
    target_manifest

    main:
    ARRAY_QC(array_input, case_id, build, strand, build_evidence, strand_evidence)
    ARRAY_ANNOTATE(array_input, ARRAY_QC.out.qc_json, target_manifest, case_id, evidence_mode)
    ARRAY_BUILD_MANIFEST(ARRAY_QC.out.qc_json, ARRAY_ANNOTATE.out.annotation_json, case_id)
    ARRAY_POLICY_EVALUATE(ARRAY_BUILD_MANIFEST.out.curation_manifest, case_id)
    ARRAY_GENERATE_REPORTS(ARRAY_BUILD_MANIFEST.out.curation_manifest, ARRAY_POLICY_EVALUATE.out.policy_evaluation, case_id)

    emit:
    qc = ARRAY_QC.out.qc_json
    annotation = ARRAY_ANNOTATE.out.annotation_json
    curation_manifest = ARRAY_BUILD_MANIFEST.out.curation_manifest
    policy_evaluation = ARRAY_POLICY_EVALUATE.out.policy_evaluation
    reports = ARRAY_GENERATE_REPORTS.out.reports
}
