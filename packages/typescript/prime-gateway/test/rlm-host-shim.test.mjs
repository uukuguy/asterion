import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { createRlmHostClient, wrapSubagentRuntimeHost } from "../resources/rlm-host-shim.mjs";
import { RlmHostBridge, listenRlmHostBridge } from "../dist/src/index.js";

test("admits a native RLM child before creating it exactly once", async () => {
  const order = [];
  const runtime = Object.freeze({ session: Object.freeze({}) });
  const nativeHost = {
    async createRlmSubagentRuntime(options) {
      order.push(`native:${options.id}`);
      return runtime;
    },
    async deleteRlmSubagentRuntime() {},
  };
  const client = {
    async proposeSpawn(proposal) {
      order.push(`propose:${proposal.child_id}`);
      return { resolution: "admitted", child_id: proposal.child_id };
    },
  };

  const wrapped = wrapSubagentRuntimeHost(nativeHost, client);
  assert.equal(await wrapped.createRlmSubagentRuntime({ id: "child-1", prompt: "private", rlmDepth: 1 }), runtime);
  assert.deepEqual(order, ["propose:child-1", "native:child-1"]);
});

test("rejects an RLM child before its native host has an effect", async () => {
  let nativeCalls = 0;
  const wrapped = wrapSubagentRuntimeHost({
    async createRlmSubagentRuntime() {
      nativeCalls += 1;
      return {};
    },
    async deleteRlmSubagentRuntime() {},
  }, {
    async proposeSpawn(proposal) {
      return { resolution: "rejected", child_id: proposal.child_id };
    },
  });

  await assert.rejects(
    () => wrapped.createRlmSubagentRuntime({ id: "child-1", prompt: "private", rlmDepth: 1 }),
    /not admitted/,
  );
  assert.equal(nativeCalls, 0);
});

test("reads one exact private discovery record and authenticates its spawn", async () => {
  const root = await mkdtemp(join(tmpdir(), "asterion-rlm-shim-"));
  const socketPath = join(root, "r.sock");
  const token = "22".repeat(32);
  const listener = await listenRlmHostBridge(socketPath, "session-1", token, new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (proposal) => ({ resolution: "admitted", childId: proposal.childId }),
  }));
  try {
    const discoveryPath = join(root, "asterion-rlm-host.json");
    await writeFile(discoveryPath, JSON.stringify({
      protocol: "asterion.prime-rlm-host-discovery/v1",
      socket_path: socketPath,
      token,
      session_id: "session-1",
    }));
    const client = await createRlmHostClient(discoveryPath);
    assert.deepEqual(await client.proposeSpawn({
      child_id: "child-1",
      goal_text: "private",
      rlm_depth: 1,
      idempotency_key: "spawn-1",
      budget: { controller_tokens: 0, application_tokens: 0, child_tokens: 1, aggregate_tokens: 1, cost_micros: 0, deadline_ms: 1 },
    }), { resolution: "admitted", child_id: "child-1" });
  } finally {
    await listener.close();
    await rm(root, { recursive: true, force: true });
  }
});
