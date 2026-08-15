nextflow.enable.dsl = 2

params.outdir = 'results/canary'

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
    CANARY()
}
