import assert from "node:assert/strict";
import { chmod, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GatewayDurableStore,
  GatewayStoreConflictError,
  GatewayStoreCorruptionError,
  GatewayStoreWriteError,
} from "../dist/src/index.js";
import {
  canonicalJsonBytes,
  sha256Hex,
} from "../dist/src/durable-store.js";

const fixtures = new URL(
  "../../../../tests/fixtures/agent_control/v1/",
  import.meta.url,
);

async function fixture(name) {
  return JSON.parse(await readFile(new URL(name, fixtures), "utf8"));
}

function event(sequence, generation = 1) {
  return {
    protocol: "asterion.agent-control/v1",
    event_id: `event-${generation}-${sequence}`,
    session_id: "session-1",
    generation,
    sequence,
    emitted_at: `2026-08-10T03:00:${String(sequence).padStart(2, "0")}Z`,
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

function contextCommand() {
  return {
    protocol: "asterion.session-context/v1",
    command_id: "context-command-1",
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: "context-operation-1",
    operation: "session.tree.read",
    payload: { continuation_id: "continuation-1" },
  };
}

function inputCommand() {
  return {
    protocol: "asterion.agent-control/v1",
    command_id: "command-input-rich",
    session_id: "session-1",
    authority_revision: 1,
    type: "input.submit",
    payload: {
      input_id: "input-rich",
      delivery: "direct",
      content_ref: "content-rich",
    },
  };
}

function inputAttachments() {
  return [
    {
      attachmentId: "attachment-1",
      mediaType: "image/png",
      sha256: "a".repeat(64),
      size: 17,
    },
    {
      attachmentId: "attachment-2",
      mediaType: "image/jpeg",
      sha256: "b".repeat(64),
      size: 23,
    },
  ];
}

function contextReceipt() {
  return {
    protocol: "asterion.session-context/v1",
    receipt_id: "context-receipt-1",
    command_id: "context-command-1",
    session_id: "session-1",
    generation: 1,
    operation: "session.tree.read",
    status: "succeeded",
    reason_code: "session-context-succeeded",
    payload: {
      evidence_ref: null,
      result: {
        continuation_id: "continuation-1",
        nodes: [],
        leaf_id: null,
      },
    },
  };
}

function contextBinding() {
  return {
    continuationId: "continuation-1",
    privateRef: "private:00000000-0000-4000-8000-000000000001",
    bindingDigest: "a".repeat(64),
  };
}

function forkCommand() {
  return {
    protocol: "asterion.session-context/v1",
    command_id: "context-fork-atomic",
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: "context-fork-atomic-once",
    operation: "session.fork",
    payload: {
      continuation_id: "continuation-1",
      entry_id: "entry-1",
      position: "at",
    },
  };
}

function forkReceipt() {
  return {
    protocol: "asterion.session-context/v1",
    receipt_id: "context-fork-atomic-receipt",
    command_id: "context-fork-atomic",
    session_id: "session-1",
    generation: 1,
    operation: "session.fork",
    status: "succeeded",
    reason_code: "session-context-succeeded",
    payload: {
      evidence_ref: null,
      result: {
        source_continuation_id: "continuation-1",
        new_continuation_id: "continuation-2",
        active_leaf_id: "entry-1",
        transition_sha256: "d".repeat(64),
      },
    },
  };
}

function modelContextCommand(
  operation = "session.compact",
  commandId = "context-model-1",
) {
  const budget = {
    controller_tokens: 50,
    application_tokens: 0,
    child_tokens: 0,
    aggregate_tokens: 50,
    cost_micros: 5_000,
    deadline_ms: 30_000,
  };
  return {
    protocol: "asterion.session-context/v1",
    command_id: commandId,
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: `${commandId}-once`,
    operation,
    payload: operation === "session.compact"
      ? {
        continuation_id: "continuation-1",
        instructions_ref: "instructions-ref-1",
        budget,
      }
      : {
        continuation_id: "continuation-1",
        entry_id: "entry-1",
        instructions_ref: "instructions-ref-1",
        budget,
      },
  };
}

function modelContextBaseline(commandId = "context-model-1") {
  return {
    commandId,
    continuationId: "continuation-1",
    leafId: "entry-2",
    contextTokens: 90,
    controllerTokens: 135,
    costMicros: 1_234,
  };
}

function compactReceipt(commandId = "context-model-1") {
  return {
    protocol: "asterion.session-context/v1",
    receipt_id: `${commandId}-receipt`,
    command_id: commandId,
    session_id: "session-1",
    generation: 1,
    operation: "session.compact",
    status: "succeeded",
    reason_code: "session-context-succeeded",
    payload: {
      evidence_ref: null,
      result: {
        continuation_id: "continuation-1",
        covered_leaf_id: "entry-2",
        before_context_tokens: 90,
        after_context_tokens: 40,
        summary_sha256: "c".repeat(64),
        usage: {
          controller_tokens: 20,
          application_tokens: 0,
          child_tokens: 0,
          aggregate_tokens: 20,
          cost_micros: 500,
        },
      },
    },
  };
}

async function temporaryStoreRoot() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-gateway-store-"));
  return {
    parent,
    root: join(parent, "gateway"),
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

test("durable store fsyncs before acknowledging and rejects divergent replay", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const stages = [];
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1", {
      faultInjector(stage) {
        stages.push(stage);
      },
    });
    const command = await fixture("valid-command-session-create.json");
    const first = await store.acceptCommand(command);
    const replay = await store.acceptCommand(structuredClone(command));

    assert.equal(first.position, 1);
    assert.equal(replay.position, first.position);
    assert.deepEqual(stages.slice(-6), [
      "before_write",
      "after_write",
      "before_rename",
      "after_rename",
      "before_directory_fsync",
      "after_directory_fsync",
    ]);
    await assert.rejects(
      store.acceptCommand({ ...command, authority_revision: 2 }),
      GatewayStoreConflictError,
    );
    assert.equal(store.snapshot().position, 1);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store atomically commits safe context receipt and current binding", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const accepted = await store.acceptContextCommand(contextCommand());
    const committed = await store.commitContextOperation(
      contextReceipt(),
      contextBinding(),
    );

    assert.equal(accepted.position, 1);
    assert.equal(committed.position, 2);
    assert.deepEqual(committed.receipt, contextReceipt());
    assert.deepEqual(committed.nextBinding, contextBinding());
    assert.deepEqual(
      store.currentContextBinding("continuation-1"),
      contextBinding(),
    );
    assert.deepEqual(store.snapshot(), {
      sessionId: "session-1",
      position: 2,
      headDigest: committed.digest,
      commandCount: 0,
      eventCount: 0,
      contextCommandCount: 1,
      contextCommitCount: 1,
    });

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.contextOperations(), [{
      command: contextCommand(),
      receipt: contextReceipt(),
      nextBinding: contextBinding(),
    }]);
    await assert.rejects(
      reopened.commitContextOperation(contextReceipt(), {
        ...contextBinding(),
        bindingDigest: "b".repeat(64),
      }),
      GatewayStoreConflictError,
    );

    const records = await Promise.all(
      (await readdir(join(fixtureRoot.root, "public", "records")))
        .filter((name) => name.endsWith(".json"))
        .map((name) => readFile(join(fixtureRoot.root, "public", "records", name), "utf8")),
    );
    assert.equal(records.join("").includes("provider/path"), false);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store persists one exact model baseline before dispatch and clears it on commit", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.initializeContextBinding(contextBinding());
    await store.acceptContextCommand(modelContextCommand());
    const prepared = await store.prepareContextModelOperation(
      "context-model-1",
      modelContextBaseline(),
    );
    assert.equal(prepared.position, 3);
    assert.deepEqual(
      store.preparedContextModelOperation("context-model-1"),
      modelContextBaseline(),
    );

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.preparedContextModelOperations(), [{
      command: modelContextCommand(),
      baseline: modelContextBaseline(),
    }]);
    const replay = await reopened.prepareContextModelOperation(
      "context-model-1",
      modelContextBaseline(),
    );
    assert.equal(replay.position, prepared.position);
    await assert.rejects(
      reopened.prepareContextModelOperation("context-model-1", {
        ...modelContextBaseline(),
        controllerTokens: 136,
      }),
      GatewayStoreConflictError,
    );

    await reopened.commitContextOperation(compactReceipt(), null);
    assert.equal(
      reopened.preparedContextModelOperation("context-model-1"),
      undefined,
    );
    const committed = await GatewayDurableStore.open(
      fixtureRoot.root,
      "session-1",
    );
    assert.deepEqual(committed.preparedContextModelOperations(), []);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable model baseline rejects wrong identity, unsupported commands, and unbounded success", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.initializeContextBinding(contextBinding());
    await store.acceptContextCommand(contextCommand());
    await assert.rejects(
      store.prepareContextModelOperation(
        contextCommand().command_id,
        modelContextBaseline(contextCommand().command_id),
      ),
      GatewayStoreConflictError,
    );

    await store.acceptContextCommand(modelContextCommand());
    await assert.rejects(
      store.prepareContextModelOperation("context-model-1", {
        ...modelContextBaseline(),
        continuationId: "continuation-foreign",
      }),
      GatewayStoreConflictError,
    );
    await store.prepareContextModelOperation(
      "context-model-1",
      modelContextBaseline(),
    );
    const overBudget = structuredClone(compactReceipt());
    overBudget.payload.result.usage.controller_tokens = 51;
    overBudget.payload.result.usage.aggregate_tokens = 51;
    await assert.rejects(
      store.commitContextOperation(overBudget, null),
      GatewayStoreConflictError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable model baseline recovery selects one exact preparation across faults", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "after_rename",
    "before_directory_fsync",
    "after_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const initial = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await initial.initializeContextBinding(contextBinding());
      await initial.acceptContextCommand(modelContextCommand());
      const faulted = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
        {
          faultInjector(stage) {
            if (stage === faultStage) {
              throw new Error(`SENTINEL_MODEL_${faultStage}`);
            }
          },
        },
      );
      await assert.rejects(
        faulted.prepareContextModelOperation(
          "context-model-1",
          modelContextBaseline(),
        ),
        GatewayStoreWriteError,
      );

      const reopened = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
      );
      await reopened.prepareContextModelOperation(
        "context-model-1",
        modelContextBaseline(),
      );
      assert.deepEqual(reopened.preparedContextModelOperations(), [{
        command: modelContextCommand(),
        baseline: modelContextBaseline(),
      }]);
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("durable input delivery binds one ordered body-free attachment set", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.ensureInputDeliveryProtocol();
    await store.acceptCommand(inputCommand());
    const first = await store.commitInputDelivery(
      "command-input-rich",
      inputAttachments(),
    );
    const replay = await store.commitInputDelivery(
      "command-input-rich",
      structuredClone(inputAttachments()),
    );

    assert.equal(replay.position, first.position);
    assert.deepEqual(store.inputDeliveries().map((delivery) => ({
      commandId: delivery.commandId,
      inputId: delivery.inputId,
      attachments: delivery.attachments,
    })), [{
      commandId: "command-input-rich",
      inputId: "input-rich",
      attachments: inputAttachments(),
    }]);
    await assert.rejects(
      store.commitInputDelivery(
        "command-input-rich",
        inputAttachments().toReversed(),
      ),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      store.commitInputDelivery("missing-command", inputAttachments()),
      GatewayStoreConflictError,
    );

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.inputDeliveries(), store.inputDeliveries());
    const records = await Promise.all(
      (await readdir(join(fixtureRoot.root, "public", "records")))
        .filter((name) => name.endsWith(".json"))
        .map((name) => readFile(
          join(fixtureRoot.root, "public", "records", name),
          "utf8",
        )),
    );
    assert.equal(records.join("").includes("SENTINEL_PRIVATE"), false);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable input delivery recovery selects one exact commit across faults", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "after_rename",
    "before_directory_fsync",
    "after_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const initial = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await initial.ensureInputDeliveryProtocol();
      await initial.acceptCommand(inputCommand());
      const faulted = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
        {
          faultInjector(stage) {
            if (stage === faultStage) {
              throw new Error(`SENTINEL_INPUT_${faultStage}`);
            }
          },
        },
      );
      await assert.rejects(
        faulted.commitInputDelivery("command-input-rich", inputAttachments()),
        GatewayStoreWriteError,
      );

      const reopened = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
      );
      await reopened.commitInputDelivery(
        "command-input-rich",
        inputAttachments(),
      );
      assert.equal(reopened.inputDeliveries().length, 1);
      assert.deepEqual(
        reopened.inputDeliveries()[0].attachments,
        inputAttachments(),
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("durable input delivery marker separates legacy accepted inputs", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.acceptCommand(inputCommand());
    assert.equal(store.inputDeliveryProtocolPosition(), undefined);
    await assert.rejects(
      store.commitInputDelivery("command-input-rich", inputAttachments()),
      GatewayStoreConflictError,
    );

    const marker = await store.ensureInputDeliveryProtocol();
    assert.equal(store.inputDeliveryProtocolPosition(), marker.position);
    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.equal(reopened.inputDeliveryProtocolPosition(), marker.position);
    assert.equal(reopened.commands()[0].position < marker.position, true);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("context commit recovery has exactly one binding across every atomic fault", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "after_rename",
    "before_directory_fsync",
    "after_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const initial = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await initial.acceptContextCommand(contextCommand());
      const faulted = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
        {
          faultInjector(stage) {
            if (stage === faultStage) {
              throw new Error(`SENTINEL_${faultStage}`);
            }
          },
        },
      );
      await assert.rejects(
        faulted.commitContextOperation(contextReceipt(), contextBinding()),
        GatewayStoreWriteError,
      );

      const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      assert.ok([1, 2].includes(reopened.snapshot().position));
      await reopened.commitContextOperation(contextReceipt(), contextBinding());
      assert.equal(reopened.snapshot().position, 2);
      assert.deepEqual(reopened.contextOperations(), [{
        command: contextCommand(),
        receipt: contextReceipt(),
        nextBinding: contextBinding(),
      }]);
      assert.deepEqual(
        reopened.currentContextBinding("continuation-1"),
        contextBinding(),
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("fork commit makes refreshed source and replacement binding visible atomically", async () => {
  const source = contextBinding();
  const refreshedSource = {
    ...source,
    privateRef: "private:00000000-0000-4000-8000-000000000002",
    bindingDigest: "b".repeat(64),
  };
  const replacement = {
    continuationId: "continuation-2",
    privateRef: "private:00000000-0000-4000-8000-000000000003",
    bindingDigest: "c".repeat(64),
  };
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "after_rename",
    "before_directory_fsync",
    "after_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const initial = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await initial.initializeContextBinding(source);
      await initial.acceptContextCommand(forkCommand());
      await initial.prepareContextOperation(forkCommand().command_id, source, {
        previousLeafId: "entry-1",
        selectedEntryId: "entry-1",
      });
      const faulted = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
        {
          faultInjector(stage) {
            if (stage === faultStage) {
              throw new Error(`SENTINEL_FORK_${faultStage}`);
            }
          },
        },
      );
      await assert.rejects(
        faulted.commitContextOperation(
          forkReceipt(),
          replacement,
          refreshedSource,
        ),
        GatewayStoreWriteError,
      );

      const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      if (reopened.contextOperations().length === 0) {
        assert.deepEqual(reopened.currentContextBinding("continuation-1"), source);
        assert.equal(reopened.currentContextBinding("continuation-2"), undefined);
        assert.deepEqual(reopened.activeContextBinding(), source);
        await reopened.commitContextOperation(
          forkReceipt(),
          replacement,
          refreshedSource,
        );
      } else {
        assert.deepEqual(
          reopened.currentContextBinding("continuation-1"),
          refreshedSource,
        );
        assert.deepEqual(
          reopened.currentContextBinding("continuation-2"),
          replacement,
        );
        assert.deepEqual(reopened.activeContextBinding(), replacement);
      }
      assert.deepEqual(
        reopened.currentContextBinding("continuation-1"),
        refreshedSource,
      );
      assert.deepEqual(reopened.activeContextBinding(), replacement);
      assert.equal(reopened.preparedContextOperations().length, 0);
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("reopen preserves a legacy fork commit that predates mutation preparation", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const source = contextBinding();
    const replacement = {
      continuationId: "continuation-2",
      privateRef: "private:00000000-0000-4000-8000-000000000003",
      bindingDigest: "c".repeat(64),
    };
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.initializeContextBinding(source);
    await store.acceptContextCommand(forkCommand());
    const previous = JSON.parse(await readFile(
      join(fixtureRoot.root, "public", "records", "000000000002.json"),
      "utf8",
    ));
    const kind = "context.operation.committed";
    const recordId = `context-commit:${forkCommand().command_id}`;
    const payload = {
      receipt: forkReceipt(),
      nextBinding: replacement,
    };
    const payloadDigest = sha256Hex(canonicalJsonBytes({
      kind,
      record_id: recordId,
      payload,
    }));
    const body = {
      format: "asterion.prime-gateway-record/v1",
      position: 3,
      previous_digest: previous.digest,
      kind,
      record_id: recordId,
      payload,
      payload_digest: payloadDigest,
    };
    const record = { ...body, digest: sha256Hex(canonicalJsonBytes(body)) };
    await writeFile(
      join(fixtureRoot.root, "public", "records", "000000000003.json"),
      Buffer.concat([canonicalJsonBytes(record), Buffer.from("\n")]),
      { mode: 0o600 },
    );

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.currentContextBinding("continuation-1"), source);
    assert.deepEqual(reopened.currentContextBinding("continuation-2"), replacement);
    assert.deepEqual(reopened.activeContextBinding(), replacement);
    assert.deepEqual(reopened.contextOperations(), [{
      command: forkCommand(),
      receipt: forkReceipt(),
      nextBinding: replacement,
    }]);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store reopens identity cursor and safe event suffix", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const command = await fixture("valid-command-session-create.json");
    const event = await fixture("valid-event-action-proposed.json");
    await store.acceptCommand(command);
    await store.bindPrimeIdentity({
      activeSessionId: "prime-root",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
    });
    await store.recordPrimeCursor({ generation: "worker-generation-1", sequence: 4 });
    const acceptedEvent = await store.appendEvent(event);

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const snapshot = reopened.snapshot();
    assert.deepEqual(snapshot, {
      sessionId: "session-1",
      position: 4,
      headDigest: acceptedEvent.digest,
      commandCount: 1,
      eventCount: 1,
      primeIdentity: {
        activeSessionId: "prime-root",
        transcriptSessionId: "transcript-1",
        supervisorGeneration: "supervisor-generation-1",
      },
      primeCursor: { generation: "worker-generation-1", sequence: 4 },
    });
    assert.deepEqual(reopened.eventsAfter(3), [
      { position: 4, digest: acceptedEvent.digest, event },
    ]);
    assert.ok(Object.isFrozen(snapshot));
    assert.ok(Object.isFrozen(reopened.eventsAfter(3)[0].event));
    assert.equal(JSON.stringify(snapshot).includes(fixtureRoot.root), false);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store reopens only a contiguous canonical client observation prefix", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const observation = (sequence) => ({
      observation_id: `prime-client-1-${sequence}`,
      active_session_id: "session-1",
      generation: 1,
      source_sequence: sequence,
      emitted_at: `2026-08-10T03:00:0${sequence}.000Z`,
      kind: "message.available",
      payload: {
        content_ref: `private:00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
        media_type: "text/plain",
        message_id: `message-${sequence}`,
        role: "assistant",
        sha256: "a".repeat(64),
        size: sequence,
      },
    });
    const stage = async (sequence) => {
      const value = observation(sequence);
      const descriptor = {
        generation: 1, nativeSequence: sequence,
        reference: value.payload.content_ref, kind: "message", mediaType: "text/plain",
        size: value.payload.size, sha256: value.payload.sha256,
      };
      await store.stageClientObservationValue(descriptor);
      return descriptor;
    };
    const first = await stage(1);
    await store.recordClientObservationProgress(1, 1, observation(1), first);
    const second = await stage(2);
    await store.recordClientObservationProgress(1, 2, observation(2), second);
    await store.recordClientObservationProgress(1, 2, observation(2), second);
    await assert.rejects(
      store.recordClientObservationProgress(1, 4, observation(3)),
    );
    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.clientObservations(1), [observation(1), observation(2)]);
    assert.deepEqual(reopened.clientObservationProgress(1), {
      nativeSequence: 2,
      observationSequence: 2,
    });
    assert.equal(JSON.stringify(reopened.clientObservations(1)).includes("SENTINEL"), false);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable client observations reject non-closed public payloads before storage", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const base = {
    observation_id: "prime-client-1-1",
    active_session_id: "session-1",
    generation: 1,
    source_sequence: 1,
    emitted_at: "2026-08-10T03:00:01.000Z",
  };
  try {
    for (const payload of [
      { commands: ["SENTINEL_BODY"], revision: 1 },
      { commands: ["beta", "alpha"], revision: 1 },
      { commands: ["alpha", "alpha"], revision: 1 },
    ]) {
      const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await assert.rejects(store.recordClientObservationProgress(1, 1, {
        ...base, kind: "commands.changed", payload,
      }));
    }
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await assert.rejects(store.recordClientObservationProgress(1, 1, {
      ...base,
      kind: "tool.started",
      payload: {
        arguments_ref: "private:00000000-0000-4000-8000-000000000001",
        call_id: "call-1",
        name: "SENTINEL_BODY",
        sha256: "a".repeat(64),
        size: 0,
      },
    }));
    await assert.rejects(store.recordClientObservationProgress(1, 1, {
      ...base,
      kind: "extension-ui.requested",
      payload: {
        deadline_ms: 1,
        method: "SENTINEL_BODY",
        payload_ref: "private:00000000-0000-4000-8000-000000000001",
        request_id: "request-1",
      },
    }));
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable progress binds its staged private reference exactly", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.stageClientObservationValue({
      generation: 1, nativeSequence: 1,
      reference: "private:00000000-0000-4000-8000-000000000001",
      kind: "message", mediaType: "text/plain", size: 1, sha256: "a".repeat(64),
    });
    await assert.rejects(store.recordClientObservationProgress(1, 1, {
      observation_id: "prime-client-1-1", active_session_id: "session-1",
      generation: 1, source_sequence: 1, emitted_at: "2026-08-10T03:00:01.000Z",
      kind: "message.available",
      payload: {
        content_ref: "private:00000000-0000-4000-8000-000000000002",
        media_type: "text/plain", message_id: "message-1", role: "assistant",
        sha256: "a".repeat(64), size: 1,
      },
    }));
    assert.equal(store.stagedClientObservationValues(1).length, 1);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable extension progress requires the authoritative staged digest and size", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const staged = {
    generation: 1, nativeSequence: 1,
    reference: "private:00000000-0000-4000-8000-000000000001",
    kind: "extension-ui", mediaType: "application/json", size: 7, sha256: "a".repeat(64),
  };
  const observation = {
    observation_id: "prime-client-1-1", active_session_id: "session-1", generation: 1,
    source_sequence: 1, emitted_at: "2026-08-10T03:00:01.000Z", kind: "extension-ui.requested",
    payload: { deadline_ms: 1, method: "extension-ui", payload_ref: staged.reference, request_id: "request-1" },
  };
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.stageClientObservationValue(staged);
    await assert.rejects(store.recordClientObservationProgress(1, 1, observation, {
      ...staged, size: 8, sha256: "b".repeat(64),
    }));
    await assert.rejects(store.recordClientObservationProgress(1, 1, observation, {
      ...staged, size: 8,
    }));
    assert.equal(store.stagedClientObservationValues(1).length, 1);
    await store.recordClientObservationProgress(1, 1, observation, staged);
    const records = (await readdir(join(fixtureRoot.root, "public", "records"))).sort();
    const path = join(fixtureRoot.root, "public", "records", records.at(-1));
    const forged = JSON.parse(await readFile(path, "utf8"));
    forged.payload.staged_size = 8;
    forged.payload_digest = sha256Hex(canonicalJsonBytes({
      kind: forged.kind, record_id: forged.record_id, payload: forged.payload,
    }));
    forged.digest = sha256Hex(canonicalJsonBytes({
      format: forged.format, position: forged.position, previous_digest: forged.previous_digest,
      kind: forged.kind, record_id: forged.record_id, payload: forged.payload,
      payload_digest: forged.payload_digest,
    }));
    await writeFile(path, Buffer.concat([canonicalJsonBytes(forged), Buffer.from("\n")]), { mode: 0o600 });
    await assert.rejects(GatewayDurableStore.open(fixtureRoot.root, "session-1"));
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store replays events by generation and sequence across mixed records", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.acceptCommand(await fixture("valid-command-session-create.json"));
    await store.appendEvent(event(1, 1));
    await store.bindPrimeIdentity({
      activeSessionId: "prime-root",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
    });
    await store.recordPrimeCursor({ generation: "worker-generation-1", sequence: 1 });
    await store.appendEvent(event(1, 2));
    await store.appendEvent(event(2, 1));

    assert.deepEqual(
      store.eventsAfterCursor({ generation: 1, sequence: 1 }).map((receipt) => [
        receipt.position,
        receipt.event.generation,
        receipt.event.sequence,
      ]),
      [[6, 1, 2]],
    );
    assert.deepEqual(
      store.eventsAfterCursor({ generation: 2, sequence: 0 }).map((receipt) => [
        receipt.event.generation,
        receipt.event.sequence,
      ]),
      [[2, 1]],
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store rejects unknown future generation cursors", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.appendEvent(event(1, 1));

    assert.throws(
      () => store.eventsAfterCursor({ generation: 2, sequence: 0 }),
      GatewayStoreConflictError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store allows explicitly registered empty current generations", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    store.registerEventGeneration(3);

    assert.deepEqual(store.eventsAfterCursor({ generation: 3, sequence: 0 }), []);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store generation cursor fails closed on gaps and wrong order", async () => {
  for (const events of [
    [event(1), event(3)],
    [event(2), event(1)],
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      for (const item of events) {
        await store.appendEvent(item);
      }

      assert.throws(
        () => store.eventsAfterCursor({ generation: 1, sequence: 0 }),
        GatewayStoreCorruptionError,
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("durable store exposes only validated body-free public protocol records", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const sentinel = "SENTINEL_PRIVATE_PROVIDER_BODY";
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const event = await fixture("valid-event-action-proposed.json");
    await store.appendEvent(event);
    await assert.rejects(
      store.appendEvent({
        ...event,
        payload: { ...event.payload, provider_payload: sentinel },
      }),
      (error) => {
        assert.equal(String(error).includes(sentinel), false);
        return true;
      },
    );
    const recordNames = await readdir(join(fixtureRoot.root, "public", "records"));
    const record = await readFile(
      join(fixtureRoot.root, "public", "records", recordNames[0]),
      "utf8",
    );
    assert.equal(record.includes(sentinel), false);
    assert.equal(record.endsWith("\n"), true);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store recovers a valid prefix across every atomic write fault", async () => {
  const command = await fixture("valid-command-session-create.json");
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "before_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      const faulted = await GatewayDurableStore.open(
        fixtureRoot.root,
        "session-1",
        {
          faultInjector(stage) {
            if (stage === faultStage) {
              throw new Error(`SENTINEL_${faultStage}`);
            }
          },
        },
      );
      await assert.rejects(
        faulted.acceptCommand(command),
        (error) => {
          assert.ok(error instanceof GatewayStoreWriteError);
          assert.equal(error.message, "Prime gateway durable write failed");
          assert.equal(error.message.includes("SENTINEL"), false);
          return true;
        },
      );

      const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      assert.ok([0, 1].includes(reopened.snapshot().position));
      const accepted = await reopened.acceptCommand(command);
      assert.equal(accepted.position, 1);
      assert.equal(reopened.snapshot().position, 1);
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("durable store permits only one concurrent writer for a position", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const firstStore = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const secondStore = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const firstCommand = await fixture("valid-command-session-create.json");
    const secondCommand = { ...firstCommand, command_id: "command-2" };

    const outcomes = await Promise.allSettled([
      firstStore.acceptCommand(firstCommand),
      secondStore.acceptCommand(secondCommand),
    ]);
    assert.equal(
      outcomes.filter((outcome) => outcome.status === "fulfilled").length,
      1,
    );
    assert.equal(
      outcomes.filter(
        (outcome) =>
          outcome.status === "rejected" &&
          outcome.reason instanceof GatewayStoreWriteError,
      ).length,
      1,
    );
    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.equal(reopened.snapshot().position, 1);
    assert.equal(reopened.snapshot().commandCount, 1);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store serializes concurrent cursor persistence for one owner", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const records = await Promise.all([
      store.recordPrimeCursor({ generation: "worker-generation-1", sequence: 1 }),
      store.recordPrimeCursor({ generation: "worker-generation-1", sequence: 2 }),
    ]);

    assert.deepEqual(records.map((record) => record.position), [1, 2]);
    assert.deepEqual(store.snapshot().primeCursor, {
      generation: "worker-generation-1",
      sequence: 2,
    });
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store reopens maximum-length protocol identities", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const command = {
      ...(await fixture("valid-command-session-create.json")),
      command_id: "c".repeat(128),
    };
    await store.acceptCommand(command);
    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.equal(reopened.snapshot().commandCount, 1);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store records a closed RLM child lifecycle across reopen", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const binding = {
    action_id: "action-1",
    child_id: "child-1",
    authority_revision: 1,
    depth: 1,
    model_selector_digest: "a".repeat(64),
  };
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await assert.rejects(
      store.recordRlmLifecycle({
        type: "rlm.child.started",
        child_id: "child-unknown",
        native_identity_digest: "a".repeat(64),
      }),
      GatewayStoreConflictError,
    );
    await store.recordRlmBinding(binding);
    await store.recordRlmLifecycle({
      type: "rlm.child.started",
      child_id: "child-1",
      native_identity_digest: "a".repeat(64),
    });
    await store.recordRlmLifecycle({
      type: "rlm.child.terminal",
      child_id: "child-1",
      status: "completed",
    });
    await store.recordRlmLifecycle({
      type: "rlm.child.deleted",
      child_id: "child-1",
    });
    assert.deepEqual(store.rlmLifecycle(), [
      { type: "rlm.child.started", child_id: "child-1", native_identity_digest: "a".repeat(64) },
      {
        type: "rlm.child.terminal",
        child_id: "child-1",
        status: "completed",
      },
      { type: "rlm.child.deleted", child_id: "child-1" },
    ]);

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.rlmLifecycle(), store.rlmLifecycle());
    await assert.rejects(
      reopened.recordRlmLifecycle({
        type: "rlm.child.terminal",
        child_id: "child-1",
        status: "failed",
      }),
      GatewayStoreConflictError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store reopens one exact safe RLM admission binding", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const binding = {
    action_id: "action-1",
    child_id: "child-1",
    authority_revision: 1,
    depth: 1,
    model_selector_digest: "a".repeat(64),
  };
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.recordRlmBinding(binding);
    assert.deepEqual(store.rlmBinding("action-1"), binding);
    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.rlmBinding("action-1"), binding);
    await assert.rejects(
      reopened.recordRlmBinding({ ...binding, child_id: "child-2" }),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      reopened.recordRlmBinding({ ...binding, action_id: "action-2" }),
      GatewayStoreConflictError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store reopens one exact body-free RLM message binding and delivery", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const binding = {
    action_id: "message-action-1",
    message_id: "message-1",
    sender_id: "session-1",
    recipient_id: "child-1",
    authority_revision: 1,
    body_digest: "b".repeat(64),
  };
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    await store.recordRlmMessageBinding(binding);
    assert.deepEqual(store.rlmMessageBinding("message-action-1"), binding);
    await store.recordRlmMessageDelivered("message-1");

    const reopened = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    assert.deepEqual(reopened.rlmMessageBinding("message-action-1"), binding);
    assert.deepEqual(reopened.rlmMessageDelivered(), ["message-1"]);
    await assert.rejects(
      reopened.recordRlmMessageBinding({ ...binding, recipient_id: "child-2" }),
      GatewayStoreConflictError,
    );
    await assert.rejects(
      reopened.recordRlmMessageDelivered("message-1"),
      GatewayStoreConflictError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("durable store rejects corrupted or weak-permission public records safely", async () => {
  for (const mutation of ["corrupt", "mode", "noncanonical"]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
      await store.acceptCommand(await fixture("valid-command-session-create.json"));
      const recordsRoot = join(fixtureRoot.root, "public", "records");
      const [recordName] = (await readdir(recordsRoot)).filter((name) =>
        name.endsWith(".json"),
      );
      const recordPath = join(recordsRoot, recordName);
      if (mutation === "corrupt") {
        await writeFile(recordPath, "SENTINEL_CORRUPTION\n");
      } else if (mutation === "mode") {
        await chmod(recordPath, 0o644);
      } else {
        const original = await readFile(recordPath);
        await writeFile(
          recordPath,
          Buffer.concat([
            original.subarray(0, original.length - 1),
            Buffer.from(" \n"),
          ]),
        );
      }
      await assert.rejects(
        GatewayDurableStore.open(fixtureRoot.root, "session-1"),
        (error) => {
          assert.ok(error instanceof GatewayStoreCorruptionError);
          assert.equal(error.message, "Prime gateway durable store is corrupt");
          assert.equal(error.message.includes("SENTINEL"), false);
          assert.equal(error.message.includes(recordPath), false);
          return true;
        },
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});
