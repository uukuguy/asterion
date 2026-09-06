import assert from "node:assert/strict";
import { createConnection, createServer } from "node:net";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { inspect } from "node:util";
import test from "node:test";

const protocol = "asterion.prime-p4-development-gateway/v1";

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function frame(value) { const body = Buffer.from(canonical(value)); const header = Buffer.alloc(4); header.writeUInt32BE(body.length); return Buffer.concat([header, body]); }
function command(sequence, request_id, kind, payload = {}) { return { protocol, run_id: "run-1", session_id: "session-1", runtime_id: "prime.agent", generation: 1, sequence, request_id, kind, payload }; }
function reader(socket) { let buffered = Buffer.alloc(0); const queued = [], waiting = []; socket.on("data", (chunk) => { buffered = Buffer.concat([buffered, chunk]); while (buffered.length >= 4 && buffered.length >= 4 + buffered.readUInt32BE()) { const n = buffered.readUInt32BE(), value = JSON.parse(buffered.subarray(4, n + 4)); buffered = buffered.subarray(n + 4); const resolve = waiting.shift(); if (resolve) resolve(value); else queued.push(value); } }); return () => queued.length ? Promise.resolve(queued.shift()) : new Promise((resolve) => waiting.push(resolve)); }

test("rejects a recovery command before any native daemon effect", async () => {
  const { P4DevelopmentBridge, P4DevelopmentBridgeError } = await import("../dist/src/index.js");
  const server = createServer(); server.listen(0, "127.0.0.1"); await once(server, "listening");
  const connected = once(server, "connection");
  const client = createConnection({ port: server.address().port, host: "127.0.0.1" }); await once(client, "connect");
  const [socket] = await connected;
  const bridge = new P4DevelopmentBridge(socket);
  const run = bridge.run();
  client.write(frame(command(1, "recover-1", "recover", { checkpoint_candidate: {}, checkpoint_sha256: `sha256:${"0".repeat(64)}` })));
  await assert.rejects(run, P4DevelopmentBridgeError);
  client.destroy(); server.close();
});

test("fails a detach before it can attach or compact", async () => {
  const { requireP4DetachedBeforeAttach } = await import("../dist/src/index.js");
  let attached = false;
  await assert.rejects(
    () => requireP4DetachedBeforeAttach(Promise.resolve({ success: false }), async () => { attached = true; return "attached"; }),
    /detach failed/,
  );
  assert.equal(attached, false);
});

test("keeps P4 bridge inspection free of transport and private payload values", async () => {
  const { P4DevelopmentBridge } = await import("../dist/src/index.js");
  const socket = createConnection({ port: 9, host: "127.0.0.1" }); socket.on("error", () => {});
  const bridge = new P4DevelopmentBridge(socket);
  assert.doesNotMatch(`${inspect(bridge)}${JSON.stringify(bridge)}`, /socket|buffer|path|prompt|code/i);
  socket.destroy();
});

test("reaps the native daemon after the private close result is written", async () => {
  const root = process.cwd(), workspace = await mkdtemp(join(tmpdir(), "asterion-p4-reap-"));
  const server = createServer(); server.listen(0, "127.0.0.1"); await once(server, "listening");
  const connected = once(server, "connection"), client = createConnection({ port: server.address().port, host: "127.0.0.1" }); await once(client, "connect"); const [socket] = await connected;
  const child = spawn(process.execPath, ["dist/src/p4-development-main.js", "3"], { cwd: root, env: {}, stdio: ["ignore", "ignore", "pipe", socket] });
  const next = reader(client); let sequence = 0; const send = (id, kind, payload = {}) => client.write(frame(command(++sequence, id, kind, payload)));
  try {
    send("open-1", "open", { prime_source_root: join(root, "../../../3th-party/prime-agent"), workspace }); assert.equal((await next()).kind, "ready");
    send("cancel-1", "cancel"); assert.deepEqual((await next()).payload.result, { lifecycle: "cancelled" });
    send("close-1", "close"); assert.equal((await next()).kind, "command.result");
    assert.equal((await once(child, "exit"))[0], 0);
  } finally { client.destroy(); socket.destroy(); server.close(); child.kill(); }
});
