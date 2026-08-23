import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, stat } from "node:fs/promises";
import test from "node:test";
import { setTimeout } from "node:timers/promises";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { acquireAuditClaim, readAuditRecord, releaseAuditClaim } from "../src/core.js";
import { createGenomeMcpServer, runAudited } from "../src/server.js";

test("MCP initialization lists only approved tools with annotations", async () => {
  const server = createGenomeMcpServer({
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot: "/audit",
  });
  const client = new Client({ name: "contract-test", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const listed = await client.listTools();
  assert.deepEqual(
    listed.tools.map((tool) => tool.name).sort(),
    ["audit_record", "reference_status", "run_synthetic_canary", "runtime_status"],
  );
  const canary = listed.tools.find((tool) => tool.name === "run_synthetic_canary");
  assert.equal(canary?.annotations?.readOnlyHint, false);
  assert.equal(canary?.annotations?.destructiveHint, false);
  await client.close();
  await server.close();
});

test("runAudited replays a successful request id without re-executing", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-audit-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  let executions = 0;
  const operation = async () => {
    executions += 1;
    return { status: "PASS" };
  };
  const first = await runAudited(options, "runtime_status", { requestId: "replay-1" }, operation);
  const second = await runAudited(options, "runtime_status", { requestId: "replay-1" }, operation);
  assert.deepEqual(first, { status: "PASS" });
  assert.deepEqual(second, first);
  assert.equal(executions, 1);
});

test("concurrent requests sharing a request id execute the operation exactly once", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-race-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  let executions = 0;
  const operation = async () => {
    executions += 1;
    // Hold the claim long enough that a caller which only consulted the record
    // before starting would observe "missing" and execute a second time.
    await setTimeout(50);
    return { status: "PASS", executions };
  };

  const outcomes = await Promise.all([
    runAudited(options, "runtime_status", { requestId: "race-1" }, operation),
    runAudited(options, "runtime_status", { requestId: "race-1" }, operation),
    runAudited(options, "runtime_status", { requestId: "race-1" }, operation),
  ]);

  assert.equal(executions, 1, "the operation must run exactly once for one request id");
  for (const outcome of outcomes) {
    assert.deepEqual(outcome, { status: "PASS", executions: 1 });
  }
  assert.equal((await readAuditRecord(auditRoot, "race-1")).status, "PASS");
});

test("a concurrent failure is recorded once and reported to every caller", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-race-fail-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  let executions = 0;
  const operation = async () => {
    executions += 1;
    await setTimeout(50);
    throw new Error("Bearer private-token /srv/genome/data/sample.bam");
  };

  const settled = await Promise.allSettled([
    runAudited(options, "runtime_status", { requestId: "race-fail-1" }, operation),
    runAudited(options, "runtime_status", { requestId: "race-fail-1" }, operation),
  ]);

  assert.equal(executions, 1, "a failing operation must not be retried by the concurrent caller");
  for (const outcome of settled) {
    assert.equal(outcome.status, "rejected");
    assert.match((outcome as PromiseRejectedResult).reason.message, /\[REDACTED_TOKEN\].*\[REDACTED_PATH\]/);
  }
});

test("the claim is released so a settled request id stays replayable", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-claim-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  await runAudited(options, "runtime_status", { requestId: "claim-1" }, async () => ({ status: "PASS" }));
  await assert.rejects(stat(path.join(auditRoot, "claim-1.lock")), /ENOENT/);
  assert.deepEqual(
    await runAudited(options, "runtime_status", { requestId: "claim-1" }, async () => ({ status: "unreachable" })),
    { status: "PASS" },
  );
});

test("a caller that loses the claim never executes the operation itself", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-inprogress-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
    claimWaitBudgetMs: 200,
  };
  const claim = await acquireAuditClaim(auditRoot, "stuck-1");
  assert.ok(claim, "the test must hold the claim it is simulating");

  let executions = 0;
  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "stuck-1" }, async () => {
      executions += 1;
      return { status: "PASS" };
    }),
    /in progress/,
  );
  assert.equal(executions, 0, "the operation must not run while another execution holds the claim");
  await releaseAuditClaim(claim);
});

test("runAudited stores and replays a sanitized failure", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-fail-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const operation = async () => {
    throw new Error("Bearer private-token /srv/genome/data/sample.bam");
  };
  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "fail-1" }, operation),
    /\[REDACTED_TOKEN\].*\[REDACTED_PATH\]/,
  );
  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "fail-1" }, async () => ({ status: "wrong" })),
    /\[REDACTED_TOKEN\].*\[REDACTED_PATH\]/,
  );
});
