import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { chmod, mkdir, mkdtemp, readFile, readdir, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrimeBoundPrivateInputs,
  PrimeGatewaySidecar,
  PRIME_GATEWAY_IPC_PROTOCOL,
  loadPrimeEcosystemModule,
  boundedRlmActionBudget,
  mayAdmitProviderOwnedRlmDeletion,
  servePrimeGatewaySidecar,
  validatePrimeSidecarDescriptor,
} from "../dist/src/main.js";
import { loadPrimeClientModule } from "../dist/src/main.js";
import { PRIME_ECOSYSTEM_LOCK_CONTRACT } from "../dist/src/ecosystem.js";
import {
  GatewayDurableStore,
  PrimeEcosystemAdapter,
  PrimeGateway,
  PrivateValueStore,
} from "../dist/src/index.js";

function sidecarDescriptor(operationHost = {
  socketPath: "/tmp/asterion-operation-host.sock",
  token: "a".repeat(64),
}) {
  return {
    agentDir: "/tmp/agent",
    artifactLockPath: "/tmp/artifact-lock.json",
    authorityId: "authority-1",
    authorityRevision: 1,
    expectedRuntimeBuildId: "build-1",
    gatewayRoot: "/tmp/gateway",
    generation: 1,
    maxContinuations: 1,
    maxControllerTokens: 100,
    maxTurns: 1,
    model: "provider-free-model",
    operationHost,
    portfolio: [{
      kind: "application",
      provider_id: "example.provider",
      application_id: "alpha",
      version: "1.0.0",
      runtime_id: "fake.runtime",
    }],
    primeSocketPath: "/tmp/prime.sock",
    primeSourceRoot: "/tmp/prime-source",
    provider: "provider-free",
    probeReady: false,
    recoveryReadOnly: false,
    remainingBudget: {
      controller_tokens: 0,
      application_tokens: 100,
      child_tokens: 100,
      aggregate_tokens: 200,
      cost_micros: 0,
      deadline_ms: 1_000,
    },
    rlmMaxChildren: 0,
    rlmMaxDepth: 0,
    sessionDir: "/tmp/session",
    sessionId: "session-1",
    skillPath: "/tmp/skill.md",
    timeoutMs: 100,
    workspace: "/tmp/workspace",
  };
}

test("production descriptor requires one exact private operation host", () => {
  const valid = validatePrimeSidecarDescriptor(sidecarDescriptor());
  assert.deepEqual(valid.operationHost, {
    socketPath: "/tmp/asterion-operation-host.sock",
    token: "a".repeat(64),
  });
  assert.equal(Object.isFrozen(valid.operationHost), true);

  const missing = sidecarDescriptor();
  delete missing.operationHost;
  for (const descriptor of [
    missing,
    sidecarDescriptor({ socketPath: "relative.sock", token: "a".repeat(64) }),
    sidecarDescriptor({ socketPath: "/tmp/host.sock", token: "SENTINEL-TOKEN" }),
    sidecarDescriptor({ socketPath: "/tmp/host.sock", token: ["a".repeat(64)] }),
    sidecarDescriptor({ socketPath: "/tmp/host.sock", token: "a".repeat(64), extra: true }),
  ]) {
    assert.throws(() => validatePrimeSidecarDescriptor(descriptor));
  }
});

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

function contextCommand(operation = "session.tree.read", payload = {
  continuation_id: "continuation-1",
}) {
  return {
    protocol: "asterion.session-context/v1",
    command_id: "context-command-1",
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: "context-operation-1",
    operation,
    payload,
  };
}

function contextReceipt(commandValue = contextCommand()) {
  const succeeded = [
    "session.attachment.bind",
    "session.tree.read",
  ].includes(commandValue.operation);
  const result = commandValue.operation === "session.attachment.bind"
    ? {
      input_id: commandValue.payload.input_id,
      attachment_id: commandValue.payload.attachment_id,
      media_type: commandValue.payload.media_type,
      sha256: commandValue.payload.sha256,
      size: commandValue.payload.size,
    }
    : commandValue.operation === "session.tree.read" ? {
      continuation_id: "continuation-1",
      nodes: [],
      leaf_id: null,
    } : null;
  return {
    protocol: "asterion.session-context/v1",
    receipt_id: "context-receipt-1",
    command_id: commandValue.command_id,
    session_id: commandValue.session_id,
    generation: commandValue.generation,
    operation: commandValue.operation,
    status: succeeded ? "succeeded" : "failed",
    reason_code: succeeded ? "session-context-succeeded" : "provider-not-ready",
    payload: {
      evidence_ref: null,
      result,
    },
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

async function ecosystemFrameFixture() {
  const parent = await realpath(await mkdtemp(join(tmpdir(), "asterion-prime-sidecar-ecosystem-")));
  const portfolioDigest = createHash("sha256").update("sidecar-portfolio").digest("hex");
  const projectionRoot = join(parent, portfolioDigest);
  await mkdir(projectionRoot, { mode: 0o700 });
  await chmod(projectionRoot, 0o700);
  return {
    frame: {
      artifactLockDigest: "34374afe3bbef57b6690764a174a22f2fbd3952e26cfac788c955a363a54274d",
      authorityDigest: createHash("sha256").update("authority-1@7").digest("hex"),
      effectId: `ecosystem:sidecar:${portfolioDigest.slice(0, 32)}`,
      features: [],
      format: "asterion.prime-ecosystem-frame/v1",
      limits: { deadlineMs: 30_000, maxBytes: 8 * 1024 * 1024, maxEntries: 4096, maxProcesses: 1 },
      mcpCredentialLeaseId: "mcp-lease:SIDECAR_PRIVATE_LEASE",
      moduleLockDigest: "4cee1b9e8a1292e92232f2cafe0872988658a27680bece3755f710ac1bad5dd2",
      portfolioDigest,
      projectionRoot,
      registrations: [],
      resources: [],
    },
    gatewayRoot: join(parent, "gateway"),
    async cleanup() { await rm(parent, { recursive: true, force: true }); },
  };
}

function ecosystemReceipt(frame) {
  return {
    authorityDigest: frame.authorityDigest,
    featureIds: [],
    lifecycleCount: 0,
    mcpCount: 0,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: 0,
    portfolioDigest: frame.portfolioDigest,
    providerOperations: 0,
    registrationCount: 0,
    resourceCount: 0,
    status: "succeeded",
  };
}

test("main resolves the exact ecosystem lock contract before importing its bundle", async () => {
  const resources = new URL("../resources/", import.meta.url);
  const binding = await loadPrimeEcosystemModule({
    artifactLockPath: await realpath(new URL("prime-artifact-lock.json", resources)),
    bundlePath: await realpath(new URL("prime-ecosystem-module.mjs", resources)),
    moduleLockPath: await realpath(new URL("prime-ecosystem-module-lock.json", resources)),
  });

  assert.deepEqual(binding.lock, PRIME_ECOSYSTEM_LOCK_CONTRACT);
  assert.equal(typeof binding.module.activate, "function");

  const temporary = await realpath(
    await mkdtemp(join(tmpdir(), "asterion-prime-ecosystem-lock-")),
  );
  try {
    const paths = {
      artifactLockPath: join(temporary, "prime-artifact-lock.json"),
      bundlePath: join(temporary, "prime-ecosystem-module.mjs"),
      moduleLockPath: join(temporary, "prime-ecosystem-module-lock.json"),
    };
    await Promise.all([
      writeFile(
        paths.artifactLockPath,
        await readFile(new URL("prime-artifact-lock.json", resources)),
        { mode: 0o600 },
      ),
      writeFile(
        paths.bundlePath,
        "SENTINEL_PRIVATE_BUNDLE_DRIFT\n",
        { mode: 0o600 },
      ),
      writeFile(
        paths.moduleLockPath,
        await readFile(new URL("prime-ecosystem-module-lock.json", resources)),
        { mode: 0o600 },
      ),
    ]);
    await assert.rejects(
      loadPrimeEcosystemModule(paths),
      (error) =>
        error.message === "Prime gateway operation failed" &&
        !error.message.includes("SENTINEL_PRIVATE_BUNDLE_DRIFT") &&
        !error.message.includes(temporary),
    );
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("native RLM actions reserve a bounded slice and use the unexpired child deadline", () => {
  const budget = boundedRlmActionBudget({
    controller_tokens: 50_000,
    application_tokens: 50_000,
    child_tokens: 50_000,
    aggregate_tokens: 150_000,
    cost_micros: 500_000,
    deadline_ms: 600_000,
  }, 1_025_000, 1_000_000);

  assert.equal(budget.deadline_ms, 25_000);
  assert.equal(budget.controller_tokens, 10_000);
  assert.equal(budget.application_tokens, 10_000);
  assert.equal(budget.child_tokens, 10_000);
  assert.equal(budget.aggregate_tokens, 30_000);
  assert.equal(budget.cost_micros, 100_000);
});

test("native RLM deletion is provider-owned only for one started, non-deleted child", () => {
  const started = [{
    type: "rlm.child.started",
    child_id: "child-1",
    native_identity_digest: "a".repeat(64),
  }];

  assert.equal(mayAdmitProviderOwnedRlmDeletion(started, "child-1"), true);
  assert.equal(mayAdmitProviderOwnedRlmDeletion([], "child-1"), false);
  assert.equal(mayAdmitProviderOwnedRlmDeletion([
    ...started,
    { type: "rlm.child.terminal", child_id: "child-1", status: "completed" },
    { type: "rlm.child.deleted", child_id: "child-1" },
  ], "child-1"), false);
});

test("main rejects a client module whose identity is not the checked-in lock", async () => {
  const resources = new URL("../resources/", import.meta.url);
  await assert.rejects(
    loadPrimeClientModule({
      artifactLockPath: await realpath(new URL("prime-artifact-lock.json", resources)),
      bundlePath: await realpath(new URL("prime-client-module-lock.json", resources)),
      moduleLockPath: await realpath(new URL("prime-client-module-lock.json", resources)),
    }),
    (error) => error.message === "Prime gateway operation failed",
  );
});

class FakePrivateValues {
  constructor() {
    this.inputs = [];
    this.results = [];
    this.attachments = [];
    this.bindings = new Map();
  }

  async putInput(value) {
    this.inputs.push(value);
    return `private:00000000-0000-4000-8000-${String(this.inputs.length).padStart(12, "0")}`;
  }

  async readInput(reference) {
    const index = Number(reference.split("-").at(-1));
    const value = this.inputs[index - 1];
    if (value === undefined) {
      throw new Error("missing private input");
    }
    return value;
  }

  async bindInputReference(commandId, sourceRef, value) {
    const key = `input:${commandId}:${sourceRef}`;
    const existing = this.bindings.get(key);
    if (existing !== undefined) {
      if (existing.value !== value) {
        throw new Error("SENTINEL_CONFLICTING_PRIVATE_BODY");
      }
      return existing.privateRef;
    }
    const privateRef = await this.putInput(value);
    this.bindings.set(key, { privateRef, sourceRef, value });
    return privateRef;
  }

  async bindResultReference(commandId, actionId, sourceRef, value) {
    const key = `result:${commandId}:${actionId}:${sourceRef}`;
    const existing = this.bindings.get(key);
    if (existing !== undefined) {
      if (JSON.stringify(existing.value) !== JSON.stringify(value)) {
        throw new Error("SENTINEL_CONFLICTING_PRIVATE_RESULT");
      }
      return existing.privateRef;
    }
    this.results.push(value);
    const privateRef = `private:11111111-1111-4111-8111-${String(this.results.length).padStart(12, "0")}`;
    this.bindings.set(key, { privateRef, sourceRef, value });
    return privateRef;
  }

  async bindAttachment(metadata, body) {
    this.attachments.push({ metadata, body: Buffer.from(body) });
    return `private:22222222-2222-4222-8222-${String(this.attachments.length).padStart(12, "0")}`;
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
    this.clientCursorRequests = [];
    this.clientObservations = [];
    this.contextExecutions = [];
    this.contextCancellations = [];
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

  clientObservationsAfterCursor(cursor) {
    this.clientCursorRequests.push(cursor);
    if (!this.knownGenerations.has(cursor.generation)) {
      throw new Error("unknown generation");
    }
    return this.clientObservations.filter((item) =>
      item.generation === cursor.generation && item.source_sequence > cursor.sequence
    );
  }

  async close() {
    this.closed += 1;
  }

  async executeSessionContext(commandValue, preparePrivate) {
    await preparePrivate();
    this.contextExecutions.push(commandValue);
    return contextReceipt(commandValue);
  }

  async cancelSessionContext(commandId) {
    this.contextCancellations.push(commandId);
  }
}

class FakePrimeSession {
  constructor(sessionPath = "/private/sessions/transcript-1.jsonl") {
    this.activeSessionId = "prime-root-1";
    this.transcriptSessionId = "transcript-1";
    this.continuationId = "continuation-1";
    this.sessionPath = sessionPath;
    this.supervisorGeneration = "supervisor-generation-1";
    this.calls = [];
    this.listener = undefined;
  }

  subscribe(listener) {
    this.listener = listener;
    return () => {
      this.listener = undefined;
    };
  }

  async submitInput(inputId, delivery, body, attachments = []) {
    this.calls.push(attachments.length === 0
      ? ["input", inputId, delivery, body]
      : ["input", inputId, delivery, body, attachments]);
    return { acknowledge: () => true };
  }

  acknowledgeInput() {
    return true;
  }

  async pause() {}

  async resume() {}

  async attach() {}

  async detach() {}

  async cancel() {}

  adoptRecovery() {}

  acknowledgeCheckpoint() {
    return true;
  }
}

function createSidecar(options = {}) {
  const gateway = options.gateway ?? new FakeGateway(options.gatewayOptions);
  if (options.rlmLifecycle !== undefined) {
    gateway.rlmLifecycle = () => options.rlmLifecycle;
  }
  const privateValues = options.privateValues ?? new FakePrivateValues();
  return {
    gateway,
    privateValues,
    sidecar: new PrimeGatewaySidecar({
      currentGeneration: options.currentGeneration ?? gateway.currentGeneration ?? 1,
      sessionId: "session-1",
      gateway,
      privateValues,
    }),
  };
}

test("private ecosystem activation reaches the injected adapter and projects the exact receipt", async () => {
  const state = await ecosystemFrameFixture();
  try {
    const gateway = new FakeGateway();
    const store = await GatewayDurableStore.open(state.gatewayRoot, "session-1");
    const module = {
      calls: 0,
      async activate(frame) {
        this.calls += 1;
        return ecosystemReceipt(frame);
      },
    };
    const adapter = new PrimeEcosystemAdapter({
      lock: PRIME_ECOSYSTEM_LOCK_CONTRACT,
      store,
      module,
    });
    gateway.activateEcosystem = (frame) => adapter.activate(frame);
    const { sidecar } = createSidecar({ gateway });

    const response = await sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "ecosystem-request-1",
      type: "ecosystem_activate",
      frame: state.frame,
    });

    assert.deepEqual(response, {
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "ecosystem-request-1",
      type: "ecosystem_receipt",
      receipt: ecosystemReceipt(state.frame),
    });
    assert.equal(Object.keys(response.receipt).length, 12);
    assert.equal(JSON.stringify(response).includes(state.frame.projectionRoot), false);
    assert.equal(JSON.stringify(response).includes(state.frame.mcpCredentialLeaseId), false);
    assert.equal(module.calls, 1);
    assert.notEqual(store.ecosystemEffectResult(state.frame.effectId), undefined);
    assert.equal(JSON.stringify(response).includes(
      store.ecosystemEffectBinding(state.frame.effectId).frameDigest,
    ), false);
  } finally {
    await state.cleanup();
  }
});

test("private ecosystem activation rejects envelope and frame drift before adapter dispatch", async () => {
  const state = await ecosystemFrameFixture();
  try {
    const gateway = new FakeGateway();
    gateway.ecosystemCalls = 0;
    gateway.activateEcosystem = async (frame) => {
      gateway.ecosystemCalls += 1;
      return ecosystemReceipt(frame);
    };
    const { sidecar } = createSidecar({ gateway });
    for (const request of [
      {
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: "ecosystem-request-extra",
        type: "ecosystem_activate",
        frame: state.frame,
        body: "SENTINEL_PRIVATE_BODY",
      },
      {
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: "ecosystem-frame-extra",
        type: "ecosystem_activate",
        frame: { ...state.frame, body: "SENTINEL_PRIVATE_BODY" },
      },
    ]) {
      assert.deepEqual(await sidecar.handleEnvelope(request), {
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: request.id,
        type: "error",
        code: "prime-gateway-sidecar-failed",
      });
    }
    assert.equal(gateway.ecosystemCalls, 0);
  } finally {
    await state.cleanup();
  }
});

async function createRealSidecarFixture() {
  const fixtureRoot = await temporaryStoreRoot();
  const sessionRoot = join(fixtureRoot.parent, "sessions");
  const sessionPath = join(sessionRoot, "transcript-1.jsonl");
  await mkdir(sessionRoot, { mode: 0o700 });
  await writeFile(sessionPath, "private transcript\n", { mode: 0o600 });
  const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
  store.registerEventGeneration(1);
  const privateValues = await PrivateValueStore.open(fixtureRoot.root, {
    continuationRoot: sessionRoot,
  });
  const session = new FakePrimeSession(sessionPath);
  const createdGoals = [];
  const contextCalls = [];
  const contextCancellations = [];
  const contextExecutor = {
    failures: 0,
    async execute(commandValue) {
      contextCalls.push(commandValue);
      if (this.failures > 0) {
        this.failures -= 1;
        throw new Error("SENTINEL_PRIVATE_PROVIDER_FAILURE");
      }
      return {
        receipt: contextReceipt(commandValue),
        nextBinding: null,
      };
    },
    async cancel(commandId) {
      contextCancellations.push(commandId);
    },
  };
  let tick = 0;
  const gateway = await PrimeGateway.open({
    sessionId: "session-1",
    generation: 1,
    authorityId: "authority-1",
    store,
    privateValues: new PrimeBoundPrivateInputs(privateValues),
    async createSession(goal, bindIdentity) {
      createdGoals.push(goal);
      await bindIdentity({
        activeSessionId: session.activeSessionId,
        transcriptSessionId: session.transcriptSessionId,
        supervisorGeneration: session.supervisorGeneration,
        continuationId: session.continuationId,
        sessionPath: session.sessionPath,
      });
      return session;
    },
    async createCheckpoint() {
      throw new Error("not used by sidecar integration test");
    },
    sessionContext: contextExecutor,
    now() {
      tick += 1;
      return `2026-08-10T03:00:${String(tick).padStart(2, "0")}Z`;
    },
  });
  const sidecar = new PrimeGatewaySidecar({
    currentGeneration: 1,
    privateValues,
    gateway: {
      accept: (value) => gateway.accept(value),
      eventsAfterCursor: (cursor) =>
        store.eventsAfterCursor(cursor).map((receipt) => receipt.event),
      executeSessionContext: (commandValue, preparePrivate) =>
        gateway.executeSessionContext(commandValue, preparePrivate),
      cancelSessionContext: (commandId) =>
        gateway.cancelSessionContext(commandId),
      close: () => gateway.close(),
    },
  });
  return {
    ...fixtureRoot,
    store,
    privateValues,
    gateway,
    session,
    createdGoals,
    contextCalls,
    contextCancellations,
    contextExecutor,
    sidecar,
  };
}

async function durableCommandRecords(root) {
  const recordsRoot = join(root, "public", "records");
  const names = await readdir(recordsRoot);
  const records = await Promise.all(
    names.filter((name) => name.endsWith(".json")).map(async (name) =>
      JSON.parse(await readFile(join(recordsRoot, name), "utf8")),
    ),
  );
  return records
    .filter((record) => record.kind === "command.accepted")
    .map((record) => record.payload.command);
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

test("sidecar returns only closed recorded RLM lifecycle observations", async () => {
  const lifecycle = [
    { type: "rlm.child.started", child_id: "child-1", native_identity_digest: "a".repeat(64) },
    { type: "rlm.child.terminal", child_id: "child-1", status: "completed" },
  ];
  const { sidecar } = createSidecar({ rlmLifecycle: lifecycle });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-lifecycle-1",
    type: "rlm.lifecycle.read",
  });

  assert.deepEqual(response, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-lifecycle-1",
    type: "rlm.lifecycle.batch",
    lifecycle,
  });
});

test("sidecar returns one exact safe RLM admission binding", async () => {
  const binding = {
    action_id: "action-1",
    child_id: "child-1",
    authority_revision: 1,
    depth: 1,
    model_selector_digest: "a".repeat(64),
  };
  const { sidecar } = createSidecar({
    gateway: {
      ...new FakeGateway(),
      rlmBinding: (actionId) => actionId === binding.action_id ? binding : undefined,
    },
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-binding-1",
    type: "rlm.binding.read",
    action_id: "action-1",
  });

  assert.deepEqual(response, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-binding-1",
    type: "rlm.binding.value",
    binding,
  });
});

test("sidecar returns an exact RLM message binding with durable delivery state", async () => {
  const binding = {
    action_id: "message-action-1",
    message_id: "message-1",
    sender_id: "session-1",
    recipient_id: "child-1",
    authority_revision: 1,
    body_digest: "b".repeat(64),
  };
  const { sidecar } = createSidecar({
    gateway: {
      ...new FakeGateway(),
      rlmMessageBinding: (actionId) => actionId === binding.action_id ? binding : undefined,
      rlmMessageDelivered: () => [binding.message_id],
    },
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-message-binding-1",
    type: "rlm.message.binding.read",
    action_id: binding.action_id,
  });

  assert.deepEqual(response, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "rlm-message-binding-1",
    type: "rlm.message.binding.value",
    binding: { ...binding, delivered: true },
  });
});

test("sidecar validates closed session-context execute and cancel envelopes", async () => {
  const { gateway, privateValues, sidecar } = createSidecar();
  const publicCommand = contextCommand();
  const execute = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-execute-1",
    type: "session-context.execute",
    command: publicCommand,
    private: {},
  });

  assert.deepEqual(execute, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-execute-1",
    type: "session-context.receipt",
    receipt: contextReceipt(publicCommand),
  });
  assert.deepEqual(gateway.contextExecutions, [publicCommand]);

  const cancelled = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-cancel-1",
    type: "session-context.cancel",
    command_id: publicCommand.command_id,
  });
  assert.deepEqual(cancelled, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-cancel-1",
    type: "session-context.cancel.accepted",
  });
  assert.deepEqual(gateway.contextCancellations, [publicCommand.command_id]);

  const rejected = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-invalid-1",
    type: "session-context.execute",
    command: publicCommand,
    private: { provider_payload: "SENTINEL_PRIVATE_BODY" },
  });
  assert.equal(rejected.type, "error");
  assert.equal(JSON.stringify(rejected).includes("SENTINEL"), false);
  assert.equal(gateway.contextExecutions.length, 1);
});

test("sidecar decodes verified attachment bytes outside the public command", async () => {
  const { createHash } = await import("node:crypto");
  const { gateway, privateValues, sidecar } = createSidecar();
  const body = Buffer.from("SENTINEL_PRIVATE_ATTACHMENT", "utf8");
  const publicCommand = contextCommand("session.attachment.bind", {
    input_id: "input-1",
    attachment_id: "attachment-1",
    body_ref: "attachment-body-1",
    media_type: "image/png",
    sha256: createHash("sha256").update(body).digest("hex"),
    size: body.byteLength,
  });

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-attachment-1",
    type: "session-context.execute",
    command: publicCommand,
    private: { body_base64: body.toString("base64") },
  });

  assert.equal(response.type, "session-context.receipt");
  assert.deepEqual(gateway.contextExecutions[0], publicCommand);
  assert.deepEqual(
    privateValues.attachments[0].body,
    body,
  );
  assert.deepEqual(privateValues.attachments[0].metadata, {
    sessionId: "session-1",
    inputId: "input-1",
    attachmentId: "attachment-1",
    mediaType: "image/png",
    sha256: publicCommand.payload.sha256,
    size: body.byteLength,
  });
  assert.equal(JSON.stringify(gateway.contextExecutions[0]).includes("SENTINEL"), false);

  const tampered = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "context-attachment-tampered",
    type: "session-context.execute",
    command: publicCommand,
    private: { body_base64: Buffer.from("different").toString("base64") },
  });
  assert.equal(tampered.type, "error");
  assert.equal(gateway.contextExecutions.length, 1);
});

test("sidecar binds context names labels and instructions by opaque public refs", async () => {
  const budget = {
    controller_tokens: 10,
    application_tokens: 0,
    child_tokens: 0,
    aggregate_tokens: 10,
    cost_micros: 10,
    deadline_ms: 1000,
  };
  for (const [operation, payload, privateValue, sourceRef] of [
    [
      "session.name.set",
      { name_ref: "name-ref-1" },
      { name: "SENTINEL_PRIVATE_NAME" },
      "name-ref-1",
    ],
    [
      "session.label.set",
      {
        continuation_id: "continuation-1",
        entry_id: "entry-1",
        label_ref: "label-ref-1",
      },
      { label: "SENTINEL_PRIVATE_LABEL" },
      "label-ref-1",
    ],
    [
      "session.compact",
      {
        continuation_id: "continuation-1",
        instructions_ref: "instructions-ref-1",
        budget,
      },
      { instructions: "SENTINEL_PRIVATE_INSTRUCTIONS" },
      "instructions-ref-1",
    ],
  ]) {
    const { gateway, privateValues, sidecar } = createSidecar();
    const publicCommand = contextCommand(operation, payload);
    const response = await sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: `request-${operation}`,
      type: "session-context.execute",
      command: publicCommand,
      private: privateValue,
    });

    assert.equal(response.type, "session-context.receipt");
    assert.equal(
      await privateValues.readBoundInputReference(sourceRef),
      Object.values(privateValue)[0],
    );
    assert.deepEqual(gateway.contextExecutions, [publicCommand]);
    assert.equal(JSON.stringify(gateway.contextExecutions).includes("SENTINEL"), false);
  }
});

test("sidecar protocol serves execute and cancel concurrently with routed responses", async () => {
  let releaseExecute;
  const executeReleased = new Promise((resolve) => {
    releaseExecute = resolve;
  });
  const gateway = new FakeGateway();
  gateway.executeSessionContext = async (commandValue, preparePrivate) => {
    await preparePrivate();
    await executeReleased;
    return contextReceipt(commandValue);
  };
  gateway.cancelSessionContext = async (commandId) => {
    gateway.contextCancellations.push(commandId);
    releaseExecute();
  };
  const { sidecar } = createSidecar({ gateway });
  async function* lines() {
    yield JSON.stringify({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "execute-request",
      type: "session-context.execute",
      command: contextCommand(),
      private: {},
    });
    yield JSON.stringify({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "cancel-request",
      type: "session-context.cancel",
      command_id: "context-command-1",
    });
  }
  const frames = [];

  await servePrimeGatewaySidecar(sidecar, lines(), async (frame) => {
    frames.push(JSON.parse(frame));
  });

  assert.deepEqual(
    frames.map((frame) => [frame.id, frame.type]),
    [
      ["cancel-request", "session-context.cancel.accepted"],
      ["execute-request", "session-context.receipt"],
    ],
  );
});

test("sidecar service rejects frames above the private attachment bound", async () => {
  const { sidecar } = createSidecar();
  async function* lines() {
    yield JSON.stringify({
      id: "oversized-request",
      padding: "x".repeat(12 * 1024 * 1024),
    });
  }
  const frames = [];

  await servePrimeGatewaySidecar(sidecar, lines(), async (frame) => {
    frames.push(JSON.parse(frame));
  });

  assert.deepEqual(frames, [{
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-invalid",
    type: "error",
    code: "prime-gateway-sidecar-failed",
  }]);
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

test("sidecar replays only the requested body-free client observation suffix", async () => {
  const gateway = new FakeGateway();
  gateway.clientObservations = [
    {
      observation_id: "prime-client-1-1",
      active_session_id: "session-1",
      generation: 1,
      source_sequence: 1,
      emitted_at: "2026-08-10T03:00:01.000Z",
      kind: "message.available",
      payload: {
        content_ref: "private:00000000-0000-4000-8000-000000000001",
        media_type: "text/plain",
        message_id: "message-1",
        role: "assistant",
        sha256: "a".repeat(64),
        size: 7,
      },
    },
    {
      observation_id: "prime-client-1-2",
      active_session_id: "session-1",
      generation: 1,
      source_sequence: 2,
      emitted_at: "2026-08-10T03:00:02.000Z",
      kind: "message.available",
      payload: {
        content_ref: "private:00000000-0000-4000-8000-000000000002",
        media_type: "text/plain",
        message_id: "message-2",
        role: "assistant",
        sha256: "b".repeat(64),
        size: 8,
      },
    },
  ];
  const { sidecar } = createSidecar({ gateway });
  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "client-observations-replay",
    type: "client_observations",
    cursor: { generation: 1, sequence: 1 },
  });
  assert.equal(response.type, "client_observations.batch");
  assert.deepEqual(response.observations, gateway.clientObservations.slice(1));
  assert.deepEqual(gateway.clientCursorRequests, [{ generation: 1, sequence: 1 }]);
  assert.equal(JSON.stringify(response).includes("SENTINEL_BODY"), false);
});

test("sidecar pages a large client observation suffix below the response frame cap", async () => {
  const gateway = new FakeGateway();
  gateway.clientObservations = Array.from({ length: 5_000 }, (_, index) => {
    const sequence = index + 1;
    return {
      observation_id: `prime-client-1-${sequence}`, active_session_id: "session-1", generation: 1,
      source_sequence: sequence, emitted_at: "2026-08-10T03:00:01.000Z", kind: "commands.changed",
      payload: { commands: ["alpha", "beta", "gamma"], revision: sequence },
    };
  });
  const { sidecar } = createSidecar({ gateway });
  const received = [];
  let cursor = { generation: 1, sequence: 0 };
  for (;;) {
    const response = await sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL, id: `client-page-${cursor.sequence}`,
      type: "client_observations", cursor,
    });
    assert.equal(response.type, "client_observations.batch");
    assert.ok(Buffer.byteLength(JSON.stringify(response), "utf8") < 1024 * 1024);
    received.push(...response.observations);
    if (response.next_cursor === null) break;
    assert.equal(response.next_cursor.generation, 1);
    assert.equal(response.next_cursor.sequence, received.length);
    cursor = response.next_cursor;
  }
  assert.deepEqual(received, gateway.clientObservations);
});

test("sidecar rejects one client observation that cannot fit a response frame", async () => {
  const gateway = new FakeGateway();
  gateway.clientObservations = [{
    observation_id: "prime-client-1-1", active_session_id: "session-1", generation: 1,
    source_sequence: 1, emitted_at: "2026-08-10T03:00:01.000Z", kind: "commands.changed",
    payload: { commands: [`a${"a".repeat(950 * 1024)}`], revision: 1 },
  }];
  const { sidecar } = createSidecar({ gateway });
  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL, id: "client-observation-oversize",
    type: "client_observations", cursor: { generation: 1, sequence: 0 },
  });
  assert.equal(response.type, "error");
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

test("real sidecar gateway resolves public refs and persists body-free commands", async () => {
  const fixture = await createRealSidecarFixture();
  try {
    const create = command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: "goal-ref-1",
    });
    const createResponse = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-create",
      type: "command.accept",
      command: create,
      private: { goal: "SENTINEL_RESOLVER_GOAL" },
    });

    assert.equal(createResponse.type, "command.accepted");
    assert.deepEqual(fixture.createdGoals, ["SENTINEL_RESOLVER_GOAL"]);

    const image = Buffer.from("SENTINEL_RESOLVER_PRIVATE_IMAGE");
    const attachment = contextCommand("session.attachment.bind", {
      input_id: "input-1",
      attachment_id: "attachment-1",
      body_ref: "attachment-body-ref-1",
      media_type: "image/png",
      sha256: createHash("sha256").update(image).digest("hex"),
      size: image.byteLength,
    });
    const attachmentResponse = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-attachment",
      type: "session-context.execute",
      command: attachment,
      private: { body_base64: image.toString("base64") },
    });
    assert.equal(attachmentResponse.type, "session-context.receipt");
    assert.equal(
      JSON.stringify(attachmentResponse).includes("SENTINEL_RESOLVER_PRIVATE_IMAGE"),
      false,
    );

    const input = command("input.submit", {
      input_id: "input-1",
      delivery: "direct",
      content_ref: "content-ref-1",
    }, "command-2");
    const inputResponse = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-input",
      type: "command.accept",
      command: input,
      private: { content: "SENTINEL_RESOLVER_INPUT" },
    });

    assert.equal(inputResponse.type, "command.accepted");
    assert.deepEqual(fixture.session.calls.map((call) =>
      call.length === 4
        ? call
        : [
            ...call.slice(0, 4),
            call[4].map(({ body, ...metadata }) => ({
              ...metadata,
              body: Buffer.from(body),
            })),
          ]
    ), [[
      "input",
      "input-1",
      "direct",
      "SENTINEL_RESOLVER_INPUT",
      [{
        attachmentId: "attachment-1",
        mediaType: "image/png",
        sha256: createHash("sha256").update(image).digest("hex"),
        size: image.byteLength,
        body: image,
      }],
    ]]);

    const durableCommands = await durableCommandRecords(fixture.root);
    assert.deepEqual(durableCommands, [create, input]);
    assert.equal(JSON.stringify(durableCommands).includes("SENTINEL_RESOLVER"), false);
    const publicRecords = await Promise.all(
      (await readdir(join(fixture.root, "public", "records")))
        .filter((name) => name.endsWith(".json"))
        .map((name) => readFile(join(fixture.root, "public", "records", name), "utf8")),
    );
    assert.equal(publicRecords.join("").includes("SENTINEL_RESOLVER"), false);
    assert.equal(fixture.store.snapshot().commandCount, 2);

    const conflictingReplay = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-conflict",
      type: "command.accept",
      command: input,
      private: { content: "SENTINEL_DIFFERENT_INPUT" },
    });
    assert.equal(conflictingReplay.type, "error");
    assert.equal(fixture.store.snapshot().commandCount, 2);
    assert.equal(JSON.stringify(conflictingReplay).includes("SENTINEL"), false);
  } finally {
    await fixture.sidecar.close().catch(() => undefined);
    await fixture.cleanup();
  }
});

test("real gateway persists context acceptance and one atomic terminal commit", async () => {
  const fixture = await createRealSidecarFixture();
  try {
    await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-create-context-session",
      type: "command.accept",
      command: command("session.create", {
        system_id: "research.system",
        system_version: "1.0.0",
        goal_id: "goal-1",
        goal_ref: "goal-ref-1",
      }),
      private: { goal: "private goal" },
    });
    const publicCommand = contextCommand();
    for (const id of ["context-real-1", "context-real-replay"]) {
      const response = await fixture.sidecar.handleEnvelope({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id,
        type: "session-context.execute",
        command: structuredClone(publicCommand),
        private: {},
      });
      assert.equal(response.type, "session-context.receipt");
      assert.deepEqual(response.receipt, contextReceipt(publicCommand));
    }

    assert.deepEqual(fixture.contextCalls, [publicCommand]);
    assert.equal(fixture.store.snapshot().contextCommandCount, 1);
    assert.equal(fixture.store.snapshot().contextCommitCount, 1);
    assert.deepEqual(fixture.store.contextOperations(), [{
      command: publicCommand,
      receipt: contextReceipt(publicCommand),
      nextBinding: null,
    }]);
    assert.equal(
      JSON.stringify(fixture.store.contextOperations()).includes("private goal"),
      false,
    );
  } finally {
    await fixture.sidecar.close().catch(() => undefined);
    await fixture.cleanup();
  }
});

test("real gateway retries one accepted uncommitted context command with the same id", async () => {
  const fixture = await createRealSidecarFixture();
  try {
    await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "request-create-retry-session",
      type: "command.accept",
      command: command("session.create", {
        system_id: "research.system",
        system_version: "1.0.0",
        goal_id: "goal-1",
        goal_ref: "goal-ref-1",
      }),
      private: { goal: "private goal" },
    });
    fixture.contextExecutor.failures = 1;
    const publicCommand = contextCommand();
    const first = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "context-retry-first",
      type: "session-context.execute",
      command: publicCommand,
      private: {},
    });
    assert.equal(first.type, "error");
    assert.equal(JSON.stringify(first).includes("SENTINEL"), false);
    assert.equal(fixture.store.snapshot().contextCommandCount, 1);
    assert.equal(fixture.store.snapshot().contextCommitCount, undefined);

    const second = await fixture.sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: "context-retry-second",
      type: "session-context.execute",
      command: structuredClone(publicCommand),
      private: {},
    });
    assert.equal(second.type, "session-context.receipt");
    assert.deepEqual(
      fixture.contextCalls.map((item) => item.command_id),
      [publicCommand.command_id, publicCommand.command_id],
    );
    assert.equal(fixture.store.snapshot().contextCommandCount, 1);
    assert.equal(fixture.store.snapshot().contextCommitCount, 1);
  } finally {
    await fixture.sidecar.close().catch(() => undefined);
    await fixture.cleanup();
  }
});

test("real gateway fails closed when a public ref has no private binding", async () => {
  const fixture = await createRealSidecarFixture();
  try {
    const create = command("session.create", {
      system_id: "research.system",
      system_version: "1.0.0",
      goal_id: "goal-1",
      goal_ref: "goal-ref-1",
    });

    await assert.rejects(
      fixture.gateway.accept(create),
    );
    const durableCommands = await durableCommandRecords(fixture.root);
    assert.deepEqual(durableCommands, [create]);
    assert.equal(JSON.stringify(durableCommands).includes("SENTINEL"), false);
    assert.equal(fixture.store.snapshot().commandCount, 1);
  } finally {
    await fixture.sidecar.close().catch(() => undefined);
    await fixture.cleanup();
  }
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

test("sidecar binds successful action receipts to stable private result refs", async () => {
  const { gateway, privateValues, sidecar } = createSidecar();
  const publicCommand = command("action.resolve", {
    action_id: "action-1",
    resolution: "succeeded",
    reason_code: "executed",
    receipt_ref: "receipt-1",
  }, "terminal-action-1");
  const privateProjection = {
    result: {
      receipt_ref: "receipt-1",
      artifact_ids: ["artifact-1"],
      media_types: ["text/plain"],
    },
  };

  for (const id of ["request-1", "request-2"]) {
    const response = await sidecar.handleEnvelope({
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id,
      type: "command.accept",
      command: structuredClone(publicCommand),
      private: structuredClone(privateProjection),
    });
    assert.equal(response.type, "command.accepted");
  }

  assert.equal(privateValues.results.length, 1);
  assert.equal(gateway.accepted.length, 2);
  assert.deepEqual(gateway.accepted, [publicCommand, publicCommand]);
  assert.match(privateValues.bindings.get(
    "result:terminal-action-1:action-1:receipt-1",
  ).privateRef, /^private:/);
  assert.equal(JSON.stringify(gateway.accepted).includes("artifact-1"), false);
});

test("sidecar passes failed action receipts byte-identically without private result", async () => {
  const { gateway, privateValues, sidecar } = createSidecar();
  const publicCommand = command("action.resolve", {
    action_id: "action-1",
    resolution: "failed",
    reason_code: "executor-failed",
    receipt_ref: "failure-receipt-1",
  }, "terminal-action-1");

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "command.accept",
    command: structuredClone(publicCommand),
    private: {},
  });

  assert.equal(response.type, "command.accepted");
  assert.deepEqual(gateway.accepted, [publicCommand]);
  assert.equal(privateValues.results.length, 0);
});

test("sidecar private read resolves generated input refs outside public command flow", async () => {
  const { gateway, privateValues, sidecar } = createSidecar();
  const reference = await privateValues.putInput("SENTINEL_PRIVATE_ACTION_INPUT");

  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-private-read",
    type: "private.read",
    reference,
  });

  assert.deepEqual(response, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-private-read",
    type: "private.value",
    text: "SENTINEL_PRIVATE_ACTION_INPUT",
  });
  assert.deepEqual(gateway.accepted, []);
});

test("sidecar rejects conflicting result projection replay", async () => {
  const { sidecar } = createSidecar();
  const publicCommand = command("action.resolve", {
    action_id: "action-1",
    resolution: "succeeded",
    reason_code: "executed",
    receipt_ref: "receipt-1",
  }, "terminal-action-1");
  const first = {
    result: {
      receipt_ref: "receipt-1",
      artifact_ids: ["artifact-1"],
      media_types: ["text/plain"],
    },
  };
  const second = {
    result: {
      receipt_ref: "receipt-1",
      artifact_ids: ["artifact-2"],
      media_types: ["text/plain"],
    },
  };

  await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-1",
    type: "command.accept",
    command: publicCommand,
    private: first,
  });
  const response = await sidecar.handleEnvelope({
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: "request-2",
    type: "command.accept",
    command: publicCommand,
    private: second,
  });

  assert.equal(response.type, "error");
  assert.equal(JSON.stringify(response).includes("artifact-2"), false);
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
