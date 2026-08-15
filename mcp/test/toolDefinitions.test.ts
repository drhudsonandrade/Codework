import assert from "node:assert/strict";
import test from "node:test";
import { TOOL_DEFINITIONS } from "../src/toolDefinitions.js";

test("private MCP exposes only the four approved tools", () => {
  assert.deepEqual(Object.keys(TOOL_DEFINITIONS).sort(), [
    "audit_record",
    "reference_status",
    "run_synthetic_canary",
    "runtime_status",
  ]);
});

test("status and audit tools are read-only while canary is non-destructive", () => {
  assert.equal(TOOL_DEFINITIONS.runtime_status.annotations.readOnlyHint, true);
  assert.equal(TOOL_DEFINITIONS.reference_status.annotations.readOnlyHint, true);
  assert.equal(TOOL_DEFINITIONS.audit_record.annotations.readOnlyHint, true);
  assert.equal(TOOL_DEFINITIONS.run_synthetic_canary.annotations.readOnlyHint, false);
  assert.equal(TOOL_DEFINITIONS.run_synthetic_canary.annotations.destructiveHint, false);
  assert.equal(TOOL_DEFINITIONS.run_synthetic_canary.annotations.openWorldHint, false);
});

test("no approved tool accepts an arbitrary command or path field", () => {
  const serialized = JSON.stringify(TOOL_DEFINITIONS);
  assert.equal(serialized.includes('"command"'), false);
  assert.equal(serialized.includes('"path"'), false);
});
