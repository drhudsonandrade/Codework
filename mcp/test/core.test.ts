import assert from "node:assert/strict";
import test from "node:test";
import os from "node:os";
import path from "node:path";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import {
  acquireAuditClaim,
  describeAuditClaim,
  readAuditRecord,
  releaseAuditClaim,
  resolveDirectoryUnderRoot,
  resolveUnderRoot,
  sanitizeError,
  sanitizeToolArguments,
  writeAuditRecord,
} from "../src/core.js";

test("resolveUnderRoot accepts a bounded identifier", () => {
  assert.equal(resolveUnderRoot("/srv/genome/audit", "canary-20260814"), "/srv/genome/audit/canary-20260814.json");
});

test("resolveUnderRoot rejects traversal and separators", () => {
  for (const value of ["../secret", "a/b", "a\\b", "", "."]) {
    assert.throws(() => resolveUnderRoot("/srv/genome/audit", value));
  }
});

test("resolveUnderRoot rejects every traversal encoding, before and after resolution", () => {
  const traversals = [
    "..",
    "../..",
    "..%2Fsecret",
    "%2e%2e%2fsecret",
    "....//secret",
    "..\\..\\secret",
    "/etc/passwd",
    "/srv/genome/audit-sibling/leak",
    "\0",
    "a\0b",
    "sub/../../escape",
    ".hidden",
    "-",
    " leading",
    "trailing ",
    "a".repeat(65),
  ];
  for (const value of traversals) {
    assert.throws(() => resolveUnderRoot("/srv/genome/audit", value), Error, `accepted: ${JSON.stringify(value)}`);
  }
});

test("resolveUnderRoot never returns a path outside the configured root", () => {
  const roots = ["/srv/genome/audit", "/srv/genome/audit/", "relative/root"];
  for (const root of roots) {
    const resolved = resolveUnderRoot(root, "canary-1");
    const absoluteRoot = path.resolve(root);
    assert.ok(
      resolved.startsWith(`${absoluteRoot}${path.sep}`),
      `${resolved} escaped ${absoluteRoot}`,
    );
    assert.equal(path.normalize(resolved), resolved, "resolved path must already be normalized");
    assert.ok(!resolved.includes(`${path.sep}..${path.sep}`), "resolved path must contain no traversal segment");
  }
});

test("a sibling directory sharing the root prefix is not treated as inside the root", () => {
  // "/srv/genome/audit-other" starts with "/srv/genome/audit" as a raw string but is
  // a different directory; the separator-terminated check is what rejects it.
  const resolved = resolveUnderRoot("/srv/genome/audit", "canary-1");
  assert.ok(!resolved.startsWith("/srv/genome/audit-other"));
  assert.ok(resolved.startsWith(`/srv/genome/audit${path.sep}`));
});

test("resolveDirectoryUnderRoot returns a child directory without an extension", () => {
  assert.equal(resolveDirectoryUnderRoot("/srv/genome/results", "canary-1"), "/srv/genome/results/canary-1");
  assert.throws(() => resolveDirectoryUnderRoot("/srv/genome/results", "../escape"));
});

test("resolveDirectoryUnderRoot rejects the same traversal encodings", () => {
  for (const value of ["..", "../escape", "a/b", "a\\b", "/absolute", "", ".", "\0"]) {
    assert.throws(
      () => resolveDirectoryUnderRoot("/srv/genome/results", value),
      Error,
      `accepted: ${JSON.stringify(value)}`,
    );
  }
});

test("sanitizeToolArguments keeps allowlisted identifiers and redacts everything else", () => {
  assert.deepEqual(
    sanitizeToolArguments({ requestId: "canary-20260814", token: "secret", path: "/private/dna.fastq.gz" }),
    { requestId: "canary-20260814", token: "[REDACTED]", path: "[REDACTED]" },
  );
});

test("sanitizeError removes bearer tokens and absolute paths", () => {
  const value = sanitizeError(new Error("Authorization: Bearer abcdef /srv/genome/data/sample.bam"));
  assert.equal(value.includes("abcdef"), false);
  assert.equal(value.includes("sample.bam"), false);
  assert.match(value, /\[REDACTED_TOKEN\]/);
  assert.match(value, /\[REDACTED_PATH\]/);
});

test("sanitizeError redacts credentials embedded in a URL before the path rules run", () => {
  const value = sanitizeError(new Error("clone failed: https://octocat:hunter2@example.test/org/private.git"));
  assert.equal(value.includes("hunter2"), false, "the password must not survive as part of a redacted path");
  assert.equal(value.includes("octocat"), false);
  assert.match(value, /\[REDACTED_CREDENTIALS\]/);
});

test("sanitizeError redacts Windows and UNC paths, not only POSIX ones", () => {
  for (const [message, leaked] of [
    ["ENOENT: C:\\Users\\genoma\\secrets\\sample.bam", "sample.bam"],
    ["cannot reach \\\\fileserver\\genome\\private.vcf", "private.vcf"],
  ] as const) {
    const value = sanitizeError(new Error(message));
    assert.equal(value.includes(leaked), false, `leaked ${leaked} from ${message}`);
    assert.match(value, /\[REDACTED_PATH\]/);
  }
});

test("sanitizeError redacts the token families the repository can plausibly emit", () => {
  const secrets = [
    "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
    "github_pat_0123456789abcdefghij",
    "sk_live_0123456789abcdefghij",
    "glpat_0123456789abcdefghij",
    "xoxb_0123456789abcdefghij",
    "AKIAIOSFODNN7EXAMPLE",
    "ASIAIOSFODNN7EXAMPLE",
    "AIzaSyA0123456789abcdefghijklmnop",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk",
  ];
  for (const secret of secrets) {
    const value = sanitizeError(new Error(`upstream rejected credential ${secret} for this request`));
    assert.equal(value.includes(secret), false, `leaked ${secret}`);
    assert.match(value, /\[REDACTED_TOKEN\]/);
  }
});

test("resolveUnderRoot contains an identifier even when the root is the filesystem root", () => {
  // A "startsWith(`${root}${sep}`)" containment test rejects this legitimate
  // child, because "/canary-1.json" never carries the doubled separator.
  assert.equal(resolveUnderRoot("/", "canary-1"), path.resolve("/", "canary-1.json"));
});

test("resolveUnderRoot honours a caller-supplied extension without widening containment", () => {
  assert.equal(resolveUnderRoot("/srv/genome/audit", "canary-1", ".lock"), "/srv/genome/audit/canary-1.lock");
  assert.throws(() => resolveUnderRoot("/srv/genome/audit", "../escape", ".lock"));
});

test("an exclusive claim admits one holder and is reusable only after release", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codework-claim-"));
  const first = await acquireAuditClaim(root, "canary-1");
  assert.ok(first, "the first caller must win the claim");
  assert.equal(await acquireAuditClaim(root, "canary-1"), undefined, "a second caller must not also win it");

  const held = await describeAuditClaim(root, "canary-1");
  assert.ok(held, "a held claim must be describable for operator diagnostics");
  assert.ok(held.ageMs >= 0);

  await releaseAuditClaim(first);
  assert.equal(await describeAuditClaim(root, "canary-1"), undefined);
  const second = await acquireAuditClaim(root, "canary-1");
  assert.ok(second, "the claim must be acquirable again once released");
  await releaseAuditClaim(second);
});

test("releasing a claim never removes a claim owned by someone else", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codework-claim-owner-"));
  const holder = await acquireAuditClaim(root, "canary-1");
  assert.ok(holder);
  await releaseAuditClaim({ ...holder, token: "not-the-owning-token" });
  assert.ok(await describeAuditClaim(root, "canary-1"), "a foreign release must leave the claim standing");
  await releaseAuditClaim(holder);
});

test("audit records are written once with restrictive permissions", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "codework-audit-"));
  const record = {
    requestId: "canary-1",
    tool: "run_synthetic_canary",
    arguments: { requestId: "canary-1" },
    status: "PASS" as const,
    startedAt: "2026-08-14T00:00:00.000Z",
    durationMs: 10,
    result: { status: "PASS" },
  };
  await writeAuditRecord(root, record);
  await writeAuditRecord(root, record);
  assert.deepEqual(await readAuditRecord(root, "canary-1"), record);
  const mode = (await stat(path.join(root, "canary-1.json"))).mode & 0o777;
  assert.equal(mode, 0o600);
  assert.doesNotMatch(await readFile(path.join(root, "canary-1.json"), "utf8"), /token/i);
});
