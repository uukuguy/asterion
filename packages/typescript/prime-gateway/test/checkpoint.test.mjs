import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrimeDaemonClient,
  PrimeCheckpointError,
  PrimeCheckpointManager,
  PrivateValueStore,
} from "../dist/src/index.js";
import { startFakePrimeDaemon } from "./fixtures/fake-prime-daemon.mjs";

const ARTIFACT_EVIDENCE = Object.freeze({
  commit: "a".repeat(40),
  packageName: "@prime-agent/coding-agent",
  packageVersion: "0.7.1",
  protocolVersion: 7,
  schemaRevision: 14,
  schemaId: "protocol-7-schema-14-816309b1cd50",
  fileDigests: Object.freeze({
    "packages/coding-agent/dist/cli.js": "b".repeat(64),
  }),
});

const PRIME_CURSOR = Object.freeze({ generation: "prime-events-1", sequence: 7 });

function hello(overrides = {}) {
  return Object.freeze({
    type: "daemon_hello",
    protocolVersion: 7,
    schemaId: "protocol-7-schema-14-816309b1cd50",
    schemaRevision: 14,
    appVersion: "0.7.1",
    runtimeBuildId: "prime-build-locked",
    supervisorGeneration: "supervisor-generation-1",
    clientId: "prime-client-1",
    serverCapabilities: Object.freeze([
      "attach_snapshot",
      "chunked_snapshot",
      "event_sequence",
      "prompt_admission_cancellation",
      "session_input_admission",
    ]),
    ...overrides,
  });
}

function rootSession(overrides = {}) {
  return {
    activeSessionId: "prime-root-1",
    sessionId: "transcript-1",
    sessionFile: "/private/sessions/root.jsonl",
    cwd: "/private/workspace",
    config: { provider: "private-provider", model: "private-model" },
    runtimeMetadata: { kind: "top-level", createdAt: 1 },
    queue: { actions: { actions: [] }, nextTurn: [] },
    shouldResume: true,
    wasStreaming: false,
    wasCompacting: false,
    wasBashRunning: false,
    hadRunningRlmChildren: false,
    wasRetrying: false,
    hadAcceptedPromptInFlight: false,
    ...overrides,
  };
}

function childSession(overrides = {}) {
  return rootSession({
    activeSessionId: "prime-child-1",
    sessionId: "transcript-child-1",
    sessionFile: "/private/sessions/child.jsonl",
    runtimeMetadata: {
      kind: "subagent",
      createdAt: 2,
      parentActiveSessionId: "prime-root-1",
      prompt: "SENTINEL_PRIVATE_CHILD_PROMPT",
    },
    ...overrides,
  });
}

function manifest(sessions = [rootSession(), childSession()]) {
  return {
    formatVersion: 1,
    createdAt: "2026-08-10T04:00:00.000Z",
    sessions,
  };
}

function coherentAttach(overrides = {}) {
  return {
    protocol: { name: "prime-agent.daemon", version: 7 },
    activeSessionId: "prime-root-1",
    snapshot: {
      activeSessionId: "prime-root-1",
      summary: {
        activeSessionId: "prime-root-1",
        sessionId: "transcript-1",
        messageCount: 0,
      },
      state: { goal: { status: "active" } },
      messages: [],
      lastEventSequence: 7,
      lastEventCursor: PRIME_CURSOR,
    },
    replay: { status: "complete", toSequence: 7 },
    lastEventSequence: 7,
    lastEventCursor: PRIME_CURSOR,
    ...overrides,
  };
}

class FakeCheckpointTransport {
  constructor({ greeting = hello(), updateManifest = manifest(), attach = coherentAttach() } = {}) {
    this.hello = greeting;
    this.updateManifest = updateManifest;
    this.attachData = attach;
    this.commands = [];
    this.acknowledgements = [];
  }

  subscribe() {
    return () => undefined;
  }

  acknowledgeResult(commandId) {
    this.acknowledgements.push(commandId);
    return true;
  }

  async request(command, commandId, timeoutMs) {
    this.commands.push({ command, commandId, timeoutMs });
    if (command.type === "attach") {
      return {
        id: commandId,
        type: "response",
        command: "attach",
        success: true,
        data: this.attachData,
      };
    }
    return {
      id: commandId,
      type: "response",
      command: command.type,
      success: true,
      data: { accepted: true },
    };
  }

  async requestDeferred(command, commandId, timeoutMs) {
    this.commands.push({ command, commandId, timeoutMs });
    return {
      response: {
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: this.updateManifest,
      },
      acknowledge: () => {
        this.acknowledgements.push(commandId);
        return true;
      },
    };
  }
}

class FakeCheckpointRuntime {
  constructor(relaunched) {
    this.relaunched = relaunched;
    this.stopCount = 0;
    this.relaunchCount = 0;
    this.relaunchError = undefined;
  }

  async stop() {
    this.stopCount += 1;
  }

  async relaunch() {
    this.relaunchCount += 1;
    if (this.relaunchError !== undefined) {
      throw this.relaunchError;
    }
    return this.relaunched;
  }
}

async function fixture({
  initial = new FakeCheckpointTransport(),
  relaunched = new FakeCheckpointTransport(),
  privateValues,
  privateValueOptions,
  onStage,
} = {}) {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-checkpoint-"));
  const root = join(parent, "gateway");
  const values = privateValues ?? await PrivateValueStore.open(
    root,
    privateValueOptions,
  );
  const runtime = new FakeCheckpointRuntime(relaunched);
  const recovered = [];
  const manager = await PrimeCheckpointManager.open({
    sessionId: "session-1",
    asterionGeneration: 1,
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
    artifactEvidence: ARTIFACT_EVIDENCE,
    expectedRuntimeBuildId: "prime-build-locked",
    privateValues: values,
    transport: initial,
    runtime,
    primeCursor: PRIME_CURSOR,
    onStage,
  });
  return {
    parent,
    root,
    values,
    initial,
    relaunched,
    runtime,
    manager,
    recovered,
    async create(checkpointId = "checkpoint-1", coveredSequence = 8) {
      return manager.create(checkpointId, coveredSequence, async () => {
        recovered.push([checkpointId, coveredSequence]);
      });
    },
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function capsulePath(root, reference) {
  return join(root, "private", "values", `${reference.slice("private:".length)}.value`);
}

test("checkpoint restarts the dedicated daemon and reattaches exact identity", async () => {
  const state = await fixture();
  try {
    const created = await state.create();

    assert.equal(created.checkpointId, "checkpoint-1");
    assert.equal(created.coveredSequence, 8);
    assert.equal(state.runtime.stopCount, 1);
    assert.equal(state.runtime.relaunchCount, 1);
    assert.deepEqual(state.recovered, [["checkpoint-1", 8]]);
    assert.deepEqual(state.initial.commands.map(({ command }) => command.type), [
      "wait_for_idle",
      "prepare_update_restart",
    ]);
    assert.deepEqual(state.relaunched.commands.map(({ command }) => command.type), ["attach"]);
    assert.equal(state.relaunched.commands[0].command.activeSessionId, "prime-root-1");
    assert.deepEqual(state.relaunched.commands[0].command.resumeCursor, {
      activeSessionId: "prime-root-1",
      ...PRIME_CURSOR,
    });
    assert.deepEqual(state.initial.acknowledgements, []);

    const capsuleBytes = await state.values.readCapsule(created.storageRef);
    assert.equal(createHash("sha256").update(capsuleBytes).digest("hex"), created.capsuleDigest);
    const capsule = JSON.parse(capsuleBytes);
    assert.equal(capsule.format, "asterion.prime-capsule/v1");
    assert.equal(capsule.activeSessionId, "prime-root-1");
    assert.equal(capsule.transcriptSessionId, "transcript-1");
    assert.deepEqual(capsule.primeCursor, PRIME_CURSOR);
    assert.equal(capsule.asterionGeneration, 1);
    assert.equal(capsule.asterionSequence, 8);
    assert.equal(JSON.stringify(created).includes("/private/"), false);
    assert.equal(JSON.stringify(created).includes("SENTINEL"), false);
    assert.equal(created.acknowledge(), true);
    assert.deepEqual(state.relaunched.acknowledgements, [
      "session-1-checkpoint-checkpoint-1-prepare",
    ]);
  } finally {
    await state.cleanup();
  }
});

test("checkpoint exposes only fixed lifecycle stages to its private observer", async () => {
  const stages = [];
  const state = await fixture({ onStage: (stage) => stages.push(stage) });
  try {
    await state.create();
    assert.deepEqual(stages, ["idle", "prepare", "stop", "relaunch", "attach", "recover", "capsule"]);
  } finally {
    await state.cleanup();
  }
});

test("checkpoint caps all daemon requests at its action deadline", async () => {
  const state = await fixture();
  try {
    await state.manager.create("checkpoint-deadline", 8, async () => undefined, 4_000);
    assert.deepEqual(
      state.initial.commands.map((entry) => entry.timeoutMs),
      [4_000, 4_000],
    );
    assert.deepEqual(
      state.relaunched.commands.map((entry) => entry.timeoutMs),
      [4_000],
    );
  } finally {
    await state.cleanup();
  }
});

test("checkpoint recovery exposes the relaunched transport and validated status", async () => {
  const state = await fixture();
  try {
    let recovery;
    await state.manager.create("checkpoint-recovery", 8, async (value) => {
      recovery = value;
    });

    assert.equal(recovery.transport, state.relaunched);
    assert.equal(recovery.transcriptSessionId, "transcript-1");
    assert.equal(recovery.supervisorGeneration, "supervisor-generation-1");
    assert.equal(recovery.sessionStatus, "running");
    assert.deepEqual(recovery.primeCursor, PRIME_CURSOR);
  } finally {
    await state.cleanup();
  }
});

test("checkpoint reports paused only from a validated paused snapshot", async () => {
  const pausedAttach = coherentAttach({
    snapshot: {
      ...coherentAttach().snapshot,
      state: { goal: { status: "paused" } },
    },
  });
  const state = await fixture({
    relaunched: new FakeCheckpointTransport({ attach: pausedAttach }),
  });
  try {
    let recovery;
    await state.manager.create("checkpoint-paused", 8, async (value) => {
      recovery = value;
    });
    assert.equal(recovery.sessionStatus, "paused");
  } finally {
    await state.cleanup();
  }

  const invalid = coherentAttach({
    snapshot: {
      ...coherentAttach().snapshot,
      state: { goal: { status: "complete" } },
    },
  });
  const rejected = await fixture({
    relaunched: new FakeCheckpointTransport({ attach: invalid }),
  });
  try {
    await assert.rejects(rejected.create(), PrimeCheckpointError);
  } finally {
    await rejected.cleanup();
  }
});

test("checkpoint maps a quiescent Prime root with no goal to paused", async () => {
  const idleAttach = coherentAttach({
    snapshot: {
      ...coherentAttach().snapshot,
      state: { goal: { status: "idle" } },
    },
  });
  const state = await fixture({
    relaunched: new FakeCheckpointTransport({ attach: idleAttach }),
  });
  try {
    let recovery;
    await state.manager.create("checkpoint-idle", 8, async (value) => {
      recovery = value;
    });
    assert.equal(recovery.sessionStatus, "paused");
  } finally {
    await state.cleanup();
  }
});

test("checkpoint rejects duplicate missing and wrong root dispositions", async () => {
  const cases = [
    ["duplicate", manifest([rootSession(), rootSession({ sessionFile: "/private/sessions/root-2.jsonl" })])],
    ["missing", manifest([childSession()])],
    ["wrong transcript", manifest([rootSession({ sessionId: "transcript-wrong" })])],
    ["unrelated child", manifest([rootSession(), childSession({ runtimeMetadata: { kind: "subagent", createdAt: 2, parentActiveSessionId: "prime-other" } })])],
  ];
  for (const [name, updateManifest] of cases) {
    const initial = new FakeCheckpointTransport({ updateManifest });
    const state = await fixture({ initial });
    try {
      await assert.rejects(state.create(), PrimeCheckpointError, name);
      assert.equal(state.runtime.stopCount, 0);
      assert.deepEqual(initial.acknowledgements, []);
    } finally {
      await state.cleanup();
    }
  }
});

test("checkpoint rejects schema build and restored identity drift", async () => {
  const cases = [
    ["schema", hello({ schemaRevision: 15 })],
    ["build", hello({ runtimeBuildId: "prime-build-other" })],
  ];
  for (const [name, greeting] of cases) {
    const state = await fixture({ relaunched: new FakeCheckpointTransport({ greeting }) });
    try {
      await assert.rejects(state.create(), PrimeCheckpointError, name);
      assert.deepEqual(state.initial.acknowledgements, []);
    } finally {
      await state.cleanup();
    }
  }

  const wrongIdentity = coherentAttach({ activeSessionId: "prime-root-other" });
  const state = await fixture({
    relaunched: new FakeCheckpointTransport({ attach: wrongIdentity }),
  });
  try {
    await assert.rejects(state.create(), PrimeCheckpointError);
    assert.deepEqual(state.initial.acknowledgements, []);
  } finally {
    await state.cleanup();
  }
});

test("checkpoint accepts unavailable replay only with one coherent snapshot", async () => {
  const valid = coherentAttach({ replay: { status: "unavailable", toSequence: 7 } });
  const accepted = await fixture({
    relaunched: new FakeCheckpointTransport({ attach: valid }),
  });
  try {
    await accepted.create();
  } finally {
    await accepted.cleanup();
  }

  for (const attach of [
    coherentAttach({ replay: { status: "partial", toSequence: 7 } }),
    coherentAttach({
      replay: { status: "unavailable", toSequence: 7 },
      snapshot: {
        ...coherentAttach().snapshot,
        summary: { ...coherentAttach().snapshot.summary, sessionId: "transcript-wrong" },
      },
    }),
    coherentAttach({
      replay: { status: "unavailable", toSequence: 7 },
      snapshot: undefined,
    }),
  ]) {
    const rejected = await fixture({
      relaunched: new FakeCheckpointTransport({ attach }),
    });
    try {
      await assert.rejects(rejected.create(), PrimeCheckpointError);
      assert.deepEqual(rejected.initial.acknowledgements, []);
    } finally {
      await rejected.cleanup();
    }
  }
});

test("checkpoint leaves the prepare result unacknowledged across crash windows", async () => {
  const beforeManifest = await fixture();
  try {
    beforeManifest.runtime.relaunchError = new Error("SENTINEL_RELAUNCH_FAILURE");
    await assert.rejects(beforeManifest.create(), (error) => {
      assert.ok(error instanceof PrimeCheckpointError);
      assert.equal(error.message.includes("SENTINEL"), false);
      return true;
    });
    assert.equal(beforeManifest.runtime.stopCount, 1);
    assert.deepEqual(beforeManifest.initial.acknowledgements, []);
  } finally {
    await beforeManifest.cleanup();
  }

  const afterWorkerStop = await fixture();
  try {
    await assert.rejects(
      afterWorkerStop.manager.create("checkpoint-1", 8, async () => {
        throw new Error("SENTINEL_CRASH_AFTER_WORKER_STOP");
      }),
      PrimeCheckpointError,
    );
    assert.equal(afterWorkerStop.runtime.relaunchCount, 1);
    assert.deepEqual(afterWorkerStop.initial.acknowledgements, []);
  } finally {
    await afterWorkerStop.cleanup();
  }

  const beforeCapsulePersistence = await fixture({
    privateValueOptions: {
      faultInjector(stage) {
        if (stage === "before_write") {
          throw new Error("SENTINEL_CAPSULE_WRITE_CRASH");
        }
      },
    },
  });
  try {
    await assert.rejects(beforeCapsulePersistence.create(), PrimeCheckpointError);
    assert.equal(beforeCapsulePersistence.runtime.relaunchCount, 1);
    assert.deepEqual(beforeCapsulePersistence.recovered, [["checkpoint-1", 8]]);
    assert.deepEqual(beforeCapsulePersistence.initial.acknowledgements, []);
  } finally {
    await beforeCapsulePersistence.cleanup();
  }
});

test("checkpoint create is idempotent and restore verifies digest and capsule path", async () => {
  const state = await fixture();
  try {
    const first = await state.create();
    const second = await state.create();
    assert.deepEqual(second, first);
    assert.equal(state.runtime.relaunchCount, 1);

    const restoredTransport = new FakeCheckpointTransport();
    state.runtime.relaunched = restoredTransport;
    const restored = await state.manager.restore(
      first.storageRef,
      first.capsuleDigest,
      async () => state.recovered.push(["restore", 8]),
    );
    assert.equal(restored.coveredSequence, 8);
    assert.equal(state.runtime.relaunchCount, 2);
    assert.deepEqual(state.recovered.at(-1), ["restore", 8]);

    const restartTransport = new FakeCheckpointTransport();
    const restartRuntime = new FakeCheckpointRuntime(restartTransport);
    const restartManager = await PrimeCheckpointManager.open({
      sessionId: "session-1",
      asterionGeneration: 1,
      activeSessionId: "prime-root-1",
      artifactEvidence: ARTIFACT_EVIDENCE,
      expectedRuntimeBuildId: "prime-build-locked",
      privateValues: state.values,
      transport: new FakeCheckpointTransport(),
      runtime: restartRuntime,
      primeCursor: PRIME_CURSOR,
    });
    const inferred = await restartManager.restore(
      first.storageRef,
      first.capsuleDigest,
    );
    assert.equal(inferred.coveredSequence, 8);
    assert.equal(restartTransport.commands[0].command.activeSessionId, "prime-root-1");

    await assert.rejects(
      state.manager.restore(first.storageRef, "f".repeat(64)),
      PrimeCheckpointError,
    );

    const target = join(state.parent, "capsule-target");
    await rm(capsulePath(state.root, first.storageRef));
    await symlink(target, capsulePath(state.root, first.storageRef));
    await assert.rejects(
      state.manager.restore(first.storageRef, first.capsuleDigest),
      PrimeCheckpointError,
    );
  } finally {
    await state.cleanup();
  }
});

test("checkpoint acknowledges through a distinct relaunched real client", async () => {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-checkpoint-wire-"));
  const daemon = await startFakePrimeDaemon({
    buildId: "prime-build-locked",
    responseData: {
      prepare_update_restart: manifest(),
      attach: coherentAttach(),
    },
  });
  const initialClient = new PrimeDaemonClient({ clientId: "checkpoint-wire-client" });
  const recoveredClient = new PrimeDaemonClient({ clientId: "checkpoint-wire-client" });
  try {
    await initialClient.connect(daemon.socketPath);
    const manager = await PrimeCheckpointManager.open({
      sessionId: "session-1",
      asterionGeneration: 1,
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      artifactEvidence: ARTIFACT_EVIDENCE,
      expectedRuntimeBuildId: "prime-build-locked",
      privateValues: await PrivateValueStore.open(join(parent, "gateway")),
      transport: initialClient,
      runtime: {
        async stop() {
          initialClient.close();
        },
        async relaunch() {
          await recoveredClient.connect(daemon.socketPath);
          return recoveredClient;
        },
      },
      primeCursor: PRIME_CURSOR,
    });

    const created = await manager.create("checkpoint-wire", 8);
    assert.equal(created.acknowledge(), true);
    await daemon.waitForAcknowledgement(
      "session-1-checkpoint-checkpoint-wire-prepare",
    );
    assert.equal(created.coveredSequence, 8);
    assert.equal(daemon.prepareCount, 1);
    assert.equal(daemon.connectionCount, 2);
    assert.equal(daemon.attachedActiveSessionId, "prime-root-1");
  } finally {
    initialClient.close();
    recoveredClient.close();
    await daemon.close();
    await rm(parent, { force: true, recursive: true });
  }
});
