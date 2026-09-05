import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";

import { PrimeP1BDevelopmentSession } from "../dist/src/index.js";

const primeSourceRoot = join(process.cwd(), "../../../3th-party/prime-agent");

async function eventStreamFactory() {
  return import(pathToFileURL(join(
    primeSourceRoot,
    "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
  )).href);
}

function usage() {
  return { input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } };
}

test("runs the pinned SDK prompt-compact-prompt topology and projects only a safe compaction witness", async () => {
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1b-sdk-"));
  const { createAssistantMessageEventStream } = await eventStreamFactory();
  const seen = { model: 0, tool: 0, compactTools: undefined };
  const session = await PrimeP1BDevelopmentSession.open({
    primeSourceRoot,
    workspace,
    model: (_model, context) => {
      seen.model += 1;
      const stream = createAssistantMessageEventStream();
      queueMicrotask(() => {
        const toolTurn = seen.model === 1 || seen.model === 4;
        if (seen.model === 3) seen.compactTools = Array.isArray(context.tools) ? context.tools.map((tool) => tool.name) : [];
        const message = {
          role: "assistant", api: "anthropic-messages", provider: "p1b", model: "p1b",
          content: toolTurn
            ? [{ type: "toolCall", id: `call-${seen.model}`, name: "ipython", arguments: { code: "SENTINEL_TOOL" } }]
            : [{ type: "text", text: seen.model === 3 ? "SENTINEL_COMPACTION_SUMMARY" : "SENTINEL_COMPLETION" }],
          usage: usage(), stopReason: toolTurn ? "toolUse" : "stop", timestamp: Date.now(),
        };
        stream.push({ type: "start", partial: { ...message, content: [] } });
        stream.push({ type: "done", reason: message.stopReason, message });
      });
      return stream;
    },
    ipython: async () => {
      seen.tool += 1;
      return { content: [{ type: "text", text: "SENTINEL_TOOL_RESULT" }], details: {}, isError: false };
    },
  });
  try {
    await session.prompt("SENTINEL_PROMPT_1");
    const compacted = await session.compact();
    await session.prompt("SENTINEL_PROMPT_2");
    assert.deepEqual(seen, { model: 5, tool: 2, compactTools: [] });
    assert.equal(compacted.compact_called, true);
    assert.equal(compacted.succeeded, true);
    assert.equal(compacted.start_count, 1);
    assert.equal(compacted.end_count, 1);
    assert.ok(compacted.message_count_before > 0);
    assert.ok(compacted.message_count_after > 0);
    assert.equal(typeof compacted.tokens_before, "number");
    assert.match(compacted.first_kept_entry_id_sha256, /^[a-f0-9]{64}$/);
    assert.doesNotMatch(JSON.stringify(compacted), /SENTINEL/);
    await assert.rejects(() => session.compact(), /prompt2|completed/);
    await assert.rejects(() => session.prompt("SENTINEL_THIRD_PROMPT"), /prompt2|completed/);
  } finally {
    await session.close();
  }
});
