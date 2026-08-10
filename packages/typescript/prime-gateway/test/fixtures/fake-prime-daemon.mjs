import {
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { writeFileSync } from "node:fs";
import { createConnection, createServer } from "node:net";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

export const defaultServerCapabilities = Object.freeze([
  "attach_snapshot",
  "event_sequence",
  "extension_ui",
  "slim_attach",
  "chunked_snapshot",
  "client_owned_sessions",
  "delete_rlm_subagent",
  "heartbeat_catalog",
  "heartbeat_management",
  "model_catalog",
  "side_question_transcript",
  "transient_bash",
  "session_input_admission",
  "prompt_admission_cancellation",
]);

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitUntil(predicate, message) {
  const deadline = Date.now() + 2_000;
  while (!predicate()) {
    if (Date.now() >= deadline) {
      throw new Error(message);
    }
    await sleep(5);
  }
}

function selected(value, index) {
  return Array.isArray(value) ? value[Math.min(index, value.length - 1)] : value;
}

export async function startFakePrimeDaemon(options = {}) {
  const ownsRoot = options.root === undefined;
  const root = options.root ?? await mkdtemp(join(tmpdir(), "asterion-fake-prime-"));
  await mkdir(root, { mode: 0o700, recursive: true });
  const socketPath = options.socketPath ?? join(root, "daemon.sock");
  const commands = [];
  const rawCommands = [];
  const clientIds = [];
  const acknowledgements = [];
  const skillOperations = [];
  const skillResponses = [];
  const skillFailures = [];
  const skillDisconnects = [];
  const emittedGoalUpdates = [];
  const deliveries = new Map();
  const mutations = new Map();
  const commandCounts = new Map();
  const cachedResponses = new Map();
  const sockets = new Set();
  const activeSessionSockets = new Map();
  const transcriptByActiveSession = new Map();
  const sessionPathByActiveSession = new Map();
  let connectionCount = 0;
  let createCount = 0;
  let outboundSequence = 0;
  let attachedActiveSessionId;
  let createConfig;
  let persistence = Promise.resolve();

  function observations() {
    return {
      scenarioId: options.scenarioId ?? "embedded",
      processId: process.pid,
      socketPath,
      connectionCount,
      modelProviderOperations: 0,
      applicationOperations: skillResponses.filter((response) =>
        response.operation === "application.invoke",
      ).length,
      commandCounts: Object.fromEntries(
        [...commandCounts.entries()].sort(([left], [right]) => left.localeCompare(right)),
      ),
      skillOperations: [...skillOperations],
      skillResponses: [...skillResponses],
      skillFailures: [...skillFailures],
      skillDisconnects: [...skillDisconnects],
      emittedGoalUpdates: [...emittedGoalUpdates],
      clientIds: [...clientIds],
      acknowledgements: [...acknowledgements],
    };
  }

  function persistObservations() {
    if (typeof options.observationsPath !== "string") {
      return Promise.resolve();
    }
    const body = `${JSON.stringify(observations(), null, 2)}\n`;
    persistence = persistence
      .then(async () => {
        const temporaryPath = `${options.observationsPath}.tmp`;
        await writeFile(temporaryPath, body);
        await rename(temporaryPath, options.observationsPath);
      })
      .catch(() => undefined);
    return persistence;
  }

  function defaultResponseData(command) {
    const activeSessionId = command.fakeActiveSessionId ?? command.activeSessionId ?? "prime-root-1";
    const transcriptSessionId = command.fakeTranscriptSessionId
      ?? transcriptByActiveSession.get(activeSessionId)
      ?? "prime-transcript-1";
    const sessionPath = sessionPathByActiveSession.get(activeSessionId)
      ?? "/private/sessions/root.jsonl";
    const sessionCwd = createConfig?.cwd ?? "/private/workspace";
    if (command.type === "create") {
      return {
        activeSessionId,
        sessionId: transcriptSessionId,
        sessionFile: sessionPath,
      };
    }
    if (command.type === "attach") {
      const cursor = { generation: "prime-events-1", sequence: 0 };
      return {
        activeSessionId,
        protocol: { name: "prime-agent.daemon", version: 7 },
        replay: { status: "complete", toSequence: 0 },
        lastEventSequence: 0,
        lastEventCursor: cursor,
        snapshot: {
          activeSessionId,
          lastEventSequence: 0,
          lastEventCursor: cursor,
          summary: {
            sessionId: transcriptSessionId,
            activeSessionId,
          },
          state: {
            goal: { status: "active" },
          },
        },
      };
    }
    if (command.type === "cancel_prompt_admission") {
      return { status: "cancelled" };
    }
    if (command.type === "get_session_header") {
      return {
        header: {
          type: "session",
          id: transcriptSessionId,
          timestamp: "2026-08-10T04:00:00.000Z",
          cwd: sessionCwd,
        },
      };
    }
    if (command.type === "get_state") {
      return {
        id: activeSessionId,
        lifecycle: "live",
        activity: "idle",
        isSessionActive: false,
        runtimeKind: "top-level",
        rlmDepth: 0,
        activeSessionId,
        sessionId: transcriptSessionId,
        sessionFile: sessionPath,
        sessionName: "private fake session",
        cwd: sessionCwd,
        thinkingLevel: "medium",
        isStreaming: false,
        isCompacting: false,
        isBashRunning: false,
        hasRunningRlmChildren: false,
        isRunningTools: false,
        attachedClients: 1,
        messageCount: 0,
        unfinishedActionCount: 0,
        sessionActions: { queuedCount: 0, steering: [], followUps: [] },
        diagnostics: [],
      };
    }
    if (command.type === "get_session_stats") {
      return {
        sessionFile: sessionPath,
        sessionId: transcriptSessionId,
        userMessages: 0,
        assistantMessages: 0,
        toolCalls: 0,
        toolResults: 0,
        totalMessages: 0,
        tokens: {
          input: 0,
          output: 0,
          cacheRead: 0,
          cacheWrite: 0,
          total: 0,
        },
        cost: 0,
        contextUsage: { tokens: 0, contextWindow: 200_000, percent: 0 },
      };
    }
    if (command.type === "get_session_tree") {
      return { flatNodes: [], leafId: null };
    }
    if (command.type === "compact") {
      return {
        summary: "private fake compaction summary",
        firstKeptEntryId: "entry-1",
        tokensBefore: 0,
      };
    }
    if (command.type === "switch_session") {
      return { cancelled: false };
    }
    if (command.type === "fork") {
      return { cancelled: false };
    }
    if (command.type === "navigate_tree") {
      return { cancelled: false };
    }
    if (command.type === "delete_saved_session") {
      return { ok: true, method: "unlink" };
    }
    if ([
      "abort_branch_summary",
      "abort_compaction",
      "rename_saved_session",
      "set_session_entry_label",
      "set_session_name",
    ].includes(command.type)) {
      return undefined;
    }
    if (command.type === "prepare_update_restart") {
      return {
        formatVersion: 1,
        createdAt: "2026-08-10T04:00:00.000Z",
        sessions: [
          {
            activeSessionId: "prime-root-1",
            sessionId: "prime-transcript-1",
            sessionFile: "/private/sessions/root.jsonl",
            runtimeMetadata: { kind: "top-level" },
          },
        ],
      };
    }
    return { accepted: true };
  }

  function scenarioRequest(command) {
    const budget = {
      controller_tokens: 0,
      application_tokens: 10,
      child_tokens: 10,
      aggregate_tokens: 20,
      cost_micros: 0,
      deadline_ms: 10_000,
    };
    const scenarioId = options.scenarioId ?? "embedded";
    if (
      scenarioId === "prime-loop-application" ||
      scenarioId === "prime-loop-gateway-crash" ||
      scenarioId === "prime-loop-supervisor-crash" ||
      scenarioId === "prime-loop-worker-crash" ||
      scenarioId === "prime-loop-cancel" ||
      scenarioId === "prime-loop-budget"
    ) {
      return {
        operation: "application.invoke",
        payload: {
          target: {
            kind: "application",
            provider_id: "example.provider",
            application_id: "alpha",
            version: "1.0.0",
            runtime_id: "fake.runtime",
          },
          input_text: `SENTINEL_TOKEN ${scenarioId}`,
          expected_artifacts: ["report.alpha"],
          idempotency_key: `${scenarioId}-application`,
          budget,
        },
      };
    }
    if (scenarioId === "prime-loop-child") {
      return {
        operation: "child.spawn",
        payload: {
          child_id: "child-1",
          goal_text: "SENTINEL_PATH child goal",
          idempotency_key: `${scenarioId}-child`,
          budget,
        },
      };
    }
    if (scenarioId === "prime-loop-checkpoint") {
      return {
        operation: "checkpoint.request",
        payload: {
          checkpoint_id: "checkpoint-1",
          idempotency_key: `${scenarioId}-checkpoint`,
          budget,
        },
      };
    }
    if (scenarioId === "prime-loop-redaction") {
      return {
        operation: "child.spawn",
        payload: {
          child_id: "child-1",
          goal_text: "SENTINEL_PATH SENTINEL_OUTPUT child goal",
          idempotency_key: `${scenarioId}-child`,
          budget,
        },
      };
    }
    return undefined;
  }

  function scenarioRequests(command) {
    const first = scenarioRequest(command);
    if (first === undefined) {
      return [];
    }
    if ((options.scenarioId ?? "embedded") !== "prime-loop-application") {
      return [first];
    }
    return [
      first,
      {
        operation: "goal.complete",
        payload: {
          goal_id: "goal-1",
          summary: "SENTINEL_OUTPUT verified goal completion",
          idempotency_key: "prime-loop-application-goal-complete",
          budget: {
            controller_tokens: 0,
            application_tokens: 0,
            child_tokens: 0,
            aggregate_tokens: 0,
            cost_micros: 0,
            deadline_ms: 10_000,
          },
        },
      },
    ];
  }

  function emitGoalUpdate(activeSessionId, status = "complete") {
    const socket = activeSessionSockets.get(activeSessionId);
    if (socket === undefined || socket.destroyed) {
      emittedGoalUpdates.push({ activeSessionId, status, delivered: false });
      void persistObservations();
      return;
    }
    outboundSequence += 1;
    const cursor = {
      generation: "prime-events-1",
      sequence: outboundSequence,
    };
    socket.write(`${JSON.stringify({
      type: "session_event",
      activeSessionId,
      event: {
        type: "goal_update",
        goal: {
          status,
          tokensUsed: 0,
        },
      },
      meta: {
        id: `prime-event-${outboundSequence}`,
        protocol: { name: "prime-agent.daemon", version: 7 },
        cursor,
        sequence: outboundSequence,
        activeSessionId,
        emittedAt: "2026-08-10T04:00:00.000Z",
      },
    })}\n`);
    emittedGoalUpdates.push({ activeSessionId, status, delivered: true, cursor });
    void persistObservations();
  }

  function readLine(socket, label) {
    return new Promise((resolve, reject) => {
      let buffer = "";
      const timer = setTimeout(
        () => reject(new Error(`timeout waiting for ${label}`)),
        5_000,
      );
      socket.setEncoding("utf8");
      socket.on("data", (chunk) => {
        buffer += chunk;
        const newline = buffer.indexOf("\n");
        if (newline !== -1) {
          clearTimeout(timer);
          resolve(buffer.slice(0, newline));
        }
      });
      socket.once("error", (error) => {
        clearTimeout(timer);
        reject(error);
      });
      socket.once("close", () => {
        if (buffer.length === 0) {
          clearTimeout(timer);
          reject(new Error(`closed waiting for ${label}`));
        }
      });
    });
  }

  async function exchangeOneWithSkillBridge(request) {
    const discoveryPath = join(createConfig.agentDir, "asterion-control.json");
    const discovery = JSON.parse(await readFile(discoveryPath, "utf8"));
    const socket = createConnection(discovery.socket_path);
    await new Promise((resolve, reject) => {
      socket.once("connect", resolve);
      socket.once("error", reject);
    });
    const requestId = `${request.operation.replace(".", "-")}-request`;
    skillOperations.push(request.operation);
    socket.write(`${JSON.stringify({
      protocol: "asterion.skill-control/v1",
      type: "authenticate",
      token: discovery.token,
      session_id: discovery.session_id,
    })}\n${JSON.stringify({
      protocol: "asterion.skill-control/v1",
      request_id: requestId,
      session_id: discovery.session_id,
      operation: request.operation,
      payload: request.payload,
    })}\n`);
    const response = JSON.parse(await readLine(socket, request.operation));
    socket.end();
    skillResponses.push({
      operation: request.operation,
      status: response.status,
      admission: response.result?.admission?.resolution,
      terminal: response.result?.terminal?.resolution,
    });
    await persistObservations();
  }

  async function exchangeWithSkillBridge(command) {
    for (const request of scenarioRequests(command)) {
      await exchangeOneWithSkillBridge(request);
    }
  }

  const server = createServer((socket) => {
    const connectionIndex = connectionCount++;
    sockets.add(socket);
    socket.on("close", () => sockets.delete(socket));
    const greetingOverride = selected(options.greetings, connectionIndex) ?? {};
    const greeting = {
      type: "daemon_hello",
      socketPath,
      protocol: {
        name: "prime-agent.daemon",
        version: greetingOverride.protocol ?? options.protocol ?? 7,
      },
      schemaId:
        greetingOverride.schemaId ??
        options.schemaId ??
        "protocol-7-schema-14-816309b1cd50",
      schemaRevision:
        greetingOverride.schemaRevision ?? options.schemaRevision ?? 14,
      appVersion: greetingOverride.appVersion ?? options.appVersion ?? "0.7.1",
      runtime: {
        buildId:
          greetingOverride.buildId ??
          options.buildId ??
          "fake-build-1",
        executablePath: "/private/sentinel/node",
        entrypointPath: "/private/sentinel/prime.ts",
      },
      supervisorGeneration:
        greetingOverride.supervisorGeneration ??
        options.supervisorGeneration ??
        `generation-${connectionIndex + 1}`,
      supervisorPid: process.pid,
      clientId: `fake-connection-${connectionIndex + 1}`,
      serverCapabilities:
        greetingOverride.capabilities ??
        options.capabilities ??
        defaultServerCapabilities,
    };
    const rawGreeting = selected(options.rawGreetings, connectionIndex);
    const greetingDelay = greetingOverride.greetingDelayMs ?? options.greetingDelayMs ?? 0;
    setTimeout(() => {
      if (!socket.destroyed) {
        socket.write(
          rawGreeting === undefined
            ? `${JSON.stringify(greeting)}\n`
            : rawGreeting,
        );
      }
    }, greetingDelay);

    let buffer = "";
    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      buffer += chunk;
      let newline = buffer.indexOf("\n");
      while (newline !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        if (line.length > 0) {
          rawCommands.push(line);
          const envelope = JSON.parse(line);
          commands.push(envelope);
          clientIds.push(envelope.clientId);
          const command = envelope.command;
          if (command.type === "ack_result") {
            acknowledgements.push(command.commandId);
          } else {
            const commandId = envelope.id;
            commandCounts.set(command.type, (commandCounts.get(command.type) ?? 0) + 1);
            if (command.type === "attach") {
              attachedActiveSessionId = command.activeSessionId;
              activeSessionSockets.set(command.activeSessionId, socket);
            }
            if (command.type === "create") {
              createCount += 1;
              command.fakeActiveSessionId = `prime-root-${createCount}`;
              command.fakeTranscriptSessionId = `prime-transcript-${createCount}`;
              transcriptByActiveSession.set(
                command.fakeActiveSessionId,
                command.fakeTranscriptSessionId,
              );
              createConfig = command.config;
              const sessionPath = join(command.config.sessionDir, "root.jsonl");
              writeFileSync(sessionPath, "private fake transcript\n", {
                mode: 0o600,
              });
              sessionPathByActiveSession.set(command.fakeActiveSessionId, sessionPath);
            }
            void persistObservations();
            deliveries.set(commandId, (deliveries.get(commandId) ?? 0) + 1);
            if (!mutations.has(commandId)) {
              mutations.set(commandId, 1);
              const configuredData = typeof options.responseData === "function"
                ? options.responseData(command, envelope, connectionIndex)
                : options.responseData?.[command.type];
              cachedResponses.set(commandId, {
                id: commandId,
                type: "response",
                command: command.type,
                success: true,
                data: configuredData ?? defaultResponseData(command),
              });
              if (options.disconnectFirstMutation) {
                socket.destroy();
                newline = buffer.indexOf("\n");
                continue;
              }
            }
            if (options.silentCommandIds?.includes(commandId)) {
              newline = buffer.indexOf("\n");
              continue;
            }
            const response = options.uncertainCommandIds?.includes(commandId)
              ? {
                  id: commandId,
                  type: "response",
                  command: command.type,
                  success: false,
                  error: "private uncertain detail",
                  errorInfo: {
                    code: "command_result_uncertain",
                    clientId: envelope.clientId,
                    commandId,
                  },
                }
              : cachedResponses.get(commandId);
            if (command.type === "create" && skillOperations.length === 0) {
              setTimeout(() => {
                exchangeWithSkillBridge(command)
                  .catch((error) => {
                    if (
                      (options.scenarioId ?? "embedded") === "prime-loop-gateway-crash" &&
                      error.message === "closed waiting for application.invoke"
                    ) {
                      skillDisconnects.push("application.invoke");
                    } else {
                      skillFailures.push(error.message);
                    }
                  })
                  .finally(() => {
                    void persistObservations();
                  });
              }, 0);
            }
            socket.write(`${JSON.stringify(response)}\n`);
            if (
              command.type === "attach" &&
              command.activeSessionId !== "prime-root-1"
            ) {
              // Let the gateway finish create/attach and install its listener;
              // this still exercises snapshot polling rather than a synthetic host event.
              setTimeout(() => emitGoalUpdate(command.activeSessionId), 200);
            }
            void persistObservations();
          }
        }
        newline = buffer.indexOf("\n");
      }
    });
  });

  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolve);
  });
  await persistObservations();

  return {
    root,
    socketPath,
    commands,
    rawCommands,
    clientIds,
    acknowledgements,
    get connectionCount() {
      return connectionCount;
    },
    get prepareCount() {
      return commandCounts.get("prepare_update_restart") ?? 0;
    },
    get attachedActiveSessionId() {
      return attachedActiveSessionId;
    },
    commandCount(type) {
      return commandCounts.get(type) ?? 0;
    },
    deliveryCount(commandId) {
      return deliveries.get(commandId) ?? 0;
    },
    mutationCount(commandId) {
      return mutations.get(commandId) ?? 0;
    },
    async mode() {
      return (await stat(root)).mode & 0o777;
    },
    broadcastRaw(raw) {
      for (const socket of sockets) {
        socket.write(raw);
      }
    },
    async waitForConnections(count) {
      await waitUntil(
        () => connectionCount >= count,
        `expected ${count} daemon connections`,
      );
    },
    async waitForDeliveries(commandId, count) {
      await waitUntil(
        () => (deliveries.get(commandId) ?? 0) >= count,
        `expected ${count} deliveries for ${commandId}`,
      );
    },
    async waitForAcknowledgement(commandId) {
      await waitUntil(
        () => acknowledgements.includes(commandId),
        `expected acknowledgement for ${commandId}`,
      );
    },
    async close() {
      for (const socket of sockets) {
        socket.destroy();
      }
      await new Promise((resolve) => server.close(resolve));
      await persistObservations();
      if (ownsRoot) {
        await rm(root, { force: true, recursive: true });
      }
    },
  };
}

function cliValue(flag) {
  const index = process.argv.indexOf(flag);
  return index === -1 ? undefined : process.argv[index + 1];
}

if (
  process.argv[1] !== undefined &&
  import.meta.url === pathToFileURL(process.argv[1]).href &&
  cliValue("--socket-path") !== undefined
) {
  const daemon = await startFakePrimeDaemon({
    root: cliValue("--root"),
    socketPath: cliValue("--socket-path"),
    observationsPath: cliValue("--observations"),
    scenarioId: cliValue("--scenario-id"),
  });
  process.stdout.write(`${JSON.stringify({
    protocol: "asterion.fake-prime-daemon/v1",
    socketPath: daemon.socketPath,
    root: daemon.root,
    pid: process.pid,
  })}\n`);
  const shutdown = async () => {
    await daemon.close().catch(() => undefined);
    process.exit(0);
  };
  process.once("SIGTERM", shutdown);
  process.once("SIGINT", shutdown);
  process.stdin.resume();
}
