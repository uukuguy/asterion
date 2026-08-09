import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  validateControlEvent,
  validateControlEventStream,
} from "@dci/agent-runtime";
import {
  GatewayDurableStore,
  PrimeGateway,
  PrimePromptAdmissionUncertainError,
  PrivateValueStore,
} from "../dist/src/index.js";

function recoveryTransport(supervisorGeneration, name) {
  return {
    hello: { supervisorGeneration, name },
    async request() {
      throw new Error("not used by fake session");
    },
    async requestDeferred() {
      throw new Error("not used by fake session");
    },
    subscribe() {
      return () => undefined;
    },
    acknowledgeResult() {
      return true;
    },
  };
}

class FakePrimeSession {
  constructor() {
    this.activeSessionId = "prime-root-1";
    this.transcriptSessionId = "transcript-1";
    this.supervisorGeneration = "supervisor-generation-1";
    this.calls = [];
    this.recoveries = [];
    this.checkpointAcknowledgements = [];
    this.checkpointAcknowledger = () => true;
    this.listener = undefined;
    this.pauseError = undefined;
  }

  subscribe(listener) {
    this.listener = listener;
    return () => {
      this.listener = undefined;
    };
  }

  async submitInput(inputId, delivery, body) {
    this.calls.push(["input", inputId, delivery, body]);
  }

  async pause(commandId) {
    this.calls.push(["pause", commandId]);
    if (this.pauseError !== undefined) {
      throw this.pauseError;
    }
  }

  async resume(commandId) {
    this.calls.push(["resume", commandId]);
  }

  async attach(commandId, cursor) {
    this.calls.push(["attach", commandId, cursor]);
  }

  async detach(commandId) {
    this.calls.push(["detach", commandId]);
  }

  async cancel(commandId) {
    this.calls.push(["cancel", commandId]);
  }

  adoptRecovery(recovery) {
    this.recoveries.push(recovery);
    this.supervisorGeneration = recovery.supervisorGeneration;
  }

  acknowledgeCheckpoint(checkpointId) {
    this.checkpointAcknowledgements.push(checkpointId);
    return this.checkpointAcknowledger(checkpointId);
  }

  emit(outbound) {
    this.listener?.(outbound);
  }
}

async function fixture({
  checkpointAckFailures = 0,
  failCheckpointEvent = false,
} = {}) {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-gateway-"));
  const root = join(parent, "gateway");
  let failNextWrite = false;
  const store = await GatewayDurableStore.open(root, "session-1", {
    faultInjector(stage) {
      if (failNextWrite && stage === "before_write") {
        failNextWrite = false;
        throw new Error("SENTINEL_CHECKPOINT_EVENT_WRITE");
      }
    },
  });
  const privateValues = await PrivateValueStore.open(root);
  const session = new FakePrimeSession();
  const createdGoals = [];
  const checkpointAcknowledgements = [];
  const checkpointAcknowledgementAttempts = [];
  const attemptCheckpointAcknowledgement = (checkpointId) => {
    checkpointAcknowledgementAttempts.push(checkpointId);
    if (checkpointAcknowledgementAttempts.length <= checkpointAckFailures) {
      return false;
    }
    checkpointAcknowledgements.push(checkpointId);
    return true;
  };
  session.checkpointAcknowledger = attemptCheckpointAcknowledgement;
  let tick = 0;
  const gateway = await PrimeGateway.open({
    sessionId: "session-1",
    generation: 1,
    authorityId: "authority-1",
    store,
    privateValues,
    async createSession(goal, bindIdentity) {
      createdGoals.push(goal);
      await bindIdentity({
        activeSessionId: session.activeSessionId,
        transcriptSessionId: session.transcriptSessionId,
        supervisorGeneration: session.supervisorGeneration,
      });
      return session;
    },
    async createCheckpoint(checkpointId, coveredSequence, onRecovered) {
      await onRecovered({
        transport: recoveryTransport(
          "supervisor-generation-2",
          "relaunched-transport",
        ),
        primeCursor: { generation: "prime-events-2", sequence: 11 },
        transcriptSessionId: "transcript-1",
        supervisorGeneration: "supervisor-generation-2",
        sessionStatus: "running",
      });
      failNextWrite = failCheckpointEvent;
      return {
        checkpointId,
        capsuleId: "capsule-1",
        capsuleDigest: "a".repeat(64),
        controlPlaneId: "prime.gateway",
        controlPlaneVersion: "0.1.0",
        checkpointVersion: "1.0.0",
        coveredSequence,
        storageRef: "private:capsule-1",
        primeCursor: { generation: "prime-events-2", sequence: 11 },
        supervisorGeneration: "supervisor-generation-2",
        acknowledge() {
          return attemptCheckpointAcknowledgement(checkpointId);
        },
      };
    },
    now() {
      tick += 1;
      return `2026-08-10T03:00:${String(tick).padStart(2, "0")}Z`;
    },
  });
  return {
    parent,
    root,
    store,
    privateValues,
    session,
    gateway,
    createdGoals,
    checkpointAcknowledgements,
    checkpointAcknowledgementAttempts,
    async cleanup({ allowCloseFailure = false } = {}) {
      if (allowCloseFailure) {
        await gateway.close().catch(() => undefined);
      } else {
        await gateway.close();
      }
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function command(type, payload, commandId) {
  return {
    protocol: "asterion.agent-control/v1",
    command_id: commandId,
    session_id: "session-1",
    authority_revision: 1,
    type,
    payload,
  };
}

function eventTypes(store) {
  return store.eventsAfter(0).map(({ event }) => event.type);
}

function proposal(identity, actionId, inputRef) {
  return {
    protocol: "asterion.agent-control/v1",
    event_id: identity.eventId,
    session_id: "session-1",
    generation: 1,
    sequence: identity.sequence,
    emitted_at: identity.emittedAt,
    type: "action.proposed",
    payload: {
      action_id: actionId,
      authority_revision: 1,
      idempotency_key: `${actionId}-once`,
      kind: "application.invoke",
      target: {
        kind: "application",
        provider_id: "example.provider",
        application_id: "alpha",
        version: "1.0.0",
        runtime_id: "fake.runtime",
      },
      input_ref: inputRef,
      expected_artifacts: [],
      budget: {
        controller_tokens: 0,
        application_tokens: 10,
        child_tokens: 0,
        aggregate_tokens: 10,
        cost_micros: 100,
        deadline_ms: 1_000,
      },
      causal_parent_ids: ["goal-1"],
    },
  };
}

test("gateway persists create before one safe running prefix", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("SENTINEL_PRIVATE_GOAL");
    const create = command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create");
    await state.gateway.accept(create);
    await state.gateway.accept(structuredClone(create));

    assert.deepEqual(state.createdGoals, ["SENTINEL_PRIVATE_GOAL"]);
    assert.deepEqual(eventTypes(state.store), ["session.created", "session.running"]);
    assert.equal(state.store.snapshot().commandCount, 1);
    assert.deepEqual(state.store.snapshot().primeIdentity, {
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
    });
    assert.equal(JSON.stringify(state.store.snapshot()).includes("SENTINEL"), false);
    const publicGateway = JSON.stringify(state.gateway);
    assert.equal(publicGateway.includes("SENTINEL"), false);
    assert.equal(publicGateway.includes(state.root), false);
    assert.deepEqual(JSON.parse(publicGateway), {
      kind: "asterion-prime-gateway",
      session_id: "session-1",
      generation: 1,
      status: "running",
    });
  } finally {
    await state.cleanup();
  }
});

test("gateway handles input pause resume attach checkpoint and detach", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("SENTINEL_PRIVATE_INPUT");
    await state.gateway.accept(command("input.submit", {
      input_id: "input-1",
      delivery: "steer",
      content_ref: inputRef,
    }, "command-input"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.accept(command("session.resume", {
      reason_code: "operator-request",
    }, "command-resume"));
    await state.gateway.accept(command("session.attach", {
      cursor: { generation: 1, sequence: 2 },
    }, "command-attach"));
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-1",
    }, "command-checkpoint"));
    await state.gateway.detach();

    assert.deepEqual(state.session.calls, [
      ["input", "input-1", "steer", "SENTINEL_PRIVATE_INPUT"],
      ["pause", "command-pause"],
      ["resume", "command-resume"],
      ["attach", "command-attach", undefined],
      ["detach", "asterion-detach"],
    ]);
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "session.paused",
      "session.running",
      "session.recovery-required",
      "session.running",
      "checkpoint.created",
    ]);
    const checkpoint = state.store.eventsAfter(0).at(-1).event;
    assert.equal(checkpoint.payload.covered_sequence, 6);
    assert.deepEqual(state.store.snapshot().primeIdentity, {
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-2",
    });
    assert.deepEqual(state.store.snapshot().primeCursor, {
      generation: "prime-events-2",
      sequence: 11,
    });
    assert.deepEqual(state.checkpointAcknowledgements, ["checkpoint-1"]);
    assert.equal(JSON.stringify(state.store.eventsAfter(0)).includes("SENTINEL"), false);
    const events = state.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(validateControlEvent), events);
    assert.deepEqual(events.map(({ sequence }) => sequence), [1, 2, 3, 4, 5, 6, 7]);
  } finally {
    await state.cleanup();
  }
});

test("gateway acknowledges Prime only after checkpoint event is durable", async () => {
  const state = await fixture({ failCheckpointEvent: true });
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-write-failure",
    }, "command-checkpoint-write-failure")));

    assert.deepEqual(state.checkpointAcknowledgements, []);
    assert.equal(eventTypes(state.store).includes("checkpoint.created"), false);
  } finally {
    await state.cleanup({ allowCloseFailure: true });
  }
});

test("gateway retries a failed checkpoint acknowledgement on command replay", async () => {
  const state = await fixture({ checkpointAckFailures: 1 });
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const checkpointCommand = command("checkpoint.request", {
      checkpoint_id: "checkpoint-ack-retry",
    }, "command-checkpoint-ack-retry");
    await state.gateway.accept(checkpointCommand);
    assert.deepEqual(state.checkpointAcknowledgementAttempts, [
      "checkpoint-ack-retry",
    ]);
    assert.deepEqual(state.checkpointAcknowledgements, []);

    await state.gateway.accept(structuredClone(checkpointCommand));
    assert.deepEqual(state.checkpointAcknowledgementAttempts, [
      "checkpoint-ack-retry",
      "checkpoint-ack-retry",
    ]);
    assert.deepEqual(state.checkpointAcknowledgements, [
      "checkpoint-ack-retry",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway retries a failed checkpoint acknowledgement after reopen", async () => {
  const state = await fixture({ checkpointAckFailures: 1 });
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-ack-reopen",
    }, "command-checkpoint-ack-reopen"));
    assert.deepEqual(state.checkpointAcknowledgements, []);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "ack-reopen-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("completed checkpoint must not be recreated");
      },
    });

    assert.deepEqual(restoredSession.checkpointAcknowledgements, [
      "checkpoint-ack-reopen",
    ]);
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway rejects checkpoint when the live supervisor identity drifted", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.supervisorGeneration = "supervisor-generation-drift";
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-identity-drift",
    }, "command-checkpoint-identity-drift")));

    assert.deepEqual(state.checkpointAcknowledgements, []);
    assert.equal(eventTypes(state.store).includes("checkpoint.created"), false);
  } finally {
    await state.cleanup();
  }
});

test("gateway drains an already queued Prime event before checkpoint recovery", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: true,
          status: "active",
          tokensUsed: 5,
          timeUsedSeconds: 1,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-1",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:20:00Z",
      },
    });
    await state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-race",
    }, "command-checkpoint-race"));

    const events = state.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(({ type }) => type), [
      "session.created",
      "session.running",
      "budget.reported",
      "session.recovery-required",
      "session.running",
      "checkpoint.created",
    ]);
    assert.equal(events.at(-1).payload.covered_sequence, 5);
    assert.deepEqual(events.map(({ sequence }) => sequence), [1, 2, 3, 4, 5, 6]);
  } finally {
    await state.cleanup();
  }
});

test("gateway resubscribes when a queued pause rejects checkpoint", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: false,
          status: "paused",
          tokensUsed: 0,
          timeUsedSeconds: 1,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-pause",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:21:00Z",
      },
    });
    await assert.rejects(state.gateway.accept(command("checkpoint.request", {
      checkpoint_id: "checkpoint-paused-race",
    }, "command-checkpoint-paused-race")));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: true,
          status: "active",
          tokensUsed: 0,
          timeUsedSeconds: 2,
          continuationsUsed: 0,
        },
      },
      meta: {
        id: "prime-event-resume",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 2,
        cursor: { generation: "worker-generation-1", sequence: 2 },
        emittedAt: "2026-08-10T03:22:00Z",
      },
    });
    await state.gateway.settle();

    assert.deepEqual(eventTypes(state.store).slice(-3), [
      "session.paused",
      "session.running",
      "goal.updated",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway reopens a checkpointed resident without creating a second Prime root", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const checkpointCommand = command("checkpoint.request", {
      checkpoint_id: "checkpoint-1",
    }, "command-checkpoint");
    await state.gateway.accept(checkpointCommand);
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    const restoredIdentities = [];
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(identity, onRecovered) {
        restoredIdentities.push(identity);
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "reopened-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("completed checkpoint must replay without side effects");
      },
    });

    await reopened.accept(structuredClone(checkpointCommand));
    const inputRef = await state.privateValues.putInput("private resumed input");
    await reopened.accept(command("input.submit", {
      input_id: "input-after-reopen",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-after-reopen"));

    assert.deepEqual(restoredIdentities, [{
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-2",
    }]);
    assert.deepEqual(restoredSession.calls, [[
      "input",
      "input-after-reopen",
      "direct",
      "private resumed input",
    ]]);
    assert.equal(reopenedStore.eventsAfter(0).filter(
      ({ event }) => event.type === "checkpoint.created",
    ).length, 1);
    assert.deepEqual(eventTypes(reopenedStore).slice(-2), [
      "session.recovery-required",
      "session.running",
    ]);
    const events = reopenedStore.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(events.map(validateControlEvent), events);
    assert.deepEqual(
      events.map(({ sequence }) => sequence),
      events.map((_, index) => index + 1),
    );
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway preserves paused state across a crash during restart recovery", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.close();

    const interruptedStore = await GatewayDurableStore.open(state.root, "session-1");
    await assert.rejects(PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: interruptedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession() {
        throw new Error("SENTINEL_CRASH_DURING_RESTORE");
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    }));
    assert.equal(eventTypes(interruptedStore).at(-1), "session.recovery-required");

    const recoveredStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: recoveredStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "crash-recovery-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });

    const inputRef = await state.privateValues.putInput("private paused input");
    await assert.rejects(reopened.accept(command("input.submit", {
      input_id: "input-after-recovery-crash",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-after-recovery-crash")));
    assert.equal(eventTypes(recoveredStore).at(-1), "session.paused");
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway preserves paused state across restart until explicit resume", async () => {
  const state = await fixture();
  let reopened;
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await state.gateway.close();

    const reopenedStore = await GatewayDurableStore.open(state.root, "session-1");
    const restoredSession = new FakePrimeSession();
    restoredSession.supervisorGeneration = "supervisor-generation-3";
    reopened = await PrimeGateway.open({
      sessionId: "session-1",
      generation: 1,
      authorityId: "authority-1",
      store: reopenedStore,
      privateValues: state.privateValues,
      async createSession() {
        throw new Error("must not create a second Prime root");
      },
      async restoreSession(_identity, onRecovered) {
        await onRecovered({
          transport: recoveryTransport(
            "supervisor-generation-3",
            "paused-reopened-transport",
          ),
          primeCursor: { generation: "prime-events-3", sequence: 12 },
          transcriptSessionId: "transcript-1",
          supervisorGeneration: "supervisor-generation-3",
          sessionStatus: "running",
        });
        return restoredSession;
      },
      async createCheckpoint() {
        throw new Error("checkpoint not expected");
      },
    });

    const inputRef = await state.privateValues.putInput("private paused input");
    await assert.rejects(reopened.accept(command("input.submit", {
      input_id: "input-before-resume",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-before-resume")));
    await reopened.accept(command("session.resume", {
      reason_code: "operator-resume",
    }, "command-resume-after-reopen"));
    await reopened.accept(command("input.submit", {
      input_id: "input-after-resume",
      delivery: "direct",
      content_ref: inputRef,
    }, "command-input-after-resume"));

    assert.deepEqual(eventTypes(reopenedStore).slice(-3), [
      "session.recovery-required",
      "session.paused",
      "session.running",
    ]);
    assert.deepEqual(restoredSession.calls, [
      ["resume", "command-resume-after-reopen"],
      ["input", "input-after-resume", "direct", "private paused input"],
    ]);
    assert.equal(restoredSession.recoveries.length, 1);
  } finally {
    await reopened?.close();
    await state.cleanup();
  }
});

test("gateway maps daemon completion cursor and cancellation to unique terminals", async () => {
  const completed = await fixture();
  try {
    const goalRef = await completed.privateValues.putInput("goal");
    await completed.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    completed.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: {
        type: "goal_update",
        goal: {
          active: false,
          status: "complete",
          tokensUsed: 17,
          timeUsedSeconds: 1,
          continuationsUsed: 1,
        },
      },
      meta: {
        id: "prime-event-1",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 1,
        cursor: { generation: "worker-generation-1", sequence: 1 },
        emittedAt: "2026-08-10T03:30:00Z",
      },
    });
    completed.session.emit({
      type: "session_closed",
      activeSessionId: "prime-root-1",
      reason: "private-close-body",
    });
    await completed.gateway.settle();
    const events = completed.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(eventTypes(completed.store), [
      "session.created",
      "session.running",
      "goal.updated",
      "budget.reported",
      "session.completed",
    ]);
    assert.deepEqual(completed.store.snapshot().primeCursor, {
      generation: "worker-generation-1",
      sequence: 1,
    });
    assert.deepEqual(validateControlEventStream(events), events);
  } finally {
    await completed.cleanup();
  }

  const cancelled = await fixture();
  try {
    const goalRef = await cancelled.privateValues.putInput("goal");
    await cancelled.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await cancelled.gateway.accept(command("session.cancel", {
      reason_code: "operator-request",
    }, "command-cancel"));
    const events = cancelled.store.eventsAfter(0).map(({ event }) => event);
    assert.deepEqual(eventTypes(cancelled.store), [
      "session.created",
      "session.running",
      "goal.updated",
      "session.cancelled",
    ]);
    assert.deepEqual(validateControlEventStream(events), events);
    assert.deepEqual(cancelled.session.calls, [["cancel", "command-cancel"]]);
  } finally {
    await cancelled.cleanup();
  }
});

test("gateway resolves admitted actions and preserves uncertain transport state", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const identity = state.gateway.nextEventIdentity();
    await state.gateway.emitActionProposal(proposal(
      identity,
      "action-1",
      inputRef,
    ));
    const admission = state.gateway.waitForAdmission("action-1");
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-admit"));
    assert.deepEqual(await admission, {
      resolution: "admitted",
      reasonCode: "authorized",
    });

    const terminal = state.gateway.waitForTerminal("action-1");
    await state.gateway.accept(command("action.resolve", {
      action_id: "action-1",
      resolution: "uncertain",
      reason_code: "transport-uncertain",
      receipt_ref: null,
    }, "command-terminal"));
    assert.deepEqual(await terminal, {
      resolution: "uncertain",
      reasonCode: "transport-uncertain",
    });
    assert.deepEqual(await state.gateway.actionStatus("action-1"), {
      action_id: "action-1",
      status: "uncertain",
      reason_code: "transport-uncertain",
    });
  } finally {
    await state.cleanup();
  }
});

test("gateway serializes concurrently reserved action proposals", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const inputRef = await state.privateValues.putInput("private action input");
    const first = state.gateway.nextEventIdentity();
    const second = state.gateway.nextEventIdentity();
    await Promise.all([
      state.gateway.emitActionProposal(proposal(first, "action-1", inputRef)),
      state.gateway.emitActionProposal(proposal(second, "action-2", inputRef)),
    ]);
    const actions = state.store.eventsAfter(0)
      .map(({ event }) => event)
      .filter((event) => event.type === "action.proposed");
    assert.deepEqual(actions.map((event) => event.payload.action_id), [
      "action-1",
      "action-2",
    ]);
    assert.deepEqual(actions.map((event) => event.sequence), [3, 4]);
  } finally {
    await state.cleanup();
  }
});

test("gateway serializes concurrent command persistence", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    const firstRef = await state.privateValues.putInput("private first");
    const secondRef = await state.privateValues.putInput("private second");
    await Promise.all([
      state.gateway.accept(command("input.submit", {
        input_id: "input-1",
        delivery: "direct",
        content_ref: firstRef,
      }, "command-input-1")),
      state.gateway.accept(command("input.submit", {
        input_id: "input-2",
        delivery: "follow_up",
        content_ref: secondRef,
      }, "command-input-2")),
    ]);
    assert.equal(state.store.snapshot().commandCount, 3);
    assert.deepEqual(state.session.calls, [
      ["input", "input-1", "direct", "private first"],
      ["input", "input-2", "follow_up", "private second"],
    ]);
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects commands incompatible with canonical session state", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    await assert.rejects(state.gateway.accept(command("session.resume", {
      reason_code: "operator-request",
    }, "command-invalid-resume")));
    assert.deepEqual(state.session.calls, []);
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    await assert.rejects(state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-invalid-pause")));
    assert.deepEqual(state.session.calls, [["pause", "command-pause"]]);
  } finally {
    await state.cleanup();
  }
});

test("gateway rejects unknown action resolution and replays failed handling", async () => {
  const state = await fixture();
  try {
    const unknown = command("action.resolve", {
      action_id: "action-unknown",
      resolution: "admitted",
      reason_code: "authorized",
      receipt_ref: null,
    }, "command-unknown-action");
    await assert.rejects(state.gateway.accept(unknown));
    await assert.rejects(state.gateway.accept(structuredClone(unknown)));
    await assert.rejects(state.gateway.actionStatus("action-unknown"));
    assert.equal(state.store.snapshot().commandCount, 1);
  } finally {
    await state.cleanup();
  }
});

test("gateway turns a cursor gap into recovery and resumes only on resync", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.emit({
      type: "session_event",
      activeSessionId: "prime-root-1",
      event: { type: "message_update", text: "SENTINEL_PRIVATE_MESSAGE" },
      meta: {
        id: "prime-event-2",
        protocol: { name: "prime-agent.daemon", version: 7 },
        sequence: 2,
        cursor: { generation: "worker-generation-1", sequence: 2 },
        emittedAt: "2026-08-10T04:00:00Z",
      },
    });
    await state.gateway.settle();
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
    ]);
    state.session.emit({
      type: "session_resynced",
      activeSessionId: "prime-root-1",
      snapshot: { private: "SENTINEL_PRIVATE_SNAPSHOT" },
    });
    await state.gateway.settle();
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
      "session.running",
    ]);
    assert.equal(JSON.stringify(state.store.eventsAfter(0)).includes("SENTINEL"), false);
  } finally {
    await state.cleanup();
  }
});

test("gateway exposes unknown prompt admission as recoverable uncertainty", async () => {
  const state = await fixture();
  try {
    const goalRef = await state.privateValues.putInput("goal");
    await state.gateway.accept(command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: goalRef,
    }, "command-create"));
    state.session.pauseError = new PrimePromptAdmissionUncertainError();
    await state.gateway.accept(command("session.pause", {
      reason_code: "operator-request",
    }, "command-pause"));
    assert.deepEqual(eventTypes(state.store), [
      "session.created",
      "session.running",
      "fault.raised",
      "session.recovery-required",
    ]);
    const fault = state.store.eventsAfter(0).at(-2).event;
    assert.deepEqual(fault.payload, {
      code: "prime-prompt-admission-uncertain",
      recoverable: true,
      evidence_ref: null,
    });
  } finally {
    await state.cleanup();
  }
});
