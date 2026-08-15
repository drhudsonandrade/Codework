# Fallow security candidate review

Review date: 2026-08-15 UTC
Analyzer: Fallow 3.16.0
Command: `fallow security --format json --quiet --surface`

Fallow surfaced 12 medium-severity path-traversal **candidates** and no high-severity candidate. They were manually verified as controlled path construction, not confirmed vulnerabilities:

| Candidate group | Control verified | Verdict |
|---|---|---|
| `resolveUnderRoot` and `resolveDirectoryUnderRoot` | The only caller-controlled component is restricted to `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, explicitly rejects `.` and `..`, and the resolved path must remain below the configured root. Tests reject traversal and separators. | Reviewed; bounded |
| Audit JSON path | Uses `resolveUnderRoot`; create-only `wx`; audit directory and records are forced to modes `0700` and `0600`. | Reviewed; bounded |
| Canary output and report path | `requestId` uses the bounded identifier schema, the directory is checked below `RESULTS_ROOT/canary`, and only the fixed `report.json` child is read. | Reviewed; bounded |
| Fixed workflow scripts | Script names are constants. `PROJECT_ROOT`, `REF_ROOT`, `RESULTS_ROOT`, and `AUDIT_ROOT` are deployment-admin environment variables, never MCP tool arguments. | Reviewed; administrative trust boundary |
| Server module location | Derived from `import.meta.url`; not caller-controlled. | Reviewed; fixed runtime value |

No broad suppression was added, so later Fallow security runs will continue surfacing these sites for regression review. The MCP exposes no arbitrary command, arbitrary path, upload, deletion, or raw-genome read tool.

This review is static pre-deployment evidence. Production authentication, tunnel authorization, container mounts, and live canary results must still be verified before `POST-DEPLOYMENT PASS`.
