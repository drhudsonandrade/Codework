import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { chmod, mkdir, open, readFile, unlink } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import type { Request, Response } from "express";
import { z } from "zod";
import {
  type AuditRecord,
  readAuditRecord,
  resolveDirectoryUnderRoot,
  resolveUnderRoot,
  sanitizeError,
  sanitizeToolArguments,
  writeAuditRecord,
} from "./core.js";
import { TOOL_DEFINITIONS } from "./toolDefinitions.js";

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

const MINUTE_MS = 60_000;

/**
 * Per-tool execution budgets, declared in one place so a slow gate cannot be
 * silently given a different timeout at each call site. Each value reflects the
 * worst-case runtime of the underlying script, not a shared default.
 */
export const TOOL_TIMEOUTS_MS = {
  runtime_status: MINUTE_MS,
  reference_status: 10 * MINUTE_MS,
  run_synthetic_canary: 60 * MINUTE_MS,
} as const;

const SCRIPT_OUTPUT_MAX_BYTES = 5 * 1024 * 1024;
const STDERR_TAIL_MAX_BYTES = 4 * 1024;
/** Time a terminated process group gets to exit before it is killed outright. */
const GROUP_TERMINATION_GRACE_MS = 5_000;
/** A claim may be recovered only after every supported tool budget has expired. */
const REQUEST_CLAIM_STALE_MS =
  Math.max(...Object.values(TOOL_TIMEOUTS_MS)) + GROUP_TERMINATION_GRACE_MS + MINUTE_MS;
/** POSIX only: a negative pid signals the whole process group instead of one process. */
const USE_PROCESS_GROUP = process.platform !== "win32";

/**
 * @internal Exported so the timeout containment contract can be tested directly.
 *
 * The script runs in its own process group. `scripts/run_canary.sh` starts pipelines and
 * background tools, so signalling only the direct child on timeout leaves those
 * descendants running against the same results directory after the tool has already
 * failed. Every timeout therefore terminates the whole group.
 */
export async function runFixedScript(
  script: string,
  args: string[],
  env: NodeJS.ProcessEnv,
  timeout: number,
): Promise<string> {
  const child = spawn(script, args, {
    env,
    windowsHide: true,
    detached: USE_PROCESS_GROUP,
    stdio: ["ignore", "pipe", "pipe"],
  });

  const terminate = (signal: NodeJS.Signals): void => {
    const pid = child.pid;
    if (pid === undefined) {
      return;
    }
    try {
      process.kill(USE_PROCESS_GROUP ? -pid : pid, signal);
    } catch {
      // The group has already exited; nothing left to signal.
    }
  };

  let stdout = "";
  let stdoutBytes = 0;
  let overflowed = false;
  child.stdout.setEncoding("utf8");
  child.stdout.on("data", (chunk: string) => {
    stdoutBytes += Buffer.byteLength(chunk, "utf8");
    if (stdoutBytes > SCRIPT_OUTPUT_MAX_BYTES) {
      overflowed = true;
      terminate("SIGKILL");
      return;
    }
    stdout += chunk;
  });

  let stderrTail = Buffer.alloc(0);
  child.stderr.on("data", (chunk: Buffer) => {
    const combined = Buffer.concat([stderrTail, chunk]);
    stderrTail = combined.subarray(Math.max(0, combined.length - STDERR_TAIL_MAX_BYTES));
  });

  let timedOut = false;
  let killTimer: NodeJS.Timeout | undefined;
  const timeoutTimer = setTimeout(() => {
    timedOut = true;
    terminate("SIGTERM");
    killTimer = setTimeout(() => terminate("SIGKILL"), GROUP_TERMINATION_GRACE_MS);
    killTimer.unref();
  }, timeout);

  try {
    const code = await new Promise<number | null>((resolve, reject) => {
      child.once("error", reject);
      child.once("close", (exitCode) => resolve(exitCode));
    });
    if (timedOut) {
      throw new Error(`fixed script timed out after ${timeout}ms and its process group was terminated`);
    }
    if (overflowed) {
      throw new Error(`fixed script exceeded the ${SCRIPT_OUTPUT_MAX_BYTES} byte output budget`);
    }
    if (code !== 0) {
      const detail = stderrTail.toString("utf8").trim();
      throw new Error(
        detail
          ? `fixed script exited with code ${code}: ${sanitizeError(detail)}`
          : `fixed script exited with code ${code}`,
      );
    }
    return stdout.trim();
  } finally {
    clearTimeout(timeoutTimer);
    if (killTimer !== undefined) {
      clearTimeout(killTimer);
    }
    terminate("SIGKILL");
  }
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

type RequestClaim = {
  claimPath: string;
  handle: Awaited<ReturnType<typeof open>>;
};

type RequestClaimMetadata = {
  requestId: string;
  tool: string;
  claimedAt: string;
};

async function isRecoverableStaleClaim(
  claimPath: string,
  requestId: string,
  tool: string,
): Promise<boolean> {
  let raw: string;
  try {
    raw = await readFile(claimPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return true;
    }
    return false;
  }

  let metadata: RequestClaimMetadata;
  try {
    metadata = JSON.parse(raw) as RequestClaimMetadata;
  } catch {
    return false;
  }
  if (
    metadata.requestId !== requestId ||
    metadata.tool !== tool ||
    typeof metadata.claimedAt !== "string"
  ) {
    return false;
  }
  const claimedAt = Date.parse(metadata.claimedAt);
  if (!Number.isFinite(claimedAt)) {
    return false;
  }
  return Date.now() - claimedAt > REQUEST_CLAIM_STALE_MS;
}

async function acquireRequestClaim(
  options: GenomeServerOptions,
  requestId: string,
  tool: string,
): Promise<RequestClaim> {
  const root = path.resolve(options.auditRoot);
  await mkdir(root, { recursive: true, mode: 0o700 });
  await chmod(root, 0o700);
  const claimPath = `${resolveUnderRoot(root, requestId)}.claim`;

  while (true) {
    try {
      const handle = await open(claimPath, "wx", 0o600);
      try {
        await handle.writeFile(
          `${JSON.stringify({ requestId, tool, claimedAt: new Date().toISOString() })}\n`,
          "utf8",
        );
      } catch (error) {
        await releaseRequestClaim({ claimPath, handle });
        throw error;
      }
      return { claimPath, handle };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
        throw error;
      }
      const completed = await loadAuditRecord(options.auditRoot, requestId);
      if (completed) {
        assertMatchingTool(completed, tool);
        const prior = decodeCompletedResult<unknown>(completed);
        if (prior.kind === "fail") {
          throw new Error(prior.error);
        }
        throw new Error("request id completed while another caller held its claim");
      }
      if (!(await isRecoverableStaleClaim(claimPath, requestId, tool))) {
        throw new Error("request id is already in progress");
      }
      try {
        await unlink(claimPath);
      } catch (unlinkError) {
        if ((unlinkError as NodeJS.ErrnoException).code !== "ENOENT") {
          throw new Error("stale request claim could not be recovered");
        }
      }
      // Retry O_EXCL acquisition after removing a demonstrably stale claim. If another
      // caller wins the race, this loop observes its new claim and fails closed as active.
    }
  }
}

function logClaimReleaseFailure(stage: "close" | "unlink", error: unknown): void {
  const code = (error as NodeJS.ErrnoException).code;
  if (code === "ENOENT") {
    return;
  }
  console.warn("request claim release cleanup failed", { stage, code: code ?? "UNKNOWN" });
}

/** @internal Exported for deterministic cleanup tests. */
export async function releaseRequestClaim(claim: RequestClaim): Promise<void> {
  try {
    await claim.handle.close();
  } catch (error) {
    logClaimReleaseFailure("close", error);
  }
  try {
    await unlink(claim.claimPath);
  } catch (error) {
    logClaimReleaseFailure("unlink", error);
  }
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

  // O_EXCL establishes ownership before the operation begins. Concurrent callers with
  // the same requestId cannot both cross this point, including across server processes.
  const claim = await acquireRequestClaim(options, requestId, tool);
  const startedAt = new Date().toISOString();
  const started = Date.now();
  try {
    const afterClaim = decodePriorResult<T>(
      await loadAuditRecord(options.auditRoot, requestId),
      tool,
    );
    if (afterClaim.kind === "pass") {
      return afterClaim.value;
    }
    if (afterClaim.kind === "fail") {
      throw new Error(afterClaim.error);
    }

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
    await releaseRequestClaim(claim);
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
          TOOL_TIMEOUTS_MS.runtime_status,
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
          TOOL_TIMEOUTS_MS.reference_status,
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
          TOOL_TIMEOUTS_MS.run_synthetic_canary,
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