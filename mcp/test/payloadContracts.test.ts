import assert from "node:assert/strict";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createGenomeMcpServer } from "../src/server.js";

type InputContract = {
  properties: string[];
  required: string[];
};

async function listToolInputContracts(): Promise<Record<string, InputContract>> {
  const server = createGenomeMcpServer({
    projectRoot: "/opt/codework",
    referenceRoot: "/refs",
    resultsRoot: "/results",
    auditRoot: "/audit",
  });
  const client = new Client({ name: "payload-contract-test", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  const listed = await client.listTools();
  await client.close();
  await server.close();
  return Object.fromEntries(
    listed.tools.map((tool) => [
      tool.name,
      {
        properties: Object.keys(tool.inputSchema.properties ?? {}).sort(),
        required: [...(tool.inputSchema.required ?? [])].sort(),
      },
    ]),
  );
}

test("MCP input schemas preserve the requestId compatibility contract", async () => {
  assert.deepEqual(await listToolInputContracts(), {
    audit_record: { properties: ["requestId"], required: ["requestId"] },
    reference_status: { properties: ["requestId"], required: [] },
    run_synthetic_canary: { properties: ["requestId"], required: ["requestId"] },
    runtime_status: { properties: ["requestId"], required: [] },
  });
});
