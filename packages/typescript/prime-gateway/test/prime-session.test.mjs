import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import {
  encodePrimeDaemonCommand,
  PrimePromptAdmissionUncertainError,
  PrimeSession,
} from "../dist/src/index.js";

class FakeTransport {
  constructor() {
    this.commands = [];
    this.cancellationStatus = "cancelled";
    this.holdPrompts = false;
    this.promptResolvers = [];
    this.acknowledgements = [];
    this.switchResponse = { cancelled: false };
    this.deleteResponse = { ok: true, method: "unlink" };
    this.sessionFile = "/private/sessions/transcript-1.jsonl";
    this.sessionHeader = {
      type: "session",
      id: "transcript-1",
      timestamp: "2026-08-10T03:00:00Z",
      cwd: "/private/workspace",
    };
    this.sessionState = {
      id: "prime-root-1",
      lifecycle: "live",
      activity: "idle",
      isSessionActive: false,
      activeSessionId: "prime-root-1",
      sessionId: "transcript-1",
      sessionFile: this.sessionFile,
      sessionName: "session-1",
      cwd: "/private/workspace",
      isStreaming: false,
      isCompacting: false,
      attachedClients: 1,
      messageCount: 3,
      sessionActions: { queuedCount: 0, steering: [], followUps: [] },
    };
    this.sessionStats = {
      sessionFile: this.sessionFile,
      sessionId: "transcript-1",
      userMessages: 2,
      assistantMessages: 1,
      toolCalls: 0,
      toolResults: 0,
      totalMessages: 3,
      tokens: {
        input: 100,
        output: 20,
        cacheRead: 10,
        cacheWrite: 5,
        total: 135,
      },
      cost: 0.001234,
      contextUsage: { tokens: 90, contextWindow: 200_000, percent: 0.045 },
    };
    this.hello = {
      supervisorGeneration: "supervisor-generation-1",
    };
  }

  request(command, commandId) {
    encodePrimeDaemonCommand(command, commandId, "fake-client-1");
    this.commands.push({ command, commandId });
    if (command.type === "prompt" && this.holdPrompts) {
      return new Promise((resolve) => {
        this.promptResolvers.push(() => resolve({
          id: commandId,
          type: "response",
          command: "prompt",
          success: true,
          data: { accepted: true },
        }));
      });
    }
    if (command.type === "create") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: "create",
        success: true,
        data: {
          activeSessionId: "prime-root-1",
          sessionId: "transcript-1",
          sessionFile: this.sessionFile,
        },
      });
    }
    if (command.type === "get_session_header") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: { header: structuredClone(this.sessionHeader) },
      });
    }
    if (command.type === "get_state") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.sessionState),
      });
    }
    if (command.type === "get_session_stats") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.sessionStats),
      });
    }
    if (command.type === "switch_session") {
      this.sessionFile = command.sessionPath;
      this.sessionHeader.id = "transcript-2";
      this.sessionState.sessionId = "transcript-2";
      this.sessionState.sessionFile = command.sessionPath;
      this.sessionStats.sessionId = "transcript-2";
      this.sessionStats.sessionFile = command.sessionPath;
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.switchResponse),
      });
    }
    if (command.type === "delete_saved_session") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.deleteResponse),
      });
    }
    if (command.type === "attach") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: "attach",
        success: true,
        data: {
          activeSessionId: "prime-root-1",
          replay: { status: "complete", toSequence: 0 },
          lastEventSequence: 0,
          snapshot: { activeSessionId: "prime-root-1" },
        },
      });
    }
    if (command.type === "cancel_prompt_admission") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: { status: this.cancellationStatus },
      });
    }
    return Promise.resolve({
      id: commandId,
      type: "response",
      command: command.type,
      success: true,
      data: { accepted: true },
    });
  }

  subscribe() {
    return () => undefined;
  }

  acknowledgeResult(commandId) {
    this.acknowledgements.push(commandId);
    return true;
  }

  async requestDeferred(command, commandId) {
    const response = await this.request(command, commandId);
    return {
      response,
      acknowledge: () => {
        this.acknowledgements.push(commandId);
        return true;
      },
    };
  }

  releasePrompts() {
    for (const resolve of this.promptResolvers.splice(0)) {
      resolve();
    }
  }
}

const PRIVATE_CONFIG = Object.freeze({
  workspace: "/private/workspace",
  agentDir: "/private/agent",
  sessionDir: "/private/sessions",
  provider: "example-provider",
  model: "example-model",
  skillPath: "/private/skills/asterion-control",
  goal: "SENTINEL_PRIVATE_INITIAL_GOAL",
  maxContinuations: 4,
  maxTurns: 9,
  maxControllerTokens: 2_000,
  timeoutMs: 60_000,
});

test("lifecycle create binds exact resident config and disables native RLM", async () => {
  const transport = new FakeTransport();
  const identities = [];
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    async bindIdentity(identity) {
      identities.push(identity);
      assert.deepEqual(transport.acknowledgements, []);
    },
  });

  assert.equal(session.activeSessionId, "prime-root-1");
  assert.equal(session.transcriptSessionId, "transcript-1");
  assert.equal(
    session.continuationId,
    `continuation-${createHash("sha256").update("session-1").digest("hex").slice(0, 32)}`,
  );
  assert.equal(session.supervisorGeneration, "supervisor-generation-1");
  assert.deepEqual(identities, [{
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
    supervisorGeneration: "supervisor-generation-1",
    continuationId: session.continuationId,
    sessionPath: "/private/sessions/transcript-1.jsonl",
  }]);
  assert.deepEqual(transport.acknowledgements, ["session-1-create"]);
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "create",
    "get_session_header",
    "set_rlm_max_depth",
    "attach",
  ]);
  const create = transport.commands[0].command;
  assert.equal(create.lifecycle, "resident");
  assert.equal(create.sessionPath, undefined);
  assert.equal(create.config.sessionDir, PRIVATE_CONFIG.sessionDir);
  assert.deepEqual(create.config, {
    cwd: PRIVATE_CONFIG.workspace,
    agentDir: PRIVATE_CONFIG.agentDir,
    sessionDir: PRIVATE_CONFIG.sessionDir,
    provider: PRIVATE_CONFIG.provider,
    model: PRIVATE_CONFIG.model,
    skills: [PRIVATE_CONFIG.skillPath],
    autonomous: {
      enabled: true,
      maxContinuations: 4,
      maxTurns: 9,
      maxTokens: 2_000,
      timeoutMs: 60_000,
      gates: { commands: [], maxRetries: 1, timeoutMs: 60_000 },
    },
    telemetryDisabled: true,
    initialGoal: {
      objective: "SENTINEL_PRIVATE_INITIAL_GOAL",
      tokenBudget: 2_000,
    },
  });
  assert.equal(transport.commands[1].command.activeSessionId, "prime-root-1");
  assert.equal(transport.commands[2].command.maxDepth, 0);
  assert.deepEqual(transport.commands[3].command.capabilities, [
    "attach_snapshot",
    "chunked_snapshot",
    "event_sequence",
    "slim_attach",
  ]);
  const publicSession = JSON.stringify(session);
  assert.equal(publicSession.includes("SENTINEL"), false);
  assert.equal(publicSession.includes("/private/"), false);
  assert.deepEqual(JSON.parse(publicSession), {
    kind: "prime-resident-session",
    active_session_id: "prime-root-1",
    supervisor_generation: "supervisor-generation-1",
  });
});

test("lifecycle rejects a missing path or mismatched pinned header before durability acknowledgement", async () => {
  for (const mutate of [
    (transport) => {
      transport.sessionFile = undefined;
    },
    (transport) => {
      transport.sessionHeader.id = "other-transcript";
    },
    (transport) => {
      transport.sessionHeader.extra = { raw: "SENTINEL_RAW_HEADER" };
    },
  ]) {
    const transport = new FakeTransport();
    mutate(transport);
    const identities = [];
    await assert.rejects(
      PrimeSession.create({
        transport,
        sessionId: "session-1",
        privateConfig: PRIVATE_CONFIG,
        async bindIdentity(identity) {
          identities.push(identity);
        },
      }),
    );
    assert.deepEqual(identities, []);
    assert.deepEqual(transport.acknowledgements, []);
  }
});

test("context naming and describe project only digests closed status and safe monotonic counts", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.commands.length = 0;
  transport.acknowledgements.length = 0;

  const named = await session.setContextName(
    "context-name-1",
    "  SENTINEL_PRIVATE_NAME  ",
  );
  assert.deepEqual(named.result, {
    continuationId: session.continuationId,
    nameSha256: createHash("sha256").update("SENTINEL_PRIVATE_NAME").digest("hex"),
  });
  assert.deepEqual(transport.acknowledgements, []);
  assert.equal(named.acknowledge(), true);
  assert.deepEqual(transport.acknowledgements, [
    "session-1-context-context-name-1-set-name",
  ]);
  transport.sessionState.sessionName = "SENTINEL_PRIVATE_NAME";

  const described = await session.describeContext("context-describe-1", "running");
  assert.deepEqual(described, {
    continuationId: session.continuationId,
    status: "idle",
    contextTokens: 90,
    turns: 2,
    usage: {
      controller_tokens: 135,
      application_tokens: 0,
      child_tokens: 0,
      aggregate_tokens: 135,
      cost_micros: 1234,
    },
    nameSha256: createHash("sha256").update("SENTINEL_PRIVATE_NAME").digest("hex"),
  });
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "set_session_name",
    "get_state",
    "get_session_stats",
  ]);
  assert.equal(JSON.stringify(described).includes("SENTINEL"), false);
  assert.equal(JSON.stringify(described).includes("/private/"), false);
});

test("context describe rejects malformed or regressing Prime statistics", async () => {
  const invalidStats = [
    (stats) => {
      stats.userMessages = -1;
    },
    (stats) => {
      stats.assistantMessages = 1.5;
    },
    (stats) => {
      stats.tokens.total = Number.MAX_SAFE_INTEGER + 1;
    },
    (stats) => {
      stats.tokens.raw = { prompt: "SENTINEL_RAW_STATS" };
    },
    (stats) => {
      stats.contextUsage.tokens = null;
      stats.contextUsage.percent = 0;
    },
  ];
  for (const mutate of invalidStats) {
    const transport = new FakeTransport();
    const session = await PrimeSession.create({
      transport,
      sessionId: "session-1",
      privateConfig: PRIVATE_CONFIG,
      bindIdentity: async () => undefined,
    });
    mutate(transport.sessionStats);
    await assert.rejects(session.describeContext("context-invalid", "running"));
  }

  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  await session.describeContext("context-first", "running");
  transport.sessionStats.tokens.input -= 1;
  transport.sessionStats.tokens.total -= 1;
  await assert.rejects(session.describeContext("context-regressed", "running"));
});

test("context describe projects post-compaction unknown usage without rejecting valid Prime stats", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.sessionStats.contextUsage.tokens = null;
  transport.sessionStats.contextUsage.percent = null;

  const described = await session.describeContext("context-compacted", "running");

  assert.equal(described.contextTokens, 0);
});

test("continuation resume and delete defer acknowledgement until durable adoption", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.commands.length = 0;
  transport.acknowledgements.length = 0;
  const target = Object.freeze({
    continuationId: "continuation-2",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-2",
    supervisorGeneration: "supervisor-generation-1",
    sessionPath: "/private/sessions/transcript-2.jsonl",
  });

  const resumed = await session.resumeContinuation("context-resume-1", target);

  assert.deepEqual(resumed.result, {
    previousContinuationId: session.continuationId,
    currentContinuationId: "continuation-2",
    transitionSha256: resumed.result.transitionSha256,
  });
  assert.match(resumed.result.transitionSha256, /^[0-9a-f]{64}$/);
  assert.equal(session.continuationId.startsWith("continuation-"), true);
  assert.deepEqual(transport.acknowledgements, []);
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "switch_session",
    "get_session_header",
    "get_state",
  ]);

  session.adoptContinuation(resumed.locator);
  assert.equal(session.continuationId, "continuation-2");
  assert.equal(session.transcriptSessionId, "transcript-2");
  assert.equal(resumed.acknowledge(), true);

  await assert.rejects(
    session.deleteContinuation("context-delete-active", resumed.locator),
  );
  const deleted = await session.deleteContinuation("context-delete-1", {
    ...target,
    continuationId: "continuation-1",
    transcriptSessionId: "transcript-1",
    sessionPath: "/private/sessions/transcript-1.jsonl",
  });
  assert.equal(deleted.result.continuationId, "continuation-1");
  assert.match(deleted.result.deletionSha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(transport.acknowledgements, [
    "session-1-context-context-resume-1-resume",
  ]);
  assert.equal(deleted.acknowledge(), true);
});

test("continuation mutations reject cancelled failed and unknown Prime result shapes", async () => {
  for (const mutate of [
    (transport) => {
      transport.switchResponse = { cancelled: true };
    },
    (transport) => {
      transport.switchResponse = { cancelled: false, raw: "SENTINEL_RAW" };
    },
  ]) {
    const transport = new FakeTransport();
    const session = await PrimeSession.create({
      transport,
      sessionId: "session-1",
      privateConfig: PRIVATE_CONFIG,
      bindIdentity: async () => undefined,
    });
    mutate(transport);
    await assert.rejects(session.resumeContinuation("resume-invalid", {
      continuationId: "continuation-2",
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-2",
      supervisorGeneration: "supervisor-generation-1",
      sessionPath: "/private/sessions/transcript-2.jsonl",
    }));
    assert.equal(JSON.stringify(session).includes("SENTINEL"), false);
  }

  for (const deleteResponse of [
    { ok: false, error: "SENTINEL_PRIVATE_DELETE" },
    { ok: true, method: "unlink", raw: "SENTINEL_RAW" },
  ]) {
    const transport = new FakeTransport();
    const session = await PrimeSession.create({
      transport,
      sessionId: "session-1",
      privateConfig: PRIVATE_CONFIG,
      bindIdentity: async () => undefined,
    });
    transport.deleteResponse = deleteResponse;
    await assert.rejects(session.deleteContinuation("delete-invalid", {
      continuationId: "continuation-2",
      activeSessionId: "prime-root-1",
      transcriptSessionId: "transcript-2",
      supervisorGeneration: "supervisor-generation-1",
      sessionPath: "/private/sessions/transcript-2.jsonl",
    }));
    assert.equal(JSON.stringify(session).includes("SENTINEL"), false);
  }
});

test("lifecycle adopts one restored resident identity without creating a new root", async () => {
  const transport = new FakeTransport();
  transport.hello = {
    supervisorGeneration: "supervisor-generation-2",
  };

  const session = PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
  });

  assert.equal(session.activeSessionId, "prime-root-1");
  assert.equal(session.transcriptSessionId, "transcript-1");
  assert.equal(session.supervisorGeneration, "supervisor-generation-2");
  assert.deepEqual(transport.commands, []);
});

test("lifecycle adopts a distinct recovery transport before new input", async () => {
  const original = new FakeTransport();
  const recovered = new FakeTransport();
  recovered.hello = { supervisorGeneration: "supervisor-generation-2" };
  const session = PrimeSession.restore({
    transport: original,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
  });

  session.adoptRecovery({
    transport: recovered,
    primeCursor: { generation: "prime-events-2", sequence: 8 },
    transcriptSessionId: "transcript-1",
    supervisorGeneration: "supervisor-generation-2",
    sessionStatus: "running",
  });
  await session.submitInput("input-recovered", "direct", "private recovered input");

  assert.equal(session.supervisorGeneration, "supervisor-generation-2");
  assert.deepEqual(original.commands, []);
  assert.deepEqual(recovered.commands.map(({ command }) => command.type), ["prompt"]);
});

test("lifecycle maps input modes pause resume detach and cancellation cascade", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.commands.length = 0;

  await session.submitInput("input-1", "direct", "private direct");
  await session.submitInput("input-2", "steer", "private steer");
  await session.submitInput("input-3", "follow_up", "private follow up");
  await session.pause("pause-1");
  await session.resume("resume-1");
  await session.detach("detach-1");
  await session.cancel("cancel-1");

  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "prompt",
    "prompt",
    "prompt",
    "abort_and_clear_queue",
    "wait_for_idle",
    "prompt",
    "detach",
    "abort_and_clear_queue",
    "kill",
  ]);
  assert.equal(transport.commands[0].command.streamingBehavior, undefined);
  assert.equal(transport.commands[1].command.streamingBehavior, "steer");
  assert.equal(transport.commands[2].command.streamingBehavior, "followUp");
  assert.equal(transport.commands[5].command.message, "Continue the active goal.");
  assert.equal(transport.commands[5].command.expandPromptTemplates, false);
  assert.equal(transport.commands[6].command.activeSessionId, "prime-root-1");
});

test("lifecycle retries one deterministic checkpoint acknowledgement", async () => {
  const transport = new FakeTransport();
  const session = PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
  });

  assert.equal(session.acknowledgeCheckpoint("checkpoint-1"), true);
  assert.deepEqual(transport.acknowledgements, [
    "session-1-checkpoint-checkpoint-1-prepare",
  ]);
});

test("lifecycle classifies prompt admission cancellation without guessing", async () => {
  for (const status of ["cancelled", "owned", "unknown"]) {
    const transport = new FakeTransport();
    transport.cancellationStatus = status;
    const session = await PrimeSession.create({
      transport,
      sessionId: "session-1",
      privateConfig: PRIVATE_CONFIG,
      bindIdentity: async () => undefined,
    });
    if (status === "unknown") {
      await assert.rejects(
        session.cancelPromptAdmission("admission-1"),
        PrimePromptAdmissionUncertainError,
      );
    } else {
      assert.equal(await session.cancelPromptAdmission("admission-1"), status);
    }
  }
});

test("lifecycle fences every pending prompt before pause", async () => {
  for (const status of ["cancelled", "owned", "unknown"]) {
    const transport = new FakeTransport();
    transport.cancellationStatus = status;
    const session = await PrimeSession.create({
      transport,
      sessionId: "session-1",
      privateConfig: PRIVATE_CONFIG,
      bindIdentity: async () => undefined,
    });
    transport.commands.length = 0;
    transport.holdPrompts = true;
    const pending = session.submitInput("input-pending", "direct", "private");
    await Promise.resolve();
    const pause = session.pause("pause-pending");
    if (status === "unknown") {
      await assert.rejects(pause, PrimePromptAdmissionUncertainError);
    } else {
      await pause;
    }
    assert.deepEqual(transport.commands.map(({ command }) => command.type), [
      "prompt",
      "cancel_prompt_admission",
      "abort_and_clear_queue",
    ]);
    transport.releasePrompts();
    await pending;
  }
});
