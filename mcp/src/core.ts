import path from "node:path";
import os from "node:os";
import { chmod, mkdir, open, readFile, unlink, writeFile } from "node:fs/promises";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SAFE_ARGUMENT_KEYS = new Set(["requestId"]);
const DEFAULT_FOREIGN_HOST_STALE_MS = 24 * 60 * 60 * 1000;

export type AuditRecord = {
  requestId: string;
  tool: string;
  arguments: Record<string, unknown>;
  status: "PASS" | "FAIL";
  startedAt: string;
  durationMs: number;
  result?: unknown;
  error?: string;
};

type AuditLock = {
  schema: "genoma-audit-lock-v1";
  requestId: string;
  pid: number;
  host: string;
  createdAt: string;
};

function validateIdentifier(identifier: string): void {
  if (!IDENTIFIER.test(identifier) || identifier === "." || identifier === "..") {
    throw new Error("invalid bounded identifier");
  }
}

export function resolveUnderRoot(root: string, identifier: string): string {
  validateIdentifier(identifier);
  const absoluteRoot = path.resolve(root);
  const candidate = path.resolve(absoluteRoot, `${identifier}.json`);
  if (!candidate.startsWith(`${absoluteRoot}${path.sep}`)) {
    throw new Error("identifier resolves outside configured root");
  }
  return candidate;
}

function resolveLockUnderRoot(root: string, identifier: string): string {
  validateIdentifier(identifier);
  const absoluteRoot = path.resolve(root);
  const candidate = path.resolve(absoluteRoot, `${identifier}.lock`);
  if (!candidate.startsWith(`${absoluteRoot}${path.sep}`)) {
    throw new Error("identifier resolves outside configured root");
  }
  return candidate;
}

export function resolveDirectoryUnderRoot(root: string, identifier: string): string {
  validateIdentifier(identifier);
  const absoluteRoot = path.resolve(root);
  const candidate = path.resolve(absoluteRoot, identifier);
  if (!candidate.startsWith(`${absoluteRoot}${path.sep}`)) {
    throw new Error("identifier resolves outside configured root");
  }
  return candidate;
}

export function sanitizeToolArguments(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).map(([key, value]) => [key, SAFE_ARGUMENT_KEYS.has(key) ? value : "[REDACTED]"]),
  );
}

export function sanitizeError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  return raw
    .replace(/Bearer\s+[^\s]+/gi, "Bearer [REDACTED_TOKEN]")
    .replace(/\/(?:[A-Za-z0-9._-]+\/)+[A-Za-z0-9._-]+/g, "[REDACTED_PATH]")
    .replace(/\b(?:sk|ghp|github_pat)_[A-Za-z0-9_-]{8,}\b/g, "[REDACTED_TOKEN]");
}

function localPidIsAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ESRCH") return false;
    return true;
  }
}

async function abandonedLockCanBeRecovered(lockPath: string): Promise<boolean> {
  let metadata: AuditLock;
  try {
    metadata = JSON.parse(await readFile(lockPath, "utf8")) as AuditLock;
  } catch {
    return false;
  }
  if (metadata.schema !== "genoma-audit-lock-v1" || !metadata.createdAt || !metadata.host) return false;
  const created = Date.parse(metadata.createdAt);
  if (!Number.isFinite(created)) return false;
  if (metadata.host === os.hostname()) {
    return !localPidIsAlive(metadata.pid);
  }
  const configured = Number(process.env.GENOMA_FOREIGN_HOST_LOCK_STALE_MS ?? DEFAULT_FOREIGN_HOST_STALE_MS);
  const threshold = Number.isFinite(configured) && configured >= DEFAULT_FOREIGN_HOST_STALE_MS
    ? configured
    : DEFAULT_FOREIGN_HOST_STALE_MS;
  return Date.now() - created > threshold;
}

export async function acquireAuditLock(root: string, requestId: string): Promise<() => Promise<void>> {
  const absoluteRoot = path.resolve(root);
  await mkdir(absoluteRoot, { recursive: true, mode: 0o700 });
  await chmod(absoluteRoot, 0o700);
  const lock = resolveLockUnderRoot(root, requestId);
  const metadata: AuditLock = {
    schema: "genoma-audit-lock-v1",
    requestId,
    pid: process.pid,
    host: os.hostname(),
    createdAt: new Date().toISOString(),
  };

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const handle = await open(lock, "wx", 0o600);
      try {
        await handle.writeFile(`${JSON.stringify(metadata)}\n`, { encoding: "utf8" });
        await handle.sync();
      } finally {
        await handle.close();
      }
      await chmod(lock, 0o600);
      return async () => {
        try {
          await unlink(lock);
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
      if (attempt === 0 && await abandonedLockCanBeRecovered(lock)) {
        await unlink(lock);
        continue;
      }
      throw new Error("request id is already in progress; lock is live or not safely recoverable");
    }
  }
  throw new Error("unable to acquire audit lock");
}

export async function readAuditRecord(root: string, requestId: string): Promise<AuditRecord> {
  const file = resolveUnderRoot(root, requestId);
  return JSON.parse(await readFile(file, "utf8")) as AuditRecord;
}

export async function writeAuditRecord(root: string, record: AuditRecord): Promise<void> {
  const file = resolveUnderRoot(root, record.requestId);
  await mkdir(path.resolve(root), { recursive: true, mode: 0o700 });
  await chmod(path.resolve(root), 0o700);
  const payload = `${JSON.stringify(record, null, 2)}\n`;
  try {
    await writeFile(file, payload, { encoding: "utf8", flag: "wx", mode: 0o600 });
    await chmod(file, 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    const existing = await readAuditRecord(root, record.requestId);
    if (JSON.stringify(existing) !== JSON.stringify(record)) {
      throw new Error("request id already belongs to a different audit record");
    }
  }
}
