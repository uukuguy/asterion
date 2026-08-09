import assert from "node:assert/strict";
import test from "node:test";

import {
  PrimeGatewaySidecar,
  PRIME_GATEWAY_IPC_PROTOCOL,
} from "../dist/src/main.js";

function command(type, payload, commandId = "command-1") {
  return {
    protocol: "asterion.agent-control/v1",
    command_id: commandId,
    session_id: "session-1",
    authority_revision: 1,
    type,
    payload,
  };
}

function event(sequence) {
  return {
    protocol: "asterion.agent-control/v1",
    event_id: `event-${sequence}`,
    session_id: "session-1",
    generation: 1,
    sequence,
    emitted_at: `2026-08-10T03:00:0${sequence}Z`,
    type: sequence === 1 ? "session.created" : "session.running",
    payload: sequence === 1
      ? {
        goal_id: "goal-1",
        authority_id: "authority-1",
        authority_revision: 1,
      }
      : { reason_code: "started" },
  };
}

class FakePrivateValues {
  constructor() {
    this.inputs = [];
    this.bindings = new Map();
  }

  async putInput(value) {
    this.inputs.push(value);
    return `private:00000000-0000-4000-8000-${String(this.inputs.length).padStart(12, "0")}`;
  }

  async bindInputReference(commandId, sourceRef, value) {
    const key = `${commandId}:${sourceRef}`;
    const existing = this.bindings.get(key);
    if (existing !== undefined) {
      if (existing.value !== value) {
        throw new Error("SENTINEL_CONFLICTING_PRIVATE_BODY");
      }
      return existing.privateRef;
    }
    const privateRef = await this.putInput(value);
    this.bindings.set(key, { privateRef, value });
    return privateRef;
  }
}

class FakeGateway {
  constructor() {
    this.accepted = [];
    this.eventsBySequence = [event(1), event(2)];
    this.cursorRequests = [];
    this.closed = 0;
  }

  async accept(value) {
    this.accepted.push(value);
  }

  eventsAfter(sequence) {
    return this.eventsBySequence.filter((item) => item.sequence > sequence);
  }

  eventsAfterCursor(cursor) {
    this.cursorRequests.push(cursor);
    return this.eventsBySequence
      .filter((item) => item.generation === cursor.generation)
      .filter((item) => item.sequence > cursor.sequence);
  }

  async close() {
    this.closed += 1;
  }
}

test("sidecar accepts a closed command envelope after private goal indirection", async () => {
  const gateway = new FakeGateway();
  const privateValues = new FakePrivateValues();
  const sidecar = new PrimeGatewaySidecar({ gateway, privateValues });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "command.accept",
    command: command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: "goal-ref-1",
    }),
    private: { goal: "SENTINEL_PRIVATE_GOAL" },
  });

  assert.deepEqual(response, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "command.accepted",
  });
  assert.equal(privateValues.inputs[0], "SENTINEL_PRIVATE_GOAL");
  assert.equal(gateway.accepted[0].payload.goal_ref, "goal-ref-1");
  assert.equal(JSON.stringify(gateway.accepted[0]).includes("SENTINEL_PRIVATE_GOAL"), false);
});

test("sidecar replays a command without changing the public command digest", async () => {
  const gateway = new FakeGateway();
  const privateValues = new FakePrivateValues();
  const sidecar = new PrimeGatewaySidecar({ gateway, privateValues });
  const publicCommand = command("session.create", {
    system_id: "research.system",
    system_version: "1.0.0",
    goal_id: "goal-1",
    goal_ref: "goal-ref-1",
  });

  for (const id of ["request-1", "request-2"]) {
    const response = await sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id,
      type: "command.accept",
      command: structuredClone(publicCommand),
      private: { goal: "SENTINEL_PRIVATE_GOAL" },
    });
    assert.equal(response.type, "command.accepted");
  }

  assert.deepEqual(gateway.accepted, [publicCommand, publicCommand]);
  assert.equal(privateValues.inputs.length, 1);
  assert.equal(JSON.stringify(gateway.accepted).includes("SENTINEL_PRIVATE_GOAL"), false);
});

test("sidecar rejects replay when the same command ref has different private content", async () => {
  const sidecar = new PrimeGatewaySidecar({
    gateway: new FakeGateway(),
    privateValues: new FakePrivateValues(),
  });
  const publicCommand = command("input.submit", {
    input_id: "input-1",
    delivery: "direct",
    content_ref: "content-ref-1",
  });
  await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "command.accept",
    command: publicCommand,
    private: { content: "SENTINEL_SECRET_A" },
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-2",
    type: "command.accept",
    command: publicCommand,
    private: { content: "SENTINEL_SECRET_B" },
  });

  assert.equal(response.type, "error");
  assert.equal(JSON.stringify(response).includes("SENTINEL_SECRET"), false);
});

test("sidecar replays public events after an exact cursor", async () => {
  const sidecar = new PrimeGatewaySidecar({
    gateway: new FakeGateway(),
    privateValues: new FakePrivateValues(),
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-2",
    type: "events.stream",
    cursor: { generation: 1, sequence: 1 },
  });

  assert.equal(response.protocol, PRIME_GATEWAY_IPC_PROTOCOL);
  assert.equal(response.id, "request-2");
  assert.equal(response.type, "events.batch");
  assert.deepEqual(response.events.map((item) => item.sequence), [2]);
});

test("sidecar replays public events through generation sequence cursor API", async () => {
  const gateway = new FakeGateway();
  gateway.eventsBySequence = [
    event(1),
    { ...event(1), event_id: "event-g2-1", generation: 2 },
    event(2),
  ];
  const sidecar = new PrimeGatewaySidecar({
    gateway,
    privateValues: new FakePrivateValues(),
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-4",
    type: "events.stream",
    cursor: { generation: 1, sequence: 1 },
  });

  assert.equal(response.type, "events.batch");
  assert.deepEqual(response.events.map((item) => [item.generation, item.sequence]), [[1, 2]]);
  assert.deepEqual(gateway.cursorRequests, [{ generation: 1, sequence: 1 }]);
});

test("sidecar error responses redact provider failures and private input", async () => {
  const sidecar = new PrimeGatewaySidecar({
    gateway: {
      async accept() {
        throw new Error("SENTINEL_SECRET provider payload");
      },
      eventsAfterCursor() {
        return [];
      },
      async close() {},
    },
    privateValues: new FakePrivateValues(),
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-3",
    type: "command.accept",
    command: command("input.submit", {
      input_id: "input-1",
      delivery: "direct",
      content_ref: "content-ref-1",
    }),
    private: { content: "SENTINEL_SECRET" },
  });

  assert.equal(response.type, "error");
  assert.equal(JSON.stringify(response).includes("SENTINEL_SECRET"), false);
});
