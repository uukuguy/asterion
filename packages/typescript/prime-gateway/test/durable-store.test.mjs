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
