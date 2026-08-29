import assert from "node:assert/strict";
import test from "node:test";

import { validateControlEvent } from "@dci/agent-runtime";
import {
  PrimeEventMapper,
  PrimeEventMappingError,
} from "../dist/src/index.js";

function mapperFixture() {
  let sequence = 0;
  return new PrimeEventMapper({
    sessionId: "session-1",
    generation: 1,
    goalId: "goal-1",
    activeSessionId: "prime-root-1",
    nextEventIdentity() {
      sequence += 1;
      return {
        eventId: `mapped-${sequence}`,
        sequence,
        emittedAt: `2026-08-10T02:00:${String(sequence).padStart(2, "0")}Z`,
      };
    },
  });
}

function primeEvent(event, sequence) {
  return {
    type: "session_event",
    activeSessionId: "prime-root-1",
    event,
    meta: {
      id: `prime-event-${sequence}`,
      protocol: { name: "prime-agent.daemon", version: 7 },
      activeSessionId: "prime-root-1",
      sequence,
      cursor: { generation: "worker-generation-1", sequence },
      emittedAt: `2026-08-10T01:00:0${sequence}Z`,
    },
  };
}

test("mapping emits safe goal usage and one terminal event", () => {
  const mapper = mapperFixture();
  const events = mapper.map(
    primeEvent(
      {
        type: "goal_update",
        goal: {
          active: false,
          status: "complete",
          goalId: "prime-private-goal",
          objective: "SENTINEL_PRIVATE_OBJECTIVE",
          tokensUsed: 77,
          timeUsedSeconds: 3,
          continuationsUsed: 2,
          lastReason: "SENTINEL_PRIVATE_REASON",
        },
      },
      1,
    ),
  );

  assert.deepEqual(events.map((event) => event.type), [
    "goal.updated",
    "budget.reported",
    "session.completed",
  ]);
  assert.equal(events[0].payload.goal_id, "goal-1");
  assert.equal(events[1].payload.controller_tokens, 77);
  assert.equal(events[1].payload.aggregate_tokens, 77);
  assert.equal(events[2].payload.reason_code, "prime-goal-complete");
  for (const event of events) {
    assert.deepEqual(validateControlEvent(event), event);
    assert.equal(JSON.stringify(event).includes("SENTINEL"), false);
  }
  assert.deepEqual(mapper.map({
    type: "session_closed",
    activeSessionId: "prime-root-1",
    reason: "SENTINEL_PRIVATE_CLOSE",
  }), []);
});

test("mapping ignores bodies and projects only fixed recoverable faults", () => {
  const mapper = mapperFixture();
  assert.deepEqual(
    mapper.map(primeEvent({ type: "message_update", text: "SENTINEL" }, 1)),
    [],
  );
  assert.deepEqual(
    mapper.map(primeEvent({ type: "bash_output", chunk: "SENTINEL" }, 2)),
    [],
  );
  const auth = mapper.map(
    primeEvent(
      { type: "auth_stale", provider: "SENTINEL", sourceTokens: ["SENTINEL"] },
      3,
    ),
  );
  const extension = mapper.map({
    type: "extension_error",
    activeSessionId: "prime-root-1",
    extensionPath: "/SENTINEL/private.py",
    event: "SENTINEL",
    error: "SENTINEL",
  });
  assert.deepEqual(auth.map((event) => event.type), ["fault.raised"]);
  assert.deepEqual(auth[0].payload, {
    code: "prime-auth-stale",
    recoverable: true,
    evidence_ref: null,
  });
  assert.deepEqual(extension[0].payload, {
    code: "prime-extension-error",
    recoverable: true,
    evidence_ref: null,
  });
  assert.equal(JSON.stringify([...auth, ...extension]).includes("SENTINEL"), false);
});

test("mapping ignores a replay carrying the exact native cursor", () => {
  const mapper = mapperFixture();
  const first = primeEvent({ type: "message_update", text: "SENTINEL_FIRST" }, 1);
  const replay = primeEvent({ type: "message_update", text: "SENTINEL_REPLAY" }, 1);

  assert.deepEqual(mapper.map(first), []);
  assert.deepEqual(mapper.map(replay), []);
});

test("mapping accepts a monotonic native cursor gap but rejects regression", () => {
  const mapper = mapperFixture();
  assert.deepEqual(mapper.map(primeEvent({ type: "message_update" }, 2)), []);
  assert.deepEqual(mapper.map(primeEvent({ type: "message_update" }, 4)), []);

  const regressed = primeEvent({ type: "message_update", text: "private" }, 3);
  assert.throws(
    () => mapper.map(regressed),
    (error) => {
      assert.ok(error instanceof PrimeEventMappingError);
      assert.equal(error.message, "Prime event mapping failed");
      assert.equal(error.kind, "cursor-generation");
      assert.equal(error.message.includes("private"), false);
      return true;
    },
  );
});

test("mapping ignores a foreign session while preserving its cursor", () => {
  const mapper = mapperFixture();
  assert.deepEqual(mapper.map({
    ...primeEvent({ type: "message_update", text: "private" }, 1),
    activeSessionId: "prime-child-1",
    meta: {
      ...primeEvent({ type: "message_update" }, 1).meta,
      activeSessionId: "prime-child-1",
      cursor: { generation: "worker-generation-child-1", sequence: 1 },
    },
  }), []);
  assert.deepEqual(mapper.map(primeEvent({ type: "message_update" }, 2)), []);
});

test("mapping converts a Prime goal budget limit into a closed terminal", () => {
  const mapper = mapperFixture();
  const events = mapper.map(primeEvent({
    type: "goal_update",
    goal: {
      active: false,
      status: "budget_limited",
      tokensUsed: 2_000,
      timeUsedSeconds: 60,
      continuationsUsed: 4,
      objective: "SENTINEL_PRIVATE_OBJECTIVE",
    },
  }, 1));
  assert.deepEqual(events.map((event) => event.type), [
    "goal.updated",
    "budget.reported",
    "session.budget-limited",
  ]);
  assert.equal(events[2].payload.reason_code, "prime-goal-budget-limited");
  assert.equal(JSON.stringify(events).includes("SENTINEL"), false);
});

test("mapping fails closed on regressed usage and unknown goal status", () => {
  const mapper = mapperFixture();
  mapper.map(primeEvent({
    type: "goal_update",
    goal: {
      active: true,
      status: "active",
      tokensUsed: 100,
      timeUsedSeconds: 1,
      continuationsUsed: 1,
    },
  }, 1));
  assert.throws(
    () => mapper.map(primeEvent({
      type: "goal_update",
      goal: {
        active: true,
        status: "active",
        tokensUsed: 99,
        timeUsedSeconds: 2,
        continuationsUsed: 1,
      },
    }, 2)),
    PrimeEventMappingError,
  );

  const unknown = mapperFixture();
  assert.throws(
    () => unknown.map(primeEvent({
      type: "goal_update",
      goal: {
        active: false,
        status: "SENTINEL_UNKNOWN_STATUS",
        tokensUsed: 0,
        timeUsedSeconds: 0,
        continuationsUsed: 0,
      },
    }, 1)),
    (error) => {
      assert.ok(error instanceof PrimeEventMappingError);
      assert.equal(error.message.includes("SENTINEL"), false);
      return true;
    },
  );
});

test("mapping treats a vanished resident goal as an explicit failure", () => {
  const mapper = mapperFixture();
  const events = mapper.map(primeEvent({
    type: "goal_update",
    goal: {
      active: false,
      status: "idle",
      tokensUsed: 0,
      timeUsedSeconds: 0,
      continuationsUsed: 0,
    },
  }, 1));
  assert.deepEqual(events.map((event) => event.type), [
    "goal.updated",
    "session.failed",
  ]);
  assert.equal(events[1].payload.reason_code, "prime-goal-unavailable");
});
