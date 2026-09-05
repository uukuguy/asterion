import assert from "node:assert/strict";
import { createConnection, createServer } from "node:net";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inspect } from "node:util";
import test from "node:test";

const protocol = "asterion.prime-p1-development-gateway/v1";
const gatewayRoot = process.cwd();
const primeSourceRoot = join(gatewayRoot, "../../../3th-party/prime-agent");

function frame(value) {
  const body = Buffer.from(canonical(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length);
  return Buffer.concat([header, body]);
}

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function reader(socket) {
  let buffered = Buffer.alloc(0);
  const waiting = [];
  socket.on("data", (chunk) => {
    buffered = Buffer.concat([buffered, chunk]);
    while (buffered.length >= 4 && buffered.length >= 4 + buffered.readUInt32BE()) {
      const length = buffered.readUInt32BE();
      const value = JSON.parse(buffered.subarray(4, 4 + length));
      buffered = buffered.subarray(4 + length);
      waiting.shift()?.(value);
    }
  });
  return () => new Promise((resolve) => waiting.push(resolve));
}

function command(sequence, request_id, kind, payload = {}) {
  return { protocol, run_id: "run-1", session_id: "session-1", runtime_id: "prime.agent", generation: 1, sequence, request_id, kind, payload };
}

test("runs a real SDK prompt through the inherited duplex bridge without exposing private values in command results", async () => {
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  const connected = once(server, "connection");
  const client = await new Promise((resolve) => {
    const socket = createConnection({ port, host: "127.0.0.1" });
    socket.once("connect", () => resolve(socket));
  });
  const [socket] = await connected;
  const child = spawn(process.execPath, ["dist/src/p1-development-main.js", "3"], {
    cwd: gatewayRoot, env: {}, stdio: ["ignore", "ignore", "pipe", socket],
  });
  const stderr = [];
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const receive = reader(client);
  const next = () => Promise.race([receive(), new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error("bridge response timed out")), 5_000); timer.unref(); })]);
  const send = (value) => client.write(frame(value));
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1-bridge-"));
  try {
    send(command(1, "open-1", "open", { prime_source_root: primeSourceRoot, workspace }));
    const ready = await next();
    assert.equal(ready.kind, "ready");
    send(command(2, "prompt-1", "prompt", { prompt: "SENTINEL_PROMPT" }));
    const firstModel = await next();
    assert.equal(firstModel.kind, "model.request");
    assert.ok(firstModel.payload.context.messages.some((item) => item.role === "user"));
    send(command(3, firstModel.request_id, "model.response", { message: assistantToolMessage() }));
    const tool = await next();
    assert.equal(tool.kind, "tool.request");
    assert.deepEqual(tool.payload, { tool_call_id: "call-1", code: "SENTINEL_TOOL_INPUT" });
    send(command(4, tool.request_id, "tool.response", { result: { content: [{ type: "text", text: "SENTINEL_TOOL_OUTPUT" }], details: {}, isError: false } }));
    const secondModel = await next();
    assert.equal(secondModel.kind, "model.request");
    send(command(5, secondModel.request_id, "model.response", { message: assistantDoneMessage() }));
    const completed = await next();
    assert.equal(completed.kind, "command.result");
    assert.deepEqual(completed.payload.result.assistant, { completed: true, stop_reason: "stop" });
    assert.doesNotMatch(JSON.stringify(completed), /SENTINEL_(PROMPT|TOOL_INPUT|TOOL_OUTPUT|MODEL_COMPLETION)/);
    send(command(6, "close-1", "close"));
    const closed = await next();
    assert.deepEqual(closed.payload.result, { lifecycle: "closed" });
  } finally {
    client.destroy(); socket.destroy(); server.close(); child.kill();
  }
  assert.equal(Buffer.concat(stderr).toString(), "");
});

test("keeps bridge inspection free of transport and path sentinels", async () => {
  const { P1DevelopmentBridge } = await import("../dist/src/p1-development-bridge.js");
  const socket = createConnection({ port: 9, host: "127.0.0.1" });
  socket.on("error", () => {});
  const bridge = new P1DevelopmentBridge(socket);
  const rendered = `${inspect(bridge)}${JSON.stringify(bridge)}`;
  assert.doesNotMatch(rendered, /SENTINEL|buffer|path|socket/i);
  socket.destroy();
});


function assistantToolMessage() {
  return { role: "assistant", api: "anthropic-messages", provider: "asterion-development", model: "p1-test", content: [{ type: "toolCall", id: "call-1", name: "ipython", arguments: { code: "SENTINEL_TOOL_INPUT" } }], usage: usage(), stopReason: "toolUse", timestamp: Date.now() };
}

function assistantDoneMessage() {
  return { role: "assistant", api: "anthropic-messages", provider: "asterion-development", model: "p1-test", content: [{ type: "text", text: "SENTINEL_MODEL_COMPLETION" }], usage: usage(), stopReason: "stop", timestamp: Date.now() };
}

function usage() { return { input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }; }
