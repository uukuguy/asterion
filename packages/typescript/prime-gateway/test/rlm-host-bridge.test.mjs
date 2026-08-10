import assert from "node:assert/strict";
import test from "node:test";

import { RlmHostBridge } from "../dist/src/index.js";

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
