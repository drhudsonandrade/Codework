import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { chmod, mkdir, open, readFile, rename, rmdir, unlink, writeFile } from "node:fs/promises";
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

type SpawnedChild = ReturnType<typeof spawn>;

function terminateProcessGroup(child: SpawnedChild, signal: NodeJS.Signals): void {
  const pid = child.pid;
  if (pid === undefined) {
    return;
  }
  try {
    process.kill(USE_PROCESS_GROUP ? -pid : pid, signal);
  } catch {
    // The group has already exited; nothing left to signal.
  }
}

function scriptExitError(code: number | null, stderrTail: Buffer): Error {
  const message = `fixed script exited with code ${code}`;
  const detail = stderrTail.toString("utf8").trim();
  if (!detail) {
    return new Error(message);
  }
  return new Error(`${message}: ${sanitizeError(detail)}`);
}

function assertScriptOutcome(
  code: number | null,
  timedOut: boolean,
  overflowed: boolean,
  stderrTail: Buffer,
  timeout: number,
): void {
  if (timedOut) {
    throw new Error(`fixed script timed out after ${timeout}ms and its process group was terminated`);
  }
  if (overflowed) {
    throw new Error(`fixed script exceeded the ${SCRIPT_OUTPUT_MAX_BYTES} byte output budget`);
  }
  if (code !== 0) {
    throw scriptExitError(code, stderrTail);
  }
}

function clearScriptTimers(timeoutTimer: NodeJS.Timeout, killTimer: NodeJS.Timeout | undefined): void {
  clearTimeout(timeoutTimer);
  if (killTimer !== undefined) {
    clearTimeout(killTimer);
  }
}

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
  const terminate = (signal: NodeJS.Signals): void => terminateProcessGroup(child, signal);

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
    assertScriptOutcome(code, timedOut, overflowed, stderrTail, timeout);
    return stdout.trim();
  } finally {
    clearScriptTimers(timeoutTimer, killTimer);
    terminate("SIGKILL");
  }
}

type PriorResult<T> =
  | { kind: "missing" }
  | { kind: "pass"; value: T }
  | { kind: "fail"; error: string };

type ReplayDecision<T> = { kind: "continue" } | { kind: "return"; value: T };

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

function replayPriorResult<T>(prior: PriorResult<T>): ReplayDecision<T> {
  if (prior.kind === "pass") {
    return { kind: "return", value: prior.value };
  }
  if (prior.kind === "fail") {
    throw new Error(prior.error);
  }
  return { kind: "continue" };
}

async function persistOutcome(
  options: GenomeServerOptions,
  record: AuditRecord,
): Promise<void> {
  await writeAuditRecord(options.auditRoot, record);
}

type RequestClaim = {
  claimPath: string;
  claimId: string;
  handle: Awaited<ReturnType<typeof open>>;
};

type RequestClaimMetadata = {
  requestId: string;
  tool: string;
  claimedAt: string;
  claimId: string;
  ownerPid: number;
};

const requestClaimMetadataSchema = z
  .object({
    requestId: z.string(),
    tool: z.string(),
    claimedAt: z.string(),
    claimId: z.string().uuid(),
    ownerPid: z.number().int().positive(),
  })
  .strict();

type ClaimInspection =
  | { kind: "missing" }
  | { kind: "invalid" }
  | { kind: "metadata"; value: RequestClaimMetadata };

async function inspectRequestClaim(claimPath: string): Promise<ClaimInspection> {
  let raw: string;
  try {
    raw = await readFile(claimPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { kind: "missing" };
    }
    return { kind: "invalid" };
  }
  try {
    return { kind: "metadata", value: requestClaimMetadataSchema.parse(JSON.parse(raw)) };
  } catch {
    return { kind: "invalid" };
  }
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== "ESRCH";
  }
}

function claimMetadataMatches(metadata: RequestClaimMetadata, requestId: string, tool: string): boolean {
  return metadata.requestId === requestId && metadata.tool === tool;
}

function claimTimestampIsStale(claimedAt: string): boolean {
  const parsed = Date.parse(claimedAt);
  return Number.isFinite(parsed) && Date.now() - parsed > REQUEST_CLAIM_STALE_MS;
}

function isRecoverableStaleClaim(
  inspection: ClaimInspection,
  requestId: string,
  tool: string,
): boolean {
  return (
    inspection.kind === "metadata" &&
    claimMetadataMatches(inspection.value, requestId, tool) &&
    claimTimestampIsStale(inspection.value.claimedAt) &&
    !processIsAlive(inspection.value.ownerPid)
  );
}

type ClaimMutationLockMetadata = {
  lockId: string;
  ownerPid: number;
  lockedAt: string;
};

type ClaimMutationLock = {
  lockPath: string;
  ownerPath: string;
  metadata: ClaimMutationLockMetadata;
};

type ClaimMutationLockInspection =
  | { kind: "owner-missing"; ownerPath: string }
  | { kind: "invalid"; ownerPath: string }
  | { kind: "owner"; ownerPath: string; metadata: ClaimMutationLockMetadata };

const claimMutationLockMetadataSchema = z
  .object({
    lockId: z.string().uuid(),
    ownerPid: z.number().int().positive(),
    lockedAt: z.string(),
    state: z.enum(["HELD", "RELEASE_PENDING"]).optional(),
  })
  .strict();

const CLAIM_MUTATION_LOCK_OWNER = "owner.json";
const INVALID_OWNERLESS_LOCK_ERRORS = new Set(["ENOTEMPTY", "EEXIST"]);

function lockContention(error: unknown): boolean {
  const code = (error as NodeJS.ErrnoException).code;
  return code === "EEXIST" || code === "ENOTEMPTY";
}

async function inspectClaimMutationLock(lockPath: string): Promise<ClaimMutationLockInspection> {
  const ownerPath = path.join(lockPath, CLAIM_MUTATION_LOCK_OWNER);
  let raw: string;
  try {
    raw = await readFile(ownerPath, "utf8");
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "ENOENT"
      ? { kind: "owner-missing", ownerPath }
      : { kind: "invalid", ownerPath };
  }
  try {
    return { kind: "owner", ownerPath, metadata: claimMutationLockMetadataSchema.parse(JSON.parse(raw)) };
  } catch {
    return { kind: "invalid", ownerPath };
  }
}

async function cleanupStagedClaimMutationLock(stagingPath: string, ownerPath: string): Promise<void> {
  try {
    await unlink(ownerPath);
  } catch {
    // Preserve the acquisition error; this staging path never became the shared lock.
  }
  try {
    await rmdir(stagingPath);
  } catch {
    // Preserve the acquisition error; a unique staging directory cannot block another owner.
  }
}

async function createClaimMutationLock(lockPath: string): Promise<ClaimMutationLock> {
  const lockId = randomUUID();
  const metadata: ClaimMutationLockMetadata = {
    lockId,
    ownerPid: process.pid,
    lockedAt: new Date().toISOString(),
  };
  const stagingPath = `${lockPath}.owner-${lockId}`;
  const stagingOwnerPath = path.join(stagingPath, CLAIM_MUTATION_LOCK_OWNER);
  await mkdir(stagingPath, { mode: 0o700 });
  try {
    await writeFile(stagingOwnerPath, `${JSON.stringify(metadata)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    await rename(stagingPath, lockPath);
  } catch (error) {
    await cleanupStagedClaimMutationLock(stagingPath, stagingOwnerPath);
    throw error;
  }
  return { lockPath, ownerPath: path.join(lockPath, CLAIM_MUTATION_LOCK_OWNER), metadata };
}

function assertRecoverableClaimMutationLock(
  inspection: ClaimMutationLockInspection,
): Extract<ClaimMutationLockInspection, { kind: "owner" }> {
  if (inspection.kind !== "owner") {
    throw new Error("request claim coordination lock is invalid");
  }
  if (processIsAlive(inspection.metadata.ownerPid)) {
    throw new Error("request id is already in progress");
  }
  return inspection;
}

async function removeClaimMutationLockOwnerForRecovery(ownerPath: string): Promise<void> {
  try {
    await unlink(ownerPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw new Error("request claim coordination lock could not be recovered");
    }
  }
}

type OwnerlessLockRemovalError = "gone" | "invalid" | "failed";

function classifyOwnerlessLockRemovalError(error: unknown): OwnerlessLockRemovalError {
  const code = (error as NodeJS.ErrnoException).code;
  if (code === "ENOENT") {
    return "gone";
  }
  return INVALID_OWNERLESS_LOCK_ERRORS.has(code ?? "") ? "invalid" : "failed";
}

async function removeOwnerlessClaimMutationLock(lockPath: string): Promise<boolean> {
  try {
    await rmdir(lockPath);
    return true;
  } catch (error) {
    const outcome = classifyOwnerlessLockRemovalError(error);
    if (outcome === "gone") {
      return true;
    }
    if (outcome === "invalid") {
      throw new Error("request claim coordination lock is invalid");
    }
    throw new Error("request claim coordination lock could not be recovered");
  }
}

async function recoverClaimMutationLock(lockPath: string): Promise<boolean> {
  const inspection = await inspectClaimMutationLock(lockPath);
  if (inspection.kind === "owner-missing") {
    return removeOwnerlessClaimMutationLock(lockPath);
  }
  const owner = assertRecoverableClaimMutationLock(inspection);
  await removeClaimMutationLockOwnerForRecovery(owner.ownerPath);
  return removeOwnerlessClaimMutationLock(lockPath);
}

async function tryCreateClaimMutationLock(lockPath: string): Promise<ClaimMutationLock | undefined> {
  try {
    return await createClaimMutationLock(lockPath);
  } catch (error) {
    if (lockContention(error)) {
      return undefined;
    }
    throw error;
  }
}

async function acquireClaimMutationLock(lockPath: string): Promise<ClaimMutationLock> {
  const immediate = await tryCreateClaimMutationLock(lockPath);
  if (immediate) {
    return immediate;
  }
  if (!(await recoverClaimMutationLock(lockPath))) {
    throw new Error("request id is already in progress");
  }
  const retried = await tryCreateClaimMutationLock(lockPath);
  if (!retried) {
    throw new Error("request id is already in progress");
  }
  return retried;
}

function logClaimMutationLockFailure(stage: "owner" | "directory" | "ownership", error?: unknown): void {
  const code = (error as NodeJS.ErrnoException | undefined)?.code;
  if (code === "ENOENT") {
    return;
  }
  console.warn("request claim coordination lock cleanup failed", { stage, code: code ?? "UNKNOWN" });
}

function claimMutationLockOwnedBy(
  inspection: ClaimMutationLockInspection,
  lockId: string,
): inspection is Extract<ClaimMutationLockInspection, { kind: "owner" }> {
  return inspection.kind === "owner" && inspection.metadata.lockId === lockId;
}

async function removeClaimMutationLockOwnerForRelease(ownerPath: string): Promise<boolean> {
  try {
    await unlink(ownerPath);
    return true;
  } catch (error) {
    logClaimMutationLockFailure("owner", error);
    return false;
  }
}

async function removeClaimMutationLockDirectoryForRelease(lockPath: string): Promise<void> {
  try {
    await rmdir(lockPath);
  } catch (error) {
    logClaimMutationLockFailure("directory", error);
  }
}

async function releaseClaimMutationLock(lock: ClaimMutationLock): Promise<void> {
  const inspection = await inspectClaimMutationLock(lock.lockPath);
  if (!claimMutationLockOwnedBy(inspection, lock.metadata.lockId)) {
    logClaimMutationLockFailure("ownership");
    return;
  }
  if (!(await removeClaimMutationLockOwnerForRelease(lock.ownerPath))) {
    return;
  }
  await removeClaimMutationLockDirectoryForRelease(lock.lockPath);
}

/** @internal Exported for deterministic coordination-lock cleanup tests. */
export async function withClaimMutationLock<T>(
  claimPath: string,
  operation: () => Promise<T>,
): Promise<T> {
  const lockPath = `${claimPath}.lock`;
  const lock = await acquireClaimMutationLock(lockPath);
  try {
    return await operation();
  } finally {
    await releaseClaimMutationLock(lock);
  }
}

async function createRequestClaim(claimPath: string, requestId: string, tool: string): Promise<RequestClaim> {
  const claimId = randomUUID();
  const handle = await open(claimPath, "wx", 0o600);
  try {
    await handle.writeFile(
      `${JSON.stringify({
        requestId,
        tool,
        claimedAt: new Date().toISOString(),
        claimId,
        ownerPid: process.pid,
      })}\n`,
      "utf8",
    );
  } catch (error) {
    try {
      await handle.close();
    } catch {
      // The original write failure remains the primary error.
    }
    try {
      await unlink(claimPath);
    } catch {
      // The coordination lock still prevents another claimant from racing this cleanup.
    }
    throw error;
  }
  return { claimPath, claimId, handle };
}

async function assertNoCompletedAudit(options: GenomeServerOptions, requestId: string, tool: string): Promise<void> {
  const completed = await loadAuditRecord(options.auditRoot, requestId);
  if (!completed) {
    return;
  }
  assertMatchingTool(completed, tool);
  const prior = decodeCompletedResult<unknown>(completed);
  if (prior.kind === "fail") {
    throw new Error(prior.error);
  }
  throw new Error("request id completed while another caller held its claim");
}

function staleClaimNeedsRemoval(
  inspection: ClaimInspection,
  requestId: string,
  tool: string,
): boolean {
  if (inspection.kind === "missing") {
    return false;
  }
  if (!isRecoverableStaleClaim(inspection, requestId, tool)) {
    throw new Error("request id is already in progress");
  }
  return true;
}

async function unlinkStaleClaim(claimPath: string): Promise<void> {
  try {
    await unlink(claimPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw new Error("stale request claim could not be recovered");
    }
  }
}

async function removeRecoverableStaleClaim(
  claimPath: string,
  inspection: ClaimInspection,
  requestId: string,
  tool: string,
): Promise<void> {
  if (!staleClaimNeedsRemoval(inspection, requestId, tool)) {
    return;
  }
  await unlinkStaleClaim(claimPath);
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

  return withClaimMutationLock(claimPath, async () => {
    await assertNoCompletedAudit(options, requestId, tool);
    const inspection = await inspectRequestClaim(claimPath);
    await removeRecoverableStaleClaim(claimPath, inspection, requestId, tool);
    return createRequestClaim(claimPath, requestId, tool);
  });
}

function logClaimReleaseFailure(stage: "close" | "unlink" | "lock", error: unknown): void {
  const code = (error as NodeJS.ErrnoException).code;
  if (code === "ENOENT") {
    return;
  }
  console.warn("request claim release cleanup failed", { stage, code: code ?? "UNKNOWN" });
}

function logClaimOwnershipChange(): void {
  console.warn("request claim release skipped because ownership changed or metadata is invalid");
}

function inspectionBelongsToClaim(inspection: ClaimInspection, claimId: string): boolean {
  return inspection.kind === "metadata" && inspection.value.claimId === claimId;
}

async function unlinkReleasedClaim(claimPath: string): Promise<void> {
  try {
    await unlink(claimPath);
  } catch (error) {
    logClaimReleaseFailure("unlink", error);
  }
}

async function releaseOwnedClaimPath(claim: RequestClaim): Promise<void> {
  const inspection = await inspectRequestClaim(claim.claimPath);
  if (inspection.kind === "missing") {
    return;
  }
  if (!inspectionBelongsToClaim(inspection, claim.claimId)) {
    logClaimOwnershipChange();
    return;
  }
  await unlinkReleasedClaim(claim.claimPath);
}

/** @internal Exported for deterministic cleanup tests. */
export async function releaseRequestClaim(claim: RequestClaim): Promise<void> {
  try {
    await claim.handle.close();
  } catch (error) {
    logClaimReleaseFailure("close", error);
  }

  try {
    await withClaimMutationLock(claim.claimPath, () => releaseOwnedClaimPath(claim));
  } catch (error) {
    logClaimReleaseFailure("lock", error);
  }
}

async function executeAuditedOperation<T>(
  options: GenomeServerOptions,
  requestId: string,
  tool: string,
  args: Record<string, unknown>,
  operation: () => Promise<T>,
  startedAt: string,
  started: number,
): Promise<T> {
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
}

/** @internal Exported for deterministic idempotency and redaction tests. */
export async function runAudited<T>(
  options: GenomeServerOptions,
  tool: string,
  args: Record<string, unknown>,
  operation: () => Promise<T>,
): Promise<T> {
  const requestId = String(args.requestId);
  const prior = replayPriorResult(
    decodePriorResult<T>(await loadAuditRecord(options.auditRoot, requestId), tool),
  );
  if (prior.kind === "return") {
    return prior.value;
  }

  // The mutation lock serializes claim-path changes, and stale recovery is allowed only
  // after the recorded owner process is no longer alive. This prevents an active owner
  // from being fenced out by elapsed wall-clock time alone.
  const claim = await acquireRequestClaim(options, requestId, tool);
  const startedAt = new Date().toISOString();
  const started = Date.now();
  try {
    const afterClaim = replayPriorResult(
      decodePriorResult<T>(await loadAuditRecord(options.auditRoot, requestId), tool),
    );
    if (afterClaim.kind === "return") {
      return afterClaim.value;
    }
    return await executeAuditedOperation(options, requestId, tool, args, operation, startedAt, started);
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
