import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdtemp, stat, writeFile } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createGenomeMcpServer, runAudited, runFixedScript } from "../src/server.js";

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

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test(
  "a timed-out script takes its whole process group down with it",
  { skip: process.platform === "win32" ? "POSIX process groups only" : false },
  async () => {
    // The script backgrounds a descendant and then blocks. Signalling only the direct
    // child leaves that descendant running, and it writes the marker a second later.
    // Killing the process group must stop it before the marker can ever appear.
    const dir = await mkdtemp(path.join(os.tmpdir(), "codework-timeout-"));
    const script = path.join(dir, "spawner.sh");
    const marker = path.join(dir, "descendant.marker");
    await writeFile(
      script,
      ["#!/bin/sh", '( sleep 1; : > "$1" ) &', "sleep 30", ""].join("\n"),
      { mode: 0o755 },
    );

    const started = Date.now();
    await assert.rejects(runFixedScript(script, [marker], process.env, 300), /timed out after 300ms/);
    assert.ok(Date.now() - started < 10_000, "the timeout must not wait for the script to finish");

    await sleep(2_500);
    await assert.rejects(stat(marker), /ENOENT/, "a descendant outlived the terminated process group");
  },
);

test("runFixedScript returns trimmed stdout and surfaces a non-zero exit", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-exit-"));
  const ok = path.join(dir, "ok.sh");
  const bad = path.join(dir, "bad.sh");
  await writeFile(ok, ["#!/bin/sh", "echo '  hello  '", ""].join("\n"), { mode: 0o755 });
  await writeFile(bad, ["#!/bin/sh", "echo boom >&2", "exit 7", ""].join("\n"), { mode: 0o755 });

  assert.equal(await runFixedScript(ok, [], process.env, 10_000), "hello");
  await assert.rejects(runFixedScript(bad, [], process.env, 10_000), /exited with code 7/);
});
