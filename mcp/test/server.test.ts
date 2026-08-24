import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdir, mkdtemp, rm, stat, unlink, writeFile, readFile } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import {
  createGenomeMcpServer,
  releaseRequestClaim,
  runAudited,
  runFixedScript,
  withClaimMutationLock,
} from "../src/server.js";

const CLAIM_ID_A = "00000000-0000-4000-8000-000000000001";
const CLAIM_ID_B = "00000000-0000-4000-8000-000000000002";
const DEAD_OWNER_PID = 2_147_483_647;

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

test("runAudited atomically prevents concurrent duplicate execution", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-race-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  let executions = 0;
  let markStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    markStarted = resolve;
  });
  let releaseOperation!: () => void;
  const blocked = new Promise<void>((resolve) => {
    releaseOperation = resolve;
  });
  const operation = async () => {
    executions += 1;
    markStarted();
    await blocked;
    return { status: "PASS" };
  };

  const first = runAudited(options, "runtime_status", { requestId: "race-1" }, operation);
  await started;
  try {
    await assert.rejects(
      runAudited(options, "runtime_status", { requestId: "race-1" }, operation),
      /already in progress/,
    );
  } finally {
    releaseOperation();
  }
  assert.deepEqual(await first, { status: "PASS" });
  assert.equal(executions, 1, "same requestId must not execute the operation twice");
});

test("runAudited recovers a stale request claim only after its owner is gone", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-stale-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "stale-1.json.claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "stale-1",
      tool: "runtime_status",
      claimedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      claimId: CLAIM_ID_A,
      ownerPid: DEAD_OWNER_PID,
    })}\n`,
    { mode: 0o600 },
  );

  const result = await runAudited(
    options,
    "runtime_status",
    { requestId: "stale-1" },
    async () => ({ status: "PASS" }),
  );

  assert.deepEqual(result, { status: "PASS" });
  await assert.rejects(stat(claimPath), /ENOENT/);
});

test("elapsed time alone never recovers a claim whose owner is still alive", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-live-stale-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "live-stale.json.claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "live-stale",
      tool: "runtime_status",
      claimedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      claimId: CLAIM_ID_A,
      ownerPid: process.pid,
    })}\n`,
    { mode: 0o600 },
  );
  let executions = 0;

  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "live-stale" }, async () => {
      executions += 1;
      return { status: "PASS" };
    }),
    /already in progress/,
  );

  assert.equal(executions, 0, "an active owner must not be fenced out by elapsed time");
  assert.equal((await stat(claimPath)).isFile(), true);
});

test("two concurrent stale-claim recoverers allow only one operation to proceed", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-stale-race-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "stale-race.json.claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "stale-race",
      tool: "runtime_status",
      claimedAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
      claimId: CLAIM_ID_A,
      ownerPid: DEAD_OWNER_PID,
    })}\n`,
    { mode: 0o600 },
  );

  let executions = 0;
  let markStarted!: () => void;
  const started = new Promise<void>((resolve) => {
    markStarted = resolve;
  });
  let releaseOperation!: () => void;
  const blocked = new Promise<void>((resolve) => {
    releaseOperation = resolve;
  });
  const operation = async () => {
    executions += 1;
    markStarted();
    await blocked;
    return { status: "PASS" };
  };
  const observe = <T>(promise: Promise<T>) =>
    promise.then(
      (value) => ({ kind: "fulfilled" as const, value }),
      (error: unknown) => ({ kind: "rejected" as const, error }),
    );

  // Attach rejection handlers at creation time so a legitimate loser cannot be
  // reported by node:test as an unhandled rejection before the winner starts.
  const first = observe(runAudited(options, "runtime_status", { requestId: "stale-race" }, operation));
  const second = observe(runAudited(options, "runtime_status", { requestId: "stale-race" }, operation));
  await started;

  const loser = await Promise.race([first, second]);
  assert.equal(loser.kind, "rejected");
  if (loser.kind === "rejected") {
    assert.ok(loser.error instanceof Error);
    assert.match(loser.error.message, /already in progress/);
  }

  releaseOperation();
  const outcomes = await Promise.all([first, second]);
  assert.equal(outcomes.filter((item) => item.kind === "fulfilled").length, 1);
  assert.equal(outcomes.filter((item) => item.kind === "rejected").length, 1);
  assert.equal(executions, 1, "stale-claim recovery must not execute twice");
});

test("runAudited recovers an orphaned interprocess mutation lock", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-lock-orphan-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "lock-orphan.json.claim");
  const lockPath = `${claimPath}.lock`;
  await mkdir(lockPath, { mode: 0o700 });
  await writeFile(
    path.join(lockPath, `owner-${CLAIM_ID_A}.json`),
    `${JSON.stringify({
      lockId: CLAIM_ID_A,
      ownerPid: DEAD_OWNER_PID,
      lockedAt: new Date(Date.now() - 60_000).toISOString(),
      state: "HELD",
    })}\n`,
    { mode: 0o600 },
  );

  const result = await runAudited(
    options,
    "runtime_status",
    { requestId: "lock-orphan" },
    async () => ({ status: "PASS" }),
  );

  assert.deepEqual(result, { status: "PASS" });
  await assert.rejects(stat(lockPath), /ENOENT/);
});

test("mutation-lock cleanup failure cannot replace the operation result and remains recoverable", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-cleanup-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  const unexpected = path.join(lockPath, "unexpected");
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };
  try {
    const first = await withClaimMutationLock(claimPath, async () => {
      await writeFile(unexpected, "blocks rmdir\n", "utf8");
      return "FIRST";
    });
    assert.equal(first, "FIRST");
    assert.equal(warnings.length, 1, "cleanup failure must be logged without replacing the result");

    await unlink(unexpected);
    const second = await withClaimMutationLock(claimPath, async () => "SECOND");
    assert.equal(second, "SECOND", "release-pending lock must be recoverable on the next acquisition");
  } finally {
    console.warn = originalWarn;
    await rm(lockPath, { recursive: true, force: true });
  }
});

test("runAudited rejects malformed request claim metadata without executing", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-invalid-claim-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "invalid-claim.json.claim");
  await writeFile(claimPath, "null\n", { mode: 0o600 });
  let executions = 0;

  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "invalid-claim" }, async () => {
      executions += 1;
      return { status: "PASS" };
    }),
    /already in progress/,
  );

  assert.equal(executions, 0, "invalid claims must block acquisition fail-closed");
  assert.equal((await stat(claimPath)).isFile(), true, "invalid claim evidence must not be deleted");
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

test("releaseRequestClaim still unlinks when handle close fails", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-release-close-"));
  const claimPath = path.join(dir, "claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "release-close",
      tool: "runtime_status",
      claimedAt: new Date().toISOString(),
      claimId: CLAIM_ID_A,
      ownerPid: process.pid,
    })}\n`,
  );
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };
  try {
    await releaseRequestClaim({
      claimPath,
      claimId: CLAIM_ID_A,
      handle: {
        close: async () => {
          throw Object.assign(new Error("close failed"), { code: "EIO" });
        },
      } as never,
    });
  } finally {
    console.warn = originalWarn;
  }
  await assert.rejects(stat(claimPath), /ENOENT/);
  assert.equal(warnings.length, 1);
});

test("releaseRequestClaim never removes a replacement claim", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-release-owner-"));
  const claimPath = path.join(dir, "claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "release-owner",
      tool: "runtime_status",
      claimedAt: new Date().toISOString(),
      claimId: CLAIM_ID_B,
      ownerPid: process.pid,
    })}\n`,
  );
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };
  try {
    await releaseRequestClaim({
      claimPath,
      claimId: CLAIM_ID_A,
      handle: { close: async () => undefined } as never,
    });
  } finally {
    console.warn = originalWarn;
  }
  const persisted = JSON.parse(await readFile(claimPath, "utf8")) as { claimId: string };
  assert.equal(persisted.claimId, CLAIM_ID_B);
  assert.equal(warnings.length, 1);
});

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

test("runFixedScript rejects a script that exceeds the output budget", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-budget-"));
  const loud = path.join(dir, "loud.sh");
  await writeFile(
    loud,
    [
      "#!/bin/sh",
      "i=0",
      "while [ $i -lt 6144 ]; do",
      "  printf '%1024d' 0",
      "  i=$((i+1))",
      "done",
      "",
    ].join("\n"),
    { mode: 0o755 },
  );
  await assert.rejects(runFixedScript(loud, [], process.env, 30_000), /output budget/);
});

test(
  "a timed-out script takes its whole process group down with it",
  { skip: process.platform === "win32" ? "POSIX process groups only" : false },
  async () => {
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

test("runFixedScript returns stdout and sanitizes retained stderr on failure", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-exit-"));
  const ok = path.join(dir, "ok.sh");
  const bad = path.join(dir, "bad.sh");
  await writeFile(ok, ["#!/bin/sh", "echo '  hello  '", ""].join("\n"), { mode: 0o755 });
  await writeFile(
    bad,
    ["#!/bin/sh", "echo 'Bearer private-token /srv/genome/data/sample.bam' >&2", "exit 7", ""].join("\n"),
    { mode: 0o755 },
  );

  assert.equal(await runFixedScript(ok, [], process.env, 10_000), "hello");
  await assert.rejects(
    runFixedScript(bad, [], process.env, 10_000),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /exited with code 7:.*\[REDACTED_TOKEN\].*\[REDACTED_PATH\]/);
      assert.doesNotMatch(error.message, /private-token/);
      assert.doesNotMatch(error.message, /\/srv\/genome\/data\/sample\.bam/);
      return true;
    },
  );
});
