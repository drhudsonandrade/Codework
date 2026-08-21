import assert from "node:assert/strict";
import test from "node:test";
import { assertBindIsSafe, isLoopbackHost } from "../src/server.js";

// The /mcp route has no auth middleware, which is safe only while the bind stays on
// loopback — and the bind is an environment variable. MCP_BIND_HOST=0.0.0.0 turned a
// private tool into an open one with no warning and no error.

test("loopback hosts are recognised", () => {
  for (const host of ["127.0.0.1", "127.0.0.53", "::1", "localhost", "LOCALHOST"]) {
    assert.equal(isLoopbackHost(host), true, host);
  }
});

test("routable hosts are not loopback", () => {
  for (const host of ["0.0.0.0", "192.168.1.10", "10.0.0.1", "example.com"]) {
    assert.equal(isLoopbackHost(host), false, host);
  }
});

test("a loopback bind needs no token", () => {
  assert.doesNotThrow(() => assertBindIsSafe("127.0.0.1", undefined));
});

test("a routable bind without a token is refused", () => {
  assert.throws(() => assertBindIsSafe("0.0.0.0", undefined), /MCP_AUTH_TOKEN/);
});

test("a short token does not count as configured authentication", () => {
  assert.throws(() => assertBindIsSafe("0.0.0.0", "short"), /at least 16/);
});

test("a routable bind with a real token starts", () => {
  assert.doesNotThrow(() => assertBindIsSafe("0.0.0.0", "0123456789abcdef0123"));
});
