import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

test("keeps one P7 SDK session for three bounded staged prompts", async () => {
  const { PrimeP7DevelopmentSession } = await import("../dist/src/index.js");
  const { createAssistantMessageEventStream } = await import(pathToFileURL(join(
    primeSourceRoot,
    "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
  )).href);
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p7-sdk-"));
  let models = 0, tools = 0;
  const contexts = [];
  const session = await PrimeP7DevelopmentSession.open({
    primeSourceRoot, workspace,
    model: (_model, context) => {
      models += 1;
      contexts.push(JSON.stringify(context));
      const stream = createAssistantMessageEventStream();
      const tool = models === 1 || models === 3 || models === 5;
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
    await session.prompt("prompt-2");
    const result = await session.prompt("prompt-3");
    assert.deepEqual({ models, tools }, { models: 6, tools: 3 });
    assert.ok(contexts.some((context) => context.includes(
      "complete the required P7 staged artifact creation",
    )));
    assert.deepEqual(result.observations, { active_tool_names: ["ipython"], compact_count: 0, model_callback_count: 6, rlm_child_count: 0, tool_call_count: 3 });
  } finally { await session.close(); }
});
