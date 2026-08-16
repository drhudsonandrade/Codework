nextflow.enable.dsl = 2

params.mode = params.mode ?: 'canary'
params.outdir = params.outdir ?: 'results/canary'
params.sample_dir = params.sample_dir ?: null
params.runtime_gate_manifest = params.runtime_gate_manifest ?: null
params.freshness_state_manifest = params.freshness_state_manifest ?: null
params.ref_root = params.ref_root ?: null
params.case_id = params.case_id ?: null
params.sample_id = params.sample_id ?: null

include { WGS_PRODUCTION } from './workflows/wgs'

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
    else {
        error "Unknown --mode '${params.mode}'. Allowed: canary, wgs"
    }
}
