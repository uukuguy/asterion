import { chmod, readFile, writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";


const [socketPath, sourceRoot, workspace, agentDir, sessionDir, resultPath] =
  process.argv.slice(2);
if (
  [socketPath, sourceRoot, workspace, agentDir, sessionDir, resultPath]
    .some((value) => typeof value !== "string" || !isAbsolute(value))
) {
  throw new Error("bounded Prime continual harness inputs are invalid");
}

const sessionManagerUrl = pathToFileURL(join(
  sourceRoot,
  "packages/coding-agent/dist/core/session-manager.js",
));
const daemonClientUrl = pathToFileURL(join(
  sourceRoot,
  "packages/coding-agent/dist/modes/daemon/daemon-client.js",
));
const { SessionManager } = await import(sessionManagerUrl.href);
const { DaemonClient } = await import(daemonClientUrl.href);
const rlmShimSource = new URL(
  "../../../../packages/typescript/prime-gateway/resources/rlm-host-shim.mjs",
  import.meta.url,
);
const rlmShimPath = join(agentDir, "asterion-rlm-host-shim.mjs");
await writeFile(rlmShimPath, await readFile(rlmShimSource), { mode: 0o600 });
await chmod(rlmShimPath, 0o600);
const rlmDiscoveryPath = join(agentDir, "asterion-rlm-host.json");
await writeFile(
  rlmDiscoveryPath,
  JSON.stringify({
    protocol: "asterion.prime-rlm-host-discovery/v1",
    socket_path: join(agentDir, "r.sock"),
    token: "0".repeat(64),
    session_id: "prime-continual-harness-bounded",
    budget: {
      controller_tokens: 0,
      application_tokens: 0,
      child_tokens: 0,
      aggregate_tokens: 0,
      cost_micros: 0,
      deadline_ms: 1,
    },
  }),
  { mode: 0o600 },
);
await chmod(rlmDiscoveryPath, 0o600);

const evidenceIds = Object.freeze(
  Array.from({ length: 7 }, (_, index) => `evidence-input-${index}`),
);
const evidenceBodies = Object.freeze([
  "Composition must remain deterministic and fail closed on ambiguity.",
  "Runtime streams require one run ID, contiguous sequences, and one terminal event.",
  "Manifests describe compatibility and must not contain credentials or mutable state.",
  "Runners execute resolved plans sequentially and stop on failure or cancellation.",
  "Host services are operator-owned and injected only after host preflight.",
  "Public evidence must redact prompts, answers, credentials, payloads, and private paths.",
  "Verification claims require a named passing command within the stated boundary.",
]);

function requireRecord(value, label) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function requireString(value, label) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function createEvidenceSession() {
  const manager = SessionManager.create(workspace, sessionDir);
  for (let index = 0; index < evidenceIds.length; index += 1) {
    manager.appendMessage({
      role: "user",
      content: `<evidence id="${evidenceIds[index]}">${evidenceBodies[index]}</evidence>`,
      timestamp: index + 1,
    });
  }
  manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text: "Evidence set received for bounded refinement." }],
    api: "openai-responses",
    provider: "faux",
    model: "faux",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "stop",
    timestamp: 8,
  });
  manager.flushNow();
  return requireString(manager.getSessionFile(), "evidence session path");
}

const configuredModel = process.env.ASTERION_PRIME_EXPERIMENT_MODEL;
const model = configuredModel === "deepseek-v4-flash-0731"
  ? "deepseek-v4-flash"
  : configuredModel;
if (typeof model !== "string" || model.length === 0) {
  throw new Error("bounded Prime continual harness model is invalid");
}

const client = new DaemonClient(socketPath);
let activeSessionId;
await client.connect(5_000);
try {
  const hello = requireRecord(await client.waitForHello(5_000), "daemon hello");
  const protocol = requireRecord(hello.protocol, "daemon protocol");
  if (
    protocol.name !== "prime-agent.daemon" ||
    protocol.version !== 7 ||
    hello.schemaRevision !== 14 ||
    hello.appVersion !== "0.7.1"
  ) {
    throw new Error("bounded Prime continual harness daemon is incompatible");
  }
  const created = await client.request({
    type: "create",
    sessionPath: createEvidenceSession(),
    continueRecent: false,
    noSession: false,
    lifecycle: "resident",
    config: {
      cwd: workspace,
      agentDir,
      sessionDir,
      provider: "deepseek",
      model,
      models: [`deepseek/${model}`],
      skills: [],
      autonomous: {
        enabled: false,
        maxContinuations: 1,
        maxTurns: 1,
        maxTokens: 1,
        timeoutMs: 1_000,
        gates: { commands: [], maxRetries: 1, timeoutMs: 1_000 },
      },
      telemetryDisabled: true,
    },
  }, 15_000);
  if (!created.success || created.command !== "create") {
    throw new Error(
      `bounded Prime continual harness resident creation failed: ${String(created.error ?? "unknown")}`,
    );
  }
  activeSessionId = requireString(
    requireRecord(created.data, "create response").activeSessionId,
    "active session",
  );
  const selected = await client.request({
    type: "set_model",
    activeSessionId,
    provider: "deepseek",
    modelId: model,
  }, 15_000);
  if (!selected.success || selected.command !== "set_model") {
    throw new Error("bounded Prime continual harness model selection failed");
  }

  if (process.env.ASTERION_PRIME_HARNESS_PREFLIGHT_ONLY === "1") {
    process.stdout.write(JSON.stringify({
      status: "PASS",
      provider_operations: 0,
      model_credential_reads: 0,
      boundary: "before-refine",
    }) + "\n");
  } else {
    const refinement = await client.request({
      type: "refine",
      activeSessionId,
      instructions: [
        "Use exactly the seven tagged evidence inputs in the conversation.",
        "Create exactly one local memory entry that preserves their shared operational lesson.",
        `The rationale must cite every evidence ID verbatim: ${evidenceIds.join(", ")}.`,
        "Do not propose update or delete edits and do not include secrets or executable commands.",
      ].join(" "),
      global: false,
    }, 570_000);
    if (!refinement.success || refinement.command !== "refine") {
      throw new Error("bounded Prime continual harness refinement failed");
    }
    const result = requireRecord(refinement.data, "refinement result");
    const applied = result.appliedEdits;
    if (
      result.scope !== "local" ||
      !Array.isArray(applied) ||
      applied.length !== 1 ||
      applied[0]?.action !== "create" ||
      applied[0]?.applied !== true ||
      !evidenceIds.every((evidenceId) =>
        typeof result.rationale === "string" && result.rationale.includes(evidenceId)
      )
    ) {
      throw new Error("bounded Prime continual harness result is ungrounded");
    }
    await writeFile(resultPath, `${JSON.stringify(result)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    process.stdout.write(JSON.stringify({
      status: "PASS",
      evidence_input_count: evidenceIds.length,
      provider_operations: 1,
      model_credential_reads: 1,
    }) + "\n");
  }
} finally {
  if (activeSessionId !== undefined) {
    try {
      await client.request({ type: "kill", activeSessionId }, 15_000);
    } catch {
      // The owning Python process terminates the isolated daemon unconditionally.
    }
  }
  client.close();
}
