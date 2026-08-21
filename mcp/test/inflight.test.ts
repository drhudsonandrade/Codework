/**
 * A request id must be claimed before the operation runs, not after it finishes.
 *
 * The idempotency check read the audit record first and wrote it last, so two concurrent
 * calls carrying the same requestId both found nothing and both executed. Only the second
 * *write* collided, by which point the side effects had happened twice: the write was
 * atomic and the execution was not.
 */
import assert from "node:assert/strict";
import { mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { claimAuditRecord, settleAuditRecord, type AuditRecord } from "../src/core.js";

async function root(): Promise<string> {
  return await mkdtemp(path.join(tmpdir(), "genoma-audit-"));
}

function reservation(requestId: string, tool = "canary"): AuditRecord {
  return {
    requestId,
    tool,
    arguments: { requestId },
    status: "RUNNING",
    startedAt: new Date().toISOString(),
    durationMs: 0,
  };
}

test("the first caller takes the claim and the second is told it is held", async () => {
  const dir = await root();
  assert.equal(await claimAuditRecord(dir, reservation("req-1")), undefined);
  const held = await claimAuditRecord(dir, reservation("req-1"));
  assert.ok(held);
  assert.equal(held.status, "RUNNING");
});

test("concurrent claims elect exactly one winner", async () => {
  const dir = await root();
  const results = await Promise.all(
    Array.from({ length: 12 }, () => claimAuditRecord(dir, reservation("req-race"))),
  );
  assert.equal(results.filter((r) => r === undefined).length, 1);
  assert.equal(results.filter((r) => r !== undefined).length, 11);
});

test("only one of many concurrent operations actually runs", async () => {
  const dir = await root();
  let executions = 0;
  const run = async () => {
    const held = await claimAuditRecord(dir, reservation("req-once"));
    if (held !== undefined) {
      return "refused";
    }
    // The window the old order left open: read-then-execute-then-write.
    await new Promise((resolve) => setTimeout(resolve, 5));
    executions += 1;
    await settleAuditRecord(dir, {
      ...reservation("req-once"),
      status: "PASS",
      durationMs: 5,
      result: { ok: true },
    });
    return "ran";
  };
  const outcomes = await Promise.all([run(), run(), run(), run(), run()]);
  assert.equal(executions, 1, "the operation executed more than once for one request id");
  assert.equal(outcomes.filter((o) => o === "ran").length, 1);
});

test("settling the claim replaces it with the outcome", async () => {
  const dir = await root();
  await claimAuditRecord(dir, reservation("req-settle"));
  await settleAuditRecord(dir, {
    ...reservation("req-settle"),
    status: "PASS",
    durationMs: 3,
    result: { value: 42 },
  });
  const written = JSON.parse(
    await readFile(path.join(dir, "req-settle.json"), "utf8"),
  ) as AuditRecord;
  assert.equal(written.status, "PASS");
  assert.deepEqual(written.result, { value: 42 });
});

test("a settled claim is replayed rather than re-run", async () => {
  const dir = await root();
  await claimAuditRecord(dir, reservation("req-replay"));
  await settleAuditRecord(dir, {
    ...reservation("req-replay"),
    status: "PASS",
    durationMs: 1,
    result: { value: "cached" },
  });
  const held = await claimAuditRecord(dir, reservation("req-replay"));
  assert.ok(held);
  assert.equal(held.status, "PASS");
  assert.deepEqual(held.result, { value: "cached" });
});
