export const TOOL_DEFINITIONS = {
  runtime_status: {
    title: "NGS runtime status",
    description: "Use this when you need the installed NGS executable versions and runtime gate status.",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      openWorldHint: false,
      idempotentHint: true,
    },
  },
  reference_status: {
    title: "GRCh38 reference status",
    description: "Use this when you need checksum, contig, index, samtools faidx and bcftools query validation for the configured GRCh38 bundle.",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      openWorldHint: false,
      idempotentHint: true,
    },
  },
  run_synthetic_canary: {
    title: "Run synthetic variant-calling canary",
    description: "Use this when you need a non-sensitive GATK and bcftools execution canary. It never accepts personal genomic data.",
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      openWorldHint: false,
      idempotentHint: true,
    },
  },
  audit_record: {
    title: "Read redacted tool audit record",
    description: "Use this when you need the recorded tool name, redacted arguments, result status and sanitized error for a prior request id.",
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      openWorldHint: false,
      idempotentHint: true,
    },
  },
} as const;
