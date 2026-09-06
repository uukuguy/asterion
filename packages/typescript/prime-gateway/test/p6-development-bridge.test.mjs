import assert from "node:assert/strict";
import { createConnection, createServer } from "node:net";
import { once } from "node:events";
import test from "node:test";

function frame(value) {
  const body = Buffer.from(canonical(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(body.length);
  return Buffer.concat([header, body]);
}

function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
    .join(",")}}`;
}

test("rejects a P6 prompt before open without starting a session", async () => {
  const { P6DevelopmentBridge, P6DevelopmentBridgeError } =
    await import("../dist/src/index.js");
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const connected = once(server, "connection");
  const client = createConnection({
    port: server.address().port,
    host: "127.0.0.1",
  });
  await once(client, "connect");
  const [socket] = await connected;
  const run = new P6DevelopmentBridge(socket).run();
  client.write(frame({
    protocol: "asterion.prime-p6-development-gateway/v1",
    run_id: "run-1",
    session_id: "session-1",
    runtime_id: "prime.agent",
    generation: 1,
    sequence: 1,
    request_id: "prompt-1",
    kind: "prompt",
    payload: { prompt: "stage" },
  }));
  await assert.rejects(run, P6DevelopmentBridgeError);
  client.destroy();
  server.close();
});
