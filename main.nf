nextflow.enable.dsl = 2

params.mode = params.mode ?: 'canary'
params.outdir = params.outdir ?: 'results/canary'
params.sample_dir = params.sample_dir ?: null
params.runtime_gate_manifest = params.runtime_gate_manifest ?: null
params.freshness_state_manifest = params.freshness_state_manifest ?: null
params.ref_root = params.ref_root ?: null
params.case_id = params.case_id ?: null
params.sample_id = params.sample_id ?: null
params.array_input = params.array_input ?: null
params.array_build = params.array_build ?: null
params.array_strand = params.array_strand ?: null
params.array_build_evidence = params.array_build_evidence ?: null
params.array_strand_evidence = params.array_strand_evidence ?: null
params.array_evidence_mode = params.array_evidence_mode ?: 'plan-only'
params.array_target_manifest = params.array_target_manifest ?: 'config/partial_genome_annotation_targets.json'

include { WGS_PRODUCTION } from './workflows/wgs'
include { ARRAY_PRODUCTION } from './workflows/array'

def requireBoundedIdentifier = { String name, value ->
    def text = value?.toString()
    if (!text || !(text ==~ /[A-Za-z0-9][A-Za-z0-9._-]{0,63}/) || text in ['.', '..']) {
        error "${name} must be a bounded identifier using only letters, numbers, dot, underscore or dash"
    }
}

def requireSafePathParameter = { String name, value ->
    def text = value?.toString()
    if (!text || !(text ==~ /[A-Za-z0-9_.\/-]+/)) {
        error "${name} contains characters that are not allowed in an execution path"
    }
    def segments = text.tokenize('/')
    if (segments.contains('..')) {
        error "${name} must not contain parent-directory traversal"
    }
}

process CANARY {
    tag 'synthetic-germline-canary'
    cpus 2
    memory '6 GB'
    time '45m'

    publishDir params.outdir, mode: 'copy', overwrite: true

    output:
    path 'canary/report.json'
    path 'canary/bcftools.score.json'
    path 'canary/gatk.score.json'
    path 'canary/tool_versions.tsv'
    path 'canary/flagstat.txt'

    script:
    """
    bash '${workflow.projectDir}/scripts/run_canary.sh' canary
    """
}

workflow {
    if (params.mode == 'canary') {
        CANARY()
    }
    else if (params.mode == 'wgs') {
        def missing = []
        if (!params.sample_dir) missing << 'sample_dir'
        if (!params.runtime_gate_manifest) missing << 'runtime_gate_manifest'
        if (!params.freshness_state_manifest) missing << 'freshness_state_manifest'
        if (!params.ref_root) missing << 'ref_root'
        if (!params.case_id) missing << 'case_id'
        if (!params.sample_id) missing << 'sample_id'
        if (missing) {
            error "WGS_PRODUCTION blocked: missing required parameters: ${missing.join(', ')}"
        }
        requireBoundedIdentifier('case_id', params.case_id)
        requireBoundedIdentifier('sample_id', params.sample_id)
        requireSafePathParameter('sample_dir', params.sample_dir)
        requireSafePathParameter('runtime_gate_manifest', params.runtime_gate_manifest)
        requireSafePathParameter('freshness_state_manifest', params.freshness_state_manifest)
        requireSafePathParameter('ref_root', params.ref_root)

        sample_dir_ch = Channel.fromPath(params.sample_dir, type: 'dir', checkIfExists: true)
        runtime_gate_ch = Channel.fromPath(params.runtime_gate_manifest, checkIfExists: true)
        freshness_state_ch = Channel.fromPath(params.freshness_state_manifest, checkIfExists: true)
        ref_root_ch = Channel.value(params.ref_root)
        case_id_ch = Channel.value(params.case_id)
        sample_id_ch = Channel.value(params.sample_id)

        WGS_PRODUCTION(
            sample_dir_ch,
            runtime_gate_ch,
            freshness_state_ch,
            ref_root_ch,
            case_id_ch,
            sample_id_ch
        )
    }
    else if (params.mode == 'array') {
        def missing = []
        if (!params.array_input) missing << 'array_input'
        if (!params.case_id) missing << 'case_id'
        if (!params.array_build) missing << 'array_build'
        if (!params.array_strand) missing << 'array_strand'
        if (!params.array_build_evidence) missing << 'array_build_evidence'
        if (!params.array_strand_evidence) missing << 'array_strand_evidence'
        if (!(params.array_evidence_mode in ['plan-only', 'live'])) missing << 'array_evidence_mode(plan-only|live)'
        if (missing) {
            error "ARRAY_PRODUCTION blocked: missing/invalid required parameters: ${missing.join(', ')}"
        }
        if (!(params.array_build in ['GRCh37', 'GRCh38'])) {
            error "ARRAY_PRODUCTION blocked: array_build must be GRCh37 or GRCh38"
        }
        if (!(params.array_strand in ['forward', 'plus', '+'])) {
            error "ARRAY_PRODUCTION blocked: array_strand must be forward/plus/+"
        }
        requireBoundedIdentifier('case_id', params.case_id)
        requireSafePathParameter('array_input', params.array_input)
        requireSafePathParameter('array_build_evidence', params.array_build_evidence)
        requireSafePathParameter('array_strand_evidence', params.array_strand_evidence)
        requireSafePathParameter('array_target_manifest', params.array_target_manifest)

        array_input_ch = Channel.fromPath(params.array_input, checkIfExists: true)
        target_manifest_ch = Channel.fromPath(params.array_target_manifest, checkIfExists: true)
        build_evidence_ch = Channel.fromPath(params.array_build_evidence, checkIfExists: true)
        strand_evidence_ch = Channel.fromPath(params.array_strand_evidence, checkIfExists: true)
        case_id_ch = Channel.value(params.case_id)
        build_ch = Channel.value(params.array_build)
        strand_ch = Channel.value(params.array_strand)
        evidence_mode_ch = Channel.value(params.array_evidence_mode)

        ARRAY_PRODUCTION(
            array_input_ch,
            case_id_ch,
            build_ch,
            strand_ch,
            build_evidence_ch,
            strand_evidence_ch,
            evidence_mode_ch,
            target_manifest_ch
        )
    }
    else {
        error "Unknown --mode '${params.mode}'. Allowed: canary, wgs, array"
    }
}
