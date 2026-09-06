import assert from "node:assert/strict";
import { createConnection, createServer } from "node:net";
import { once } from "node:events";
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

test("keeps P4 bridge inspection free of transport and private payload values", async () => {
  const { P4DevelopmentBridge } = await import("../dist/src/index.js");
  const socket = createConnection({ port: 9, host: "127.0.0.1" }); socket.on("error", () => {});
  const bridge = new P4DevelopmentBridge(socket);
  assert.doesNotMatch(`${inspect(bridge)}${JSON.stringify(bridge)}`, /socket|buffer|path|prompt|code/i);
  socket.destroy();
});
