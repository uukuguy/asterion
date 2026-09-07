import assert from "node:assert/strict";
import { once } from "node:events";
import { createConnection, createServer } from "node:net";
import test from "node:test";

const PROTOCOL = "asterion.prime-p7-solving-gateway/v1";
const identity = { run_id: "run-1", session_id: "session-1", runtime_id: "prime.agent", generation: 1 };
function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function framed(value) {
  const body = Buffer.from(canonical(value)); const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length); return Buffer.concat([header, body]);
}
async function readFrame(socket, state) {
  while (state.buffer.length < 4) state.buffer = Buffer.concat([state.buffer, await once(socket, "data").then(([x]) => x)]);
  const size = state.buffer.readUInt32BE();
  while (state.buffer.length < size + 4) state.buffer = Buffer.concat([state.buffer, await once(socket, "data").then(([x]) => x)]);
  const body = state.buffer.subarray(4, size + 4); state.buffer = state.buffer.subarray(size + 4);
  return JSON.parse(body.toString("utf8"));
}

test("bridge preserves two sibling IPython calls in source order and stops after their solved turn", async () => {
  const { P7SolvingBridge } = await import("../dist/src/p7-solving-bridge.js");
  const server = createServer(); server.listen(0, "127.0.0.1"); await once(server, "listening");
  const connected = once(server, "connection");
  const client = createConnection({ port: server.address().port, host: "127.0.0.1" });
  await once(client, "connect"); const [socket] = await connected;
  const run = new P7SolvingBridge(socket).run();
  const state = { buffer: Buffer.alloc(0), input: 0 };
  const send = (kind, request_id, payload) => client.write(framed({ protocol: PROTOCOL, ...identity, sequence: ++state.input, request_id, kind, payload }));
  send("open", "open-1", { prime_source_root: `${process.cwd()}/../../../3th-party/prime-agent`, workspace: process.cwd() });
  assert.equal((await readFrame(client, state)).kind, "ready");
  send("prompt", "prompt-1", { prompt: "solve" });
  const model = await readFrame(client, state); assert.equal(model.kind, "model.request");
  const message = {
    role: "assistant", api: "anthropic-messages", provider: "test", model: "test",
    content: [
      { type: "text", text: "first" },
      { type: "toolCall", id: "original-a", name: "ipython", arguments: { code: "a()" } },
      { type: "text", text: "between" },
      { type: "toolCall", id: "original-b", name: "ipython", arguments: { code: "b()" } },
    ],
    usage: { input: 7, output: 5, cacheRead: 0, cacheWrite: 0, totalTokens: 12,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: "toolUse", timestamp: 0,
  };
  send("model.response", model.request_id, { message });
  const first = await readFrame(client, state);
  assert.deepEqual(first.payload, { tool_call_id: "original-a", code: "a()" });
  send("tool.response", first.request_id, { result: { content: [{ type: "text", text: "a-result" }], details: { broker_terminal: "ACTIVE" }, isError: false } });
  const second = await readFrame(client, state);
  assert.deepEqual(second.payload, { tool_call_id: "original-b", code: "b()" });
  send("tool.response", second.request_id, { result: { content: [{ type: "text", text: "b-result" }], details: { broker_terminal: "LEVEL_SOLVED" }, isError: false } });
  const done = await readFrame(client, state);
  assert.equal(done.kind, "command.result");
  assert.deepEqual(done.payload.result.observations, {
    active_tool_names: ["ipython"], compact_count: 0,
    normal_model_callback_count: 1, summary_model_callback_count: 0,
    rlm_child_count: 0, tool_call_count: 2, solved_latched: true,
  });
  send("close", "close-1", {}); assert.equal((await readFrame(client, state)).kind, "command.result");
  await run; client.destroy(); server.close();
});
