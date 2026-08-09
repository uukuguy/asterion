import assert from "node:assert/strict";
import { mkdtemp, rm, stat } from "node:fs/promises";
import { createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  AsterionSkillBridge,
  MAX_SKILL_FRAME_BYTES,
  PrivateValueStore,
} from "../dist/src/index.js";

const TOKEN = "11".repeat(32);
const TARGET = Object.freeze({
  kind: "application",
  provider_id: "example.provider",
  application_id: "alpha",
  version: "1.0.0",
  runtime_id: "fake.runtime",
});
const BUDGET = Object.freeze({
  controller_tokens: 0,
  application_tokens: 100,
  child_tokens: 0,
  aggregate_tokens: 100,
  cost_micros: 5_000,
  deadline_ms: 10_000,
});

async function temporaryRoot() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-skill-bridge-"));
  return {
    parent,
    root: join(parent, "gateway"),
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function applicationRequest(overrides = {}) {
  return {
    protocol: "asterion.skill-control/v1",
    request_id: "request-1",
    session_id: "session-1",
    operation: "application.invoke",
    payload: {
      target: TARGET,
      input_text: "SENTINEL_PRIVATE_APPLICATION_INPUT",
      idempotency_key: "application-once-1",
      budget: BUDGET,
      expected_artifacts: ["report.alpha"],
    },
    ...overrides,
  };
}

async function readLine(socket) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timeout = setTimeout(() => reject(new Error("response timeout")), 1_000);
    const cleanup = () => {
      clearTimeout(timeout);
      socket.off("data", onData);
      socket.off("error", onError);
      socket.off("close", onClose);
    };
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const newline = buffer.indexOf("\n");
      if (newline !== -1) {
        cleanup();
        resolve(buffer.slice(0, newline));
      }
    };
    const onError = () => {
      cleanup();
      reject(new Error("socket failed"));
    };
    const onClose = () => {
      cleanup();
      resolve(buffer.length === 0 ? undefined : buffer);
    };
    socket.on("data", onData);
    socket.once("error", onError);
    socket.once("close", onClose);
  });
}

async function exchange(
  socketPath,
  request,
  { token = TOKEN, sessionId = "session-1", closeAfterWrite = false } = {},
) {
  const socket = createConnection(socketPath);
  await new Promise((resolve, reject) => {
    socket.once("connect", resolve);
    socket.once("error", reject);
  });
  const auth = {
    protocol: "asterion.skill-control/v1",
    type: "authenticate",
    token,
    session_id: sessionId,
  };
  socket.write(`${JSON.stringify(auth)}\n${JSON.stringify(request)}\n`);
  if (closeAfterWrite) {
    socket.destroy();
    return undefined;
  }
  const line = await readLine(socket);
  socket.end();
  return line === undefined ? undefined : JSON.parse(line);
}

async function createBridge(fixtureRoot, overrides = {}) {
  const privateValues = await PrivateValueStore.open(fixtureRoot.root);
  const resultRef = await privateValues.putResult({
    receiptRef: "receipt-1",
    artifactIds: ["artifact-1"],
    mediaTypes: ["text/plain"],
  });
  const proposals = [];
  const calls = [];
  let sequence = 0;
  const bridge = await AsterionSkillBridge.listen({
    root: fixtureRoot.root,
    sessionId: "session-1",
    authorityRevision: 1,
    generation: 1,
    goalId: "goal-1",
    causalParentIds: ["goal-1"],
    token: TOKEN,
    portfolio: [TARGET],
    remainingBudget: BUDGET,
    privateValues,
    nextEventIdentity() {
      sequence += 1;
      return {
        eventId: `skill-event-${sequence}`,
        sequence,
        emittedAt: `2026-08-10T00:00:0${sequence}Z`,
      };
    },
    async emitActionProposal(event) {
      calls.push("proposal");
      proposals.push(event);
      assert.equal(
        await privateValues.readInput(event.payload.input_ref),
        "SENTINEL_PRIVATE_APPLICATION_INPUT",
      );
    },
    async waitForAdmission() {
      calls.push("admission");
      return { resolution: "admitted", reasonCode: "authorized" };
    },
    async waitForTerminal() {
      calls.push("terminal");
      return {
        resolution: "succeeded",
        reasonCode: "completed",
        resultRef,
      };
    },
    async actionStatus(actionId) {
      return { action_id: actionId, status: "succeeded" };
    },
    ...overrides,
  });
  return { bridge, privateValues, proposals, calls };
}

test("skill bridge authenticates, persists input, and returns only safe results", async () => {
  const fixtureRoot = await temporaryRoot();
  const state = await createBridge(fixtureRoot);
  try {
    const response = await exchange(
      state.bridge.socketPath,
      applicationRequest(),
    );
    assert.equal(response.status, "ok");
    assert.deepEqual(response.result.admission, {
      resolution: "admitted",
      reason_code: "authorized",
    });
    assert.deepEqual(response.result.terminal, {
      resolution: "succeeded",
      reason_code: "completed",
    });
    assert.deepEqual(response.result.result, {
      receipt_ref: "receipt-1",
      artifact_ids: ["artifact-1"],
      media_types: ["text/plain"],
    });
    assert.deepEqual(state.calls, ["proposal", "admission", "terminal"]);
    assert.equal(state.proposals.length, 1);
    assert.equal(state.proposals[0].type, "action.proposed");
    assert.equal(state.proposals[0].payload.kind, "application.invoke");
    assert.equal(
      JSON.stringify(state.proposals[0]).includes("SENTINEL_PRIVATE_APPLICATION_INPUT"),
      false,
    );
    assert.equal(JSON.stringify(response).includes("SENTINEL"), false);
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});

test("skill bridge deduplicates equal effects and rejects divergent reuse", async () => {
  const fixtureRoot = await temporaryRoot();
  const state = await createBridge(fixtureRoot);
  try {
    const first = await exchange(state.bridge.socketPath, applicationRequest());
    const replay = await exchange(
      state.bridge.socketPath,
      applicationRequest({ request_id: "request-2" }),
    );
    assert.equal(replay.result.action_id, first.result.action_id);
    assert.equal(state.proposals.length, 1);

    const divergent = applicationRequest({ request_id: "request-3" });
    divergent.payload = {
      ...divergent.payload,
      input_text: "SENTINEL_DIVERGENT_PRIVATE_INPUT",
    };
    const conflict = await exchange(state.bridge.socketPath, divergent);
    assert.deepEqual(conflict, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-3",
      status: "error",
      code: "request-conflicts",
    });
    assert.equal(JSON.stringify(conflict).includes("SENTINEL"), false);
    assert.equal(state.proposals.length, 1);
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});

test("skill bridge rejects wrong token and cross-session authentication", async () => {
  const fixtureRoot = await temporaryRoot();
  const state = await createBridge(fixtureRoot);
  try {
    for (const auth of [
      { token: "22".repeat(32) },
      { sessionId: "session-2" },
    ]) {
      const response = await exchange(
        state.bridge.socketPath,
        applicationRequest(),
        auth,
      );
      assert.deepEqual(response, {
        protocol: "asterion.skill-control/v1",
        request_id: "authentication",
        status: "error",
        code: "authentication-failed",
      });
      assert.equal(JSON.stringify(response).includes(TOKEN), false);
    }
    assert.equal(state.proposals.length, 0);
    assert.equal((await stat(fixtureRoot.root)).mode & 0o777, 0o700);
    assert.equal((await stat(state.bridge.socketPath)).mode & 0o777, 0o600);
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});

test("skill bridge rejects a terminal effect for another goal", async () => {
  const fixtureRoot = await temporaryRoot();
  const state = await createBridge(fixtureRoot);
  try {
    const response = await exchange(state.bridge.socketPath, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-cross-goal",
      session_id: "session-1",
      operation: "goal.complete",
      payload: {
        goal_id: "goal-2",
        summary: "SENTINEL_PRIVATE_CROSS_GOAL_SUMMARY",
        idempotency_key: "cross-goal-once-1",
        budget: BUDGET,
      },
    });
    assert.deepEqual(response, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-cross-goal",
      status: "error",
      code: "request-invalid",
    });
    assert.equal(JSON.stringify(response).includes("SENTINEL"), false);
    assert.equal(state.proposals.length, 0);
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});

test("skill bridge preserves one effect when the peer closes before response", async () => {
  const fixtureRoot = await temporaryRoot();
  let releaseAdmission;
  const admissionGate = new Promise((resolve) => {
    releaseAdmission = resolve;
  });
  let proposalSeen;
  const proposalGate = new Promise((resolve) => {
    proposalSeen = resolve;
  });
  const state = await createBridge(fixtureRoot, {
    async emitActionProposal(event) {
      state.proposals.push(event);
      proposalSeen();
    },
    async waitForAdmission() {
      await admissionGate;
      return { resolution: "admitted", reasonCode: "authorized" };
    },
  });
  try {
    await exchange(state.bridge.socketPath, applicationRequest(), {
      closeAfterWrite: true,
    });
    await proposalGate;
    releaseAdmission();
    const recovered = await exchange(
      state.bridge.socketPath,
      applicationRequest({ request_id: "request-recovery" }),
    );
    assert.equal(recovered.status, "ok");
    assert.equal(state.proposals.length, 1);
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});

test("skill bridge serves safe queries and enforces request and response caps", async () => {
  const fixtureRoot = await temporaryRoot();
  const state = await createBridge(fixtureRoot, {
    async actionStatus() {
      return { detail: "SENTINEL_PRIVATE_STATUS".repeat(10_000) };
    },
  });
  try {
    const portfolio = await exchange(state.bridge.socketPath, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-portfolio",
      session_id: "session-1",
      operation: "portfolio.get",
      payload: {},
    });
    assert.deepEqual(portfolio.result, [TARGET]);
    const budget = await exchange(state.bridge.socketPath, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-budget",
      session_id: "session-1",
      operation: "budget.get",
      payload: {},
    });
    assert.deepEqual(budget.result, BUDGET);

    const oversizedStatus = await exchange(state.bridge.socketPath, {
      protocol: "asterion.skill-control/v1",
      request_id: "request-status",
      session_id: "session-1",
      operation: "action.status",
      payload: { action_id: "action-1" },
    });
    assert.equal(oversizedStatus.code, "response-too-large");
    assert.equal(JSON.stringify(oversizedStatus).includes("SENTINEL"), false);

    const socket = createConnection(state.bridge.socketPath);
    await new Promise((resolve) => socket.once("connect", resolve));
    socket.write(
      `${JSON.stringify({
        protocol: "asterion.skill-control/v1",
        type: "authenticate",
        token: TOKEN,
        session_id: "session-1",
      })}\n${"x".repeat(MAX_SKILL_FRAME_BYTES + 1)}\n`,
    );
    const line = await readLine(socket);
    const oversizedRequest = JSON.parse(line);
    assert.equal(oversizedRequest.code, "request-too-large");
    socket.destroy();
  } finally {
    await state.bridge.close();
    await fixtureRoot.cleanup();
  }
});
