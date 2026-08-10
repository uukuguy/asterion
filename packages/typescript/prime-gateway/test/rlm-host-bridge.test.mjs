import assert from "node:assert/strict";
import { createConnection } from "node:net";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { RlmHostBridge, authenticateRlmHostFrame, listenRlmHostBridge } from "../dist/src/index.js";

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
    waitForTerminal: async () => new Promise(() => undefined),
  });

  const result = await Promise.race([
    bridge.proposeSpawn({ childId: "child-1", requestId: "request-1" }),
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
    waitForTerminal: async () => undefined,
  });
  const proposal = { childId: "child-1", requestId: "request-1" };
  assert.deepEqual(await bridge.proposeSpawn(proposal), await bridge.proposeSpawn(proposal));
  assert.equal(proposed, 1);
  await assert.rejects(
    () => bridge.proposeSpawn({ childId: "child-2", requestId: "request-1" }),
    /conflicts/,
  );
});

test("serves an authenticated RLM spawn over its private socket", async () => {
  const root = await mkdtemp(join(tmpdir(), "asterion-rlm-"));
  const path = join(root, "r.sock");
  const bridge = new RlmHostBridge({ sessionId: "session-1", admitSpawn: async (p) => ({ resolution: "admitted", childId: p.childId }), waitForTerminal: async () => undefined });
  const listener = await listenRlmHostBridge(path, "session-1", "11".repeat(32), bridge);
  try {
    const response = await new Promise((resolve, reject) => {
      const socket = createConnection(path);
      let body = "";
      socket.on("connect", () => socket.write(`${JSON.stringify({ protocol: "asterion.prime-rlm-host/v1", type: "authenticate", token: "11".repeat(32), session_id: "session-1" })}\n${JSON.stringify({ type: "rlm.spawn.propose", request_id: "r1", child_id: "c1" })}\n`));
      socket.on("data", (chunk) => { body += chunk; }); socket.on("end", () => resolve(JSON.parse(body))); socket.on("error", reject);
    });
    assert.deepEqual(response, { resolution: "admitted", childId: "c1" });
  } finally { await listener.close(); await rm(root, { recursive: true, force: true }); }
});
