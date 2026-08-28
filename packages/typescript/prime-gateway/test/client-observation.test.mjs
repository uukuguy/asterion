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
