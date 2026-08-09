import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_DAEMON_LINE_BYTES,
  PrimeDaemonCompatibilityError,
  PrimeDaemonProtocolError,
  REQUIRED_SERVER_CAPABILITIES,
  assertPrimeDaemonCompatible,
  cursorFromPrimeDaemonOutbound,
  decodePrimeDaemonLine,
  encodePrimeDaemonCommand,
} from "../dist/src/index.js";
import { defaultServerCapabilities } from "./fixtures/fake-prime-daemon.mjs";

function hello(overrides = {}) {
  return {
    type: "daemon_hello",
    socketPath: "/private/SENTINEL_SOCKET",
    protocol: { name: "prime-agent.daemon", version: 7 },
    schemaId: "protocol-7-schema-14-816309b1cd50",
    schemaRevision: 14,
    appVersion: "0.7.1",
    runtime: {
      buildId: "build-1",
      executablePath: "/private/SENTINEL_EXECUTABLE",
    },
    supervisorGeneration: "generation-1",
    supervisorPid: 123,
    clientId: "daemon-client-1",
    serverCapabilities: defaultServerCapabilities,
    ...overrides,
  };
}

function assertFixedProtocolError(action) {
  assert.throws(action, (error) => {
    assert.ok(error instanceof PrimeDaemonProtocolError);
    assert.equal(error.message, "Prime daemon protocol violation");
    assert.equal(error.message.includes("SENTINEL"), false);
    return true;
  });
}

test("daemon wire exposes the exact required capability set", () => {
  assert.deepEqual(REQUIRED_SERVER_CAPABILITIES, [
    "attach_snapshot",
    "chunked_snapshot",
    "event_sequence",
    "prompt_admission_cancellation",
    "session_input_admission",
  ]);
  assert.ok(Object.isFrozen(REQUIRED_SERVER_CAPABILITIES));
});

test("daemon wire decodes and sanitizes the pinned hello", () => {
  const decoded = decodePrimeDaemonLine(JSON.stringify(hello()));
  assert.deepEqual(decoded, {
    type: "daemon_hello",
    protocolVersion: 7,
    schemaId: "protocol-7-schema-14-816309b1cd50",
    schemaRevision: 14,
    appVersion: "0.7.1",
    runtimeBuildId: "build-1",
    supervisorGeneration: "generation-1",
    clientId: "daemon-client-1",
    serverCapabilities: defaultServerCapabilities,
  });
  assertPrimeDaemonCompatible(decoded);
  assert.equal(JSON.stringify(decoded).includes("SENTINEL"), false);
  assert.ok(Object.isFrozen(decoded));
  assert.ok(Object.isFrozen(decoded.serverCapabilities));
});

test("daemon wire rejects every compatibility drift with one safe error", () => {
  for (const changed of [
    { protocol: { name: "prime-agent.daemon", version: 6 } },
    { schemaId: "wrong" },
    { schemaRevision: 13 },
    { appVersion: "0.7.0" },
    { runtime: { executablePath: "/private/SENTINEL" } },
    { supervisorGeneration: undefined },
    {
      serverCapabilities: defaultServerCapabilities.filter(
        (value) => value !== "session_input_admission",
      ),
    },
  ]) {
    const decoded = decodePrimeDaemonLine(JSON.stringify(hello(changed)));
    assert.throws(
      () => assertPrimeDaemonCompatible(decoded),
      (error) => {
        assert.ok(error instanceof PrimeDaemonCompatibilityError);
        assert.equal(error.message, "Prime daemon is incompatible");
        assert.equal(error.message.includes("SENTINEL"), false);
        return true;
      },
    );
  }
});

test("daemon wire rejects malformed, oversized, missing, and unknown values", () => {
  for (const line of [
    "{SENTINEL_INVALID_JSON",
    "x".repeat(MAX_DAEMON_LINE_BYTES + 1),
    JSON.stringify({ type: "response", success: true }),
    JSON.stringify({ type: "SENTINEL_UNKNOWN_OUTBOUND" }),
    JSON.stringify({ ...hello(), unexpected: true }),
  ]) {
    assertFixedProtocolError(() => decodePrimeDaemonLine(line));
  }
});

test("daemon wire rejects missing fields for every consumed event family", () => {
  for (const value of [
    { type: "session_event", activeSessionId: "prime-root" },
    { type: "session_snapshot_begin", activeSessionId: "prime-root" },
    { type: "session_closed", activeSessionId: "prime-root" },
    { type: "extension_ui_request", activeSessionId: "prime-root" },
  ]) {
    assertFixedProtocolError(() => decodePrimeDaemonLine(JSON.stringify(value)));
  }
});

test("daemon wire emits a stable v7 mutation envelope", () => {
  const sentinel = "SENTINEL_PRIVATE_PROMPT";
  const line = encodePrimeDaemonCommand(
    { type: "prompt", activeSessionId: "prime-root", message: sentinel },
    "asterion-command-1",
    "asterion-client-1",
  );
  assert.deepEqual(JSON.parse(line), {
    type: "command",
    id: "asterion-command-1",
    protocol: { name: "prime-agent.daemon", version: 7 },
    clientId: "asterion-client-1",
    command: {
      id: "asterion-command-1",
      type: "prompt",
      activeSessionId: "prime-root",
      message: sentinel,
    },
  });
  assert.equal(line.endsWith("\n"), true);
});

test("daemon wire preserves only a valid generation-aware event cursor", () => {
  const decoded = decodePrimeDaemonLine(
    JSON.stringify({
      type: "session_status",
      activeSessionId: "prime-root",
      meta: {
        id: "event-3",
        protocol: { name: "prime-agent.daemon", version: 7 },
        activeSessionId: "prime-root",
        sequence: 3,
        cursor: { generation: "worker-generation-1", sequence: 3 },
        emittedAt: "2026-08-10T00:00:00Z",
      },
    }),
  );
  assert.deepEqual(cursorFromPrimeDaemonOutbound(decoded), {
    generation: "worker-generation-1",
    sequence: 3,
  });
  assert.ok(Object.isFrozen(cursorFromPrimeDaemonOutbound(decoded)));
});
