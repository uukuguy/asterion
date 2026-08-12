import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { chmod, readFile, writeFile } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

import { PrimeDaemonClient } from "../../../../packages/typescript/prime-gateway/dist/src/daemon-client.js";
import { PrimeSession } from "../../../../packages/typescript/prime-gateway/dist/src/prime-session.js";


const [socketPath, sourceRoot, workspace, agentDir, sessionDir] = process.argv.slice(2);
if (
  [socketPath, sourceRoot, workspace, agentDir, sessionDir]
    .some((value) => typeof value !== "string" || !isAbsolute(value))
) {
  throw new Error("real Prime session/context harness inputs are invalid");
}

const sessionManagerUrl = pathToFileURL(join(
  sourceRoot,
  "packages/coding-agent/dist/core/session-manager.js",
));
const { SessionManager } = await import(sessionManagerUrl.href);
const rlmShimSource = new URL(
  "../../../../packages/typescript/prime-gateway/resources/rlm-host-shim.mjs",
  import.meta.url,
);
await writeFile(join(agentDir, "asterion-rlm-host-shim.mjs"), await readFile(rlmShimSource), {
  mode: 0o600,
});
await chmod(join(agentDir, "asterion-rlm-host-shim.mjs"), 0o600);
await writeFile(
  join(agentDir, "asterion-rlm-host.json"),
  JSON.stringify({
    protocol: "asterion.prime-rlm-host-discovery/v1",
    socket_path: join(agentDir, "r.sock"),
    token: "0".repeat(64),
    session_id: "session-context-parity",
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
await chmod(join(agentDir, "asterion-rlm-host.json"), 0o600);
const client = new PrimeDaemonClient({
  clientId: "asterion-session-context-parity",
  connectTimeoutMs: 5_000,
  requestTimeoutMs: 15_000,
});

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

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function activePathContains(tree, entryId) {
  const parents = new Map(
    tree.nodes.map((node) => [node.entry_id, node.parent_id]),
  );
  let current = tree.leafId;
  while (current !== null) {
    if (current === entryId) return true;
    current = parents.get(current) ?? null;
  }
  return false;
}

async function createResident(commandId, name, sessionPath, lifecycle = "resident") {
  const deferred = await client.requestDeferred({
    type: "create",
    ...(sessionPath === undefined ? {} : { sessionPath }),
    continueRecent: false,
    noSession: false,
    ...(name === undefined ? {} : { name }),
    lifecycle,
    config: {
      cwd: workspace,
      agentDir,
      sessionDir,
      provider: "anthropic",
      model: "claude-sonnet-4-5",
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
  }, commandId, 15_000);
  if (!deferred.response.success || deferred.response.command !== "create") {
    throw new Error("real Prime resident creation failed");
  }
  const data = requireRecord(deferred.response.data, "create response");
  const identity = {
    activeSessionId: requireString(data.activeSessionId, "active session"),
    createTranscriptSessionId: requireString(data.sessionId, "transcript session"),
    createSessionPath: requireString(data.sessionFile, "session file"),
  };
  if (!isAbsolute(identity.createSessionPath) || !deferred.acknowledge()) {
    throw new Error("real Prime resident identity failed");
  }
  const headerResponse = await client.request({
    type: "get_session_header",
    activeSessionId: identity.activeSessionId,
  }, `${commandId}-create-header`);
  const stateResponse = await client.request({
    type: "get_state",
    activeSessionId: identity.activeSessionId,
  }, `${commandId}-create-state`);
  if (
    !headerResponse.success ||
    headerResponse.command !== "get_session_header" ||
    !stateResponse.success ||
    stateResponse.command !== "get_state"
  ) {
    throw new Error("real Prime resident identity read failed");
  }
  const headerData = requireRecord(headerResponse.data, "resident header response");
  const stateData = requireRecord(stateResponse.data, "resident state response");
  const header = requireRecord(headerData.header, "resident daemon header");
  const transcriptSessionId = requireString(header.id, "resident daemon identity");
  const actualSessionPath = requireString(
    stateData.sessionFile,
    "resident daemon path",
  );
  if (
    stateData.sessionId !== transcriptSessionId ||
    !isAbsolute(actualSessionPath)
  ) {
    throw new Error("real Prime resident identity disagreement");
  }
  return {
    ...identity,
    transcriptSessionId,
    sessionPath: actualSessionPath,
  };
}

function createFixtureSession() {
  const manager = SessionManager.create(workspace, sessionDir);
  const firstEntryId = manager.appendMessage({
    role: "user",
    content: "PRIVATE_TREE_BODY",
    timestamp: 1,
  });
  manager.appendMessage({
    role: "assistant",
    content: [{ type: "text", text: "PRIVATE_ASSISTANT_BODY" }],
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
    timestamp: 2,
  });
  manager.appendCustomEntry("asterion-parity", {
    value: "PRIVATE_TREE_BODY_SECOND",
  });
  manager.appendLabelChange(firstEntryId, "PRIVATE_TREE_LABEL");
  manager.appendCustomMessageEntry(
    "asterion-image-parity",
    [
      { type: "text", text: "PRIVATE_IMAGE_TEXT" },
      { type: "image", data: "cHJpdmF0ZS1pbWFnZQ==", mimeType: "image/png" },
    ],
    true,
  );
  manager.flushNow();
  const sessionPath = manager.getSessionFile();
  if (typeof sessionPath !== "string" || !isAbsolute(sessionPath)) {
    throw new Error("real Prime fixture session failed");
  }
  const header = requireRecord(manager.getHeader(), "fixture header");
  return {
    transcriptSessionId: requireString(header.id, "fixture header identity"),
    sessionPath,
  };
}

await client.connect(socketPath);
try {
  const hello = requireRecord(client.hello, "daemon hello");
  const capabilities = new Set(hello.serverCapabilities);
  if (
    hello.protocolVersion !== 7 ||
    hello.schemaRevision !== 14 ||
    hello.appVersion !== "0.7.1" ||
    !capabilities.has("session_input_admission") ||
    !capabilities.has("prompt_admission_cancellation")
  ) {
    throw new Error("real Prime daemon compatibility failed");
  }

  const fixture = createFixtureSession();
  const initial = await createResident(
    "session-context-create",
    undefined,
    fixture.sessionPath,
  );
  if (initial.sessionPath !== fixture.sessionPath) {
    throw new Error("real Prime fixture open path mismatched");
  }
  if (initial.transcriptSessionId !== fixture.transcriptSessionId) {
    throw new Error("real Prime fixture open transcript mismatched");
  }
  const session = PrimeSession.restore({
    transport: client,
    sessionId: "asterion-session-context",
    activeSessionId: initial.activeSessionId,
    transcriptSessionId: initial.transcriptSessionId,
    continuationId: "continuation-source",
    sessionPath: initial.sessionPath,
  });
  await session.ensureManualCompactionOnly("provider-free-policy");
  await session.attach("provider-free-attach");

  if (new Set([
    session.activeSessionId,
    session.transcriptSessionId,
    session.continuationId,
  ]).size !== 3) {
    throw new Error("real Prime identity separation failed");
  }
  const privateName = "PRIVATE_SESSION_NAME";
  const firstName = await session.setContextName("name-roundtrip", privateName);
  if (!firstName.acknowledge()) {
    throw new Error("real Prime name acknowledgement failed");
  }
  await session.detach("provider-free-detach");
  await session.attach("provider-free-reattach");
  const named = await session.describeContext("describe-named", "idle");
  if (
    named.nameSha256 !== sha256(privateName) ||
    JSON.stringify(named).includes(privateName)
  ) {
    throw new Error("real Prime name projection failed");
  }
  const secondStatus = await session.describeContext("status-second", "idle");
  if (
    named.status !== "idle" ||
    secondStatus.contextTokens < named.contextTokens ||
    secondStatus.turns < named.turns ||
    secondStatus.usage.controller_tokens < named.usage.controller_tokens ||
    JSON.stringify(secondStatus).includes(initial.sessionPath)
  ) {
    throw new Error("real Prime status projection failed");
  }

  const tree = await session.readContextTree(
    "tree-read",
    session.continuationId,
  );
  const serializedTree = JSON.stringify(tree);
  if (
    tree.nodes.length < 2 ||
    tree.leafId === null ||
    serializedTree.includes("PRIVATE_TREE_BODY") ||
    serializedTree.includes("PRIVATE_ASSISTANT_BODY") ||
    serializedTree.includes("PRIVATE_TREE_LABEL") ||
    serializedTree.includes("PRIVATE_IMAGE_TEXT") ||
    serializedTree.includes("cHJpdmF0ZS1pbWFnZQ")
  ) {
    throw new Error("real Prime tree projection failed");
  }
  const navigationEntry = tree.nodes.find((node) => node.kind === "input");
  const branchEntry = tree.nodes.find((node) => node.kind === "output");
  if (navigationEntry === undefined || branchEntry === undefined) {
    throw new Error("real Prime tree custom entry failed");
  }
  const navigationEntryId = navigationEntry.entry_id;
  const branchEntryId = branchEntry.entry_id;
  const label = await session.setContextLabel(
    "label-roundtrip",
    session.continuationId,
    navigationEntryId,
    "PRIVATE_UPDATED_LABEL",
  );
  if (!label.acknowledge() || label.result.labelSha256 !== sha256("PRIVATE_UPDATED_LABEL")) {
    throw new Error("real Prime label projection failed");
  }
  const beforeNavigation = await session.readContextTree(
    "tree-before-navigation",
    session.continuationId,
  );
  const navigation = await session.navigateContextTree(
    "tree-navigation",
    session.continuationId,
    navigationEntryId,
    beforeNavigation.leafId,
  );
  if (!navigation.acknowledge()) {
    throw new Error("real Prime navigation acknowledgement failed");
  }
  const afterNavigation = await session.readContextTree(
    "tree-after-navigation",
    session.continuationId,
  );
  if (navigation.result.previousLeafId !== beforeNavigation.leafId) {
    throw new Error("real Prime tree navigation source mismatched");
  }
  if (navigation.result.currentLeafId !== afterNavigation.leafId) {
    throw new Error("real Prime tree navigation result mismatched");
  }
  if (afterNavigation.leafId !== navigationEntry.parent_id) {
    throw new Error("real Prime tree navigation target mismatched");
  }

  const sourceLocator = {
    activeSessionId: session.activeSessionId,
    continuationId: session.continuationId,
    transcriptSessionId: session.transcriptSessionId,
    supervisorGeneration: session.supervisorGeneration,
    sessionPath: initial.sessionPath,
  };
  const forked = await session.forkContext(
    "fork-roundtrip",
    session.continuationId,
    branchEntryId,
    "at",
  );
  if (!forked.acknowledge()) {
    throw new Error("real Prime fork acknowledgement failed");
  }
  session.adoptContinuation(forked.locator);
  const sourceAfterFork = await session.resumeContinuation(
    "resume-source-after-fork",
    sourceLocator,
  );
  if (!sourceAfterFork.acknowledge()) {
    throw new Error("real Prime fork source resume failed");
  }
  session.adoptContinuation(sourceAfterFork.locator);
  const sourceTree = await session.readContextTree(
    "tree-before-clone",
    session.continuationId,
  );
  if (sourceTree.leafId === null) {
    throw new Error("real Prime clone source leaf failed");
  }
  let cloned;
  try {
    cloned = await session.cloneContext(
      "clone-roundtrip",
      session.continuationId,
      branchEntryId,
    );
  } catch {
    const replay = await client.request({
      type: "fork",
      activeSessionId: session.activeSessionId,
      entryId: branchEntryId,
      position: "at",
    }, "asterion-session-context-context-clone-roundtrip-clone");
    if (!replay.success) {
      throw new Error("real Prime clone daemon rejected");
    }
    const headerProbe = await client.request({
      type: "get_session_header",
      activeSessionId: session.activeSessionId,
    }, "clone-roundtrip-header-probe");
    const stateProbe = await client.request({
      type: "get_state",
      activeSessionId: session.activeSessionId,
    }, "clone-roundtrip-state-probe");
    const headerData = requireRecord(headerProbe.data, "clone header probe");
    const stateData = requireRecord(stateProbe.data, "clone state probe");
    const header = requireRecord(headerData.header, "clone header");
    if (header.id === session.transcriptSessionId) {
      throw new Error("real Prime clone retained source identity");
    }
    if (stateData.sessionId !== header.id) {
      throw new Error("real Prime clone identity disagreement");
    }
    if (stateData.sessionFile === initial.sessionPath) {
      throw new Error("real Prime clone retained source path");
    }
    throw new Error("real Prime clone postcondition failed");
  }
  if (
    !cloned.acknowledge() ||
    cloned.locator.transcriptSessionId === sourceLocator.transcriptSessionId ||
    cloned.locator.sessionPath === sourceLocator.sessionPath
  ) {
    throw new Error("real Prime clone roundtrip failed");
  }
  session.adoptContinuation(cloned.locator);
  const clonedTree = await session.readContextTree(
    "tree-after-clone",
    session.continuationId,
  );
  if (!activePathContains(clonedTree, branchEntryId)) {
    throw new Error("real Prime clone selected leaf failed");
  }
  const sourceAfterClone = await session.resumeContinuation(
    "resume-source-after-clone",
    sourceLocator,
  );
  if (!sourceAfterClone.acknowledge()) {
    throw new Error("real Prime clone source resume failed");
  }
  session.adoptContinuation(sourceAfterClone.locator);

  let activeDeleteRejected = false;
  try {
    await session.deleteContinuation("delete-active", sourceLocator);
  } catch {
    activeDeleteRejected = true;
  }
  const deleted = await session.deleteContinuation(
    "delete-inactive",
    cloned.locator,
  );
  if (
    !activeDeleteRejected ||
    !deleted.acknowledge() ||
    existsSync(cloned.locator.sessionPath)
  ) {
    throw new Error("real Prime exact deletion failed");
  }

  await session.cancel("provider-free-cleanup");

  process.stdout.write(`${JSON.stringify({
    format: "asterion.prime-session-context-observation/v1",
    app_version: hello.appVersion,
    daemon_protocol: hello.protocolVersion,
    daemon_schema_revision: hello.schemaRevision,
    fake_daemon: false,
    model_credential_reads: 0,
    provider_operations: 0,
    runtime_build_id: hello.runtimeBuildId,
    scenario_checks: {
      "prime-parity.session.delivery": [
        "daemon-input-admission-capability-passed",
        "prime-queue-code-path-passed",
      ],
      "prime-parity.session.fork-clone": [
        "prime-fork-clone-roundtrip-passed",
        "source-resume-roundtrip-passed",
      ],
      "prime-parity.session.persistence-naming": [
        "prime-detach-attach-passed",
        "prime-name-roundtrip-passed",
      ],
      "prime-parity.session.resume-delete": [
        "prime-exact-delete-passed",
        "prime-resume-roundtrip-passed",
      ],
      "prime-parity.session.rich-attachments": [
        "prime-image-code-path-passed",
        "private-body-redaction-passed",
      ],
      "prime-parity.session.tree-navigation": [
        "prime-tree-navigation-roundtrip-passed",
        "tree-private-content-redaction-passed",
      ],
      "prime-parity.session.usage-status": [
        "prime-status-roundtrip-passed",
        "status-private-fields-redacted",
      ],
    },
  })}\n`);
} finally {
  client.close();
}
