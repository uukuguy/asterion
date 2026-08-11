import assert from "node:assert/strict";
import { execFile as execFileCallback, spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  open,
  readFile,
  stat,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

import {
  PRIME_GATEWAY_IPC_PROTOCOL,
} from "../dist/src/main.js";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const execFile = promisify(execFileCallback);
const scenariosUrl = new URL(
  "../../../../tests/fixtures/prime_gateway/v1/verified-loop-scenarios.json",
  import.meta.url,
);
const expectedIds = Object.freeze([
  "prime-loop-application",
  "prime-loop-child",
  "prime-loop-detach-attach",
  "prime-loop-checkpoint",
  "prime-loop-gateway-crash",
  "prime-loop-supervisor-crash",
  "prime-loop-worker-crash",
  "prime-loop-cancel",
  "prime-loop-budget",
  "prime-loop-redaction",
]);
const sentinels = Object.freeze([
  "SENTINEL_PROMPT",
  "SENTINEL_TOKEN",
  "SENTINEL_PATH",
  "SENTINEL_OUTPUT",
]);
const discoveryFileName = "asterion-control.json";
const rlmDiscoveryFileName = "asterion-rlm-host.json";

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function writeFixtureFile(root, relativePath, value) {
  const target = join(root, relativePath);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, value);
}

async function createPrimeSource(root) {
  const contents = {
    "package-lock.json": JSON.stringify({
      name: "prime-agent",
      version: "0.7.1",
      lockfileVersion: 3,
      packages: {
        "": { name: "prime-agent", version: "0.7.1" },
        "packages/coding-agent": {
          name: "@earendil-works/pi-coding-agent",
          version: "0.7.1",
        },
      },
    }),
    "packages/coding-agent/package.json": JSON.stringify({
      name: "@earendil-works/pi-coding-agent",
      version: "0.7.1",
    }),
    "packages/coding-agent/src/modes/daemon/daemon-client.ts":
      "export const fixtureClient = true;\n",
    "packages/coding-agent/src/modes/daemon/daemon-protocol.ts":
      "export const DAEMON_PROTOCOL_VERSION = 7;\n",
    "prime-agent.sh": "#!/bin/sh\nexit 0\n",
  };
  for (const [relativePath, value] of Object.entries(contents)) {
    await writeFixtureFile(root, relativePath, value);
  }
  await chmod(join(root, "prime-agent.sh"), 0o755);
  let sourceCommit;
  try {
    ({ stdout: sourceCommit } = await execFile("git", ["rev-parse", "HEAD"], {
      cwd: root,
    }));
  } catch {
    await execFile("git", ["init", "--quiet"], { cwd: root });
    await execFile("git", ["config", "user.name", "Asterion Test"], {
      cwd: root,
    });
    await execFile(
      "git",
      ["config", "user.email", "asterion@example.invalid"],
      { cwd: root },
    );
    await execFile("git", ["add", "."], { cwd: root });
    await execFile("git", ["commit", "--quiet", "-m", "fixture"], {
      cwd: root,
    });
    ({ stdout: sourceCommit } = await execFile("git", ["rev-parse", "HEAD"], {
      cwd: root,
    }));
  }
  const lock = {
    format: "asterion.prime-artifact-lock/v1",
    source_commit: sourceCommit.trim(),
    package_name: "@earendil-works/pi-coding-agent",
    package_version: "0.7.1",
    daemon_protocol: 7,
    daemon_schema_revision: 14,
    daemon_schema_id: "protocol-7-schema-14-816309b1cd50",
    files: Object.fromEntries(
      Object.entries(contents).map(([name, value]) => [name, sha256(value)]),
    ),
    rlm_runtime: {
      entry: "packages/coding-agent/src/modes/daemon/daemon-client.ts",
      binding_chunk: "packages/coding-agent/src/modes/daemon/daemon-protocol.ts",
      patch_sha256: sha256("fixture-rlm-patch"),
      closure: {
        "packages/coding-agent/src/modes/daemon/daemon-client.ts": sha256(contents["packages/coding-agent/src/modes/daemon/daemon-client.ts"]),
        "packages/coding-agent/src/modes/daemon/daemon-protocol.ts": sha256(contents["packages/coding-agent/src/modes/daemon/daemon-protocol.ts"]),
      },
      derived_closure: {
        "packages/coding-agent/src/modes/daemon/daemon-client.ts": sha256(contents["packages/coding-agent/src/modes/daemon/daemon-client.ts"]),
        "packages/coding-agent/src/modes/daemon/daemon-protocol.ts": sha256("fixture-derived-rlm-binding"),
      },
    },
  };
  return lock;
}

function captureStream(stream) {
  const chunks = [];
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => chunks.push(chunk));
  return {
    text() {
      return chunks.join("");
    },
  };
}

function createLineReader(stream) {
  const pending = [];
  let buffer = "";
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    buffer += chunk;
    let newline = buffer.indexOf("\n");
    while (newline !== -1 && pending.length > 0) {
      const next = pending.shift();
      const line = buffer.slice(0, newline);
      buffer = buffer.slice(newline + 1);
      clearTimeout(next.timer);
      next.resolve(line);
      newline = buffer.indexOf("\n");
    }
  });
  stream.on("error", (error) => {
    while (pending.length > 0) {
      const next = pending.shift();
      clearTimeout(next.timer);
      next.reject(error);
    }
  });
  return {
    readLine(label, timeoutMs = 5_000) {
      const newline = buffer.indexOf("\n");
      if (newline !== -1) {
        const line = buffer.slice(0, newline);
        buffer = buffer.slice(newline + 1);
        return Promise.resolve(line);
      }
      return new Promise((resolveLine, reject) => {
        const timer = setTimeout(
          () => reject(new Error(`timeout waiting for ${label}`)),
          timeoutMs,
        );
        pending.push({ resolve: resolveLine, reject, timer });
      });
    },
  };
}

function waitForExit(child, label, timeoutMs = 5_000) {
  return new Promise((resolveLine, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`timeout waiting for ${label} exit`)),
      timeoutMs,
    );
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolveLine({ code, signal });
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

function writeEnvelope(process, envelope) {
  process.stdin.write(`${JSON.stringify(envelope)}\n`);
}

async function request(gateway, envelope) {
  const line = gateway.reader.readLine(envelope.id);
  writeEnvelope(gateway.child, envelope);
  return JSON.parse(await line);
}

async function waitUntil(predicate, label, timeoutMs = 5_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await predicate();
    if (value !== undefined && value !== false) {
      return value;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(`timeout waiting for ${label}`);
}

async function startFakeDaemon(root, scenarioId) {
  const observationsPath = join(root, "daemon-observations.json");
  await rm(join(root, "p.sock"), { force: true });
  const child = spawn(process.execPath, [
    join(packageRoot, "test/fixtures/fake-prime-daemon.mjs"),
    "--socket-path",
    join(root, "p.sock"),
    "--observations",
    observationsPath,
    "--scenario-id",
    scenarioId,
  ], {
    cwd: packageRoot,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout = captureStream(child.stdout);
  const stderr = captureStream(child.stderr);
  const reader = createLineReader(child.stdout);
  const ready = JSON.parse(await reader.readLine("fake daemon ready"));
  return { child, observationsPath, socketPath: ready.socketPath, stderr, stdout };
}

async function startGateway(root, scenario, socketPath, descriptorPatch = {}) {
  const gatewayRoot = join(root, `${scenario.scenario_id}-gateway`);
  const primeSourceRoot = join(root, `${scenario.scenario_id}-prime-source`);
  const artifactLockPath = join(root, `${scenario.scenario_id}-artifact-lock.json`);
  const agentDir = join(root, "agent");
  for (const directory of [
    gatewayRoot,
    primeSourceRoot,
    join(root, "workspace"),
    agentDir,
    join(root, "session"),
  ]) {
    await mkdir(directory, { mode: 0o700, recursive: true });
  }
  await writeFile(artifactLockPath, JSON.stringify(await createPrimeSource(primeSourceRoot)));
  const descriptor = {
    agentDir,
    artifactLockPath,
    authorityId: "authority-1",
    authorityRevision: 1,
    expectedRuntimeBuildId: "fake-build-1",
    gatewayRoot,
    generation: 1,
    maxContinuations: 1,
    maxControllerTokens: 100,
    maxTurns: 1,
    model: "provider-free-model",
    portfolio: [{
      kind: "application",
      provider_id: "example.provider",
      application_id: "alpha",
      version: "1.0.0",
      runtime_id: "fake.runtime",
    }],
    primeSocketPath: socketPath,
    primeSourceRoot,
    provider: "provider-free",
    remainingBudget: {
      controller_tokens: 0,
      application_tokens: 100,
      child_tokens: 100,
      aggregate_tokens: 200,
      cost_micros: 0,
      deadline_ms: 10_000,
    },
    sessionDir: join(root, "session"),
    sessionId: "session-1",
    skillPath: join(root, "skill.md"),
    timeoutMs: 2_000,
    workspace: join(root, "workspace"),
    ...descriptorPatch,
  };
  await writeFile(descriptor.skillPath, "# provider-free skill\n");
  const descriptorPath = join(root, `${scenario.scenario_id}-descriptor.json`);
  await writeFile(descriptorPath, JSON.stringify(descriptor));
  const descriptorFile = await open(descriptorPath, "r");
  const child = spawn(process.execPath, [join(packageRoot, "dist/src/main.js")], {
    cwd: packageRoot,
    env: {
      ...process.env,
      ASTERION_PRIME_PRIVATE_FD: "3",
    },
    stdio: ["pipe", "pipe", "pipe", descriptorFile.fd],
  });
  child.once("exit", () => descriptorFile.close().catch(() => undefined));
  return {
    child,
    agentDir,
    gatewayRoot,
    stderr: captureStream(child.stderr),
    stdout: captureStream(child.stdout),
    reader: createLineReader(child.stdout),
  };
}

async function startInvalidDescriptorGateway(portfolio) {
  const root = await mkdtemp(join(tmpdir(), "asterion-prime-invalid-"));
  const gateway = await startGateway(
    root,
    { scenario_id: "portfolio-invalid" },
    join(root, "missing-prime.sock"),
    { portfolio },
  );
  gateway.child.stdin.end();
  const exit = await waitForExit(gateway.child, "invalid descriptor gateway");
  await rm(root, { recursive: true, force: true });
  return exit;
}

function command(type, payload, commandId) {
  return {
    protocol: "asterion.agent-control/v1",
    command_id: commandId,
    session_id: "session-1",
    authority_revision: 1,
    type,
    payload,
  };
}

function terminalForScenario(scenarioId) {
  if (scenarioId === "prime-loop-cancel") {
    return ["cancelled", "cancelled"];
  }
  if (scenarioId === "prime-loop-budget") {
    return ["failed", "budget-limited"];
  }
  if (scenarioId === "prime-loop-worker-crash") {
    return ["uncertain", "worker-crash"];
  }
  return ["uncertain", "wire-closed"];
}

async function streamEvents(gateway, scenarioId, cursor = null) {
  const response = await request(gateway, {
    protocol: PRIME_GATEWAY_IPC_PROTOCOL,
    id: `${scenarioId}-events-${Date.now()}`,
    type: "events.stream",
    cursor,
  });
  assert.equal(
    response.type,
    "events.batch",
    `${scenarioId} events failed; stderr=${gateway.stderr.text()}`,
  );
  return response.events;
}

async function readJsonFile(path) {
  return JSON.parse(await readFile(path, "utf8"));
}

async function waitForJsonFile(path, label) {
  return waitUntil(async () => {
    try {
      return await readJsonFile(path);
    } catch {
      return undefined;
    }
  }, label);
}

async function resolveObservedActions(gateway, scenario, pathlightNodes, expectedCount = 1) {
  const resolved = new Set();
  await waitUntil(async () => {
    const events = await streamEvents(gateway, scenario.scenario_id);
    const proposals = events.filter((event) => event.type === "action.proposed");
    for (const proposal of proposals) {
      const actionId = proposal.payload.action_id;
      if (resolved.has(actionId)) {
        continue;
      }
      resolved.add(actionId);
      if (proposal.payload.kind === "child.spawn") {
        pathlightNodes.push("child-session");
        if (scenario.scenario_id === "prime-loop-redaction") {
          pathlightNodes.push("action-running");
        }
      } else {
        pathlightNodes.push("action-running");
      }
      const admission = await request(gateway, {
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: `${scenario.scenario_id}-admit-${resolved.size}`,
        type: "command.accept",
        command: command("action.resolve", {
          action_id: actionId,
          resolution: "admitted",
          reason_code: "authorized",
          receipt_ref: null,
        }, `${scenario.scenario_id}-admit-${resolved.size}`),
        private: {},
      });
      assert.equal(admission.type, "command.accepted", `${scenario.scenario_id} admission failed`);
      const [resolution, reasonCode] = terminalForScenario(scenario.scenario_id);
      const terminal = await request(gateway, {
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: `${scenario.scenario_id}-terminal-${resolved.size}`,
        type: "command.accept",
        command: command("action.resolve", {
          action_id: actionId,
          resolution,
          reason_code: reasonCode,
          receipt_ref: null,
        }, `${scenario.scenario_id}-terminal-${resolved.size}`),
        private: {},
      });
      assert.equal(terminal.type, "command.accepted", `${scenario.scenario_id} terminal failed`);
      pathlightNodes.push("action-receipt");
    }
    return resolved.size >= expectedCount ? true : undefined;
  }, `${scenario.scenario_id} action proposal`);
}

function scenarioHasBridgeEffect(scenarioId) {
  return [
    "prime-loop-application",
    "prime-loop-child",
    "prime-loop-redaction",
    "prime-loop-worker-crash",
    "prime-loop-cancel",
    "prime-loop-budget",
  ].includes(scenarioId);
}

function stableUnique(values) {
  return [...new Set(values)];
}

function mergeCounts(left = {}, right = {}) {
  const merged = { ...left };
  for (const [key, value] of Object.entries(right)) {
    merged[key] = (merged[key] ?? 0) + value;
  }
  return merged;
}

async function runScenario(scenario) {
  const root = await mkdtemp(join(tmpdir(), "asterion-prime-loop-"));
  let daemon;
  let gateway;
  let daemonStarts = 0;
  let gatewayStarts = 0;
  let commandCounts = {};
  try {
    daemon = await startFakeDaemon(root, scenario.scenario_id);
    daemonStarts += 1;
    gateway = await startGateway(root, scenario, daemon.socketPath);
    gatewayStarts += 1;
    const createResponse = await request(gateway, {
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: `${scenario.scenario_id}-create`,
      type: "command.accept",
      command: command("session.create", {
        system_id: "research.system",
        system_version: "1.0.0",
        goal_id: "goal-1",
        goal_ref: "goal-ref-1",
      }, "command-create"),
      private: { goal: "SENTINEL_PROMPT" },
    });
    assert.equal(
      createResponse.type,
      "command.accepted",
      `${scenario.scenario_id} create failed; stderr=${gateway.stderr.text()}`,
    );
    const discoveryPath = join(gateway.agentDir, discoveryFileName);
    const discovery = JSON.parse(await readFile(discoveryPath, "utf8"));
    assert.equal(discovery.protocol, "asterion.skill-control-discovery/v1");
    assert.equal(discovery.session_id, "session-1");
    assert.match(discovery.token, /^[0-9a-f]{64}$/u);
    assert.equal((await stat(discoveryPath)).mode & 0o777, 0o600);
    const rlmDiscoveryPath = join(gateway.agentDir, rlmDiscoveryFileName);
    const rlmDiscovery = JSON.parse(await readFile(rlmDiscoveryPath, "utf8"));
    assert.equal(rlmDiscovery.protocol, "asterion.prime-rlm-host-discovery/v1");
    assert.equal(rlmDiscovery.session_id, "session-1");
    assert.match(rlmDiscovery.token, /^[0-9a-f]{64}$/u);
    assert.equal((await stat(rlmDiscoveryPath)).mode & 0o777, 0o600);
    if (scenario.scenario_id === "prime-loop-gateway-crash") {
      gateway.child.kill("SIGTERM");
      await waitForExit(gateway.child, `${scenario.scenario_id} gateway crash`);
      gateway = await startGateway(root, scenario, daemon.socketPath);
      gatewayStarts += 1;
    }
    if (scenario.scenario_id === "prime-loop-supervisor-crash") {
      const beforeRestart = await waitForJsonFile(
        daemon.observationsPath,
        `${scenario.scenario_id} restart observations`,
      );
      commandCounts = mergeCounts(commandCounts, beforeRestart.commandCounts);
      daemon.child.kill("SIGTERM");
      await waitForExit(daemon.child, `${scenario.scenario_id} fake daemon crash`);
      daemon = await startFakeDaemon(root, scenario.scenario_id);
      daemonStarts += 1;
    }
    if (scenarioHasBridgeEffect(scenario.scenario_id)) {
      await resolveObservedActions(
        gateway,
        scenario,
        [],
        scenario.scenario_id === "prime-loop-application" ? 2 : 1,
      );
    }
    const events = await streamEvents(gateway, scenario.scenario_id);
    await waitUntil(async () => {
      let current;
      try {
        current = JSON.parse(await readFile(daemon.observationsPath, "utf8"));
      } catch {
        return undefined;
      }
      const expectedResponses =
        scenario.scenario_id === "prime-loop-application" && daemonStarts === 1
          ? 2
          : scenarioHasBridgeEffect(scenario.scenario_id) && daemonStarts === 1
            ? 1
            : 0;
      return (
        current.skillResponses.length >= expectedResponses ||
        current.skillFailures.length > 0
      ) ? current : undefined;
    }, `${scenario.scenario_id} daemon observations`);
    gateway.child.stdin.end();
    await waitForExit(gateway.child, `${scenario.scenario_id} gateway`);
    daemon.child.kill("SIGTERM");
    await waitForExit(daemon.child, `${scenario.scenario_id} fake daemon`);
    const daemonObservations = await waitForJsonFile(
      daemon.observationsPath,
      `${scenario.scenario_id} final daemon observations`,
    );
    commandCounts = mergeCounts(commandCounts, daemonObservations.commandCounts);
    const observations = { ...daemonObservations, commandCounts };
    assert.deepEqual(observations.skillFailures, [], scenario.scenario_id);
    const serialized = JSON.stringify({
      createResponse,
      events,
      observations,
      gatewayStdout: gateway.stdout.text(),
      gatewayStderr: gateway.stderr.text(),
      daemonStdout: daemon.stdout.text(),
      daemonStderr: daemon.stderr.text(),
    });
    for (const sentinel of sentinels) {
      assert.equal(serialized.includes(sentinel), false);
    }
    assert.equal(observations.modelProviderOperations, 0);
    return {
      observations,
      events,
      discovery,
      processCounts: {
        fake_daemon: daemonStarts,
        gateway: gatewayStarts,
      },
      stderr: gateway.stderr.text(),
      stdout: gateway.stdout.text(),
    };
  } finally {
    gateway?.child.kill("SIGTERM");
    daemon?.child.kill("SIGTERM");
    await rm(root, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 50,
    });
  }
}

test("sidecar recovery and bridge boundaries use provider-free real processes", async () => {
  const scenarios = JSON.parse(await readFile(scenariosUrl, "utf8"));
  assert.deepEqual(scenarios.map((item) => item.scenario_id), expectedIds);
  const byId = new Map(scenarios.map((item) => [item.scenario_id, item]));

  const application = await runScenario(byId.get("prime-loop-application"));
  assert.equal(application.observations.scenarioId, "prime-loop-application");
  assert.deepEqual(application.observations.skillOperations, [
    "application.invoke",
    "goal.complete",
  ]);
  assert.equal(application.observations.applicationOperations, 1);
  assert.equal(application.observations.commandCounts.create, 1);
  assert.equal(application.observations.commandCounts.set_rlm_max_depth, 1);
  assert.equal(application.observations.commandCounts.attach, 1);
  assert.equal(application.observations.commandCounts.detach, 1);
  assert.equal(application.discovery.protocol, "asterion.skill-control-discovery/v1");

  const gatewayCrash = await runScenario(byId.get("prime-loop-gateway-crash"));
  assert.equal(gatewayCrash.processCounts.gateway, 2);
  assert.equal(gatewayCrash.observations.commandCounts.attach, 2);
  assert.equal(gatewayCrash.observations.commandCounts.detach, 1);
  assert.ok(
    gatewayCrash.events.some((event) => event.type === "session.recovery-required"),
  );
  assert.ok(gatewayCrash.events.some((event) => event.type === "session.running"));

  const redaction = await runScenario(byId.get("prime-loop-redaction"));
  assert.deepEqual(redaction.observations.skillOperations, ["child.spawn"]);
  assert.equal(JSON.stringify(redaction).includes("SENTINEL"), false);
});

test("sidecar descriptor requires non-empty sorted unique exact portfolio", async () => {
  const alpha = {
    kind: "application",
    provider_id: "example.provider",
    application_id: "alpha",
    version: "1.0.0",
    runtime_id: "fake.runtime",
  };
  const beta = {
    kind: "application",
    provider_id: "example.provider",
    application_id: "beta",
    version: "1.0.0",
    runtime_id: "fake.runtime",
  };

  for (const portfolio of [
    [],
    [alpha, alpha],
    [beta, alpha],
  ]) {
    const exit = await startInvalidDescriptorGateway(portfolio);
    assert.equal(exit.code, 1);
  }
});
