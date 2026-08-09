import assert from "node:assert/strict";
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
        data: { activeSessionId: "prime-root-1", id: "transcript-1" },
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

  async requestDeferred(command, commandId) {
    const response = await this.request(command, commandId);
    return {
      response,
      acknowledge: () => this.acknowledgements.push(commandId),
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
  assert.equal(session.supervisorGeneration, "supervisor-generation-1");
  assert.deepEqual(identities, [{
    activeSessionId: "prime-root-1",
    supervisorGeneration: "supervisor-generation-1",
  }]);
  assert.deepEqual(transport.acknowledgements, ["session-1-create"]);
  assert.deepEqual(transport.commands.map(({ command }) => command.type), [
    "create",
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
  assert.equal(transport.commands[1].command.maxDepth, 0);
  assert.deepEqual(transport.commands[2].command.capabilities, [
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
