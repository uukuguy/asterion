import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrimeBoundPrivateInputs,
  PrimeGatewaySidecar,
  PRIME_GATEWAY_IPC_PROTOCOL,
} from "../dist/src/main.js";
import {
  PrivateValueStore,
} from "../dist/src/index.js";

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

async function temporaryStoreRoot() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-sidecar-"));
  return {
    parent,
    root: join(parent, "gateway"),
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function event(sequence, generation = 1) {
  return {
    protocol: "asterion.agent-control/v1",
    event_id: `event-${generation}-${sequence}`,
    session_id: "session-1",
    generation,
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

  async readBoundInputReference(sourceRef) {
    for (const binding of this.bindings.values()) {
      if (binding.sourceRef === sourceRef) {
        return binding.value;
      }
    }
    throw new Error("missing binding");
  }
}

class FakeGateway {
  constructor({ currentGeneration = 1, knownGenerations = [currentGeneration] } = {}) {
    this.accepted = [];
    this.currentGeneration = currentGeneration;
    this.knownGenerations = new Set(knownGenerations);
    this.eventsBySequence = [event(1, currentGeneration), event(2, currentGeneration)];
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
    if (!this.knownGenerations.has(cursor.generation)) {
      throw new Error("unknown generation");
    }
    return this.eventsBySequence
      .filter((item) => item.generation === cursor.generation)
      .filter((item) => item.sequence > cursor.sequence);
  }

  async close() {
    this.closed += 1;
  }
}

function createSidecar(options = {}) {
  const gateway = options.gateway ?? new FakeGateway(options.gatewayOptions);
  const privateValues = options.privateValues ?? new FakePrivateValues();
  return {
    gateway,
    privateValues,
    sidecar: new PrimeGatewaySidecar({
      currentGeneration: options.currentGeneration ?? gateway.currentGeneration ?? 1,
      gateway,
      privateValues,
    }),
  };
}

test("bound private inputs resolve private-looking public refs through bindings", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const privateValues = await PrivateValueStore.open(fixtureRoot.root);
    const publicRef = await privateValues.putInput("SENTINEL_OLD_LOCAL_VALUE");
    await privateValues.bindInputReference(
      "command-1",
      publicRef,
      "SENTINEL_RESOLVER_BODY",
    );
    const boundPrivateInputs = new PrimeBoundPrivateInputs(privateValues);

    assert.equal(
      await boundPrivateInputs.readInput(publicRef),
      "SENTINEL_RESOLVER_BODY",
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("sidecar null event cursor replays the injected current generation", async () => {
  const gateway = new FakeGateway({
    currentGeneration: 2,
    knownGenerations: [1, 2],
  });
  gateway.eventsBySequence = [event(1, 1), event(1, 2), event(2, 2)];
  const { sidecar } = createSidecar({ gateway, currentGeneration: 2 });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-current-generation",
    type: "events.stream",
    cursor: null,
  });

  assert.equal(response.type, "events.batch");
  assert.deepEqual(
    response.events.map((item) => [item.generation, item.sequence]),
    [[2, 1], [2, 2]],
  );
  assert.deepEqual(gateway.cursorRequests, [{ generation: 2, sequence: 0 }]);
});

test("sidecar null event cursor succeeds for an explicitly empty current generation", async () => {
  const gateway = new FakeGateway({
    currentGeneration: 3,
    knownGenerations: [3],
  });
  gateway.eventsBySequence = [];
  const { sidecar } = createSidecar({ gateway, currentGeneration: 3 });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-empty-generation",
    type: "events.stream",
    cursor: null,
  });

  assert.equal(response.type, "events.batch");
  assert.deepEqual(response.events, []);
  assert.deepEqual(gateway.cursorRequests, [{ generation: 3, sequence: 0 }]);
});

test("sidecar rejects unknown generation cursors instead of returning empty batches", async () => {
  const { sidecar } = createSidecar({
    gateway: new FakeGateway({
      currentGeneration: 1,
      knownGenerations: [1],
    }),
    currentGeneration: 1,
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-future-generation",
    type: "events.stream",
    cursor: { generation: 2, sequence: 0 },
  });

  assert.equal(response.type, "error");
});

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
