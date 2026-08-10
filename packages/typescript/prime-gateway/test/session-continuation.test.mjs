import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rename, rm, symlink, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  GatewayDurableStore,
  GatewayStoreConflictError,
  PrivateValueInvalidError,
  PrivateValueStore,
} from "../dist/src/index.js";
import { canonicalJsonBytes } from "../dist/src/durable-store.js";

function contextCommand(operation, continuationId, commandId) {
  return {
    protocol: "asterion.session-context/v1",
    command_id: commandId,
    session_id: "session-1",
    generation: 1,
    authority_revision: 1,
    idempotency_key: `${commandId}-once`,
    operation,
    payload: { continuation_id: continuationId },
  };
}

function receipt(command, result) {
  return {
    protocol: "asterion.session-context/v1",
    receipt_id: `receipt-${command.command_id}`,
    command_id: command.command_id,
    session_id: command.session_id,
    generation: command.generation,
    operation: command.operation,
    status: "succeeded",
    reason_code: "session-context-succeeded",
    payload: { evidence_ref: null, result },
  };
}

async function continuationFixture() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-continuation-"));
  const root = join(parent, "gateway");
  const sessionRoot = join(parent, "sessions");
  await mkdir(sessionRoot, { mode: 0o700 });
  return {
    parent,
    root,
    sessionRoot,
    async file(name, body = `${name}\n`) {
      const path = join(sessionRoot, name);
      await writeFile(path, body, { mode: 0o600 });
      return path;
    },
    async cleanup() {
      await rm(parent, { recursive: true, force: true });
    },
  };
}

test("prepared continuation replay accepts only the pinned inode or an exact deleted target", async () => {
  const fixture = await continuationFixture();
  try {
    const sessionPath = await fixture.file("transcript-1.jsonl", "before\n");
    const values = await PrivateValueStore.open(fixture.root, {
      continuationRoot: fixture.sessionRoot,
    });
    const binding = await values.putContinuationLocator({
      continuationId: "continuation-1",
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
      sessionPath,
    });

    await writeFile(sessionPath, "after Prime switch\n", { mode: 0o600 });
    await assert.rejects(
      values.readContinuationLocator(binding),
      PrivateValueInvalidError,
    );
    assert.equal(
      (await values.readPreparedContinuationLocator(binding, false)).sessionPath,
      sessionPath,
    );

    const replacement = await fixture.file("replacement.jsonl", "replacement\n");
    await rename(sessionPath, `${sessionPath}.old`);
    await symlink(replacement, sessionPath);
    await assert.rejects(
      values.readPreparedContinuationLocator(binding, false),
      PrivateValueInvalidError,
    );
    await unlink(sessionPath);
    assert.equal(
      (await values.readPreparedContinuationLocator(binding, true)).sessionPath,
      sessionPath,
    );
    await assert.rejects(
      values.readPreparedContinuationLocator(binding, false),
      PrivateValueInvalidError,
    );
    await rename(fixture.sessionRoot, `${fixture.sessionRoot}.replaced`);
    await mkdir(fixture.sessionRoot, { mode: 0o700 });
    await assert.rejects(
      values.readPreparedContinuationLocator(binding, true),
      PrivateValueInvalidError,
    );
  } finally {
    await fixture.cleanup();
  }
});

test("legacy strict locator upgrades privately before inode-pinned replay", async () => {
  const fixture = await continuationFixture();
  try {
    const sessionPath = await fixture.file("transcript-legacy.jsonl");
    const values = await PrivateValueStore.open(fixture.root, {
      continuationRoot: fixture.sessionRoot,
    });
    const locator = {
      continuationId: "continuation-legacy",
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-legacy",
      supervisorGeneration: "supervisor-generation-1",
      sessionPath,
    };
    const current = await values.putContinuationLocator(locator);
    const valuePath = join(
      fixture.root,
      "private",
      "values",
      `${current.privateRef.slice("private:".length)}.value`,
    );
    const storedBytes = await readFile(valuePath);
    const newline = storedBytes.indexOf(0x0a);
    const header = JSON.parse(storedBytes.subarray(0, newline).toString("utf8"));
    const body = JSON.parse(storedBytes.subarray(newline + 1).toString("utf8"));
    delete body.transcriptDevice;
    delete body.transcriptInode;
    body.format = "asterion.prime-private-continuation/v1";
    const legacyBody = canonicalJsonBytes(body);
    header.size = legacyBody.byteLength;
    header.digest = createHash("sha256").update(legacyBody).digest("hex");
    await writeFile(valuePath, Buffer.concat([
      canonicalJsonBytes(header),
      Buffer.from("\n"),
      legacyBody,
    ]), { mode: 0o600 });
    const legacy = {
      ...current,
      bindingDigest: header.digest,
    };

    assert.deepEqual(await values.readContinuationLocator(legacy), locator);
    const upgraded = await values.ensurePreparedContinuationLocator(legacy);
    assert.deepEqual(upgraded.locator, locator);
    assert.notEqual(upgraded.binding.privateRef, legacy.privateRef);
    assert.deepEqual(
      await values.readPreparedContinuationLocator(upgraded.binding, false),
      locator,
    );
    await unlink(sessionPath);
    await assert.rejects(
      values.readPreparedContinuationLocator(legacy, true),
      PrivateValueInvalidError,
    );
  } finally {
    await fixture.cleanup();
  }
});

test("durable continuation prepare fences selector swaps and delete tombstones only an inactive binding", async () => {
  const fixture = await continuationFixture();
  try {
    const store = await GatewayDurableStore.open(fixture.root, "session-1");
    const bindingA = {
      continuationId: "continuation-1",
      privateRef: "private:00000000-0000-4000-8000-000000000001",
      bindingDigest: "a".repeat(64),
    };
    const bindingB = {
      continuationId: "continuation-2",
      privateRef: "private:00000000-0000-4000-8000-000000000002",
      bindingDigest: "b".repeat(64),
    };
    await store.initializeContextBinding(bindingA);
    const fork = contextCommand("session.fork", "continuation-1", "fork-1");
    fork.payload.entry_id = "entry-1";
    fork.payload.position = "at";
    await store.acceptContextCommand(fork);
    await store.commitContextOperation(receipt(fork, {
      source_continuation_id: "continuation-1",
      new_continuation_id: "continuation-2",
      active_leaf_id: null,
      transition_sha256: "c".repeat(64),
    }), bindingB);
    assert.deepEqual(store.activeContextBinding(), bindingB);

    const removeA = contextCommand(
      "session.continuation.delete",
      "continuation-1",
      "delete-1",
    );
    await store.acceptContextCommand(removeA);
    await store.prepareContextOperation(removeA.command_id, bindingA);
    assert.deepEqual(store.preparedContextBinding(removeA.command_id), bindingA);
    const competing = contextCommand(
      "session.continuation.resume",
      "continuation-1",
      "resume-competing",
    );
    await store.acceptContextCommand(competing);
    await assert.rejects(
      store.prepareContextOperation(competing.command_id, bindingA),
      GatewayStoreConflictError,
    );
    await store.rebindContextBinding({
      ...bindingA,
      privateRef: "private:00000000-0000-4000-8000-000000000003",
      bindingDigest: "d".repeat(64),
    });
    assert.notDeepEqual(
      store.currentContextBinding("continuation-1"),
      store.preparedContextBinding(removeA.command_id),
    );
    await assert.rejects(
      store.commitContextOperation(receipt(removeA, {
        continuation_id: "continuation-1",
        deletion_sha256: "e".repeat(64),
      }), null),
      GatewayStoreConflictError,
    );

    const exactStore = await GatewayDurableStore.open(fixture.root, "session-1");
    await exactStore.rebindContextBinding(bindingA);
    await exactStore.commitContextOperation(receipt(removeA, {
      continuation_id: "continuation-1",
      deletion_sha256: "e".repeat(64),
    }), null);
    assert.equal(exactStore.currentContextBinding("continuation-1"), undefined);
    assert.deepEqual(exactStore.activeContextBinding(), bindingB);
    await exactStore.bindPrimeIdentity({
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-1",
      supervisorGeneration: "supervisor-generation-1",
    });
    await exactStore.bindPrimeIdentity({
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-2",
      supervisorGeneration: "supervisor-generation-1",
    });
    const reopened = await GatewayDurableStore.open(fixture.root, "session-1");
    assert.equal(reopened.currentContextBinding("continuation-1"), undefined);
    assert.deepEqual(reopened.activeContextBinding(), bindingB);
    assert.equal(
      reopened.snapshot().primeIdentity.transcriptSessionId,
      "transcript-2",
    );

    const revive = contextCommand(
      "session.fork",
      "continuation-2",
      "fork-revive-deleted",
    );
    revive.payload.entry_id = "entry-2";
    revive.payload.position = "at";
    await reopened.acceptContextCommand(revive);
    await assert.rejects(
      reopened.commitContextOperation(receipt(revive, {
        source_continuation_id: "continuation-2",
        new_continuation_id: "continuation-1",
        active_leaf_id: null,
        transition_sha256: "f".repeat(64),
      }), bindingA),
      GatewayStoreConflictError,
    );
  } finally {
    await fixture.cleanup();
  }
});
