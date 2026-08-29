import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GatewayDurableStore,
  GatewayStoreConflictError,
  PRIME_GATEWAY_IPC_PROTOCOL,
  PrimeGatewaySidecar,
  PrimeSession,
} from "../dist/src/index.js";


async function withStore(run) {
  const temporary = await mkdtemp(join(tmpdir(), "asterion-long-running-"));
  const root = join(temporary, "gateway");
  try {
    await run(root, await GatewayDurableStore.open(root, "session-1"));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}


function restoreSession(transport, store) {
  return PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root",
    transcriptSessionId: "transcript-1",
    longRunningStore: store,
  });
}


function heartbeatTransport(store) {
  return {
    hello: { supervisorGeneration: "supervisor-generation-1" },
    requests: [],
    acknowledgeResult() {
      return true;
    },
    async request(command, commandId) {
      assert.notEqual(store.longRunningBinding("heartbeat-command-1"), undefined);
      this.requests.push({ command, commandId });
      return {
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
      };
    },
    async requestDeferred() {
      throw new Error("not used");
    },
    subscribe() {
      return () => {};
    },
  };
}


test("durable heartbeat binding precedes a body-free terminal result", async () => {
  await withStore(async (root, store) => {
    const command = {
      type: "heartbeat_set",
      activeSessionId: "prime-root",
      schedule: "0 * * * *",
      prompt: "SENTINEL_PRIVATE_HEARTBEAT_BODY",
      deliveryMode: "followUp",
    };

    const binding = await store.bindLongRunningCommand(
      "heartbeat-command-1",
      command,
    );

    assert.equal(binding.commandId, "heartbeat-command-1");
    assert.match(binding.commandDigest, /^[0-9a-f]{64}$/u);
    assert.deepEqual(store.longRunningBinding("heartbeat-command-1"), binding);
    assert.equal(store.longRunningResult("heartbeat-command-1"), undefined);
    assert.equal(
      JSON.stringify(store.snapshot()).includes("SENTINEL_PRIVATE_HEARTBEAT_BODY"),
      false,
    );

    const result = await store.commitLongRunningResult(
      "heartbeat-command-1",
      "succeeded",
    );
    assert.deepEqual(result, {
      commandId: "heartbeat-command-1",
      commandDigest: binding.commandDigest,
      status: "succeeded",
    });

    const reopened = await GatewayDurableStore.open(root, "session-1");
    assert.deepEqual(reopened.longRunningBinding("heartbeat-command-1"), binding);
    assert.deepEqual(reopened.longRunningResult("heartbeat-command-1"), result);
  });
});


test("durable heartbeat binding fails closed on aliases and identity drift", async () => {
  await withStore(async (_root, store) => {
    await store.bindLongRunningCommand(
      "heartbeat-command-1",
      { type: "heartbeats_list" },
    );

    await assert.rejects(
      store.bindLongRunningCommand(
        "heartbeat-command-1",
        { type: "heartbeat_get", activeSessionId: "prime-root" },
      ),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      store.bindLongRunningCommand(
        "heartbeat-alias",
        { type: "list_heartbeats" },
      ),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      store.commitLongRunningResult("heartbeat-missing", "succeeded"),
      GatewayStoreConflictError,
    );
  });
});


test("recovery exposes an uncommitted mutation without inventing success", async () => {
  await withStore(async (root, store) => {
    const binding = await store.bindLongRunningCommand(
      "heartbeat-command-uncertain",
      {
        type: "heartbeat_update",
        activeSessionId: "prime-root",
        action: "pause",
      },
    );

    const reopened = await GatewayDurableStore.open(root, "session-1");
    assert.deepEqual(
      reopened.longRunningBinding("heartbeat-command-uncertain"),
      binding,
    );
    assert.equal(
      reopened.longRunningResult("heartbeat-command-uncertain"),
      undefined,
    );
  });
});


test("Prime session durably binds a heartbeat before sending its exact command", async () => {
  await withStore(async (_root, store) => {
    const transport = heartbeatTransport(store);
    const session = restoreSession(transport, store);
    const result = await session.executeLongRunningCommand(
      "heartbeat-command-1",
      {
        type: "heartbeat_set",
        activeSessionId: "prime-root",
        schedule: "0 * * * *",
        prompt: "SENTINEL_PRIVATE_HEARTBEAT_BODY",
        deliveryMode: "followUp",
      },
    );

    assert.equal(transport.requests.length, 1);
    assert.equal(transport.requests[0].command.type, "heartbeat_set");
    assert.deepEqual(result, store.longRunningResult("heartbeat-command-1"));
    assert.equal(result.status, "succeeded");
    assert.equal(JSON.stringify(result).includes("SENTINEL_PRIVATE_HEARTBEAT_BODY"), false);
  });
});


test("Prime session recovery fences an uncommitted heartbeat without resending it", async () => {
  await withStore(async (root, store) => {
    const command = {
      type: "heartbeat_update",
      activeSessionId: "prime-root",
      action: "pause",
    };
    await store.bindLongRunningCommand("heartbeat-command-1", command);

    const reopened = await GatewayDurableStore.open(root, "session-1");
    const transport = heartbeatTransport(reopened);
    const result = await restoreSession(transport, reopened)
      .executeLongRunningCommand("heartbeat-command-1", command);

    assert.equal(transport.requests.length, 0);
    assert.equal(result.status, "uncertain");
    assert.deepEqual(result, reopened.longRunningResult("heartbeat-command-1"));
  });
});


test("Prime session rejects heartbeat commands for a different active session", async () => {
  await withStore(async (_root, store) => {
    const transport = heartbeatTransport(store);
    const session = restoreSession(transport, store);

    await assert.rejects(
      session.executeLongRunningCommand("heartbeat-command-1", {
        type: "heartbeat_get",
        activeSessionId: "prime-other",
      }),
    );
    assert.equal(transport.requests.length, 0);
    assert.equal(store.longRunningBinding("heartbeat-command-1"), undefined);
  });
});


test("private long-running IPC returns only a body-free durable receipt", async () => {
  const calls = [];
  const sidecar = new PrimeGatewaySidecar({
    gateway: {
      async accept() {},
      updateRemainingBudget() {},
      eventsAfterCursor() {
        return [];
      },
      async executeLongRunning(commandId, command) {
        calls.push({ commandId, command });
        return {
          commandId,
          commandDigest: "a".repeat(64),
          status: "succeeded",
        };
      },
      async close() {},
    },
    privateValues: {},
  });
  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "long-running.execute",
    command_id: "heartbeat-command-1",
    command: {
      type: "heartbeat_set",
      activeSessionId: "prime-root",
      schedule: "0 * * * *",
      prompt: "SENTINEL_PRIVATE_HEARTBEAT_BODY",
      deliveryMode: "followUp",
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(response.type, "long-running.receipt");
  assert.equal(response.receipt.status, "succeeded");
  assert.equal(JSON.stringify(response).includes("SENTINEL_PRIVATE_HEARTBEAT_BODY"), false);
});
