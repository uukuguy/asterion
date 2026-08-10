import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  open,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  PRIME_GATEWAY_IPC_PROTOCOL,
} from "../dist/src/main.js";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
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
  const lock = {
    format: "asterion.prime-artifact-lock/v1",
    source_commit: "a18809e00ea30638584d87b3afea7285a9d7296c",
    package_name: "@earendil-works/pi-coding-agent",
    package_version: "0.7.1",
    daemon_protocol: 7,
    daemon_schema_revision: 14,
    daemon_schema_id: "protocol-7-schema-14-816309b1cd50",
    files: Object.fromEntries(
      Object.entries(contents).map(([name, value]) => [name, sha256(value)]),
    ),
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

async function startFakeDaemon(root, scenarioId) {
  const observationsPath = join(root, "daemon-observations.json");
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

async function startGateway(root, scenario, socketPath) {
  const gatewayRoot = join(root, `${scenario.scenario_id}-gateway`);
  const primeSourceRoot = join(root, `${scenario.scenario_id}-prime-source`);
  const artifactLockPath = join(root, `${scenario.scenario_id}-artifact-lock.json`);
  for (const directory of [
    gatewayRoot,
    primeSourceRoot,
    join(root, "workspace"),
    join(root, "agent"),
    join(root, "session"),
  ]) {
    await mkdir(directory, { mode: 0o700, recursive: true });
  }
  await writeFile(artifactLockPath, JSON.stringify(await createPrimeSource(primeSourceRoot)));
  const descriptor = {
    agentDir: join(root, "agent"),
    artifactLockPath,
    authorityId: "authority-1",
    expectedRuntimeBuildId: "fake-build-1",
    gatewayRoot,
    generation: 1,
    maxContinuations: 1,
    maxControllerTokens: 100,
    maxTurns: 1,
    model: "provider-free-model",
    primeSocketPath: socketPath,
    primeSourceRoot,
    provider: "provider-free",
    sessionDir: join(root, "session"),
    sessionId: "session-1",
    skillPath: join(root, "skill.md"),
    timeoutMs: 2_000,
    workspace: join(root, "workspace"),
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
    gatewayRoot,
    stderr: captureStream(child.stderr),
    stdout: captureStream(child.stdout),
    reader: createLineReader(child.stdout),
  };
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

async function runScenario(scenario) {
  const root = await mkdtemp(join(tmpdir(), "asterion-prime-loop-"));
  let daemon;
  let gateway;
  try {
    daemon = await startFakeDaemon(root, scenario.scenario_id);
    gateway = await startGateway(root, scenario, daemon.socketPath);
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
    if (scenario.scenario_id === "prime-loop-gateway-crash") {
      gateway.child.kill("SIGTERM");
      await waitForExit(gateway.child, `${scenario.scenario_id} gateway crash`);
      gateway = await startGateway(root, scenario, daemon.socketPath);
    }
    const events = await request(gateway, {
      protocol: PRIME_GATEWAY_IPC_PROTOCOL,
      id: `${scenario.scenario_id}-events`,
      type: "events.stream",
      cursor: null,
    });
    assert.equal(
      events.type,
      "events.batch",
      `${scenario.scenario_id} events failed; stderr=${gateway.stderr.text()}`,
    );
    gateway.child.stdin.end();
    await waitForExit(gateway.child, `${scenario.scenario_id} gateway`);
    daemon.child.kill("SIGTERM");
    await waitForExit(daemon.child, `${scenario.scenario_id} fake daemon`);
    const observations = JSON.parse(await readFile(daemon.observationsPath, "utf8"));
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
    return observations;
  } finally {
    gateway?.child.kill("SIGTERM");
    daemon?.child.kill("SIGTERM");
    await rm(root, { recursive: true, force: true });
  }
}

test("verified loop scenarios run through provider-free real processes", async () => {
  const scenarios = JSON.parse(await readFile(scenariosUrl, "utf8"));
  assert.deepEqual(scenarios.map((item) => item.scenario_id), expectedIds);
  for (const scenario of scenarios) {
    const observations = await runScenario(scenario);
    assert.equal(observations.scenarioId, scenario.scenario_id);
    assert.ok(observations.commandCounts.create >= 1);
    assert.equal(observations.commandCounts.set_rlm_max_depth, 1);
    assert.ok(observations.commandCounts.attach >= 1);
  }
});
