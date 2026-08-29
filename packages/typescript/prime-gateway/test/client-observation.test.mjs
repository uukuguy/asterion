import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrimeClientObservationMapper,
  PrivateValueStore,
} from "../dist/src/index.js";

async function temporaryStoreRoot() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-client-observation-"));
  return {
    root: join(parent, "gateway"),
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function mapperFixture(values) {
  return new PrimeClientObservationMapper({
    sessionId: "session-1",
    generation: 1,
    activeSessionId: "prime-session-1",
    privateValues: values,
    now: () => "2026-08-10T03:00:00Z",
  });
}

test("stores client bodies and emits only references", async () => {
  const root = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(root.root);
    const mapper = mapperFixture(values);
    const mapped = await mapper.map({
      type: "session_event",
      activeSessionId: "prime-session-1",
      meta: { sequence: 1 },
      event: { type: "message_end", role: "assistant", content: "SENTINEL_BODY" },
    });
    assert.equal(mapped[0].kind, "message.available");
    assert.equal(typeof mapped[0].payload.content_ref, "string");
    assert.equal(JSON.stringify(mapped).includes("SENTINEL_BODY"), false);

    const descriptor = await values.describeClientValue(mapped[0].payload.content_ref);
    assert.equal(descriptor.sha256, createHash("sha256").update("SENTINEL_BODY").digest("hex"));
    assert.equal((await values.readClientValue(descriptor.reference, 1024)).toString("utf8"), "SENTINEL_BODY");
    const reopened = await PrivateValueStore.open(root.root);
    assert.deepEqual(await reopened.describeClientValue(descriptor.reference, "session-1"), descriptor);
    await assert.rejects(reopened.readClientValue(descriptor.reference, 1024, "session-2"));
    assert.equal(String(mapper).includes("SENTINEL_BODY"), false);
  } finally {
    await root.cleanup();
  }
});

test("fails closed for cursor gaps, foreign sessions, and post-close observations", async () => {
  const root = await temporaryStoreRoot();
  try {
    const mapper = mapperFixture(await PrivateValueStore.open(root.root));
    await mapper.map({
      type: "session_event",
      activeSessionId: "prime-session-1",
      event: { type: "message_end", role: "assistant", content: "one" },
      meta: { sequence: 1 },
    });
    await assert.rejects(mapper.map({
      type: "session_event",
      activeSessionId: "prime-session-1",
      event: { type: "message_end", role: "assistant", content: "gap" },
      meta: { sequence: 3 },
    }));
    await assert.rejects(mapper.map({
      type: "session_event",
      activeSessionId: "prime-session-2",
      event: { type: "message_end", role: "assistant", content: "foreign" },
      meta: { sequence: 2 },
    }));
    await mapper.close();
    await assert.rejects(mapper.map({
      type: "session_event",
      activeSessionId: "prime-session-1",
      event: { type: "message_end", role: "assistant", content: "late" },
      meta: { sequence: 2 },
    }));
  } finally {
    await root.cleanup();
  }
});

test("requires an exact native sequence and does not consume it when storage fails", async () => {
  let fail = true;
  const root = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(root.root);
    const mapper = mapperFixture({
      async putClientValue(...args) {
        if (fail) throw new Error("store failed");
        return values.putClientValue(...args);
      },
    });
    const native = {
      type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      event: { type: "message_end", role: "assistant", content: "retry-body" },
    };
    await assert.rejects(mapper.map({ ...native, meta: {} }));
    await assert.rejects(mapper.map(native));
    fail = false;
    const [mapped] = await mapper.map(native);
    assert.equal(mapped.source_sequence, 1);
    assert.equal(mapped.observation_id, "prime-client-1-1");
  } finally {
    await root.cleanup();
  }
});

test("rejects hostile client descriptors before body-free observations escape", async () => {
  const mapper = mapperFixture({
    async putClientValue() {
      return { reference: "SENTINEL_BODY", kind: "message", mediaType: "text/plain", size: 1, sha256: "0".repeat(64) };
    },
  });
  await assert.rejects(mapper.map({
    type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
    event: { type: "message_end", role: "assistant", content: "SENTINEL_BODY" },
  }));
});

test("rejects a client value above the conservative one-frame limit", async () => {
  const root = await temporaryStoreRoot();
  try {
    const mapper = mapperFixture(await PrivateValueStore.open(root.root));
    await assert.rejects(mapper.map({
      type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      event: { type: "message_end", role: "assistant", content: "x".repeat(700 * 1024 + 1) },
    }));
  } finally {
    await root.cleanup();
  }
});

test("passes unscoped daemon events through without consuming the client sequence", async () => {
  const root = await temporaryStoreRoot();
  try {
    const mapper = mapperFixture(await PrivateValueStore.open(root.root));
    for (const outbound of [
      { type: "daemon_closing", reason: "shutdown" },
      { type: "heartbeats_changed" },
      { type: "extension_error", activeSessionId: "prime-session-1", error: { code: "private" } },
    ]) {
      assert.deepEqual(await mapper.map(outbound), []);
    }
    const [observation] = await mapper.map({
      type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      event: { type: "message_end", role: "assistant", content: "mapped" },
    });
    assert.equal(observation.source_sequence, 1);
  } finally {
    await root.cleanup();
  }
});

test("rejects non-canonical commands and broad tool or extension identifiers", async () => {
  const root = await temporaryStoreRoot();
  try {
    const mapper = mapperFixture(await PrivateValueStore.open(root.root));
    for (const event of [
      { type: "commands_changed", commands: ["SENTINEL_BODY"], revision: 1 },
      { type: "commands_changed", commands: ["beta", "alpha"], revision: 1 },
      { type: "commands_changed", commands: ["alpha", "alpha"], revision: 1 },
      { type: "tool_start", callId: "call-1", name: "SENTINEL_BODY", arguments: {} },
    ]) {
      await assert.rejects(mapper.map({
        type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 }, event,
      }));
    }
    await assert.rejects(mapper.map({
      type: "extension_ui_request", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      id: "request-1", method: "SENTINEL_BODY", payload: {},
    }));
    assert.equal(JSON.stringify(await mapper.map({
      type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      event: { type: "commands_changed", commands: ["alpha", "beta"], revision: 1 },
    })).includes("SENTINEL_BODY"), false);
  } finally {
    await root.cleanup();
  }
});

test("rolls back a staged private body when observation progress commit fails", async () => {
  const root = await temporaryStoreRoot();
  let descriptor;
  let failCommit = true;
  try {
    const values = await PrivateValueStore.open(root.root);
    const mapper = new PrimeClientObservationMapper({
      sessionId: "session-1", generation: 1, activeSessionId: "prime-session-1",
      privateValues: {
        async putClientValue(...args) {
          descriptor = await values.putClientValue(...args);
          return descriptor;
        },
        deleteClientValue(reference, sessionId) {
          return values.deleteClientValue(reference, sessionId);
        },
      },
      async commit() {
        if (failCommit) throw new Error("commit failed");
      },
      now: () => "2026-08-10T03:00:00Z",
    });
    const outbound = {
      type: "session_event", activeSessionId: "prime-session-1", meta: { sequence: 1 },
      event: { type: "message_end", role: "assistant", content: "SENTINEL_ROLLBACK_BODY" },
    };
    await assert.rejects(mapper.map(outbound));
    assert.ok(descriptor);
    await assert.rejects(values.describeClientValue(descriptor.reference, "session-1"));
    failCommit = false;
    const [retry] = await mapper.map(outbound);
    assert.equal(retry.source_sequence, 1);
  } finally {
    await root.cleanup();
  }
});
