# Portability and longevity matrix

GENOMA adopts standards and patterns from mature genomics/workflow ecosystems while keeping its policy semantics independent.

| Concern | GENOMA design | Comparable mature pattern | Lock-in stance |
|---|---|---|---|
| Workflow portability | Nextflow/container Scientific Data Plane; future WES adapter | GA4GH Workflow Execution Service abstracts workflow engines/environments | Core policy does not depend on WES or Nextflow |
| Task portability | container/task contract; future TES adapter | GA4GH Task Execution Service targets HPC/cloud task execution | Optional adapter |
| Data location abstraction | content-addressed evidence refs; future DRS adapter | GA4GH Data Repository Service | Optional adapter |
| Workflow engine | current Nextflow + shell/CLI | Nextflow supports multiple executors and container backends | Replaceable |
| Durable orchestration | no requirement in core | replay/history + activities in any durable engine | Optional |
| Edge/security | loopback/private origin first | a reverse tunnel and access proxy can avoid exposing the origin | Optional |
| Evidence query database | rebuildable projection | PostgreSQL with grants and row-level security | Optional, never canonical |
| Supply-chain provenance | OCI digest + BuildKit provenance + SBOM | SLSA provenance concepts | Registry/provider replaceable |
| Policy | Python deterministic gates + Rego parity + structured attestations | Policy-as-code / independent policy engines | Normative TXT remains source |
| Operator interface | CLI + HTTP first; MCP adapter | vendor UI/agent ecosystems | Fully optional |

## Design advantages over monolithic systems

1. **Scientific truth is not in the UI.** An agent client, web application, notebook or future interface can disappear without changing the stored execution evidence.
2. **Normative text is content-addressed.** Each rule is machine-addressable and rules requiring judgement retain structured attestation instead of fake booleans.
3. **Data plane and policy plane fail independently.** A workflow can execute but fail policy; a policy can be healthy while NGS compute is unavailable. Neither is allowed to impersonate the other.
4. **Audit evidence is exportable.** JSON/JSONL, SHA-256, OCI digests and plain files survive vendor changes better than proprietary dashboards.
5. **Federation-ready.** GA4GH WES/TES/DRS-compatible adapters can be added later without rewriting the core.

## Primary references

- GA4GH WES: https://www.ga4gh.org/product/workflow-execution-service-wes
- GA4GH TES overview: https://www.ga4gh.org/news/ga4gh-tes-api-bringing-compatibility-to-task-execution-across-hpc-systems-the-cloud-and-beyond
- Nextflow executors: https://docs.seqera.io/nextflow/executor
- Nextflow containers: https://docs.seqera.io/nextflow/container
- GitHub self-hosted runners: https://docs.github.com/actions/hosting-your-own-runners
- GATK resource bundle: https://gatk.broadinstitute.org/hc/en-us/articles/360035890811-Resource-bundle
- BWA-MEM2: https://github.com/bwa-mem2/bwa-mem2
