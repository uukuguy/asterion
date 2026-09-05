import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

import { PrimeP1DevelopmentSession } from "../dist/src/index.js";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

async function eventStreamFactory() {
  return import(pathToFileURL(join(
    primeSourceRoot,
    "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
  )).href);
}

function usage() {
  return {
    input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

test("runs one real SDK prompt tool loop through injected callbacks without leaking private values", async () => {
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1-sdk-"));
  const { createAssistantMessageEventStream } = await eventStreamFactory();
  const seen = { model: 0, tool: 0 };
  const session = await PrimeP1DevelopmentSession.open({
    primeSourceRoot,
    workspace,
    model: (_model, context) => {
      seen.model += 1;
      assert.deepEqual(context.tools.map((tool) => tool.name), ["ipython"]);
      assert.ok(context.messages.some((message) => message.role === "user"));
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const toolTurn = seen.model === 1;
        const message = {
          role: "assistant",
          api: "anthropic-messages", provider: "asterion-development", model: "p1-test",
          content: toolTurn
            ? [{ type: "toolCall", id: "call-ipython-1", name: "ipython", arguments: { code: "SENTINEL_TOOL_INPUT" } }]
            : [{ type: "text", text: "SENTINEL_MODEL_COMPLETION" }],
          usage: usage(), stopReason: toolTurn ? "toolUse" : "stop", timestamp: Date.now(),
        };
        stream.push({ type: "start", partial: { ...message, content: [] } });
        stream.push({ type: "done", reason: toolTurn ? "toolUse" : "stop", message });
      });
      return stream;
    },
    ipython: async (toolCallId, input) => {
      seen.tool += 1;
      assert.equal(toolCallId, "call-ipython-1");
      assert.deepEqual(input, { code: "SENTINEL_TOOL_INPUT" });
      return { content: [{ type: "text", text: "SENTINEL_TOOL_OUTPUT" }], details: {}, isError: false };
    },
  });
  try {
    const result = await session.prompt("SENTINEL_PROMPT");
    assert.equal(seen.model, 2);
    assert.equal(seen.tool, 1);
    assert.deepEqual(result, {
      lifecycle: "completed",
      usage: { input_tokens: 6, output_tokens: 4, total_tokens: 10 },
      assistant: { completed: true, stop_reason: "stop" },
    });
    assert.doesNotMatch(JSON.stringify(result), /SENTINEL_(PROMPT|MODEL_COMPLETION|TOOL_INPUT|TOOL_OUTPUT)/);
  } finally {
    await session.close();
  }
});

test("locks new dispatch after cancellation", async () => {
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1-sdk-"));
  const session = await PrimeP1DevelopmentSession.open({
    primeSourceRoot,
    workspace,
    model: () => { throw new Error("must not dispatch after cancellation"); },
    ipython: async () => ({ content: [], details: {}, isError: false }),
  });
  try {
    await session.cancel();
    await assert.rejects(() => session.prompt("SENTINEL_PROMPT_AFTER_CANCEL"), /cancelled/);
  } finally {
    await session.close();
  }
});
