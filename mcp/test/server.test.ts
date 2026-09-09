import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import { mkdir, mkdtemp, readdir, readFile, rm, stat, unlink, writeFile } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import {
  createGenomeMcpServer,
  recoverClaimMutationLock,
  releaseRequestClaim,
  renewRequestClaimLease,
  runAudited,
  runFixedScript,
  withClaimMutationLock,
} from "../src/server.js";

const CLAIM_ID_A = "00000000-0000-4000-8000-000000000001";
const CLAIM_ID_B = "00000000-0000-4000-8000-000000000002";
const pastIso = (ms = 60_000) => new Date(Date.now() - ms).toISOString();
const futureIso = (ms = 60_000) => new Date(Date.now() + ms).toISOString();
const observe = <T>(promise: Promise<T>) =>
  promise.then(
    (value) => ({ kind: "fulfilled" as const, value }),
    (error: unknown) => ({ kind: "rejected" as const, error }),
  );

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

  type InputSchema = { properties?: Record<string, unknown>; required?: string[] };
  const schemas = Object.fromEntries(
    listed.tools.map((tool) => [tool.name, tool.inputSchema as InputSchema]),
  ) as Record<string, InputSchema>;
  for (const name of ["runtime_status", "reference_status", "run_synthetic_canary", "audit_record"]) {
    assert.deepEqual(Object.keys(schemas[name]?.properties ?? {}).sort(), ["requestId"]);
  }
  assert.deepEqual(schemas.runtime_status?.required ?? [], []);
  assert.deepEqual(schemas.reference_status?.required ?? [], []);
  assert.deepEqual(schemas.run_synthetic_canary?.required, ["requestId"]);
  assert.deepEqual(schemas.audit_record?.required, ["requestId"]);
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

test("runAudited recovers an expired request lease without PID liveness", async () => {
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
      claimedAt: pastIso(2 * 60 * 60 * 1000),
      leaseExpiresAt: pastIso(),
      claimId: CLAIM_ID_A,
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

test("an unexpired request lease blocks recovery even when claimedAt is old", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-live-lease-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const claimPath = path.join(auditRoot, "live-lease.json.claim");
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "live-lease",
      tool: "runtime_status",
      claimedAt: pastIso(2 * 60 * 60 * 1000),
      leaseExpiresAt: futureIso(10 * 60 * 1000),
      claimId: CLAIM_ID_A,
    })}\n`,
    { mode: 0o600 },
  );
  let executions = 0;

  await assert.rejects(
    runAudited(options, "runtime_status", { requestId: "live-lease" }, async () => {
      executions += 1;
      return { status: "PASS" };
    }),
    /already in progress/,
  );

  assert.equal(executions, 0, "a live lease must preserve the active owner");
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
      claimedAt: pastIso(2 * 60 * 60 * 1000),
      leaseExpiresAt: pastIso(),
      claimId: CLAIM_ID_A,
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

test("stale recovery fences an older owner before audit persistence", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-fence-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const requestId = "fence-1";
  const claimPath = path.join(auditRoot, `${requestId}.json.claim`);
  let markFirstStarted!: () => void;
  const firstStarted = new Promise<void>((resolve) => {
    markFirstStarted = resolve;
  });
  let releaseFirst!: () => void;
  const firstBlocked = new Promise<void>((resolve) => {
    releaseFirst = resolve;
  });

  const first = observe(
    runAudited(options, "runtime_status", { requestId }, async () => {
      markFirstStarted();
      await firstBlocked;
      return { owner: "first" };
    }),
  );
  await firstStarted;

  const stale = JSON.parse(await readFile(claimPath, "utf8")) as Record<string, unknown>;
  stale.leaseExpiresAt = pastIso();
  await writeFile(claimPath, `${JSON.stringify(stale)}\n`, { mode: 0o600 });

  const second = await runAudited(options, "runtime_status", { requestId }, async () => ({ owner: "second" }));
  assert.deepEqual(second, { owner: "second" });

  releaseFirst();
  const firstOutcome = await first;
  assert.equal(firstOutcome.kind, "rejected");
  if (firstOutcome.kind === "rejected") {
    assert.ok(firstOutcome.error instanceof Error);
    assert.match(firstOutcome.error.message, /ownership was lost/);
  }

  const audit = JSON.parse(await readFile(path.join(auditRoot, `${requestId}.json`), "utf8")) as {
    result: unknown;
  };
  assert.deepEqual(audit.result, { owner: "second" });
});

test("a lease that lapses during a long operation still persists the owner's PASS", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-lease-boundary-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const requestId = "lease-boundary";
  const claimPath = path.join(auditRoot, `${requestId}.json.claim`);

  const result = await runAudited(options, "run_synthetic_canary", { requestId }, async () => {
    // A canary that uses its whole budget can reach persistence with the lease already
    // spent; nothing else has claimed the request id, so the result must survive.
    const claim = JSON.parse(await readFile(claimPath, "utf8")) as Record<string, unknown>;
    claim.leaseExpiresAt = pastIso();
    await writeFile(claimPath, `${JSON.stringify(claim)}\n`, { mode: 0o600 });
    return { status: "PASS" };
  });

  assert.deepEqual(result, { status: "PASS" });
  const audit = JSON.parse(await readFile(path.join(auditRoot, `${requestId}.json`), "utf8")) as {
    status: string;
    result: unknown;
  };
  assert.equal(audit.status, "PASS");
  assert.deepEqual(audit.result, { status: "PASS" });
});

test("renewRequestClaimLease extends a held claim and refuses a superseded one", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-claim-renew-"));
  const claimPath = path.join(dir, "claim");
  const claimedAt = pastIso(30 * 60 * 1000);
  await writeFile(
    claimPath,
    `${JSON.stringify({
      requestId: "renew-1",
      tool: "run_synthetic_canary",
      claimedAt,
      leaseExpiresAt: pastIso(),
      claimId: CLAIM_ID_A,
    })}\n`,
    { mode: 0o600 },
  );
  const claim = { claimPath, claimId: CLAIM_ID_A, handle: {} as never };

  assert.equal(await renewRequestClaimLease(claim, "renew-1", "run_synthetic_canary"), true);
  const renewed = JSON.parse(await readFile(claimPath, "utf8")) as Record<string, string>;
  assert.equal(renewed.claimId, CLAIM_ID_A);
  assert.equal(renewed.claimedAt, claimedAt, "renewal must not rewrite the original claim identity");
  assert.ok(Date.parse(renewed.leaseExpiresAt) > Date.now(), "renewal must move the lease ahead of now");
  assert.deepEqual(await readdir(dir), ["claim"], "renewal must not leak staging files");

  assert.equal(
    await renewRequestClaimLease(claim, "renew-1", "runtime_status"),
    false,
    "a claim held for another tool must not be renewed",
  );

  await writeFile(claimPath, `${JSON.stringify({ ...renewed, claimId: CLAIM_ID_B })}\n`, { mode: 0o600 });
  assert.equal(
    await renewRequestClaimLease(claim, "renew-1", "run_synthetic_canary"),
    false,
    "a replaced claim belongs to its new owner",
  );
});

test("audit persistence failure cannot replace the operation error", async () => {
  const auditRoot = await mkdtemp(path.join(os.tmpdir(), "codework-server-persist-fail-"));
  const options = {
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot,
  };
  const requestId = "persist-fail";
  const claimPath = path.join(auditRoot, `${requestId}.json.claim`);
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };

  try {
    await assert.rejects(
      runAudited(options, "runtime_status", { requestId }, async () => {
        await unlink(claimPath);
        throw new Error("PRIMARY_OPERATION_FAILURE");
      }),
      /PRIMARY_OPERATION_FAILURE/,
    );
  } finally {
    console.warn = originalWarn;
  }

  assert.equal(warnings.length, 1, "the fenced persistence attempt must be logged");
  assert.match(String(warnings[0]?.[0]), /audit persistence failed/);
  await assert.rejects(stat(path.join(auditRoot, `${requestId}.json`)), /ENOENT/);
});

test("runAudited recovers an expired interprocess mutation-lock lease", async () => {
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
    path.join(lockPath, "owner.json"),
    `${JSON.stringify({
      lockId: CLAIM_ID_A,
      lockedAt: pastIso(10 * 60 * 1000),
      leaseExpiresAt: pastIso(),
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

test("an unexpired mutation-lock lease is never recovered", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-live-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  await mkdir(lockPath, { mode: 0o700 });
  await writeFile(
    path.join(lockPath, "owner.json"),
    `${JSON.stringify({
      lockId: CLAIM_ID_A,
      lockedAt: new Date().toISOString(),
      leaseExpiresAt: futureIso(),
    })}\n`,
    { mode: 0o600 },
  );
  let executions = 0;

  await assert.rejects(
    withClaimMutationLock(claimPath, async () => {
      executions += 1;
      return "unexpected";
    }),
    /already in progress/,
  );
  assert.equal(executions, 0);
  assert.equal((await stat(lockPath)).isDirectory(), true);
});

test("invalid owner.json blocks mutation-lock recovery fail-closed", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-invalid-owner-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  await mkdir(lockPath, { mode: 0o700 });
  await writeFile(path.join(lockPath, "owner.json"), "null\n", { mode: 0o600 });
  let executions = 0;

  await assert.rejects(
    withClaimMutationLock(claimPath, async () => {
      executions += 1;
      return "unexpected";
    }),
    /coordination lock is invalid/,
  );
  assert.equal(executions, 0);
});

test("an empty lock directory left by a half-finished release is absorbed", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-empty-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  await mkdir(lockPath, { mode: 0o700 });
  let executions = 0;

  const result = await withClaimMutationLock(claimPath, async () => {
    executions += 1;
    return "PASS";
  });

  assert.equal(result, "PASS");
  assert.equal(executions, 1, "a directory no owner ever claimed cannot block acquisition");
  await assert.rejects(stat(lockPath), /ENOENT/);
});

test("a concurrent observer never sees the lock path without its owner", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-atomic-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  const ACQUISITIONS = 40;

  // The observer runs on the same event loop as the acquisition, so it is scheduled in
  // exactly the gaps where a publish could expose an unfinished lock: any implementation
  // that creates the lock path and only then fills it has to await in between, and that
  // await is where this loop gets to look. Only the publish phase is judged — a release
  // unlinks the owner file before removing the directory, so an empty lock path after the
  // callback is the documented leftover that recovery absorbs, not an unfinished publish.
  const exposedLockEntries = async (): Promise<string[] | undefined> => {
    try {
      const entries = await readdir(lockPath);
      return entries.includes("owner.json") ? undefined : entries;
    } catch {
      // The lock path does not exist yet, which is the only other legal publish state.
      return undefined;
    }
  };

  const state = { publishing: false, running: true };
  const exposures: string[][] = [];
  const observer = (async () => {
    while (state.running) {
      const exposed = state.publishing ? await exposedLockEntries() : undefined;
      if (exposed) {
        exposures.push(exposed);
      }
      await new Promise((resolve) => setImmediate(resolve));
    }
  })();

  try {
    for (let attempt = 0; attempt < ACQUISITIONS; attempt += 1) {
      state.publishing = true;
      const held = await withClaimMutationLock(claimPath, async () => {
        state.publishing = false;
        assert.deepEqual(await readdir(lockPath), ["owner.json"]);
        return readdir(dir);
      });
      assert.deepEqual(held, ["claim.lock"], "the staging directory must not outlive the publish");
    }
  } finally {
    state.publishing = false;
    state.running = false;
    await observer;
  }

  assert.deepEqual(exposures, [], "the lock path was observable without its owner inside it");
  assert.deepEqual(await readdir(dir), [], "release must leave the claim directory clean");
});

test("a staging failure keeps its own errno instead of reading as lock contention", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-staging-"));
  const occupied = path.join(dir, "occupied");
  await writeFile(occupied, "not a directory\n", { mode: 0o600 });
  // Staging is created next to the claim, so a file where its parent should be fails the
  // mkdir with ENOTDIR — an errno the publish step would legitimately read as contention.
  const claimPath = path.join(occupied, "claim");
  let executions = 0;

  await assert.rejects(
    withClaimMutationLock(claimPath, async () => {
      executions += 1;
      return "unexpected";
    }),
    (error: unknown) => {
      assert.ok(error instanceof Error);
      assert.equal(
        (error as NodeJS.ErrnoException).code,
        "ENOTDIR",
        "a failure to stage the lock must surface as itself, not as a busy or invalid lock",
      );
      return true;
    },
  );
  assert.equal(executions, 0);
});

test("recovery clears an ownerless lock directory without touching a live one", async () => {
  // On POSIX the staged rename absorbs an empty lock directory before recovery is ever
  // consulted; on Windows that rename is refused, and acquisition falls back to exactly
  // this contract. Driving it directly keeps the win32 path covered on every platform.
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-recovery-"));
  const ownerless = path.join(dir, "ownerless.lock");
  await mkdir(ownerless, { mode: 0o700 });

  assert.equal(await recoverClaimMutationLock(ownerless), true);
  await assert.rejects(stat(ownerless), /ENOENT/, "an ownerless directory must not block acquisition");

  const live = path.join(dir, "live.lock");
  await mkdir(live, { mode: 0o700 });
  await writeFile(
    path.join(live, "owner.json"),
    `${JSON.stringify({ lockId: CLAIM_ID_A, lockedAt: new Date().toISOString(), leaseExpiresAt: futureIso() })}\n`,
    { mode: 0o600 },
  );
  await assert.rejects(recoverClaimMutationLock(live), /already in progress/);
  assert.deepEqual(await readdir(live), ["owner.json"], "a live owner must survive recovery");

  const unexpected = path.join(dir, "unexpected.lock");
  await mkdir(unexpected, { mode: 0o700 });
  await writeFile(path.join(unexpected, "stray.json"), "{}\n", { mode: 0o600 });
  await assert.rejects(recoverClaimMutationLock(unexpected), /coordination lock is invalid/);
  assert.deepEqual(await readdir(unexpected), ["stray.json"], "unexpected content must be preserved");
});

test(
  "win32 acquisition recovers an empty lock directory the rename cannot replace",
  { skip: process.platform === "win32" ? false : "win32-only rename semantics" },
  async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-win32-"));
    const claimPath = path.join(dir, "claim");
    const lockPath = `${claimPath}.lock`;
    await mkdir(lockPath, { mode: 0o700 });

    const result = await withClaimMutationLock(claimPath, async () => "PASS");

    assert.equal(result, "PASS", "EPERM from a refused directory rename must not wedge the request id");
    await assert.rejects(stat(lockPath), /ENOENT/);
  },
);

test("a lock directory with unexpected entries stays fail-closed", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-unexpected-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  await mkdir(lockPath, { mode: 0o700 });
  await writeFile(path.join(lockPath, "stray.json"), "{}\n", { mode: 0o600 });
  let executions = 0;

  await assert.rejects(
    withClaimMutationLock(claimPath, async () => {
      executions += 1;
      return "unexpected";
    }),
    /coordination lock is invalid/,
  );
  assert.equal(executions, 0);
  assert.equal((await stat(lockPath)).isDirectory(), true, "unexpected lock content must be preserved");
});

test("mutation-lock release never removes a replacement lockId", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-replacement-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  const ownerPath = path.join(lockPath, "owner.json");
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };
  try {
    const result = await withClaimMutationLock(claimPath, async () => {
      const current = JSON.parse(await readFile(ownerPath, "utf8")) as Record<string, unknown>;
      current.lockId = CLAIM_ID_B;
      await writeFile(ownerPath, `${JSON.stringify(current)}\n`, { mode: 0o600 });
      return "PASS";
    });
    assert.equal(result, "PASS");
    assert.equal((await stat(lockPath)).isDirectory(), true);
    assert.equal(warnings.length, 1);
  } finally {
    console.warn = originalWarn;
    await rm(lockPath, { recursive: true, force: true });
  }
});

test("mutation-lock cleanup failure cannot replace the primary operation error", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-lock-cleanup-"));
  const claimPath = path.join(dir, "claim");
  const lockPath = `${claimPath}.lock`;
  const ownerPath = path.join(lockPath, "owner.json");
  const warnings: unknown[][] = [];
  const originalWarn = console.warn;
  console.warn = (...args: unknown[]) => {
    warnings.push(args);
  };
  try {
    await assert.rejects(
      withClaimMutationLock(claimPath, async () => {
        await writeFile(ownerPath, "null\n", "utf8");
        throw new Error("PRIMARY_OPERATION_FAILURE");
      }),
      /PRIMARY_OPERATION_FAILURE/,
    );
    assert.equal(warnings.length, 1, "cleanup failure must be logged without replacing the operation error");
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
      leaseExpiresAt: futureIso(),
      claimId: CLAIM_ID_A,
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
      leaseExpiresAt: futureIso(),
      claimId: CLAIM_ID_B,
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

test("a script that has already exited is never signalled again", async () => {
  const dir = await mkdtemp(path.join(os.tmpdir(), "codework-reaped-"));
  const ok = path.join(dir, "ok.sh");
  await writeFile(ok, ["#!/bin/sh", "echo done", ""].join("\n"), { mode: 0o755 });

  const originalKill = process.kill.bind(process);
  const signalled: number[] = [];
  process.kill = ((pid: number, signal?: string | number) => {
    signalled.push(pid);
    return originalKill(pid, signal as NodeJS.Signals);
  }) as typeof process.kill;

  try {
    assert.equal(await runFixedScript(ok, [], process.env, 10_000), "done");
  } finally {
    process.kill = originalKill;
  }

  assert.deepEqual(signalled, [], "a reaped pid may already belong to an unrelated process group");
});

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
