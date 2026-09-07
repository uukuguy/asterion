import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

function usage(input = 3, output = 2) {
  return { input, output, cacheRead: 0, cacheWrite: 0, totalTokens: input + output,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
}

test("one solving prompt alternates model and persistent IPython turns until the private solved latch", async () => {
  const { PrimeP7SolvingSession } = await import("../dist/src/p7-solving-session.js");
  const { createAssistantMessageEventStream } = await import(pathToFileURL(join(
    primeSourceRoot, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
  )).href);
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p7-solving-"));
  const seen = { models: [], tools: [] };
  let modelCalls = 0;
  const session = await PrimeP7SolvingSession.open({
    primeSourceRoot, workspace,
    model: (model, context, options) => {
      modelCalls += 1;
      seen.models.push({ model, context, options });
      const stream = createAssistantMessageEventStream();
      const call = `call-${modelCalls}`;
      const message = {
        role: "assistant", api: "anthropic-messages", provider: "test", model: "test",
        content: [{ type: "toolCall", id: call, name: "ipython", arguments: { code: `step_${modelCalls}()` } }],
        usage: usage(modelCalls + 1, modelCalls), stopReason: "toolUse", timestamp: 0,
      };
      queueMicrotask(() => {
        stream.push({ type: "start", partial: { ...message, content: [] } });
        stream.push({ type: "done", reason: "toolUse", message });
      });
      return stream;
    },
    ipython: async (id, input) => {
      seen.tools.push([id, input.code]);
      return {
        content: [{ type: "text", text: id === "call-1" ? "still active" : "level transitioned" }],
        details: { broker_terminal: id === "call-2" ? "LEVEL_SOLVED" : "ACTIVE" },
        isError: false,
      };
    },
  });
  try {
    const result = await session.prompt("solve the first public level");
    assert.deepEqual(seen.tools, [["call-1", "step_1()"], ["call-2", "step_2()"]]);
    assert.equal(seen.models.length, 2);
    assert.equal(seen.models[0].model.contextWindow, 131072);
    assert.deepEqual(result.observations, {
      active_tool_names: ["ipython"], compact_count: 0,
      normal_model_callback_count: 2, summary_model_callback_count: 0,
      rlm_child_count: 0, tool_call_count: 2, solved_latched: true,
    });
    assert.deepEqual(result.usage, { input_tokens: 5, output_tokens: 3, total_tokens: 8 });
    const context = JSON.stringify(seen.models[0].context);
    const systemPrompt = seen.models[0].context.systemPrompt;
    assert.equal(typeof systemPrompt, "string");
    assert.match(systemPrompt, /visual.*interactive.*reasoning/i);
    assert.match(systemPrompt, /world model.*player.*objects.*controls.*hypotheses.*rejected.*plan.*last_frame/is);
    assert.match(systemPrompt, /only.*ipython.*p7_client/is);
    assert.match(systemPrompt, /before batching actions.*first\s+1.{0,12}2\s+steps?/is);
    assert.match(systemPrompt, /do not repeat.*no-op|no-op.*do not repeat/i);
    assert.match(systemPrompt, /death path/i);
    assert.doesNotMatch(systemPrompt, /LS20|\b13\s*steps?\b|\bcoordinates?\b/i);
    assert.match(context, /outputs and state persist/i);
    assert.doesNotMatch(context, /fixed (?:file|path|action)|staged artifact/i);
    await assert.rejects(() => session.prompt("second prompt"), /one prompt|completed/);
  } finally {
    await session.close();
  }
});
