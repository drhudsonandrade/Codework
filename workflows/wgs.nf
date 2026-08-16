nextflow.enable.dsl = 2

/*
 * Production Scientific Data Plane for real WGS SNV/small-indel processing.
 *
 * This workflow is deliberately fail-closed. It does NOT claim CNV, SV, repeat-
 * expansion, HLA, CYP2D6, mtDNA-specialized, or other complex-class coverage from a
 * generic short-variant VCF. Those classes are emitted as NÃO DISPONÍVEL in the
 * capability manifest until specialized validated workflows are added.
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

process INGEST_AND_QC {
    tag 'wgs-input-qc'

    input:
    path sample_dir
    path verified_runtime
    path current_freshness

    output:
    path 'qc/input-qc.json', emit: input_qc

    script:
    """
    mkdir -p qc
    test -s '${verified_runtime}'
    test -s '${current_freshness}'
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
    WGS_THREADS=${task.cpus} WGS_SORT_THREADS=${Math.max(1, (task.cpus as int) / 2 as int)} \
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
    mkdir -p normalized
    ref='${ref_root}/Homo_sapiens_assembly38.fasta'
    bcftools norm -f "\$ref" -m -any '${raw_vcf}' -Ou \
      | bcftools sort -Oz -o normalized/sample.normalized.vcf.gz
    bcftools index -f -t normalized/sample.normalized.vcf.gz
    bcftools view -h normalized/sample.normalized.vcf.gz >/dev/null
    """
}

process ANNOTATE_EVIDENCE {
    tag 'evidence-adapter-snapshot'

    input:
    path normalized_vcf

    output:
    path 'evidence/adapter-capabilities.json', emit: evidence_snapshot

    script:
    """
    mkdir -p evidence
    python3 - <<'PY'
    import json
    from evidence_adapters import ADAPTERS
    payload = {
      'schema': 'genoma-evidence-adapter-capabilities-v1',
      'status': 'VERIFICADO',
      'adapters': sorted(ADAPTERS),
      'note': 'Variant-specific queries are executed during curation; this step never fabricates a consulted source.',
      'vcf': 'sample.normalized.vcf.gz'
    }
    open('evidence/adapter-capabilities.json','w',encoding='utf-8').write(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    PY
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
    mkdir -p curation
    python3 '${workflow.projectDir}/scripts/build_wgs_curated_manifest.py' \
      --case-id '${case_id}' \
      --sample-id '${sample_id}' \
      --vcf '${normalized_vcf}' \
      --runtime-gate '${pre_call_gate}' \
      --output curation/analysis-manifest.json
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
    mkdir -p policy
    set +e
    PYTHONPATH='${workflow.projectDir}/policy_engine' \
      python3 -m genoma_policy evaluate '${curation_manifest}' > policy/evaluation.json
    code=\$?
    set -e
    if [ \$code -ne 0 ]; then
      # Expected until evidence/clinical curation/final audit are genuinely complete.
      python3 - <<'PY'
    import json
    from pathlib import Path
    p=Path('policy/evaluation.json')
    if not p.exists() or not p.read_text(encoding='utf-8').strip():
        p.write_text(json.dumps({'status':'NÃO DISPONÍVEL','reason':'policy evaluation blocked or unavailable'},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    PY
    fi
    """
}

process GENERATE_REPORTS {
    tag 'eleven-final-reports'

    input:
    path curation_manifest
    path policy_evaluation

    output:
    path 'reports', emit: reports

    script:
    """
    mkdir -p reports
    python3 - <<'PY'
    import json
    from pathlib import Path
    p=json.loads(Path('${curation_manifest}').read_text(encoding='utf-8'))
    if p.get('publication_gate',{}).get('passed') is not True:
        raise SystemExit('NÃO DISPONÍVEL: final reports remain blocked until curation/Evidence/Final Audit are VERIFICADO')
    PY
    for id in \$(seq -w 1 11); do
      python3 '${workflow.projectDir}/scripts/generate_report.py' \
        --report "\$id" --mode FINAL --input '${curation_manifest}' --output-dir reports
    done
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
    INGEST_AND_QC(sample_dir, VERIFY_RUNTIME_GATE.out.verified_runtime, REFRESH_FRESHNESS_GATE.out.current_freshness)
    ALIGN_OR_STAGE(sample_dir, INGEST_AND_QC.out.input_qc, ref_root)
    RERUN_SAMPLE_RUNTIME_GATE(ALIGN_OR_STAGE.out.alignment, freshness_state_manifest, ref_root)
    CALL_SHORT_VARIANTS(ALIGN_OR_STAGE.out.alignment, RERUN_SAMPLE_RUNTIME_GATE.out.pre_call_gate, ref_root)
    NORMALIZE_VARIANTS(CALL_SHORT_VARIANTS.out.raw_vcf, CALL_SHORT_VARIANTS.out.raw_vcf_index, ref_root)
    ANNOTATE_EVIDENCE(NORMALIZE_VARIANTS.out.normalized_vcf)
    BUILD_CURATED_MANIFEST(
      NORMALIZE_VARIANTS.out.normalized_vcf,
      NORMALIZE_VARIANTS.out.normalized_index,
      RERUN_SAMPLE_RUNTIME_GATE.out.pre_call_gate,
      INGEST_AND_QC.out.input_qc,
      ANNOTATE_EVIDENCE.out.evidence_snapshot,
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
