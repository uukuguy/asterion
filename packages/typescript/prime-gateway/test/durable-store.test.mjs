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

const fixtures = new URL(
  "../../../../tests/fixtures/agent_control/v1/",
  import.meta.url,
);

async function fixture(name) {
  return JSON.parse(await readFile(new URL(name, fixtures), "utf8"));
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
    assert.deepEqual(stages.slice(-4), [
      "before_write",
      "after_write",
      "before_rename",
      "before_directory_fsync",
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

test("durable store reopens identity cursor and safe event suffix", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const store = await GatewayDurableStore.open(fixtureRoot.root, "session-1");
    const command = await fixture("valid-command-session-create.json");
    const event = await fixture("valid-event-action-proposed.json");
    await store.acceptCommand(command);
    await store.bindPrimeIdentity({
      activeSessionId: "prime-root",
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
