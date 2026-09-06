import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

test("keeps one P5 SDK session for two bounded repair prompts", async () => {
  const { PrimeP5DevelopmentSession } = await import("../dist/src/index.js");
  const { createAssistantMessageEventStream } = await import(pathToFileURL(join(
    primeSourceRoot,
    "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
  )).href);
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p5-sdk-"));
  let models = 0, tools = 0;
  const session = await PrimeP5DevelopmentSession.open({
    primeSourceRoot, workspace,
    model: () => {
      models += 1;
      const stream = createAssistantMessageEventStream();
      const tool = models === 1 || models === 3;
      const message = {
        role: "assistant", api: "anthropic-messages", provider: "test", model: "test",
        content: tool ? [{ type: "toolCall", id: `call-${models}`, name: "ipython", arguments: { code: "fixed" } }] : [{ type: "text", text: "done" }],
        usage: { input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
        stopReason: tool ? "toolUse" : "stop", timestamp: 0,
      };
      queueMicrotask(() => { stream.push({ type: "start", partial: { ...message, content: [] } }); stream.push({ type: "done", reason: message.stopReason, message }); });
      return stream;
    },
    ipython: async () => { tools += 1; return { content: [], details: {}, isError: false }; },
  });
  try {
    await session.prompt("prompt-1");
    const result = await session.prompt("prompt-2");
    assert.deepEqual({ models, tools }, { models: 4, tools: 2 });
    assert.deepEqual(result.observations, { active_tool_names: ["ipython"], compact_count: 0, model_callback_count: 4, rlm_child_count: 0, tool_call_count: 2 });
  } finally { await session.close(); }
});
