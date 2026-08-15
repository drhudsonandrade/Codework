# Pre-deployment validation — 2026-08-15 UTC

## Result

`PRE-DEPLOYMENT VALIDATION PASS / POST-DEPLOYMENT PENDENTE`

This report records only evidence executed in the ChatGPT Work scratch runtime. It is not target-host or clinical validation.

## Repository and code gates

| Gate | Result | Evidence |
|---|---|---|
| Locked npm install | PASS | `npm ci --offline --ignore-scripts` installed 112 packages from the pinned lockfile. |
| TypeScript compile | PASS | `tsc -p mcp/tsconfig.json`; explicit Express request/response types added. |
| MCP tests | PASS | 12/12. |
| Python tests | PASS | 5/5. |
| Shell syntax | PASS | Every `scripts/*.sh` passed `bash -n`. |
| YAML parse | PASS | Both workflows, Compose and `environment.yml`. |
| Repository contract | PASS | Required paths, payload exclusions and lock rules. |
| GRCh38 source manifest | PASS | Exactly 9/9 declared artifacts. This does not mean that the artifacts are installed. |
| Ruleset identity | PASS | SHA-256 `ebad57ae4864418bd5d8e9126c12fbf938b341af5fb73d3511e63e6a8eae221a`; `VIGENTE`; v3.3; 14/08/2026. |
| Fallow 3.16.0 quality | PASS | 0 issues; 0 critical/high/moderate complexity findings. |
| Fallow security review | REVIEWED | 12 medium path-construction candidates, 0 high. All 12 are covered by bounded identifiers, fixed script names or administrator-controlled roots; no suppression was added. |

## Live MCP transport canary

- `GET /healthz`: PASS, HTTP 200.
- Streamable HTTP `initialize`: PASS, protocol `2025-06-18`.
- `tools/list`: PASS; exactly `runtime_status`, `reference_status`, `run_synthetic_canary`, and `audit_record`.
- `GET /mcp`: PASS, HTTP 405 as designed.
- Sensitive payload: none.

The non-sensitive execution canary was called with:

```json
{
  "tool": "run_synthetic_canary",
  "arguments": { "requestId": "canary-nosensitive-20260815a" }
}
```

Observed result: expected FAIL on this host because the pinned NGS executables are absent. The server stored an idempotent redacted audit record containing tool, bounded arguments, `status: "FAIL"`, duration and sanitized error. The audit file mode was `0600`.

## Host capability gates

- Java: present.
- Required but absent from the core runtime contract: `samtools`, `bcftools`, `bwa-mem2`, `gatk`, `nextflow`, and `snakemake`.
- Also absent: Docker, Podman, conda, mamba and micromamba.
- Host resources observed: 15 GiB RAM, no swap, about 46 GiB free workspace storage.
- GRCh38 payload: not installed on this host; only the 9/9 acquisition manifest and validation scripts are present.
- Full GATK/bcftools calling: not executed here. The container canary workflow must run it.

## Connector canaries

No sensitive arguments or genomic payloads were sent.

| Integration | Call | Result |
|---|---|---|
| GitHub | authenticated user | PASS |
| GitHub | installed accounts/installations | BLOCKED — zero installations |
| GitHub | repository `drhudsonandrade/Codework` | BLOCKED — 404/not accessible to the App |
| microfn | `ping {}` | PASS |
| Supabase | `list_projects {}` | PASS; project details intentionally omitted |
| Exa | public documentation search | PASS |
| Parallel Search | public documentation search | PASS |
| Noodle Seed | `noodle setup --write --json` | NOT AVAILABLE in this sandbox; its managed profile requires a host-home path that is not writable here |

Fallow is the only selected integration needed in the repository's critical CI path. Supabase, microfn, Temporal, Flower and Cloudflare are not dependencies of the first private genomic runtime and were not added to the data plane.

## Blocking gates before post-deployment

1. Install the ChatGPT/OpenAI GitHub App on the account and grant it access to `Codework`; then publish one draft PR and run both workflows.
2. Build the pinned container and pass the synthetic GATK/bcftools canary.
3. Deploy to the target VM, install the 9 GRCh38 artifacts, externally approve `GRCh38.lock.sha256`, build the five bwa-mem2 index files, and pass contig/faidx/query validation.
4. Activate the canonical ruleset and BOOTSTRAP CURTO in the ChatGPT Project.
5. Execute section 260 live and require 15/15 with no critical failure.

Until all five gates pass, never record `POST-DEPLOYMENT PASS`.
