import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
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

test("runAudited fails closed instead of concurrently executing the same request id", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-race-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  let executions = 0;
  let signalStarted!: () => void;
  let releaseFirst!: () => void;
  const started = new Promise<void>((resolve) => { signalStarted = resolve; });
  const release = new Promise<void>((resolve) => { releaseFirst = resolve; });
  const operation = async () => {
    executions += 1;
    signalStarted();
    await release;
    return { status: "PASS" };
  };

  const first = runAudited(options, "runtime_status", { requestId: "race-1" }, operation);
  await started;
  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "race-1" }, operation),
    /already in progress/,
  );
  assert.equal(executions, 1);
  releaseFirst();
  assert.deepEqual(await first, { status: "PASS" });
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
