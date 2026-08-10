import { mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
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
  const deliveries = new Map();
  const mutations = new Map();
  const commandCounts = new Map();
  const cachedResponses = new Map();
  const sockets = new Set();
  let connectionCount = 0;
  let attachedActiveSessionId;

  function observations() {
    return {
      scenarioId: options.scenarioId ?? "embedded",
      processId: process.pid,
      socketPath,
      connectionCount,
      modelProviderOperations: 0,
      applicationOperations: 0,
      commandCounts: Object.fromEntries(
        [...commandCounts.entries()].sort(([left], [right]) => left.localeCompare(right)),
      ),
      clientIds: [...clientIds],
      acknowledgements: [...acknowledgements],
    };
  }

  async function persistObservations() {
    if (typeof options.observationsPath !== "string") {
      return;
    }
    await writeFile(options.observationsPath, `${JSON.stringify(observations(), null, 2)}\n`)
      .catch(() => undefined);
  }

  function defaultResponseData(command) {
    const activeSessionId = command.activeSessionId ?? "prime-root-1";
    if (command.type === "create") {
      return {
        activeSessionId,
        sessionId: "prime-transcript-1",
      };
    }
    if (command.type === "attach") {
      return { activeSessionId };
    }
    if (command.type === "cancel_prompt_admission") {
      return { status: "cancelled" };
    }
    return { accepted: true };
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
          `fake-build-${connectionIndex + 1}`,
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
            socket.write(`${JSON.stringify(response)}\n`);
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
