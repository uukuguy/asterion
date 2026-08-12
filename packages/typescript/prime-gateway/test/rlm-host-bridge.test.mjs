import assert from "node:assert/strict";
import { createConnection } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { RLM_HOST_PROTOCOL, RlmHostBridge, authenticateRlmHostFrame, listenRlmHostBridge } from "../dist/src/index.js";

const proposal = (overrides = {}) => ({
  requestId: "request-1",
  childId: "child-1",
  idempotencyKey: "spawn-1",
  goalText: "private goal",
  rlmDepth: 1,
  modelSelectorDigest: "a".repeat(64),
  budget: {
    controller_tokens: 0,
    application_tokens: 0,
    child_tokens: 1,
    aggregate_tokens: 1,
    cost_micros: 0,
    deadline_ms: 1,
  },
  ...overrides,
});

test("accepts only the exact authenticated RLM host frame", () => {
  assert.equal(authenticateRlmHostFrame(Buffer.from(JSON.stringify({
    protocol: "asterion.prime-rlm-host/v1", type: "authenticate", token: "11".repeat(32), session_id: "session-1",
  })), "session-1", "11".repeat(32)), true);
  assert.equal(authenticateRlmHostFrame(Buffer.from("SENTINEL_PRIVATE"), "session-1", "11".repeat(32)), false);
});

test("returns an admitted RLM spawn before its terminal lifecycle event", async () => {
  let proposed = 0;
  const bridge = new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (proposal) => {
      proposed += 1;
      return { resolution: "admitted", childId: proposal.childId };
    },
  });

  const result = await Promise.race([
    bridge.proposeSpawn(proposal()),
    new Promise((_, reject) => setTimeout(() => reject(new Error("waited terminal")), 100)),
  ]);

  assert.deepEqual(result, { resolution: "admitted", childId: "child-1" });
  assert.equal(proposed, 1);
});

test("replays one RLM request identity and rejects a conflicting child", async () => {
  let proposed = 0;
  const bridge = new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (proposal) => {
      proposed += 1;
      return { resolution: "admitted", childId: proposal.childId };
    },
  });
  const request = proposal();
  assert.deepEqual(await bridge.proposeSpawn(request), await bridge.proposeSpawn(request));
  assert.equal(proposed, 1);
  await assert.rejects(
    () => bridge.proposeSpawn(proposal({ childId: "child-2" })),
    /conflicts/,
  );
});

test("rejects an RLM spawn with an incomplete private effect payload", async () => {
  let proposed = 0;
  const bridge = new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (request) => {
      proposed += 1;
      return { resolution: "admitted", childId: request.childId };
    },
  });
  await assert.rejects(
    () => bridge.proposeSpawn(proposal({ budget: { ...proposal().budget, deadline_ms: 0 } })),
    /invalid/,
  );
  assert.equal(proposed, 0);
});

test("serves an authenticated RLM spawn over its private socket", async () => {
  const root = await mkdtemp(join(tmpdir(), "asterion-rlm-"));
  const path = join(root, "r.sock");
  const bridge = new RlmHostBridge({ sessionId: "session-1", admitSpawn: async (p) => ({ resolution: "admitted", childId: p.childId }) });
  const listener = await listenRlmHostBridge(path, "session-1", "11".repeat(32), bridge);
  try {
    const response = await new Promise((resolve, reject) => {
      const socket = createConnection(path);
      let body = "";
      socket.on("connect", () => socket.write(`${JSON.stringify({ protocol: "asterion.prime-rlm-host/v1", type: "authenticate", token: "11".repeat(32), session_id: "session-1" })}\n${JSON.stringify({ type: "rlm.spawn.propose", request_id: "r1", child_id: "c1", idempotency_key: "spawn-1", goal_text: "private goal", rlm_depth: 1, model_selector_digest: "a".repeat(64), budget: proposal().budget })}\n`));
      socket.on("data", (chunk) => { body += chunk; }); socket.on("end", () => resolve(JSON.parse(body))); socket.on("error", reject);
    });
    assert.deepEqual(response, { resolution: "admitted", childId: "c1" });
  } finally { await listener.close(); await rm(root, { recursive: true, force: true }); }
});

test("serves one authenticated closed child terminal lifecycle frame", async () => {
  const root = await mkdtemp(join(tmpdir(), "asterion-rlm-lifecycle-"));
  const path = join(root, "r.sock");
  const observed = [];
  const listener = await listenRlmHostBridge(path, "session-1", "33".repeat(32), new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (proposal) => ({ resolution: "admitted", childId: proposal.childId }),
    recordLifecycle: async (event) => { observed.push(event); },
  }));
  try {
    const response = await new Promise((resolve, reject) => {
      const socket = createConnection(path);
      let body = "";
      socket.setEncoding("utf8");
      socket.once("connect", () => socket.write(`${JSON.stringify({ protocol: RLM_HOST_PROTOCOL, type: "authenticate", session_id: "session-1", token: "33".repeat(32) })}\n${JSON.stringify({ type: "rlm.child.terminal", child_id: "child-1", status: "completed" })}\n`));
      socket.on("data", (chunk) => { body += chunk; });
      socket.once("error", reject);
      socket.once("end", () => resolve(JSON.parse(body)));
    });
    assert.deepEqual(response, { resolution: "recorded", childId: "child-1" });
    assert.deepEqual(observed, [{ type: "rlm.child.terminal", childId: "child-1", status: "completed" }]);
  } finally {
    await listener.close();
    await rm(root, { recursive: true, force: true });
  }
});

test("records one closed native child lifecycle after admission", async () => {
  const lifecycle = [];
  const bridge = new RlmHostBridge({
    sessionId: "session-1",
    admitSpawn: async (proposal) => ({ resolution: "admitted", childId: proposal.childId }),
    recordLifecycle: async (event) => { lifecycle.push(event); },
  });

  await bridge.recordLifecycle({ type: "rlm.child.started", childId: "child-1", nativeIdentityDigest: "a".repeat(64) });
  await bridge.recordLifecycle({ type: "rlm.child.terminal", childId: "child-1", status: "completed" });

  assert.deepEqual(lifecycle, [
    { type: "rlm.child.started", childId: "child-1", nativeIdentityDigest: "a".repeat(64) },
    { type: "rlm.child.terminal", childId: "child-1", status: "completed" },
  ]);
  await assert.rejects(
    () => bridge.recordLifecycle({ type: "rlm.child.terminal", childId: "child-1", status: "private-path" }),
    /invalid/u,
  );
});
