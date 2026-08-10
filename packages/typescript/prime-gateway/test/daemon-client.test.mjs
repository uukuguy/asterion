import assert from "node:assert/strict";
import test from "node:test";

import {
  PrimeDaemonClient,
  PrimeDaemonCompatibilityError,
  PrimeDaemonProtocolError,
  PrimeDaemonTimeoutError,
  PrimeDaemonUncertainError,
} from "../dist/src/index.js";
import {
  defaultServerCapabilities,
  startFakePrimeDaemon,
} from "./fixtures/fake-prime-daemon.mjs";

function client(options = {}) {
  return new PrimeDaemonClient({
    clientId: "asterion-client-1",
    connectTimeoutMs: 250,
    requestTimeoutMs: 250,
    ...options,
  });
}

test("daemon client rejects a stale handshake before create", async () => {
  const daemon = await startFakePrimeDaemon({ protocol: 6 });
  const subject = client();
  try {
    await assert.rejects(
      subject.connect(daemon.socketPath),
      PrimeDaemonCompatibilityError,
    );
    assert.deepEqual(daemon.commands, []);
    assert.equal(await daemon.mode(), 0o700);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client rejects capability drift before any command", async () => {
  const daemon = await startFakePrimeDaemon({
    capabilities: defaultServerCapabilities.filter(
      (value) => value !== "prompt_admission_cancellation",
    ),
  });
  const subject = client();
  try {
    await assert.rejects(
      subject.connect(daemon.socketPath),
      PrimeDaemonCompatibilityError,
    );
    assert.deepEqual(daemon.commands, []);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client rejects an unexpected initial runtime build", async () => {
  const daemon = await startFakePrimeDaemon({ buildId: "prime-build-other" });
  const subject = client({ expectedRuntimeBuildId: "prime-build-locked" });
  try {
    await assert.rejects(
      subject.connect(daemon.socketPath),
      PrimeDaemonCompatibilityError,
    );
    assert.deepEqual(daemon.commands, []);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client replays one stable mutation envelope after disconnect", async () => {
  const daemon = await startFakePrimeDaemon({
    disconnectFirstMutation: true,
    greetings: [
      { supervisorGeneration: "generation-1" },
      { supervisorGeneration: "generation-2" },
    ],
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.request(
      {
        type: "prompt",
        activeSessionId: "prime-root",
        message: "SENTINEL_PRIVATE_PROMPT",
      },
      "asterion-command-1",
    );
    await daemon.waitForDeliveries("asterion-command-1", 1);
    await subject.reconnect();
    const response = await pending;

    assert.equal(response.success, true);
    assert.equal(daemon.deliveryCount("asterion-command-1"), 2);
    assert.equal(daemon.mutationCount("asterion-command-1"), 1);
    const replayed = daemon.rawCommands.filter(
      (line) => JSON.parse(line).id === "asterion-command-1",
    );
    assert.equal(replayed.length, 2);
    assert.equal(replayed[0], replayed[1]);
    assert.deepEqual(
      daemon.commands
        .filter((envelope) => envelope.id === "asterion-command-1")
        .map((envelope) => envelope.clientId),
      ["asterion-client-1", "asterion-client-1"],
    );
    assert.equal(subject.hello.supervisorGeneration, "generation-2");
    await daemon.waitForAcknowledgement("asterion-command-1");
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client rejects replay when reconnect capabilities downgrade", async () => {
  const daemon = await startFakePrimeDaemon({
    disconnectFirstMutation: true,
    greetings: [
      {},
      {
        capabilities: defaultServerCapabilities.filter(
          (value) => value !== "session_input_admission",
        ),
      },
    ],
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.request(
      { type: "prompt", activeSessionId: "prime-root", message: "private" },
      "asterion-command-downgrade",
    );
    const rejected = assert.rejects(pending, PrimeDaemonCompatibilityError);
    await daemon.waitForDeliveries("asterion-command-downgrade", 1);
    await assert.rejects(subject.reconnect(), PrimeDaemonCompatibilityError);
    await rejected;
    assert.equal(daemon.deliveryCount("asterion-command-downgrade"), 1);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client pins the runtime build before replay", async () => {
  const commandId = "asterion-command-build-drift";
  const daemon = await startFakePrimeDaemon({
    disconnectFirstMutation: true,
    greetings: [
      { buildId: "prime-build-locked" },
      { buildId: "prime-build-next" },
    ],
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.request(
      { type: "get_state", activeSessionId: "prime-root" },
      commandId,
    );
    const rejected = assert.rejects(pending, PrimeDaemonCompatibilityError);
    await daemon.waitForDeliveries(commandId, 1);
    await assert.rejects(subject.reconnect(), PrimeDaemonCompatibilityError);
    await rejected;
    assert.equal(daemon.deliveryCount(commandId), 1);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client acknowledges and classifies a structured uncertain result", async () => {
  const daemon = await startFakePrimeDaemon({
    uncertainCommandIds: ["asterion-command-uncertain"],
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    await assert.rejects(
      subject.request(
        { type: "abort", activeSessionId: "prime-root" },
        "asterion-command-uncertain",
      ),
      (error) => {
        assert.ok(error instanceof PrimeDaemonUncertainError);
        assert.equal(error.commandId, "asterion-command-uncertain");
        assert.equal(error.message, "Prime daemon mutation result is uncertain");
        assert.equal(error.message.includes("private uncertain detail"), false);
        return true;
      },
    );
    await daemon.waitForAcknowledgement("asterion-command-uncertain");
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client defers an uncertain acknowledgement until it is durable", async () => {
  const commandId = "asterion-command-deferred-uncertain";
  const daemon = await startFakePrimeDaemon({
    uncertainCommandIds: [commandId],
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const deferred = await subject.requestDeferred(
      { type: "compact", activeSessionId: "prime-root" },
      commandId,
    );
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(deferred.response.success, false);
    assert.deepEqual(deferred.response.errorInfo, {
      code: "command_result_uncertain",
      clientId: "asterion-client-1",
      commandId,
    });
    assert.equal(daemon.acknowledgements.includes(commandId), false);
    assert.equal(deferred.acknowledge(), true);
    await daemon.waitForAcknowledgement(commandId);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client rejects a deferred uncertain marker for another identity", async () => {
  const commandId = "asterion-command-mismatched-uncertain";
  const daemon = await startFakePrimeDaemon({ silentCommandIds: [commandId] });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.requestDeferred(
      { type: "compact", activeSessionId: "prime-root" },
      commandId,
    );
    const rejected = assert.rejects(pending, PrimeDaemonProtocolError);
    await daemon.waitForDeliveries(commandId, 1);
    daemon.broadcastRaw(`${JSON.stringify({
      id: commandId,
      type: "response",
      command: "compact",
      success: false,
      error: "private uncertain detail",
      errorInfo: {
        code: "command_result_uncertain",
        clientId: "another-client",
        commandId: "another-command",
      },
    })}\n`);
    await rejected;
    assert.equal(daemon.acknowledgements.includes(commandId), false);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client defers acknowledgement until durable identity binding", async () => {
  const daemon = await startFakePrimeDaemon({
    responseData: { fork: { cancelled: false } },
  });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const deferred = await subject.requestDeferred(
      {
        type: "fork",
        activeSessionId: "prime-root",
        entryId: "entry-1",
        position: "at",
      },
      "asterion-command-deferred",
    );
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(
      daemon.acknowledgements.includes("asterion-command-deferred"),
      false,
    );
    deferred.acknowledge();
    await daemon.waitForAcknowledgement("asterion-command-deferred");
    assert.equal(deferred.response.success, true);
    assert.deepEqual(deferred.response.data, { cancelled: false });
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client rejects a response correlated to the wrong command", async () => {
  const commandId = "asterion-command-mismatch";
  const daemon = await startFakePrimeDaemon({ silentCommandIds: [commandId] });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.request(
      { type: "get_state", activeSessionId: "prime-root" },
      commandId,
    );
    const rejected = assert.rejects(pending, PrimeDaemonProtocolError);
    await daemon.waitForDeliveries(commandId, 1);
    daemon.broadcastRaw(`${JSON.stringify({
      id: commandId,
      type: "response",
      command: "get_session_stats",
      success: true,
      data: {},
    })}\n`);
    await rejected;
    assert.equal(daemon.acknowledgements.includes(commandId), false);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client never exposes private daemon failure text", async () => {
  const commandId = "asterion-command-private-failure";
  const daemon = await startFakePrimeDaemon({ silentCommandIds: [commandId] });
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    const pending = subject.request(
      {
        type: "switch_session",
        activeSessionId: "prime-root",
        sessionPath: "/private/SENTINEL_SESSION.jsonl",
      },
      commandId,
    );
    await daemon.waitForDeliveries(commandId, 1);
    daemon.broadcastRaw(`${JSON.stringify({
      id: commandId,
      type: "response",
      command: "switch_session",
      success: false,
      error: "SENTINEL_PRIVATE_DAEMON_ERROR",
    })}\n`);
    const response = await pending;
    assert.deepEqual(response, {
      id: commandId,
      type: "response",
      command: "switch_session",
      success: false,
    });
    assert.equal(JSON.stringify(response).includes("SENTINEL"), false);
    await daemon.waitForAcknowledgement(commandId);
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client times out without rendering a private command", async () => {
  const daemon = await startFakePrimeDaemon({
    silentCommandIds: ["asterion-command-timeout"],
  });
  const subject = client({ requestTimeoutMs: 30 });
  try {
    await subject.connect(daemon.socketPath);
    await assert.rejects(
      subject.request(
        {
          type: "prompt",
          activeSessionId: "prime-root",
          message: "SENTINEL_PRIVATE_PROMPT",
        },
        "asterion-command-timeout",
      ),
      (error) => {
        assert.ok(error instanceof PrimeDaemonTimeoutError);
        assert.equal(error.message, "Prime daemon request timed out");
        assert.equal(error.message.includes("SENTINEL"), false);
        return true;
      },
    );
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client isolates subscribers on a real socket event", async () => {
  const daemon = await startFakePrimeDaemon();
  const subject = client();
  try {
    await subject.connect(daemon.socketPath);
    subject.subscribe(() => {
      throw new Error("SENTINEL_LISTENER_FAILURE");
    });
    const received = new Promise((resolve) => {
      subject.subscribe(resolve);
    });
    daemon.broadcastRaw(
      `${JSON.stringify({
        type: "session_status",
        activeSessionId: "prime-root",
        meta: {
          id: "event-1",
          protocol: { name: "prime-agent.daemon", version: 7 },
          activeSessionId: "prime-root",
          sequence: 1,
          cursor: { generation: "worker-generation-1", sequence: 1 },
          emittedAt: "2026-08-10T00:00:00Z",
        },
      })}\n`,
    );
    const event = await received;
    assert.equal(event.type, "session_status");
    assert.equal(event.activeSessionId, "prime-root");
    assert.ok(Object.isFrozen(event));
  } finally {
    subject.close();
    await daemon.close();
  }
});

test("daemon client fails closed on malformed, oversized, and unknown outbound", async () => {
  const rawValues = [
    "{SENTINEL_INVALID_JSON\n",
    `${"x".repeat(1024 * 1024 + 1)}\n`,
    `${JSON.stringify({ type: "SENTINEL_UNKNOWN_OUTBOUND" })}\n`,
  ];
  for (const raw of rawValues) {
    const commandId = `command-${rawValues.indexOf(raw)}`;
    const daemon = await startFakePrimeDaemon({
      silentCommandIds: [commandId],
    });
    const subject = client();
    try {
      await subject.connect(daemon.socketPath);
      const pending = subject.request(
        { type: "get_state", activeSessionId: "prime-root" },
        commandId,
      );
      const rejected = assert.rejects(pending, (error) => {
        assert.ok(error instanceof PrimeDaemonProtocolError);
        assert.equal(error.message, "Prime daemon protocol violation");
        assert.equal(error.message.includes("SENTINEL"), false);
        return true;
      });
      daemon.broadcastRaw(raw);
      await rejected;
    } finally {
      subject.close();
      await daemon.close();
    }
  }
});

test("daemon client times out an incomplete greeting without leaking the socket", async () => {
  const daemon = await startFakePrimeDaemon({ greetingDelayMs: 1_000 });
  const subject = client({ connectTimeoutMs: 20 });
  try {
    await assert.rejects(subject.connect(daemon.socketPath), (error) => {
      assert.ok(error instanceof PrimeDaemonTimeoutError);
      assert.equal(error.message, "Prime daemon handshake timed out");
      assert.equal(error.message.includes(daemon.socketPath), false);
      return true;
    });
  } finally {
    subject.close();
    await daemon.close();
  }
});
