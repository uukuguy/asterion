import assert from "node:assert/strict";
import test from "node:test";

import {
  MAX_DAEMON_JSON_DEPTH,
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

test("daemon wire rejects malformed create configuration before encoding", () => {
  assertFixedProtocolError(() => encodePrimeDaemonCommand({
    type: "create",
    config: "SENTINEL_PRIVATE_CONFIGURATION",
  }, "create-invalid", "asterion-client-1"));
});

test("daemon wire rejects unbounded create configuration fields", () => {
  assertFixedProtocolError(() => encodePrimeDaemonCommand({
    type: "create",
    config: { cwd: "/private/workspace", injected: "SENTINEL" },
  }, "create-extra", "asterion-client-1"));
});

test("daemon wire rejects unbounded create runtime metadata", () => {
  assertFixedProtocolError(() => encodePrimeDaemonCommand({
    type: "create",
    runtimeMetadata: {
      kind: "subagent",
      createdAt: 1,
      injected: "SENTINEL_RUNTIME_METADATA",
    },
  }, "create-metadata-extra", "asterion-client-1"));
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
    JSON.stringify({
      id: "oversized-response",
      type: "response",
      command: "get_state",
      success: true,
      data: "SENTINEL".repeat(MAX_DAEMON_LINE_BYTES),
    }),
    JSON.stringify({ type: "response", success: true }),
    JSON.stringify({
      id: "inherited-command",
      type: "response",
      command: "toString",
      success: true,
    }),
    JSON.stringify({ type: "toString" }),
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

test("daemon wire admits metadata-only daemon list reads", () => {
  const line = encodePrimeDaemonCommand(
    { type: "list", all: true },
    "asterion-list-1",
    "asterion-client-1",
  );
  assert.deepEqual(JSON.parse(line).command, {
    id: "asterion-list-1",
    type: "list",
    all: true,
  });
});

test("daemon wire admits only the pinned session command shapes", () => {
  const commands = [
    { type: "abort_branch_summary", activeSessionId: "prime-root" },
    { type: "abort_compaction", activeSessionId: "prime-root" },
    {
      type: "set_auto_compaction",
      activeSessionId: "prime-root",
      enabled: false,
    },
    {
      type: "compact",
      activeSessionId: "prime-root",
      customInstructions: "private compact instructions",
    },
    {
      type: "delete_saved_session",
      activeSessionId: "prime-root",
      sessionPath: "/private/session.jsonl",
    },
    {
      type: "fork",
      activeSessionId: "prime-root",
      entryId: "entry-1",
      position: "at",
    },
    { type: "get_session_stats", activeSessionId: "prime-root" },
    { type: "get_session_tree", activeSessionId: "prime-root" },
    { type: "get_state", activeSessionId: "prime-root" },
    {
      type: "navigate_tree",
      activeSessionId: "prime-root",
      targetId: "entry-2",
      summarize: true,
      customInstructions: "private branch instructions",
      replaceInstructions: false,
      label: "private label",
    },
    {
      type: "rename_saved_session",
      sessionPath: "/private/session.jsonl",
      name: "private saved name",
    },
    {
      type: "set_session_entry_label",
      activeSessionId: "prime-root",
      entryId: "entry-2",
      label: "private label",
    },
    {
      type: "set_session_name",
      activeSessionId: "prime-root",
      name: "private live name",
    },
    {
      type: "switch_session",
      activeSessionId: "prime-root",
      sessionPath: "/private/session.jsonl",
      cwdOverride: "/private/workspace",
    },
  ];

  for (const [index, command] of commands.entries()) {
    const id = `session-command-${index}`;
    const encoded = JSON.parse(
      encodePrimeDaemonCommand(command, id, "asterion-client-1"),
    );
    assert.deepEqual(encoded.command, { id, ...command });
  }

  for (const command of [
    { type: "clone", activeSessionId: "prime-root" },
    {
      type: "set_auto_compaction",
      activeSessionId: "prime-root",
      enabled: true,
    },
    { type: "toString", activeSessionId: "prime-root" },
    {
      type: "fork",
      activeSessionId: "prime-root",
      entryId: "entry-1",
      position: "after",
    },
    {
      type: "set_session_name",
      activeSessionId: "prime-root",
      name: "name",
      workerToken: "SENTINEL_WORKER_TOKEN",
    },
    {
      type: "delete_saved_session",
      sessionPath: "/private/session.jsonl",
      recursive: true,
    },
    {
      type: "navigate_tree",
      activeSessionId: "prime-root",
      targetId: "entry-1",
      summarize: "yes",
    },
  ]) {
    assertFixedProtocolError(() =>
      encodePrimeDaemonCommand(command, "invalid-command", "asterion-client-1"),
    );
  }
});

test("daemon wire validates prompt content and images as exact closed values", () => {
  const image = {
    type: "image",
    data: Buffer.from("private image bytes").toString("base64"),
    mimeType: "image/png",
  };
  const line = encodePrimeDaemonCommand(
    {
      type: "prompt",
      activeSessionId: "prime-root",
      message: "private prompt",
      content: [{ type: "text", text: "private text" }, image],
      images: [image],
    },
    "image-command",
    "asterion-client-1",
  );
  assert.deepEqual(JSON.parse(line).command.content, [
    { type: "text", text: "private text" },
    image,
  ]);

  for (const invalidContent of [
    [{ type: "text", text: "private", textSignature: "SENTINEL_SIGNATURE" }],
    [{ ...image, mimeType: "text/plain" }],
    [{ ...image, data: "not-canonical-base64" }],
    [{ ...image, nextBuildField: true }],
    [],
  ]) {
    assertFixedProtocolError(() =>
      encodePrimeDaemonCommand(
        {
          type: "prompt",
          activeSessionId: "prime-root",
          message: "private prompt",
          content: invalidContent,
        },
        "invalid-image-command",
        "asterion-client-1",
      ),
    );
  }

  for (const mimeType of ["application/octet-stream", "image/svg+xml"]) {
    assertFixedProtocolError(() =>
      encodePrimeDaemonCommand(
        {
          type: "prompt",
          activeSessionId: "prime-root",
          message: "private prompt",
          images: [{ ...image, mimeType }],
        },
        "invalid-image-list-command",
        "asterion-client-1",
      ),
    );
  }
});

test("daemon wire bounds response depth and strips private failure text", () => {
  let nested = { value: true };
  for (let index = 0; index < MAX_DAEMON_JSON_DEPTH + 2; index += 1) {
    nested = { nested };
  }
  assertFixedProtocolError(() =>
    decodePrimeDaemonLine(JSON.stringify({
      id: "deep-response",
      type: "response",
      command: "get_state",
      success: true,
      data: nested,
    })),
  );

  const decoded = decodePrimeDaemonLine(JSON.stringify({
    id: "failed-response",
    type: "response",
    command: "switch_session",
    success: false,
    error: "SENTINEL_PRIVATE_DAEMON_ERROR",
  }));
  assert.deepEqual(decoded, {
    id: "failed-response",
    type: "response",
    command: "switch_session",
    success: false,
  });
  assert.equal(JSON.stringify(decoded).includes("SENTINEL"), false);

  assertFixedProtocolError(() =>
    decodePrimeDaemonLine(JSON.stringify({
      id: "next-build-response",
      type: "response",
      command: "switch_session",
      success: false,
      error: "private",
      errorInfo: {
        code: "command_result_uncertain",
        clientId: "asterion-client-1",
        commandId: "next-build-response",
        nextBuildField: "SENTINEL",
      },
    })),
  );
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
