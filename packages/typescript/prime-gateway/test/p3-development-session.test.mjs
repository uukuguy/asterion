import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

async function streamFactory() {
  return import(pathToFileURL(join(primeSourceRoot,
    "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js")).href);
}

const usage = () => ({ input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } });

test("runs SDK-owned depth-one children and retains the review session for follow-up", async () => {
  const { PrimeP3DevelopmentSession } = await import("../dist/src/index.js");
  const { createAssistantMessageEventStream } = await streamFactory();
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p3-sdk-"));
  const calls = { root: 0, implementation: 0, review: 0, tools: 0 };
  let session;
  const makeMessage = (role, tool) => ({ role: "assistant", api: "anthropic-messages", provider: "test", model: role,
    content: tool ? [{ type: "toolCall", id: `${role}-${calls[role]}`, name: "ipython", arguments: { code: "fixed" } }] : [{ type: "text", text: "done" }],
    usage: usage(), stopReason: tool ? "toolUse" : "stop", timestamp: Date.now() });
  session = await PrimeP3DevelopmentSession.open({
    primeSourceRoot, workspace,
    model: (role) => {
      calls[role] += 1;
      const stream = createAssistantMessageEventStream();
      const message = makeMessage(role, calls[role] === 1 || (role === "review" && calls[role] === 3));
      queueMicrotask(() => { stream.push({ type: "start", partial: { ...message, content: [] } }); stream.push({ type: "done", reason: message.stopReason, message }); });
      return stream;
    },
    ipython: async (role) => {
      calls.tools += 1;
      if (role === "root") {
        const implementation = await session.spawn("implementation", "implement");
        const review = await session.spawn("review", "review");
        await session.wait(implementation.rlm_child_id);
        await session.wait(review.rlm_child_id);
        await session.followUp(review.rlm_child_id, "verify");
        await session.delete(implementation.rlm_child_id);
        await session.delete(review.rlm_child_id);
        assert.deepEqual((await session.list()).subagents, []);
      }
      return { content: [], details: {}, isError: false };
    },
  });
  try {
    const result = await session.prompt("fixed");
    assert.equal(calls.root + calls.implementation + calls.review, 8);
    assert.equal(calls.tools, 4);
    assert.deepEqual(result.observations, { child_count: 2, max_depth: 1, model_callback_count: 8,
      remaining_child_count: 0, retained_follow_up_count: 1, tool_call_count: 4 });
  } finally { await session.close(); }
});
