# Portability and longevity matrix

GENOMA adopts standards and patterns from mature genomics/workflow ecosystems while keeping policy semantics independent.

| Concern | GENOMA design | Comparable mature pattern | Lock-in stance |
|---|---|---|---|
| Workflow portability | Nextflow/container Scientific Data Plane; future WES adapter | GA4GH Workflow Execution Service | Core policy does not depend on WES or Nextflow |
| Task portability | container/task contract; future TES adapter | GA4GH Task Execution Service | Optional adapter |
| Data location abstraction | content-addressed evidence refs; future DRS adapter | GA4GH Data Repository Service | Optional adapter |
| Workflow engine | current Nextflow + shell/CLI | multiple executors/container backends | Replaceable |
| Durable orchestration | no requirement in core | event-history/replay workflow systems | Optional |
| Edge/security | loopback/private origin first | authenticated private tunnel/zero-trust ingress | Optional |
| Evidence query database | rebuildable projection | PostgreSQL-compatible SQL with grants/RLS | Optional, never canonical |
| Supply-chain provenance | OCI digest + provenance + SBOM | SLSA provenance concepts | Registry/provider replaceable |
| Policy | Python deterministic gates + Rego parity + structured attestations | policy-as-code | Normative TXT remains source |
| Human/agent interface | CLI + HTTP first; MCP optional | standard tool-interface ecosystems | Fully optional |

## Design advantages over monolithic systems

1. Scientific truth is not stored in the UI.
2. Normative text is content-addressed.
3. Data plane and policy plane fail independently and fail closed.
4. Audit evidence is exportable as plain JSON/JSONL, SHA-256 and OCI metadata.
5. GA4GH-compatible adapters can be added later without rewriting the core.

## Primary references

- GA4GH WES: https://www.ga4gh.org/product/workflow-execution-service-wes
- GA4GH TES overview: https://www.ga4gh.org/news/ga4gh-tes-api-bringing-compatibility-to-task-execution-across-hpc-systems-the-cloud-and-beyond
- Nextflow executors: https://docs.seqera.io/nextflow/executor
- Nextflow containers: https://docs.seqera.io/nextflow/container
- GitHub self-hosted runners: https://docs.github.com/actions/hosting-your-own-runners
- GATK resource bundle: https://gatk.broadinstitute.org/hc/en-us/articles/360035890811-Resource-bundle
- BWA-MEM2: https://github.com/bwa-mem2/bwa-mem2
