import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { inspect } from "node:util";
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
  await writeFile(join(workspace, "AGENTS.md"), "SENTINEL_ANCESTOR_RESOURCE");
  const { createAssistantMessageEventStream } = await eventStreamFactory();
  const seen = { model: 0, tool: 0 };
  const session = await PrimeP1DevelopmentSession.open({
    primeSourceRoot,
    workspace,
    model: (_model, context) => {
      seen.model += 1;
      assert.deepEqual(context.tools.map((tool) => tool.name), ["ipython"]);
      assert.ok(context.messages.some((message) => message.role === "user"));
      assert.doesNotMatch(String(context.systemPrompt), /SENTINEL_ANCESTOR_RESOURCE/);
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
    assert.doesNotMatch(inspect(session), /SENTINEL_/);
    assert.doesNotMatch(JSON.stringify(session), /SENTINEL_/);
  } finally {
    await session.close();
  }
});

test("locks new dispatch after cancellation", async () => {
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1-sdk-"));
  const { createAssistantMessageEventStream } = await eventStreamFactory();
  let calls = 0;
  let started;
  const startedPromise = new Promise((resolve) => { started = resolve; });
  const session = await PrimeP1DevelopmentSession.open({
    primeSourceRoot,
    workspace,
    model: () => {
      calls += 1;
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        stream.push({ type: "start", partial: { role: "assistant", api: "ignored", provider: "cancel", model: "cancel", content: [], usage: usage(), stopReason: "aborted", timestamp: Date.now() } });
        started();
      });
      return stream;
    },
    ipython: async () => ({ content: [], details: {}, isError: false }),
  });
  try {
    const pending = session.prompt("SENTINEL_PROMPT_IN_FLIGHT");
    await startedPromise;
    await session.cancel();
    const cancelled = await pending;
    assert.equal(cancelled.lifecycle, "cancelled");
    assert.equal(cancelled.assistant.stop_reason, "aborted");
    await assert.rejects(() => session.prompt("SENTINEL_PROMPT_AFTER_CANCEL"), /cancelled/);
    assert.equal(calls, 1);
  } finally {
    await session.close();
  }
});

test("isolates registered SDK providers between simultaneous sessions", async () => {
  const { createAssistantMessageEventStream } = await eventStreamFactory();
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1-sdk-"));
  const calls = { a: 0, b: 0 };
  const model = (name) => () => {
    calls[name] += 1;
    const stream = createAssistantMessageEventStream();
    queueMicrotask(() => {
      const message = { role: "assistant", api: "ignored", provider: name, model: name, content: [{ type: "text", text: name }], usage: usage(), stopReason: "stop", timestamp: Date.now() };
      stream.push({ type: "start", partial: { ...message, content: [] } });
      stream.push({ type: "done", reason: "stop", message });
    });
    return stream;
  };
  const a = await PrimeP1DevelopmentSession.open({ primeSourceRoot, workspace, model: model("a"), ipython: async () => ({ content: [], details: {}, isError: false }) });
  const b = await PrimeP1DevelopmentSession.open({ primeSourceRoot, workspace, model: model("b"), ipython: async () => ({ content: [], details: {}, isError: false }) });
  try {
    await a.prompt("a"); await b.prompt("b"); await b.close(); await a.prompt("a again");
    assert.deepEqual(calls, { a: 2, b: 1 });
  } finally { await a.close(); await b.close(); }
});
