import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createServer } from "node:net";
import { join } from "node:path";
import { tmpdir } from "node:os";
import test from "node:test";

import {
  PRIME_OPERATION_HOST_PROTOCOL,
  PrimeOperationError,
  PrimeOperationHostClient,
} from "../dist/src/index.js";
import { createPrimeOperationGatewayFromDescriptor } from "../dist/src/main.js";


const token = "a".repeat(64);

function transaction() {
  return {
    protocol: "asterion.operation/v1",
    operation_id: "operation-1",
    request: {
      protocol: "asterion.operation/v1",
      request_kind: "operation.auth-request",
      request_ref: "request-1",
      request_sha256: "b".repeat(64),
      media_type: "application/json",
      byte_count: 24,
      purpose: "operation.auth",
      client_id: "client-1",
      session_id: "session-1",
      generation: 2,
      authority_revision: 3,
    },
    session_id: "session-1",
    client_id: "client-1",
    generation: 2,
    authority_revision: 3,
    authority_id: "authority-1",
    idempotency_key: "key-operation-1",
    feature_id: "operation.auth",
    requested_at: "2026-08-30T10:00:00Z",
  };
}

function receipt(status = "succeeded") {
  const value = transaction();
  return {
    protocol: "asterion.operation/v1",
    receipt_id: "receipt-operation-1",
    operation_id: value.operation_id,
    request_ref: value.request.request_ref,
    request_sha256: value.request.request_sha256,
    purpose: value.request.purpose,
    session_id: value.session_id,
    client_id: value.client_id,
    generation: value.generation,
    authority_revision: value.authority_revision,
    authority_id: value.authority_id,
    idempotency_key: value.idempotency_key,
    feature_id: value.feature_id,
    status,
    reason_code: `operation-${status}`,
    receipt_ref: "public-operation-1",
    reconciliation_ref: null,
    effect_counts: {
      credential_value_reads: 0,
      provider_model_requests: 0,
      network_operations: 0,
      package_manager_operations: 0,
      os_process_restart_operations: 0,
      external_telemetry_deliveries: 0,
      uploads: 0,
    },
    completed_at: "2026-08-30T10:00:01Z",
  };
}

function client(socketPath, timeoutMs = 100) {
  return new PrimeOperationHostClient({ socketPath, token }, {
    sessionId: "session-1",
    generation: 2,
    authorityId: "authority-1",
    authorityRevision: 3,
    timeoutMs,
  });
}

async function operationServer(handler) {
  const root = await mkdtemp(join(tmpdir(), "asterion-operation-host-"));
  const socketPath = join(root, "operation.sock");
  const sockets = new Set();
  const server = createServer({ allowHalfOpen: true }, (socket) => {
    sockets.add(socket);
    socket.once("close", () => sockets.delete(socket));
    const chunks = [];
    socket.on("data", (chunk) => chunks.push(chunk));
    socket.on("end", () => {
      Promise.resolve(handler(Buffer.concat(chunks), socket)).catch(() => socket.destroy());
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });
  return {
    socketPath,
    async close() {
      const closed = new Promise((resolve) => server.close(resolve));
      for (const socket of sockets) socket.destroy();
      await closed;
      await rm(root, { recursive: true, force: true });
    },
  };
}

function sendReceipt(request, socket, value = receipt()) {
  socket.end(`${JSON.stringify({
    protocol: PRIME_OPERATION_HOST_PROTOCOL,
    id: request.id,
    type: "operation.receipt",
    receipt: value,
  })}\n`);
}

test("operation host client sends exact EOF-terminated execute reconcile and cancel frames", async () => {
  const frames = [];
  const host = await operationServer((frame, socket) => {
    assert.equal(frame.at(-1), 0x0a);
    const request = JSON.parse(frame.toString("utf8"));
    frames.push(request);
    sendReceipt(request, socket, receipt(request.type === "operation.cancel" ? "cancelled" : "succeeded"));
  });
  try {
    const dispatcher = client(host.socketPath);
    await dispatcher.execute(transaction());
    await dispatcher.reconcile(transaction());
    await dispatcher.cancel("operation-1", 3);
    assert.equal(frames.length, 3);
    for (const [index, type] of ["operation.execute", "operation.reconcile", "operation.cancel"].entries()) {
      const frame = frames[index];
      assert.equal(frame.protocol, PRIME_OPERATION_HOST_PROTOCOL);
      assert.equal(frame.type, type);
      assert.equal(frame.token, token);
      assert.equal(frame.session_id, "session-1");
      assert.equal(frame.generation, 2);
      assert.equal(frame.authority_id, "authority-1");
      assert.equal(frame.authority_revision, 3);
      assert.match(frame.id, /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u);
      assert.deepEqual(
        Object.keys(frame).sort(),
        (type === "operation.cancel"
          ? ["authority_id", "authority_revision", "generation", "id", "operation_id", "protocol", "session_id", "token", "type"]
          : ["authority_id", "authority_revision", "generation", "id", "protocol", "session_id", "token", "transaction", "type"]
        ).sort(),
      );
      assert.equal(JSON.stringify(frame).includes("SENTINEL-BODY"), false);
    }
  } finally {
    await host.close();
  }
});

test("production descriptor builder constructs the operation host gateway chain", async () => {
  let calls = 0;
  const host = await operationServer((frame, socket) => {
    calls += 1;
    const request = JSON.parse(frame.toString("utf8"));
    assert.equal(request.type, "operation.execute");
    sendReceipt(request, socket);
  });
  try {
    const gateway = createPrimeOperationGatewayFromDescriptor({
      operationHost: { socketPath: host.socketPath, token },
      sessionId: "session-1",
      generation: 2,
      authorityId: "authority-1",
      authorityRevision: 3,
      timeoutMs: 100,
    });
    assert.deepEqual(await gateway.execute(transaction()), receipt());
    assert.equal(calls, 1);
  } finally {
    await host.close();
  }
});

test("operation host client rejects unsafe responses without retry or disclosure", async () => {
  const cases = [
    (request, socket) => socket.end("not-json\n"),
    (request, socket) => socket.end(`${JSON.stringify({ protocol: PRIME_OPERATION_HOST_PROTOCOL, id: request.id, type: "error", code: "operation-host-failed" })}\n`),
    (request, socket) => socket.end(`${JSON.stringify({ protocol: PRIME_OPERATION_HOST_PROTOCOL, id: "wrong-id", type: "operation.receipt", receipt: receipt() })}\n`),
    (request, socket) => socket.end(`${JSON.stringify({ protocol: PRIME_OPERATION_HOST_PROTOCOL, id: request.id, type: "operation.receipt", receipt: receipt() })}\n{}\n`),
    (request, socket) => socket.end(`${JSON.stringify({ protocol: PRIME_OPERATION_HOST_PROTOCOL, id: request.id, type: "operation.receipt", receipt: { ...receipt(), authority_id: "authority-hostile" } })}\n`),
    (request, socket) => socket.end(`{"protocol":"${PRIME_OPERATION_HOST_PROTOCOL}","id":"${request.id}","id":"${request.id}","type":"operation.receipt","receipt":${JSON.stringify(receipt())}}\n`),
    (request, socket) => socket.end(`${JSON.stringify({ protocol: PRIME_OPERATION_HOST_PROTOCOL, id: request.id, type: "operation.receipt", receipt: receipt() }).replace('"authority_id":"authority-1"', '"authority_id":"authority-1","authority_id":"authority-1"')}\n`),
    (request, socket) => socket.end("x".repeat(70_000)),
    (request, socket) => socket.destroy(),
  ];
  for (const [index, respond] of cases.entries()) {
    let connections = 0;
    const host = await operationServer((frame, socket) => {
      connections += 1;
      respond(JSON.parse(frame.toString("utf8")), socket);
    });
    try {
      await assert.rejects(client(host.socketPath).execute(transaction()), (error) => {
        assert.equal(error instanceof PrimeOperationError, true);
        assert.equal(error.message, "Prime operation failed");
        assert.equal(String(error).includes(token), false);
        assert.equal(String(error).includes(host.socketPath), false);
        return true;
      }, `case ${index}`);
      assert.equal(connections, 1);
    } finally {
      await host.close();
    }
  }
});

test("operation host client times out once and validates bound identity", async () => {
  let connections = 0;
  const host = await operationServer(() => { connections += 1; });
  try {
    await assert.rejects(client(host.socketPath, 20).execute(transaction()), PrimeOperationError);
    assert.equal(connections, 1);
    await assert.rejects(
      client(host.socketPath).execute({ ...transaction(), session_id: "session-2" }),
      PrimeOperationError,
    );
    await assert.rejects(client(host.socketPath).cancel("operation-1", 4), PrimeOperationError);
    assert.equal(connections, 1);
  } finally {
    await host.close();
  }
});

test("operation host client enforces an absolute deadline against slow drip", async () => {
  const host = await operationServer((frame, socket) => {
    assert.ok(frame.byteLength > 0);
    const interval = setInterval(() => socket.write(" "), 10);
    const finish = setTimeout(() => {
      clearInterval(interval);
      socket.end();
    }, 120);
    socket.once("close", () => {
      clearInterval(interval);
      clearTimeout(finish);
    });
  });
  try {
    const started = Date.now();
    await assert.rejects(
      client(host.socketPath, 30).execute(transaction()),
      PrimeOperationError,
    );
    assert.ok(Date.now() - started < 90);
  } finally {
    await host.close();
  }
});

test("operation host client rejects malformed descriptors with one safe error", () => {
  for (const descriptor of [
    { socketPath: "relative.sock", token },
    { socketPath: "/tmp/operation.sock", token: "SENTINEL-TOKEN" },
    { socketPath: "/tmp/operation.sock", token, extra: true },
    Object.defineProperty({ socketPath: "/tmp/operation.sock" }, "token", {
      enumerable: true,
      get() { throw new Error("SENTINEL-PRIVATE-DESCRIPTOR"); },
    }),
  ]) {
    assert.throws(
      () => new PrimeOperationHostClient(descriptor, {
        sessionId: "session-1",
        generation: 2,
        authorityId: "authority-1",
        authorityRevision: 3,
        timeoutMs: 100,
      }),
      PrimeOperationError,
    );
  }
});
