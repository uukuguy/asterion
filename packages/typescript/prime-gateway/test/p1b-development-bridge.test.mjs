import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp } from "node:fs/promises";
import { createConnection, createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const protocol = "asterion.prime-p1-b-development-gateway/v1";
const gatewayRoot = process.cwd();
const primeSourceRoot = join(gatewayRoot, "../../../3th-party/prime-agent");

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function frame(value) {
  const body = Buffer.from(canonical(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length);
  return Buffer.concat([header, body]);
}

function reader(socket) {
  let buffered = Buffer.alloc(0);
  const queued = [], waiting = [];
  socket.on("data", (chunk) => {
    buffered = Buffer.concat([buffered, chunk]);
    while (buffered.length >= 4 && buffered.length >= 4 + buffered.readUInt32BE()) {
      const length = buffered.readUInt32BE();
      const value = JSON.parse(buffered.subarray(4, 4 + length));
      buffered = buffered.subarray(4 + length);
      const resolve = waiting.shift();
      if (resolve) resolve(value); else queued.push(value);
    }
  });
  return () => queued.length ? Promise.resolve(queued.shift()) : new Promise((resolve) => waiting.push(resolve));
}

function command(sequence, request_id, kind, payload = {}) {
  return { protocol, run_id: "run-1", session_id: "session-1", runtime_id: "prime.agent", generation: 1, sequence, request_id, kind, payload };
}

function assistant(toolCall) {
  return {
    role: "assistant", api: "anthropic-messages", provider: "p1b-test", model: "p1b-test",
    content: toolCall ? [{ type: "toolCall", id: toolCall, name: "ipython", arguments: { code: "SENTINEL_TOOL" } }] : [{ type: "text", text: "SENTINEL_COMPLETION" }],
    usage: { input: 3, output: 2, cacheRead: 0, cacheWrite: 0, totalTokens: 5, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    stopReason: toolCall ? "toolUse" : "stop", timestamp: Date.now(),
  };
}

test("runs the real SDK P1B open-prompt-compact-prompt-close bridge flow", async () => {
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const connected = once(server, "connection");
  const client = await new Promise((resolve) => {
    const socket = createConnection({ port: server.address().port, host: "127.0.0.1" });
    socket.once("connect", () => resolve(socket));
  });
  const [socket] = await connected;
  const child = spawn(process.execPath, ["dist/src/p1b-development-main.js", "3"], {
    cwd: gatewayRoot, env: {}, stdio: ["ignore", "ignore", "pipe", socket],
  });
  const stderr = [];
  let modelCallbacks = 0;
  let toolCallbacks = 0;
  child.stderr.on("data", (chunk) => stderr.push(chunk));
  const receive = reader(client);
  const next = () => Promise.race([receive(), new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error("bridge response timed out")), 5_000);
    timer.unref();
  })]);
  const send = (value) => client.write(frame(value));
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1b-bridge-"));
  try {
    send(command(1, "open-1", "open", { prime_source_root: primeSourceRoot, workspace }));
    assert.equal((await next()).kind, "ready");
    send(command(2, "prompt-1", "prompt", { prompt: "SENTINEL_PROMPT_1" }));
    const model1 = await next(); assert.equal(model1.kind, "model.request"); modelCallbacks += 1;
    send(command(3, model1.request_id, "model.response", { message: assistant("call-1") }));
    const tool1 = await next(); assert.equal(tool1.kind, "tool.request"); toolCallbacks += 1;
    send(command(4, tool1.request_id, "tool.response", { result: { content: [{ type: "text", text: "SENTINEL_TOOL_RESULT" }], details: {}, isError: false } }));
    const model2 = await next(); assert.equal(model2.kind, "model.request"); modelCallbacks += 1;
    send(command(5, model2.request_id, "model.response", { message: assistant() }));
    const prompt1 = await next(); assert.equal(prompt1.kind, "command.result");
    send(command(6, "compact-1", "compact"));
    const model3 = await next(); assert.equal(model3.kind, "model.request"); modelCallbacks += 1;
    send(command(7, model3.request_id, "model.response", { message: assistant() }));
    const compact = await next();
    assert.deepEqual(compact.payload.result.compact_called, true);
    assert.deepEqual(compact.payload.result.succeeded, true);
    assert.match(compact.payload.result.first_kept_entry_id_sha256, /^sha256:[a-f0-9]{64}$/);
    send(command(8, "prompt-2", "prompt", { prompt: "SENTINEL_PROMPT_2" }));
    const model4 = await next(); assert.equal(model4.kind, "model.request"); modelCallbacks += 1;
    send(command(9, model4.request_id, "model.response", { message: assistant("call-2") }));
    const tool2 = await next(); assert.equal(tool2.kind, "tool.request"); toolCallbacks += 1;
    send(command(10, tool2.request_id, "tool.response", { result: { content: [{ type: "text", text: "SENTINEL_TOOL_RESULT" }], details: {}, isError: false } }));
    const model5 = await next(); assert.equal(model5.kind, "model.request"); modelCallbacks += 1;
    send(command(11, model5.request_id, "model.response", { message: assistant() }));
    const prompt2 = await next(); assert.equal(prompt2.kind, "command.result");
    assert.deepEqual(prompt2.payload.result.assistant, { completed: true, stop_reason: "stop" });
    assert.deepEqual({ modelCallbacks, toolCallbacks }, { modelCallbacks: 5, toolCallbacks: 2 });
    assert.doesNotMatch(JSON.stringify([prompt1, compact, prompt2]), /SENTINEL|path|credential|docker/i);
    send(command(12, "close-1", "close"));
    assert.deepEqual((await next()).payload.result, { lifecycle: "closed" });
    assert.equal((await once(child, "exit"))[0], 0);
  } finally {
    client.destroy(); socket.destroy(); server.close(); child.kill();
  }
  assert.equal(Buffer.concat(stderr).toString(), "");
});

test("settles the active compact command once when cancelled", async () => {
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const connected = once(server, "connection");
  const client = await new Promise((resolve) => {
    const socket = createConnection({ port: server.address().port, host: "127.0.0.1" });
    socket.once("connect", () => resolve(socket));
  });
  const [socket] = await connected;
  const child = spawn(process.execPath, ["dist/src/p1b-development-main.js", "3"], {
    cwd: gatewayRoot, env: {}, stdio: ["ignore", "ignore", "pipe", socket],
  });
  const receive = reader(client);
  const next = () => Promise.race([receive(), new Promise((_, reject) => {
    const timer = setTimeout(() => reject(new Error("bridge response timed out")), 5_000);
    timer.unref();
  })]);
  const send = (value) => client.write(frame(value));
  const workspace = await mkdtemp(join(tmpdir(), "asterion-p1b-cancel-"));
  try {
    send(command(1, "open-1", "open", { prime_source_root: primeSourceRoot, workspace }));
    assert.equal((await next()).kind, "ready");
    send(command(2, "prompt-1", "prompt", { prompt: "SENTINEL_PROMPT_1" }));
    const model1 = await next();
    send(command(3, model1.request_id, "model.response", { message: assistant("call-1") }));
    const tool1 = await next();
    send(command(4, tool1.request_id, "tool.response", { result: { content: [], details: {}, isError: false } }));
    const model2 = await next();
    send(command(5, model2.request_id, "model.response", { message: assistant() }));
    assert.equal((await next()).request_id, "prompt-1");
    send(command(6, "compact-1", "compact"));
    const model3 = await next();
    assert.equal(model3.kind, "model.request");
    send(command(7, "cancel-1", "cancel"));
    const settled = [await next(), await next()]
      .map((event) => [event.request_id, event.payload.result])
      .sort(([a], [b]) => a.localeCompare(b));
    assert.deepEqual(settled, [
      ["cancel-1", { lifecycle: "cancelled" }],
      ["compact-1", { lifecycle: "cancelled" }],
    ]);
    send(command(8, "close-1", "close"));
    assert.deepEqual((await next()).payload.result, { lifecycle: "closed" });
    assert.equal((await once(child, "exit"))[0], 0);
  } finally {
    client.destroy(); socket.destroy(); server.close(); child.kill();
  }
});
