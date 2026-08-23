import { randomUUID } from "node:crypto";
import path from "node:path";
import { chmod, mkdir, readFile, unlink, writeFile } from "node:fs/promises";

const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const SAFE_ARGUMENT_KEYS = new Set(["requestId"]);
const AUDIT_RECORD_EXTENSION = ".json";
const AUDIT_LOCK_EXTENSION = ".lock";

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

function validateIdentifier(identifier: string): void {
  if (!IDENTIFIER.test(identifier) || identifier === "." || identifier === "..") {
    throw new Error("invalid bounded identifier");
  }
}

/**
 * Resolve one direct child of ``root`` and prove containment with ``path.relative``.
 *
 * A ``startsWith`` prefix test is not a containment test: it rejects a legitimate
 * child when the root is "/" (the candidate never carries the doubled separator)
 * and it depends on the caller having normalised the root first. Comparing the
 * relative path is exact — it must be the single expected segment, never empty,
 * never a traversal, never absolute (which is how a Windows drive change appears).
 */
function resolveChildUnderRoot(root: string, child: string): string {
  const absoluteRoot = path.resolve(root);
  const candidate = path.resolve(absoluteRoot, child);
  const relative = path.relative(absoluteRoot, candidate);
  if (relative !== child || relative === "" || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("identifier resolves outside configured root");
  }
  return candidate;
}

export function resolveUnderRoot(root: string, identifier: string, extension: string = AUDIT_RECORD_EXTENSION): string {
  validateIdentifier(identifier);
  return resolveChildUnderRoot(root, `${identifier}${extension}`);
}

export function resolveDirectoryUnderRoot(root: string, identifier: string): string {
  validateIdentifier(identifier);
  return resolveChildUnderRoot(root, identifier);
}

export function sanitizeToolArguments(input: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(input).map(([key, value]) => [key, SAFE_ARGUMENT_KEYS.has(key) ? value : "[REDACTED]"]),
  );
}

/**
 * Redaction rules applied to every message that leaves the server, in order.
 *
 * Order is part of the contract: credentials embedded in a URL are redacted
 * before the path rules run, otherwise the path rule consumes the URL and the
 * credential survives inside the "[REDACTED_PATH]" it produced.
 */
const REDACTIONS: ReadonlyArray<readonly [RegExp, string]> = [
  [/Bearer\s+[^\s]+/gi, "Bearer [REDACTED_TOKEN]"],
  // user:password@host in any URL, before the path rules can swallow it.
  [/[A-Za-z][A-Za-z0-9+.-]*:\/\/[^/\s:@]+:[^/\s@]*@/g, "[REDACTED_CREDENTIALS]@"],
  // Windows drive and UNC paths, plus bare backslash-separated paths.
  [/\b[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*/g, "[REDACTED_PATH]"],
  [/\\\\(?:[A-Za-z0-9._$-]+\\)+[A-Za-z0-9._$-]+/g, "[REDACTED_PATH]"],
  [/\/(?:[A-Za-z0-9._-]+\/)+[A-Za-z0-9._-]+/g, "[REDACTED_PATH]"],
  // Vendor-prefixed credentials. Underscore-separated and opaque prefixes are
  // listed separately because only the first family carries the "_" delimiter.
  [/\b(?:sk|pk|rk|ghp|gho|ghu|ghs|ghr|github_pat|glpat|xox[abioprs])_[A-Za-z0-9_-]{8,}\b/g, "[REDACTED_TOKEN]"],
  [/\b(?:AKIA|ASIA|ABIA|ACCA|A3T)[A-Z0-9]{12,}\b/g, "[REDACTED_TOKEN]"],
  [/\bAIza[A-Za-z0-9_-]{16,}\b/g, "[REDACTED_TOKEN]"],
  // JSON Web Tokens, whose payload routinely carries identity claims.
  [/\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\b/g, "[REDACTED_TOKEN]"],
];

export function sanitizeError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  return REDACTIONS.reduce((message, [pattern, replacement]) => message.replace(pattern, replacement), raw);
}

export async function readAuditRecord(root: string, requestId: string): Promise<AuditRecord> {
  const file = resolveUnderRoot(root, requestId);
  return JSON.parse(await readFile(file, "utf8")) as AuditRecord;
}

async function ensureAuditRoot(root: string): Promise<void> {
  await mkdir(path.resolve(root), { recursive: true, mode: 0o700 });
  await chmod(path.resolve(root), 0o700);
}

/** Proof that this caller, and no other, holds the right to execute a request id. */
export type AuditClaim = {
  requestId: string;
  file: string;
  token: string;
};

type AuditClaimPayload = {
  requestId: string;
  token: string;
  pid: number;
  acquiredAt: string;
};

/**
 * Take the exclusive right to execute ``requestId``, or report that someone else holds it.
 *
 * The claim is the ``wx`` creation itself: the kernel admits exactly one creator
 * of a given path, so the winner is decided before any work starts rather than
 * when the result is finally written. Writing the record atomically is not
 * enough on its own — by then both callers have already run the operation.
 *
 * A claim is never stolen, not even a very old one. Silent takeover would
 * reintroduce exactly the double-execution this function exists to prevent, so
 * an abandoned claim is surfaced to an operator by ``describeAuditClaim``
 * instead of being cleared automatically.
 */
export async function acquireAuditClaim(root: string, requestId: string): Promise<AuditClaim | undefined> {
  const file = resolveUnderRoot(root, requestId, AUDIT_LOCK_EXTENSION);
  await ensureAuditRoot(root);
  const claim: AuditClaim = { requestId, file, token: randomUUID() };
  const payload: AuditClaimPayload = {
    requestId,
    token: claim.token,
    pid: process.pid,
    acquiredAt: new Date().toISOString(),
  };
  try {
    await writeFile(file, `${JSON.stringify(payload)}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") {
      return undefined;
    }
    throw error;
  }
  return claim;
}

/** Release a claim, and only ever the caller's own. */
export async function releaseAuditClaim(claim: AuditClaim): Promise<void> {
  let held: AuditClaimPayload;
  try {
    held = JSON.parse(await readFile(claim.file, "utf8")) as AuditClaimPayload;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return;
    }
    throw error;
  }
  if (held.token !== claim.token) {
    return;
  }
  try {
    await unlink(claim.file);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      throw error;
    }
  }
}

/** Age of the claim currently held for ``requestId``, for operator-facing diagnostics. */
export async function describeAuditClaim(
  root: string,
  requestId: string,
): Promise<{ acquiredAt: string; ageMs: number } | undefined> {
  const file = resolveUnderRoot(root, requestId, AUDIT_LOCK_EXTENSION);
  let held: AuditClaimPayload;
  try {
    held = JSON.parse(await readFile(file, "utf8")) as AuditClaimPayload;
  } catch {
    return undefined;
  }
  const acquired = Date.parse(held.acquiredAt);
  return {
    acquiredAt: held.acquiredAt,
    ageMs: Number.isNaN(acquired) ? Number.POSITIVE_INFINITY : Date.now() - acquired,
  };
}

export async function writeAuditRecord(root: string, record: AuditRecord): Promise<void> {
  const file = resolveUnderRoot(root, record.requestId);
  await ensureAuditRoot(root);
  const payload = `${JSON.stringify(record, null, 2)}\n`;
  try {
    await writeFile(file, payload, { encoding: "utf8", flag: "wx", mode: 0o600 });
    await chmod(file, 0o600);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") {
      throw error;
    }
    const existing = await readAuditRecord(root, record.requestId);
    if (JSON.stringify(existing) !== JSON.stringify(record)) {
      throw new Error("request id already belongs to a different audit record");
    }
  }
}
