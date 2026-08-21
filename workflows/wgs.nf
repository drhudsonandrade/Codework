nextflow.enable.dsl = 2

/*
 * GENOMA production Scientific Data Plane for real WGS SNV/small-indel processing.
 *
 * The technical output includes an explicit `unsupported_variant_classes` field.
 * Generic short-variant calling MUST NOT be promoted to CNV, SV, repeat-expansion,
 * HLA, CYP2D6, mtDNA-specialized or other complex-class coverage. Those remain
 * NÃO DISPONÍVEL until a specialized validated workflow is actually executed.
 */

process VERIFY_RUNTIME_GATE {
    tag 'environment-runtime-gate'

    input:
    path runtime_gate_manifest

    output:
    path 'gate/runtime-entry.json', emit: verified_runtime

    script:
    """
    mkdir -p gate
    python3 '${workflow.projectDir}/scripts/verify_runtime_gate_manifest.py' \
      --input '${runtime_gate_manifest}' \
      --scope environment \
      --output gate/runtime-entry.json
    """
}

process REFRESH_FRESHNESS_GATE {
    tag 'freshness-recheck-immediately-before-dna'

    input:
    path freshness_state_manifest

    output:
    path 'freshness/current-gate.json', emit: current_freshness

    script:
    """
    mkdir -p freshness
    python3 '${workflow.projectDir}/scripts/freshness_gate.py' \
      --input '${freshness_state_manifest}' \
      --output freshness/current-gate.json
    jq -e '.ready_for_dna == true' freshness/current-gate.json >/dev/null
    """
}

process VERIFY_CONSENT_PROVENANCE {
    tag 'consent-provenance-before-first-dna-read'

    input:
    path sample_dir

    output:
    path 'consent/gate.json', emit: consent_gate

    script:
    """
    mkdir -p consent
    python3 '${workflow.projectDir}/scripts/wgs_consent_gate.py' \
      --manifest '${sample_dir}/sample-manifest.json' \
      --purpose genomic_analysis \
      --output consent/gate.json
    jq -e '.ready_for_first_dna_read == true and .status == "VERIFICADO"' consent/gate.json >/dev/null
    """
}

process INGEST_AND_QC {
    tag 'wgs-input-qc'

    input:
    path sample_dir
    path verified_runtime
    path current_freshness
    path consent_gate

    output:
    path 'qc/input-qc.json', emit: input_qc

    script:
    """
    test -s '${verified_runtime}'
    test -s '${current_freshness}'
    jq -e '.ready_for_first_dna_read == true and .status == "VERIFICADO"' '${consent_gate}' >/dev/null
    mkdir -p qc
    python3 '${workflow.projectDir}/scripts/wgs_input_gate.py' \
      --manifest '${sample_dir}/sample-manifest.json' \
      --output qc/input-qc.json
    jq -e '.status == "VERIFICADO"' qc/input-qc.json >/dev/null
    """
}

process ALIGN_OR_STAGE {
    tag 'wgs-align-or-stage'
    cpus { params.wgs_cpus ?: 8 }
    memory { params.wgs_memory ?: '24 GB' }
    time { params.wgs_align_time ?: '24h' }

    input:
    path sample_dir
    path input_qc
    val ref_root

    output:
    tuple path('aligned/sample.bam'), path('aligned/sample.bam.bai'), emit: alignment

    script:
    """
    test -s '${input_qc}'
    mkdir -p aligned
    WGS_THREADS=${task.cpus} WGS_SORT_THREADS=${task.cpus} \
      bash '${workflow.projectDir}/scripts/wgs_align_or_stage.sh' \
        '${sample_dir}/sample-manifest.json' \
        '${ref_root}/Homo_sapiens_assembly38.fasta' \
        aligned/sample.bam
    """
}

process RERUN_SAMPLE_RUNTIME_GATE {
    tag 'pre-calling-runtime-resource-gate'

    input:
    tuple path(bam), path(bai)
    path freshness_state_manifest
    val ref_root

    output:
    path 'gate/pre-calling-runtime.json', emit: pre_call_gate

    script:
    """
    test -s '${bai}'
    mkdir -p gate freshness
    python3 '${workflow.projectDir}/scripts/freshness_gate.py' \
      --input '${freshness_state_manifest}' \
      --output freshness/pre-calling.json
    jq -e '.ready_for_dna == true' freshness/pre-calling.json >/dev/null

    python3 '${workflow.projectDir}/scripts/latest_runtime_resource_gate.py' \
      --freshness-gate freshness/pre-calling.json \
      --ref-root '${ref_root}' \
      --bam '${bam}' \
      --caller gatk-haplotypecaller \
      --require-real-calling \
      --output gate/pre-calling-runtime.json

    python3 '${workflow.projectDir}/scripts/verify_runtime_gate_manifest.py' \
      --input gate/pre-calling-runtime.json \
      --scope full \
      --output gate/pre-calling-verification.json
    """
}

process CALL_SHORT_VARIANTS {
    tag 'gatk-haplotypecaller-gvcf'
    cpus { params.wgs_call_cpus ?: 8 }
    memory { params.wgs_call_memory ?: '24 GB' }
    time { params.wgs_call_time ?: '24h' }

    input:
    tuple path(bam), path(bai)
    path pre_call_gate
    val ref_root

    output:
    path 'variants/sample.g.vcf.gz', emit: gvcf
    path 'variants/sample.g.vcf.gz.tbi', emit: gvcf_index
    path 'variants/sample.raw.vcf.gz', emit: raw_vcf
    path 'variants/sample.raw.vcf.gz.tbi', emit: raw_vcf_index

    script:
    """
    jq -e '.ready_for_real_calling == true and .status == "EXECUTADO"' '${pre_call_gate}' >/dev/null
    mkdir -p variants
    ref='${ref_root}/Homo_sapiens_assembly38.fasta'
    gatk HaplotypeCaller \
      -R "\$ref" \
      -I '${bam}' \
      -O variants/sample.g.vcf.gz \
      -ERC GVCF \
      --native-pair-hmm-threads ${task.cpus}
    gatk GenotypeGVCFs \
      -R "\$ref" \
      -V variants/sample.g.vcf.gz \
      -O variants/sample.raw.vcf.gz
    test -s variants/sample.g.vcf.gz.tbi
    test -s variants/sample.raw.vcf.gz.tbi
    """
}

process NORMALIZE_VARIANTS {
    tag 'normalize-short-variants'

    input:
    path raw_vcf
    path raw_vcf_index
    val ref_root

    output:
    path 'normalized/sample.normalized.vcf.gz', emit: normalized_vcf
    path 'normalized/sample.normalized.vcf.gz.tbi', emit: normalized_index

    script:
    """
    test -s '${raw_vcf_index}'
    mkdir -p normalized
    ref='${ref_root}/Homo_sapiens_assembly38.fasta'
    bcftools norm -f "\$ref" -m -any '${raw_vcf}' -Ou \
      | bcftools sort -Oz -o normalized/sample.normalized.vcf.gz
    bcftools index -f -t normalized/sample.normalized.vcf.gz
    bcftools view -h normalized/sample.normalized.vcf.gz >/dev/null
    """
}

process ADAPTER_CAPABILITY_INVENTORY {
    tag 'evidence-adapter-capabilities'

    input:
    path normalized_vcf

    output:
    path 'evidence/adapter-capabilities.json', emit: evidence_snapshot

    script:
    """
    mkdir -p evidence
    python3 '${workflow.projectDir}/scripts/build_adapter_capabilities.py' \
      --vcf '${normalized_vcf}' \
      --output evidence/adapter-capabilities.json
    """
}

process BUILD_CURATED_MANIFEST {
    tag 'build-fail-closed-curation-manifest'

    input:
    path normalized_vcf
    path normalized_index
    path pre_call_gate
    path input_qc
    path evidence_snapshot
    val case_id
    val sample_id

    output:
    path 'curation/analysis-manifest.json', emit: curation_manifest

    script:
    """
    test -s '${normalized_index}'
    test -s '${input_qc}'
    test -s '${evidence_snapshot}'
    mkdir -p curation
    # `input_qc` and `evidence_snapshot` were staged and proved non-empty above, then never
    # handed to the builder: the manifest reported zero sources and a constant qc_verified on
    # every run. Checking that a file exists is not the same as reading it.
    python3 '${workflow.projectDir}/scripts/build_wgs_curated_manifest.py' \
      --case-id '${case_id}' \
      --sample-id '${sample_id}' \
      --vcf '${normalized_vcf}' \
      --runtime-gate '${pre_call_gate}' \
      --input-qc '${input_qc}' \
      --evidence '${evidence_snapshot}' \
      --output curation/analysis-manifest.json
    jq -e '.unsupported_variant_classes | index("CNV") and index("SV") and index("CYP2D6")' curation/analysis-manifest.json >/dev/null
    # The evidence must arrive by hash, and POST-DEPLOYMENT is never granted by a pipeline step.
    jq -e '.sources | length > 0' curation/analysis-manifest.json >/dev/null
    jq -e '.post_deployment_status == "PENDENTE"' curation/analysis-manifest.json >/dev/null
    """
}

process POLICY_EVALUATE {
    tag 'policy-evidence-audit-gates'

    input:
    path curation_manifest

    output:
    path 'policy/evaluation.json', emit: policy_evaluation

    script:
    """
    mkdir -p policy/normative
    python3 '${workflow.projectDir}/scripts/materialize_ruleset.py' \
      --output-dir policy/normative \
      --evidence policy/ruleset-materialization.json
    canonical='policy/normative/REGRAS_PROJETO_GENOMA_VIGENTE_v3.4_2026-08-17.txt'
    set +e
    GENOMA_RULESET_PATH="\$canonical" \
    GENOMA_RULESET_SHA_MANIFEST='${workflow.projectDir}/manifests/RULESET_V3.4.sha256' \
    PYTHONPATH='${workflow.projectDir}/policy_engine' \
      python3 -m genoma_policy evaluate '${curation_manifest}' --output policy/evaluation.json
    code=\$?
    set -e
    test -s policy/evaluation.json
    printf '%s\n' "\$code" > policy/evaluation.exit-code
    # The exit code is the verdict, not a note about it. It was captured, written to a file
    # and then ignored, so a refused evaluation still emitted evaluation.json and the channel
    # carried it straight into report generation. Non-zero fails the process here.
    if [ "\$code" -ne 0 ]; then
      echo "NAO DISPONIVEL: policy evaluation refused this manifest (exit \$code)" >&2
      exit "\$code"
    fi
    """
}

process GENERATE_REPORTS {
    tag 'eleven-report-release-gate'

    input:
    path curation_manifest
    path policy_evaluation

    output:
    path 'reports', emit: reports

    script:
    """
    test -s '${policy_evaluation}'
    # The evaluation was staged and proved non-empty and then never passed, the same shape
    # as the evidence snapshot in BUILD_CURATED_MANIFEST. Without it the release was
    # assembled from whatever the curation manifest said about its own publication gate,
    # with no policy evaluation involved at all.
    python3 '${workflow.projectDir}/scripts/generate_all_reports.py' \
      --input '${curation_manifest}' \
      --policy '${policy_evaluation}' \
      --output-dir reports
    """
}

workflow WGS_PRODUCTION {
    take:
    sample_dir
    runtime_gate_manifest
    freshness_state_manifest
    ref_root
    case_id
    sample_id

    main:
    VERIFY_RUNTIME_GATE(runtime_gate_manifest)
    REFRESH_FRESHNESS_GATE(freshness_state_manifest)
    VERIFY_CONSENT_PROVENANCE(sample_dir)
    INGEST_AND_QC(
        sample_dir,
        VERIFY_RUNTIME_GATE.out.verified_runtime,
        REFRESH_FRESHNESS_GATE.out.current_freshness,
        VERIFY_CONSENT_PROVENANCE.out.consent_gate
    )
    ALIGN_OR_STAGE(sample_dir, INGEST_AND_QC.out.input_qc, ref_root)
    RERUN_SAMPLE_RUNTIME_GATE(ALIGN_OR_STAGE.out.alignment, freshness_state_manifest, ref_root)
    CALL_SHORT_VARIANTS(ALIGN_OR_STAGE.out.alignment, RERUN_SAMPLE_RUNTIME_GATE.out.pre_call_gate, ref_root)
    NORMALIZE_VARIANTS(CALL_SHORT_VARIANTS.out.raw_vcf, CALL_SHORT_VARIANTS.out.raw_vcf_index, ref_root)
    ADAPTER_CAPABILITY_INVENTORY(NORMALIZE_VARIANTS.out.normalized_vcf)
    BUILD_CURATED_MANIFEST(
        NORMALIZE_VARIANTS.out.normalized_vcf,
        NORMALIZE_VARIANTS.out.normalized_index,
        RERUN_SAMPLE_RUNTIME_GATE.out.pre_call_gate,
        INGEST_AND_QC.out.input_qc,
        ADAPTER_CAPABILITY_INVENTORY.out.evidence_snapshot,
        case_id,
        sample_id
    )
    POLICY_EVALUATE(BUILD_CURATED_MANIFEST.out.curation_manifest)
    GENERATE_REPORTS(BUILD_CURATED_MANIFEST.out.curation_manifest, POLICY_EVALUATE.out.policy_evaluation)

    emit:
    normalized_vcf = NORMALIZE_VARIANTS.out.normalized_vcf
    curation_manifest = BUILD_CURATED_MANIFEST.out.curation_manifest
    policy_evaluation = POLICY_EVALUATE.out.policy_evaluation
    reports = GENERATE_REPORTS.out.reports
}
