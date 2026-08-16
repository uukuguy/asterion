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
    this.forkResponse = { cancelled: false };
    this.forkSequence = 0;
    this.navigateResponse = { cancelled: false };
    this.compactResponse = {
      summary: "SENTINEL_PRIVATE_COMPACTION_SUMMARY",
      firstKeptEntryId: "entry-2",
      tokensBefore: 90,
    };
    this.modelFailure = undefined;
    this.holdModelOperations = false;
    this.modelResolvers = [];
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
    this.sessionTree = {
      flatNodes: [
        {
          entry: {
            type: "message",
            id: "entry-1",
            parentId: null,
            timestamp: "2026-08-10T03:00:00Z",
            message: {
              role: "user",
              content: "SENTINEL_PRIVATE_TREE_INPUT",
              timestamp: 1,
            },
          },
        },
        {
          entry: {
            type: "message",
            id: "entry-2",
            parentId: "entry-1",
            timestamp: "2026-08-10T03:00:01Z",
            message: {
              role: "assistant",
              content: [{ type: "text", text: "SENTINEL_PRIVATE_TREE_OUTPUT" }],
              api: "messages",
              provider: "private-provider",
              model: "private-model",
              usage: {
                input: 1,
                output: 2,
                cacheRead: 0,
                cacheWrite: 0,
                totalTokens: 3,
                cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
              },
              stopReason: "stop",
              timestamp: 2,
            },
          },
          label: "SENTINEL_PRIVATE_TREE_LABEL",
        },
      ],
      leafId: "entry-2",
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
      if (command.lifecycle === "client_owned") {
        return Promise.resolve({
          id: commandId,
          type: "response",
          command: "create",
          success: true,
          data: {
            activeSessionId: "prime-child-1",
            sessionId: "transcript-child-1",
            sessionFile: "/private/sessions/transcript-child-1.jsonl",
          },
        });
      }
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
    if (command.type === "get_session_tree") {
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.sessionTree),
      });
    }
    if (command.type === "navigate_tree") {
      if (command.summarize === true) {
        const respond = () => {
          if (this.modelFailure !== undefined) {
            return {
              id: commandId,
              type: "response",
              command: command.type,
              success: false,
              ...this.modelFailure,
            };
          }
          const summaryEntry = {
            type: "branch_summary",
            id: "summary-entry-1",
            parentId: command.targetId,
            timestamp: "2026-08-10T03:00:02Z",
            fromId: command.targetId,
            summary: "SENTINEL_PRIVATE_BRANCH_SUMMARY",
            details: { readFiles: [], modifiedFiles: [] },
            fromHook: false,
          };
          this.sessionTree.flatNodes.push({ entry: summaryEntry });
          this.sessionTree.leafId = summaryEntry.id;
          this.sessionStats.tokens.input += 8;
          this.sessionStats.tokens.output += 4;
          this.sessionStats.tokens.total += 12;
          this.sessionStats.cost += 0.0003;
          this.sessionStats.contextUsage.tokens = 102;
          return {
            id: commandId,
            type: "response",
            command: command.type,
            success: true,
            data: { cancelled: false, summaryEntry },
          };
        };
        if (this.holdModelOperations) {
          return new Promise((resolve) => this.modelResolvers.push(
            () => resolve(respond()),
          ));
        }
        return Promise.resolve(respond());
      }
      if (this.navigateResponse.cancelled === false) {
        const target = this.sessionTree.flatNodes.find(
          ({ entry }) => entry.id === command.targetId,
        )?.entry;
        this.sessionTree.leafId = target?.type === "message" &&
            target.message.role === "user"
          ? target.parentId
          : command.targetId;
      }
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.navigateResponse),
      });
    }
    if (command.type === "compact") {
      const respond = () => {
        if (this.modelFailure !== undefined) {
          return {
            id: commandId,
            type: "response",
            command: command.type,
            success: false,
            ...this.modelFailure,
          };
        }
        const entry = {
          type: "compaction",
          id: "compaction-entry-1",
          parentId: "entry-2",
          timestamp: "2026-08-10T03:00:02Z",
          summary: this.compactResponse.summary,
          firstKeptEntryId: this.compactResponse.firstKeptEntryId,
          tokensBefore: this.compactResponse.tokensBefore,
        };
        this.sessionTree.flatNodes.push({ entry });
        this.sessionTree.leafId = entry.id;
        this.sessionStats.tokens.input += 12;
        this.sessionStats.tokens.output += 8;
        this.sessionStats.tokens.total += 20;
        this.sessionStats.cost += 0.0005;
        this.sessionStats.contextUsage.tokens = 40;
        return {
          id: commandId,
          type: "response",
          command: command.type,
          success: true,
          data: structuredClone(this.compactResponse),
        };
      };
      if (this.holdModelOperations) {
        return new Promise((resolve) => this.modelResolvers.push(
          () => resolve(respond()),
        ));
      }
      return Promise.resolve(respond());
    }
    if (command.type === "set_session_entry_label") {
      const target = this.sessionTree.flatNodes.find(
        ({ entry }) => entry.id === command.entryId,
      );
      if (target === undefined) {
        return Promise.resolve({
          id: commandId,
          type: "response",
          command: command.type,
          success: false,
        });
      }
      if (command.label === undefined) {
        delete target.label;
      } else {
        target.label = command.label;
      }
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
      });
    }
    if (command.type === "fork") {
      if (this.forkResponse.cancelled === false) {
        this.forkSequence += 1;
        const transcriptId = `transcript-fork-${this.forkSequence}`;
        this.sessionFile = `/private/sessions/${transcriptId}.jsonl`;
        this.sessionHeader.id = transcriptId;
        this.sessionState.sessionId = transcriptId;
        this.sessionState.sessionFile = this.sessionFile;
        this.sessionStats.sessionId = transcriptId;
        this.sessionStats.sessionFile = this.sessionFile;
        const selected = this.sessionTree.flatNodes.find(
          ({ entry }) => entry.id === command.entryId,
        )?.entry;
        this.sessionTree.leafId = command.position === "before"
          ? selected?.parentId ?? null
          : command.entryId;
      }
      return Promise.resolve({
        id: commandId,
        type: "response",
        command: command.type,
        success: true,
        data: structuredClone(this.forkResponse),
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

  releaseModelOperations() {
    for (const resolve of this.modelResolvers.splice(0)) {
      resolve();
    }
  }
}

const MODEL_BUDGET = Object.freeze({
  controller_tokens: 50,
  application_tokens: 0,
  child_tokens: 0,
  aggregate_tokens: 50,
  cost_micros: 5_000,
  deadline_ms: 30_000,
});

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
  assert.deepEqual(transport.acknowledgements, [
    "session-1-create-materialize",
    "session-1-create",
  ]);
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "create",
    "get_session_header",
    "set_session_name",
    "set_auto_compaction",
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
  assert.equal(transport.commands[2].command.name, "asterion-controlled");
  assert.equal(transport.commands[3].command.enabled, false);
  assert.equal(transport.commands[4].command.maxDepth, 0);
  assert.deepEqual(transport.commands[5].command.capabilities, [
    "attach_snapshot",
    "chunked_snapshot",
    "client_owned_sessions",
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

test("native RLM child uses the pinned daemon create and prompt protocol", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: { ...PRIVATE_CONFIG, rlmMaxDepth: 1 },
    async bindIdentity() {},
  });

  const child = await session.spawnNativeRlmChild(
    "native-child-1",
    "child-1",
    "SENTINEL_PRIVATE_CHILD_GOAL",
  );

  assert.deepEqual(child, {
    childId: "child-1",
    activeSessionId: "prime-child-1",
    transcriptSessionId: "transcript-child-1",
    sessionPath: "/private/sessions/transcript-child-1.jsonl",
  });
  const create = transport.commands.find(
    ({ command }) => command.type === "create" && command.lifecycle === "client_owned",
  ).command;
  assert.deepEqual(create.config, {
    cwd: "/private/workspace",
    agentDir: "/private/agent",
    sessionDir: "/private/sessions",
    provider: "example-provider",
    model: "example-model",
    skills: ["/private/skills/asterion-control"],
    autonomous: {
      enabled: true,
      maxContinuations: 4,
      maxTurns: 9,
      maxTokens: 2_000,
      timeoutMs: 60_000,
      gates: { commands: [], maxRetries: 1, timeoutMs: 60_000 },
    },
    telemetryDisabled: true,
  });
  assert.deepEqual({
    ...create.runtimeMetadata,
    createdAt: typeof create.runtimeMetadata.createdAt,
  }, {
    kind: "subagent",
    createdAt: "number",
    parentActiveSessionId: "prime-root-1",
    parentSessionId: "transcript-1",
    parentSessionFile: "/private/sessions/transcript-1.jsonl",
    rlmChildId: "child-1",
    prompt: "SENTINEL_PRIVATE_CHILD_GOAL",
    sessionDir: "/private/sessions",
  });
  assert.deepEqual(transport.commands.at(-1).command, {
    type: "prompt",
    activeSessionId: "prime-child-1",
    message: "SENTINEL_PRIVATE_CHILD_GOAL",
  });
});

test("native RLM child message stays on the pinned daemon protocol", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: { ...PRIVATE_CONFIG, rlmMaxDepth: 1 },
    async bindIdentity() {},
  });
  await session.spawnNativeRlmChild("native-child-1", "child-1", "private goal");

  await session.sendNativeRlmChildMessage(
    "native-message-1",
    "child-1",
    "SENTINEL_PRIVATE_MESSAGE",
  );

  assert.deepEqual(transport.commands.at(-1).command, {
    type: "send_message",
    targetActiveSessionId: "prime-child-1",
    fromActiveSessionId: "prime-root-1",
    message: "SENTINEL_PRIVATE_MESSAGE",
    agentOrigin: true,
  });
});

test("native RLM children are killed before their owning root is cancelled", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: { ...PRIVATE_CONFIG, rlmMaxDepth: 1 },
    async bindIdentity() {},
  });
  await session.spawnNativeRlmChild("native-child-1", "child-1", "private goal");
  await session.waitForNativeRlmChild("wait-child-1", "child-1");

  await session.cancel("cancel-children-1");

  const kills = transport.commands
    .filter(({ command }) => command.type === "kill")
    .map(({ command }) => command.activeSessionId);
  assert.deepEqual(kills, ["prime-child-1", "prime-root-1"]);
  await assert.rejects(
    session.terminateNativeRlmChild("terminate-child-1", "child-1"),
    { name: "PrimeSessionError" },
  );
});

test("lifecycle enables one native RLM level only when private config requests it", async () => {
  const transport = new FakeTransport();
  await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: { ...PRIVATE_CONFIG, rlmMaxDepth: 1 },
    bindIdentity: async () => undefined,
  });

  const command = transport.commands.find(({ command }) => command.type === "set_rlm_max_depth");
  assert.deepEqual(command?.command, {
    type: "set_rlm_max_depth",
    activeSessionId: "prime-root-1",
    maxDepth: 1,
    global: false,
  });
});

test("lifecycle materializes the resident transcript before durability binding", async () => {
  const transport = new FakeTransport();
  await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    async bindIdentity() {
      assert.deepEqual(transport.commands.map(({ command }) => command.type), [
        "create",
        "get_session_header",
        "set_session_name",
      ]);
      assert.deepEqual(transport.acknowledgements, []);
    },
  });

  assert.deepEqual(transport.acknowledgements.slice(0, 2), [
    "session-1-create-materialize",
    "session-1-create",
  ]);
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

test("context labels set and clear privately with stable deferred acknowledgement", async () => {
  const transport = new FakeTransport();
  const session = PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
    continuationId: "continuation-1",
    sessionPath: transport.sessionFile,
  });

  const set = await session.setContextLabel(
    "context-label-set",
    "continuation-1",
    "entry-2",
    "SENTINEL_PRIVATE_LABEL",
  );
  assert.deepEqual(set.result, {
    continuationId: "continuation-1",
    entryId: "entry-2",
    labelSha256: createHash("sha256")
      .update("SENTINEL_PRIVATE_LABEL")
      .digest("hex"),
  });
  assert.equal(JSON.stringify(set.result).includes("SENTINEL"), false);
  assert.equal(set.acknowledge(), true);

  const cleared = await session.setContextLabel(
    "context-label-clear",
    "continuation-1",
    "entry-2",
    null,
  );
  assert.equal(cleared.result.labelSha256, null);
  assert.equal(cleared.acknowledge(), true);
  await assert.rejects(session.setContextLabel(
    "context-label-empty",
    "continuation-1",
    "entry-2",
    "",
  ));
  assert.deepEqual(
    transport.commands
      .filter(({ command }) => command.type === "set_session_entry_label")
      .map(({ command, commandId }) => [commandId, command.label]),
    [
      ["session-1-context-context-label-set-label", "SENTINEL_PRIVATE_LABEL"],
      ["session-1-context-context-label-clear-label", undefined],
    ],
  );
});

test("manual compaction and branch summary reconcile exact durable baselines and private output", async () => {
  const transport = new FakeTransport();
  const session = PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
    continuationId: "continuation-1",
    sessionPath: transport.sessionFile,
  });
  await session.ensureManualCompactionOnly("context-model-policy");
  const compactBaseline = await session.measureContextModelBaseline(
    "context-compact",
    "continuation-1",
  );
  assert.deepEqual(compactBaseline, {
    commandId: "context-compact",
    continuationId: "continuation-1",
    leafId: "entry-2",
    contextTokens: 90,
    controllerTokens: 135,
    costMicros: 1_234,
  });
  const compacted = await session.compactContext(
    "context-compact",
    "continuation-1",
    "SENTINEL_PRIVATE_COMPACT_INSTRUCTIONS",
    MODEL_BUDGET,
    compactBaseline,
  );
  assert.equal(compacted.status, "succeeded");
  assert.deepEqual(compacted.result, {
    continuationId: "continuation-1",
    coveredLeafId: "entry-2",
    beforeContextTokens: 90,
    afterContextTokens: 40,
    summarySha256: createHash("sha256")
      .update("SENTINEL_PRIVATE_COMPACTION_SUMMARY")
      .digest("hex"),
    usage: {
      controller_tokens: 20,
      application_tokens: 0,
      child_tokens: 0,
      aggregate_tokens: 20,
      cost_micros: 500,
    },
  });
  assert.equal(JSON.stringify(compacted.result).includes("SENTINEL"), false);
  assert.equal(compacted.acknowledge(), true);

  const summaryBaseline = await session.measureContextModelBaseline(
    "context-summary",
    "continuation-1",
  );
  const summarized = await session.summarizeContextBranch(
    "context-summary",
    "continuation-1",
    "entry-1",
    "SENTINEL_PRIVATE_BRANCH_INSTRUCTIONS",
    MODEL_BUDGET,
    summaryBaseline,
  );
  assert.equal(summarized.status, "succeeded");
  assert.equal(summarized.result.previousLeafId, "compaction-entry-1");
  assert.equal(summarized.result.currentLeafId, "summary-entry-1");
  assert.equal(
    summarized.result.summarySha256,
    createHash("sha256").update("SENTINEL_PRIVATE_BRANCH_SUMMARY").digest("hex"),
  );
  assert.deepEqual(summarized.result.usage, {
    controller_tokens: 12,
    application_tokens: 0,
    child_tokens: 0,
    aggregate_tokens: 12,
    cost_micros: 300,
  });
  assert.equal(JSON.stringify(summarized.result).includes("SENTINEL"), false);
  assert.equal(summarized.acknowledge(), true);
  assert.deepEqual(
    transport.commands
      .filter(({ command }) => ["compact", "navigate_tree"].includes(command.type))
      .map(({ command, commandId }) => [commandId, command]),
    [
      ["session-1-context-context-compact-compact", {
        type: "compact",
        activeSessionId: "prime-root-1",
        customInstructions: "SENTINEL_PRIVATE_COMPACT_INSTRUCTIONS",
      }],
      ["session-1-context-context-summary-branch-summary", {
        type: "navigate_tree",
        activeSessionId: "prime-root-1",
        targetId: "entry-1",
        summarize: true,
        customInstructions: "SENTINEL_PRIVATE_BRANCH_INSTRUCTIONS",
        replaceInstructions: false,
      }],
    ],
  );
});

test("bounded model operations distinguish rejection, cancellation, and post-effect uncertainty", async () => {
  const makeSession = (transport) => PrimeSession.restore({
    transport,
    sessionId: "session-1",
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-1",
    continuationId: "continuation-1",
    sessionPath: transport.sessionFile,
  });

  const rejectedTransport = new FakeTransport();
  rejectedTransport.modelFailure = {};
  const rejectedSession = makeSession(rejectedTransport);
  const rejectedBaseline = await rejectedSession.measureContextModelBaseline(
    "context-provider-rejected",
    "continuation-1",
  );
  const rejected = await rejectedSession.compactContext(
    "context-provider-rejected",
    "continuation-1",
    null,
    MODEL_BUDGET,
    rejectedBaseline,
  );
  assert.equal(rejected.status, "rejected");
  assert.equal(rejected.result, null);
  assert.equal(rejected.acknowledge(), true);

  const cancelledTransport = new FakeTransport();
  cancelledTransport.holdModelOperations = true;
  cancelledTransport.modelFailure = {};
  const cancelledSession = makeSession(cancelledTransport);
  const cancelledBaseline = await cancelledSession.measureContextModelBaseline(
    "context-cancelled",
    "continuation-1",
  );
  const pending = cancelledSession.compactContext(
    "context-cancelled",
    "continuation-1",
    null,
    MODEL_BUDGET,
    cancelledBaseline,
  );
  await new Promise((resolve) => setImmediate(resolve));
  await cancelledSession.abortContextModelOperation(
    "context-cancelled",
    "session.compact",
  );
  cancelledTransport.releaseModelOperations();
  const cancelled = await pending;
  assert.equal(cancelled.status, "cancelled");
  assert.equal(cancelled.result, null);
  assert.equal(cancelled.acknowledge(), true);
  assert.equal(
    cancelledTransport.commands.some(
      ({ command }) => command.type === "abort_compaction",
    ),
    true,
  );

  const overBudgetTransport = new FakeTransport();
  const overBudgetSession = makeSession(overBudgetTransport);
  const overBudgetBaseline = await overBudgetSession.measureContextModelBaseline(
    "context-over-budget",
    "continuation-1",
  );
  const overBudget = await overBudgetSession.compactContext(
    "context-over-budget",
    "continuation-1",
    null,
    { ...MODEL_BUDGET, controller_tokens: 19, aggregate_tokens: 19 },
    overBudgetBaseline,
  );
  assert.equal(overBudget.status, "uncertain");
  assert.equal(overBudget.result, null);
  assert.equal(
    overBudgetTransport.acknowledgements.includes(
      "session-1-context-context-over-budget-compact",
    ),
    false,
  );
  assert.equal(
    overBudgetTransport.commands.some(
      ({ command }) => command.type === "abort_compaction",
    ),
    true,
  );

  const uncertainTransport = new FakeTransport();
  uncertainTransport.modelFailure = {
    errorInfo: {
      code: "command_result_uncertain",
      clientId: "fake-client-1",
      commandId: "session-1-context-context-provider-uncertain-compact",
    },
  };
  const uncertainSession = makeSession(uncertainTransport);
  const uncertainBaseline = await uncertainSession.measureContextModelBaseline(
    "context-provider-uncertain",
    "continuation-1",
  );
  const uncertain = await uncertainSession.compactContext(
    "context-provider-uncertain",
    "continuation-1",
    null,
    MODEL_BUDGET,
    uncertainBaseline,
  );
  assert.equal(uncertain.status, "uncertain");
  assert.equal(uncertain.result, null);
  assert.equal(
    uncertainTransport.acknowledgements.includes(
      "session-1-context-context-provider-uncertain-compact",
    ),
    false,
  );
  assert.equal(uncertain.acknowledge(), true);
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

test("tree read and navigation expose only closed topology and defer mutation acknowledgement", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.commands.length = 0;
  transport.acknowledgements.length = 0;

  const tree = await session.readContextTree("context-tree-1", session.continuationId);
  assert.deepEqual(tree, {
    nodes: [
      { entry_id: "entry-1", parent_id: null, kind: "input", label_sha256: null, token_count: 0 },
      { entry_id: "entry-2", parent_id: "entry-1", kind: "output", label_sha256: tree.nodes[1].label_sha256, token_count: 3 },
    ],
    leafId: "entry-2",
  });
  assert.match(tree.nodes[1].label_sha256, /^[0-9a-f]{64}$/);
  assert.equal(JSON.stringify(tree).includes("SENTINEL"), false);
  assert.equal(JSON.stringify(tree).includes("private-provider"), false);

  const navigated = await session.navigateContextTree(
    "context-navigate-1",
    session.continuationId,
    "entry-1",
    "entry-2",
  );
  assert.deepEqual(navigated.result, {
    continuationId: session.continuationId,
    previousLeafId: "entry-2",
    currentLeafId: null,
    transitionSha256: navigated.result.transitionSha256,
  });
  assert.match(navigated.result.transitionSha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(transport.acknowledgements, []);
  assert.equal(navigated.acknowledge(), true);
  assert.deepEqual(transport.acknowledgements, [
    "session-1-context-context-navigate-1-tree-navigate",
  ]);
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "get_session_tree",
    "get_session_tree",
    "navigate_tree",
    "get_session_tree",
  ]);
});

test("tree operations reject scope response and topology drift without raw disclosure", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  await assert.rejects(
    session.readContextTree("tree-wrong-scope", "continuation-other"),
  );
  transport.sessionTree.flatNodes[1].entry.parentId = "missing";
  await assert.rejects(
    session.readContextTree("tree-invalid", session.continuationId),
  );
  transport.sessionTree = new FakeTransport().sessionTree;
  transport.navigateResponse = { cancelled: false, raw: "SENTINEL_RAW_NAVIGATE" };
  await assert.rejects(session.navigateContextTree(
    "navigate-invalid",
    session.continuationId,
    "entry-2",
    "entry-2",
  ));
  assert.equal(JSON.stringify(session).includes("SENTINEL"), false);
});

test("fork and clone reconstruct exact replacement identities and defer acknowledgement", async () => {
  const forkTransport = new FakeTransport();
  const forkSession = await PrimeSession.create({
    transport: forkTransport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  forkTransport.commands.length = 0;
  forkTransport.acknowledgements.length = 0;

  const forked = await forkSession.forkContext(
    "context-fork-1",
    forkSession.continuationId,
    "entry-1",
    "before",
  );

  assert.equal(forked.result.sourceContinuationId, forkSession.continuationId);
  assert.notEqual(forked.result.newContinuationId, forkSession.continuationId);
  assert.equal(forked.result.activeLeafId, null);
  assert.match(forked.result.transitionSha256, /^[0-9a-f]{64}$/);
  assert.deepEqual(forked.locator, {
    continuationId: forked.result.newContinuationId,
    activeSessionId: "prime-root-1",
    transcriptSessionId: "transcript-fork-1",
    supervisorGeneration: "supervisor-generation-1",
    sessionPath: "/private/sessions/transcript-fork-1.jsonl",
  });
  assert.deepEqual(forkTransport.acknowledgements, []);
  assert.deepEqual(forkTransport.commands.map(({ command }) => command.type), [
    "fork",
    "get_session_header",
    "get_state",
    "get_session_tree",
  ]);
  assert.equal(forked.acknowledge(), true);
  assert.deepEqual(forkTransport.acknowledgements, [
    "session-1-context-context-fork-1-fork",
  ]);

  const cloneTransport = new FakeTransport();
  const cloneSession = await PrimeSession.create({
    transport: cloneTransport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  cloneTransport.commands.length = 0;
  cloneTransport.acknowledgements.length = 0;
  const cloned = await cloneSession.cloneContext(
    "context-clone-1",
    cloneSession.continuationId,
    "entry-2",
  );

  assert.equal(cloned.result.sourceContinuationId, cloneSession.continuationId);
  assert.equal(cloned.result.activeLeafId, "entry-2");
  assert.equal(cloned.locator.transcriptSessionId, "transcript-fork-1");
  assert.deepEqual(cloneTransport.commands.map(({ command }) => command.type), [
    "fork",
    "get_session_header",
    "get_state",
    "get_session_tree",
  ]);
  assert.equal(cloned.acknowledge(), true);
  assert.deepEqual(cloneTransport.acknowledgements, [
    "session-1-context-context-clone-1-clone",
  ]);
});

test("fork and clone reject conflicting replay and replacement identity drift", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  await session.forkContext(
    "context-fork-replay",
    session.continuationId,
    "entry-2",
    "at",
  );
  await assert.rejects(session.forkContext(
    "context-fork-replay",
    session.continuationId,
    "entry-1",
    "at",
  ));

  const invalidResponse = new FakeTransport();
  invalidResponse.forkResponse = {
    cancelled: false,
    raw: "SENTINEL_RAW_FORK",
  };
  const invalidSession = await PrimeSession.create({
    transport: invalidResponse,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  await assert.rejects(invalidSession.cloneContext(
    "context-clone-invalid",
    invalidSession.continuationId,
    "entry-2",
  ));

  const escapedPath = new FakeTransport();
  const originalRequest = escapedPath.request.bind(escapedPath);
  escapedPath.request = async (command, commandId) => {
    const response = await originalRequest(command, commandId);
    if (command.type === "fork") {
      escapedPath.sessionState.sessionFile = "/private/outside/fork.jsonl";
    }
    return response;
  };
  const escapedSession = await PrimeSession.create({
    transport: escapedPath,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  await assert.rejects(escapedSession.forkContext(
    "context-fork-escaped",
    escapedSession.continuationId,
    "entry-2",
    "at",
  ));
  assert.equal(JSON.stringify(invalidSession).includes("SENTINEL"), false);
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

test("lifecycle delivers exact private images with stable input replay identity", async () => {
  const transport = new FakeTransport();
  const session = await PrimeSession.create({
    transport,
    sessionId: "session-1",
    privateConfig: PRIVATE_CONFIG,
    bindIdentity: async () => undefined,
  });
  transport.commands.length = 0;
  const first = Buffer.from("SENTINEL_PRIVATE_IMAGE_FIRST", "utf8");
  const second = Buffer.from("SENTINEL_PRIVATE_IMAGE_SECOND", "utf8");
  const attachments = [
    {
      attachmentId: "attachment-1",
      mediaType: "image/png",
      sha256: createHash("sha256").update(first).digest("hex"),
      size: first.byteLength,
      body: first,
    },
    {
      attachmentId: "attachment-2",
      mediaType: "image/jpeg",
      sha256: createHash("sha256").update(second).digest("hex"),
      size: second.byteLength,
      body: second,
    },
  ];

  for (const [inputId, delivery] of [
    ["input-images-direct", "direct"],
    ["input-images-steer", "steer"],
    ["input-images-follow-up", "follow_up"],
    ["input-images-direct", "direct"],
  ]) {
    await session.submitInput(inputId, delivery, "private text", attachments);
  }

  assert.deepEqual(transport.commands.map(({ commandId }) => commandId), [
    "session-1-input-input-images-direct",
    "session-1-input-input-images-steer",
    "session-1-input-input-images-follow-up",
    "session-1-input-input-images-direct",
  ]);
  for (const { command } of transport.commands) {
    assert.deepEqual(command.images, [
      { type: "image", data: first.toString("base64"), mimeType: "image/png" },
      { type: "image", data: second.toString("base64"), mimeType: "image/jpeg" },
    ]);
    assert.equal(JSON.stringify(command).includes("SENTINEL_PRIVATE_IMAGE"), false);
  }
  assert.deepEqual(
    transport.acknowledgements.filter((value) => value.includes("-input-")),
    [],
  );
  assert.equal(session.acknowledgeInput("input-images-direct"), true);
  assert.equal(
    transport.acknowledgements.at(-1),
    "session-1-input-input-images-direct",
  );

  for (const invalid of [
    attachments.toReversed(),
    [attachments[0], attachments[0]],
    [{ ...attachments[0], mediaType: "application/octet-stream" }],
    [{ ...attachments[0], body: Buffer.from("substituted") }],
  ]) {
    await assert.rejects(
      session.submitInput("input-invalid", "direct", "private", invalid),
    );
  }
  assert.equal(transport.commands.length, 4);
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
