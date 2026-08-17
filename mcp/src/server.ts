import { randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { promisify } from "node:util";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { Request, Response } from "express";
import { z } from "zod";
import {
  acquireAuditLock,
  type AuditRecord,
  readAuditRecord,
  resolveDirectoryUnderRoot,
  sanitizeError,
  sanitizeToolArguments,
  writeAuditRecord,
} from "./core.js";
import { TOOL_DEFINITIONS } from "./toolDefinitions.js";

const execFileAsync = promisify(execFile);
const requestIdSchema = z
  .string()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/)
  .describe("Bounded idempotency and audit identifier; no paths or secrets.");

export type GenomeServerOptions = {
  projectRoot: string;
  referenceRoot: string;
  resultsRoot: string;
  auditRoot: string;
};

function textResult(value: unknown) {
  const text = JSON.stringify(value, null, 2);
  return {
    content: [{ type: "text" as const, text }],
    structuredContent: value as Record<string, unknown>,
  };
}

async function runFixedScript(
  script: string,
  args: string[],
  env: NodeJS.ProcessEnv,
  timeout: number,
): Promise<string> {
  const { stdout } = await execFileAsync(script, args, {
    env,
    maxBuffer: 5 * 1024 * 1024,
    timeout,
    windowsHide: true,
  });
  return stdout.trim();
}

type PriorResult<T> =
  | { kind: "missing" }
  | { kind: "pass"; value: T }
  | { kind: "fail"; error: string };

async function loadAuditRecord(auditRoot: string, requestId: string): Promise<AuditRecord | undefined> {
  try {
    return await readAuditRecord(auditRoot, requestId);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return undefined;
    }
    throw error;
  }
}

function assertMatchingTool(existing: AuditRecord, tool: string): void {
  if (existing.tool !== tool) {
    throw new Error("request id already belongs to a different tool");
  }
}

function decodeCompletedResult<T>(existing: AuditRecord): PriorResult<T> {
  if (existing.status === "PASS") {
    return { kind: "pass", value: existing.result as T };
  }
  return { kind: "fail", error: existing.error || "prior request failed" };
}

function decodePriorResult<T>(existing: AuditRecord | undefined, tool: string): PriorResult<T> {
  if (!existing) {
    return { kind: "missing" };
  }
  assertMatchingTool(existing, tool);
  return decodeCompletedResult<T>(existing);
}

async function persistOutcome(
  options: GenomeServerOptions,
  record: AuditRecord,
): Promise<void> {
  await writeAuditRecord(options.auditRoot, record);
}

/** @internal Exported for deterministic idempotency and redaction tests. */
export async function runAudited<T>(
  options: GenomeServerOptions,
  tool: string,
  args: Record<string, unknown>,
  operation: () => Promise<T>,
): Promise<T> {
  const requestId = String(args.requestId);
  const existing = await loadAuditRecord(options.auditRoot, requestId);
  const prior = decodePriorResult<T>(existing, tool);
  if (prior.kind === "pass") {
    return prior.value;
  }
  if (prior.kind === "fail") {
    throw new Error(prior.error);
  }

  const releaseLock = await acquireAuditLock(options.auditRoot, requestId);
  try {
    const afterLock = decodePriorResult<T>(await loadAuditRecord(options.auditRoot, requestId), tool);
    if (afterLock.kind === "pass") {
      return afterLock.value;
    }
    if (afterLock.kind === "fail") {
      throw new Error(afterLock.error);
    }

    const startedAt = new Date().toISOString();
    const started = Date.now();
    try {
      const result = await operation();
      const record: AuditRecord = {
        requestId,
        tool,
        arguments: sanitizeToolArguments({ ...args, requestId }),
        status: "PASS",
        startedAt,
        durationMs: Date.now() - started,
        result,
      };
      await persistOutcome(options, record);
      return result;
    } catch (error) {
      const sanitized = sanitizeError(error);
      const record: AuditRecord = {
        requestId,
        tool,
        arguments: sanitizeToolArguments({ ...args, requestId }),
        status: "FAIL",
        startedAt,
        durationMs: Date.now() - started,
        error: sanitized,
      };
      await persistOutcome(options, record);
      throw new Error(sanitized);
    }
  } finally {
    await releaseLock();
  }
}

export function createGenomeMcpServer(options: GenomeServerOptions): McpServer {
  const server = new McpServer(
    { name: "codework-private-genome", version: "0.1.0" },
    {
      instructions:
        "Use status tools before any genomic workflow. Only the synthetic canary can execute in this version. Never request or return raw genomic data. External GRCh38 lock approval and live post-deployment gates remain human-controlled.",
    },
  );

  server.registerTool(
    "runtime_status",
    {
      ...TOOL_DEFINITIONS.runtime_status,
      inputSchema: { requestId: requestIdSchema.optional() },
    },
    async ({ requestId }) => {
      const auditRequestId = requestId ?? randomUUID();
      const result = await runAudited(options, "runtime_status", { requestId: auditRequestId }, async () => {
        const output = await runFixedScript(
          path.join(options.projectRoot, "scripts", "check_versions.sh"),
          [],
          process.env,
          60_000,
        );
        return { status: "PASS", output: sanitizeError(output) };
      });
      return textResult(result);
    },
  );

  server.registerTool(
    "reference_status",
    {
      ...TOOL_DEFINITIONS.reference_status,
      inputSchema: { requestId: requestIdSchema.optional() },
    },
    async ({ requestId }) => {
      const auditRequestId = requestId ?? randomUUID();
      const result = await runAudited(options, "reference_status", { requestId: auditRequestId }, async () => {
        const output = await runFixedScript(
          path.join(options.projectRoot, "scripts", "validate_grch38.sh"),
          [],
          { ...process.env, REF_ROOT: options.referenceRoot, REQUIRE_BWA_INDEX: "1" },
          10 * 60_000,
        );
        return { status: "PASS", output: sanitizeError(output) };
      });
      return textResult(result);
    },
  );

  server.registerTool(
    "run_synthetic_canary",
    {
      ...TOOL_DEFINITIONS.run_synthetic_canary,
      inputSchema: { requestId: requestIdSchema },
    },
    async ({ requestId }) => {
      const result = await runAudited(options, "run_synthetic_canary", { requestId }, async () => {
        const canaryRoot = resolveDirectoryUnderRoot(path.join(options.resultsRoot, "canary"), requestId);
        await runFixedScript(
          path.join(options.projectRoot, "scripts", "run_canary.sh"),
          [canaryRoot],
          process.env,
          60 * 60_000,
        );
        return JSON.parse(await readFile(path.join(canaryRoot, "report.json"), "utf8")) as Record<string, unknown>;
      });
      return textResult(result);
    },
  );

  server.registerTool(
    "audit_record",
    {
      ...TOOL_DEFINITIONS.audit_record,
      inputSchema: { requestId: requestIdSchema },
    },
    async ({ requestId }) => textResult(await readAuditRecord(options.auditRoot, requestId)),
  );

  return server;
}

export function createHttpApp(options: GenomeServerOptions) {
  const app = createMcpExpressApp();
  app.get("/healthz", (_req: Request, res: Response) => res.status(200).json({ status: "ok" }));
  app.post("/mcp", async (req: Request, res: Response) => {
    const server = createGenomeMcpServer(options);
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res, req.body);
      res.on("close", () => {
        void transport.close();
        void server.close();
      });
    } catch (error) {
      const sanitized = sanitizeError(error);
      if (!res.headersSent) {
        res.status(500).json({
          jsonrpc: "2.0",
          error: { code: -32603, message: sanitized },
          id: null,
        });
      }
    }
  });
  for (const method of ["get", "delete"] as const) {
    app[method]("/mcp", (_req: Request, res: Response) =>
      res.status(405).json({ jsonrpc: "2.0", error: { code: -32000, message: "Method not allowed" }, id: null }),
    );
  }
  return app;
}

const defaultProjectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const options: GenomeServerOptions = {
  projectRoot: process.env.PROJECT_ROOT ?? defaultProjectRoot,
  referenceRoot: process.env.REF_ROOT ?? "/refs",
  resultsRoot: process.env.RESULTS_ROOT ?? "/results",
  auditRoot: process.env.AUDIT_ROOT ?? "/audit",
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const port = Number(process.env.PORT ?? "3000");
  const host = process.env.MCP_BIND_HOST ?? "127.0.0.1";
  createHttpApp(options).listen(port, host, (error?: Error) => {
    if (error) {
      process.stderr.write(`${sanitizeError(error)}\n`);
      process.exitCode = 1;
      return;
    }
    process.stdout.write(`codework-private-genome listening on ${host}:${port}\n`);
  });
}
