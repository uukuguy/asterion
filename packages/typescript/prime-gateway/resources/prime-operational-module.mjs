import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, mkdtemp, open, readFile, readdir, readlink, realpath, rm } from "node:fs/promises";
import { constants } from "node:fs";
import { isAbsolute, join, normalize, relative, sep } from "node:path";
import { tmpdir } from "node:os";
import { pathToFileURL } from "node:url";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const FORMAT = "asterion.prime-operational-module-lock/v1";
const SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c";
const NODE_RUNTIME = "v22.23.2";
const SOURCE_ANCHORS = Object.freeze([
  "packages/coding-agent/src/core/agent-session.ts",
  "packages/coding-agent/src/core/auth-storage.ts",
  "packages/coding-agent/src/core/diagnostics.ts",
  "packages/coding-agent/src/core/keybindings.ts",
  "packages/coding-agent/src/core/resource-loader.ts",
  "packages/coding-agent/src/core/settings-manager.ts",
  "packages/coding-agent/src/core/telemetry.ts",
  "packages/coding-agent/src/core/usage.ts",
  "packages/coding-agent/src/package-manager-cli.ts",
]);
const BUILT_ANCHORS = Object.freeze(SOURCE_ANCHORS.map((path) => path.replace("/src/", "/dist/").replace(/\.ts$/u, ".js")));
const PACKAGE_IDS = Object.freeze(["auth", "controlled-update-restart", "doctor", "model-selection", "settings-keybindings", "telemetry-usage"]);
const EFFECT_KEYS = Object.freeze([
  "credential_reads", "fake_coordinator_calls", "host_service_calls", "injected_sink_calls",
  "mock_refresh_calls", "network_requests", "provider_operations", "reconcile_calls",
  "retained_processes", "stdout_writes", "unauthorized_uploads",
]);

function fail() { throw new Error("Prime operational harness rejected its frame"); }
function sha256(value) { return createHash("sha256").update(value).digest("hex"); }
function record(value) { if (typeof value !== "object" || value === null || Array.isArray(value)) fail(); return value; }
function exactKeys(value, keys) { const actual = Object.keys(value).sort(); const expected = [...keys].sort(); if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(); }
function safeRelative(value) {
  if (typeof value !== "string" || !value || isAbsolute(value) || value.includes("\\") || normalize(value) !== value || value === ".." || value.startsWith(`..${sep}`) || value.endsWith(sep)) fail();
  return value;
}
function inside(root, target) { const remainder = relative(root, target); return remainder !== "" && remainder !== ".." && !remainder.startsWith(`..${sep}`) && !isAbsolute(remainder); }
function contained(root, target) { return root === target || inside(root, target); }
function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(canonicalJson);
  const item = record(value);
  return Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonicalJson(item[key])]));
}
function exactMap(value, expected) {
  const map = record(value); const keys = Object.keys(map);
  if (keys.join("\n") !== [...keys].sort().join("\n") || keys.join("\n") !== expected.join("\n")) fail();
  for (const key of expected) if (safeRelative(key) !== key || typeof map[key] !== "string" || !/^[0-9a-f]{64}$/u.test(map[key])) fail();
  return Object.freeze({ ...map });
}
async function lockedFile(root, path) {
  const relativePath = safeRelative(path); let current = root;
  for (const [index, part] of relativePath.split("/").entries()) {
    current = join(current, part); const metadata = await lstat(current); const last = index === relativePath.split("/").length - 1;
    if (metadata.isSymbolicLink() || (last ? !metadata.isFile() : !metadata.isDirectory())) fail();
  }
  const resolved = await realpath(current); if (!inside(root, resolved)) fail();
  const descriptor = await open(current, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const before = await descriptor.stat(); if (!before.isFile()) fail();
    const body = await descriptor.readFile(); const after = await descriptor.stat();
    if (before.dev !== after.dev || before.ino !== after.ino) fail();
    return body;
  } finally { await descriptor.close().catch(() => undefined); }
}
async function lockedAbsolute(path) {
  if (typeof path !== "string" || !isAbsolute(path)) fail();
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.isSymbolicLink() || (metadata.mode & 0o002) !== 0 || await realpath(path) !== path) fail();
  return await readFile(path);
}
async function canonicalTemporaryDirectory(path, temporaryRoot) {
  if (path === temporaryRoot || !inside(temporaryRoot, path)) fail();
  let current = temporaryRoot;
  for (const part of relative(temporaryRoot, path).split(sep)) {
    current = join(current, part);
    const metadata = await lstat(current);
    if (metadata.isSymbolicLink() || !metadata.isDirectory()) fail();
  }
}
async function isAsterionProjectTree(path) {
  try {
    const [project, schemas, packages] = await Promise.all([
      lstat(join(path, "pyproject.toml")), lstat(join(path, "schemas")), lstat(join(path, "packages")),
    ]);
    if (project.isSymbolicLink() || schemas.isSymbolicLink() || packages.isSymbolicLink() || !project.isFile() || !schemas.isDirectory() || !packages.isDirectory()) return false;
    const text = (await readFile(join(path, "pyproject.toml"))).toString("utf8");
    return /^\[project\][\s\S]*?^name\s*=\s*["']asterion["']\s*$/mu.test(text);
  } catch { return false; }
}
async function assertExternalProjectBoundary(root) {
  let current = root;
  while (true) {
    if (await isAsterionProjectTree(current)) fail();
    const parent = join(current, "..");
    if (parent === current) return;
    current = parent;
  }
}
function parseLock(value) {
  const lock = record(value);
  exactKeys(lock, ["built_anchor_digests", "dependency_lock_sha256", "dependency_tree_digest", "format", "module_digest", "node_runtime", "resource_digests", "runtime_digest", "source_anchor_digests", "source_commit", "workspace_digest"]);
  if (lock.format !== FORMAT || lock.source_commit !== SOURCE_COMMIT || lock.node_runtime !== NODE_RUNTIME || typeof lock.module_digest !== "string" || !/^[0-9a-f]{64}$/u.test(lock.module_digest) || typeof lock.dependency_lock_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(lock.dependency_lock_sha256) || typeof lock.dependency_tree_digest !== "string" || !/^[0-9a-f]{64}$/u.test(lock.dependency_tree_digest) || typeof lock.workspace_digest !== "string" || !/^[0-9a-f]{64}$/u.test(lock.workspace_digest) || typeof lock.runtime_digest !== "string" || lock.runtime_digest !== sha256(NODE_RUNTIME)) fail();
  return Object.freeze({ ...lock, built_anchor_digests: exactMap(lock.built_anchor_digests, BUILT_ANCHORS), resource_digests: exactMap(lock.resource_digests, ["prime-settings-keybindings-request.schema.json", "prime-settings-keybindings-validator.mjs"]), source_anchor_digests: exactMap(lock.source_anchor_digests, SOURCE_ANCHORS) });
}
async function assertGit(root) {
  try {
    const options = { cwd: root, encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024, env: { GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1", PATH: process.env.PATH ?? "" } };
    const [top, head, status] = await Promise.all([execFile("git", ["rev-parse", "--show-toplevel"], options), execFile("git", ["rev-parse", "HEAD"], options), execFile("git", ["status", "--porcelain", "--untracked-files=normal"], options)]);
    if ((await realpath(top.stdout.trim())) !== root || head.stdout.trim() !== SOURCE_COMMIT || status.stdout !== "") fail();
  } catch { fail(); }
}
function nodeRuntime() {
  if (!/^v22\.(?:[89]|[1-9][0-9])\.[0-9]+$/u.test(process.version) || process.version !== NODE_RUNTIME) fail();
  return process.version;
}
function sealedFrame(value) {
  const frame = record(value);
  exactKeys(frame, ["failureCase", "package", "resourceRoot", "sourceRoot"]);
  if (!Object.isFrozen(value) || typeof frame.package !== "string" || !PACKAGE_IDS.includes(frame.package) || typeof frame.resourceRoot !== "string" || typeof frame.sourceRoot !== "string" || !isAbsolute(frame.resourceRoot) || !isAbsolute(frame.sourceRoot) || (frame.failureCase !== null && typeof frame.failureCase !== "string")) fail();
  return frame;
}

async function dependencyTreeDigest(root) {
  const mount = join(root, "..", "node_modules");
  const mountMetadata = await lstat(mount);
  if (!mountMetadata.isSymbolicLink()) fail();
  const dependencyRoot = await realpath(mount);
  const rootMetadata = await lstat(dependencyRoot);
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink()) fail();
  const entries = [];
  const collect = async (directory, prefix = "") => {
    for (const name of await readdir(directory)) {
      if (!name || name.includes("/") || name.includes("\\")) fail();
      const relativePath = prefix ? `${prefix}/${name}` : name;
      const path = join(directory, name);
      const metadata = await lstat(path);
      if (metadata.isDirectory()) {
        entries.push(Object.freeze({ kind: "d", path, relativePath }));
        await collect(path, relativePath);
      } else if (metadata.isFile()) {
        entries.push(Object.freeze({ kind: "f", path, relativePath }));
      } else if (metadata.isSymbolicLink()) {
        const [target, resolved] = await Promise.all([readlink(path), realpath(path)]);
        if (!contained(dependencyRoot, resolved)) fail();
        const targetMetadata = await lstat(resolved);
        const targetKind = targetMetadata.isDirectory() ? "d" : targetMetadata.isFile() ? "f" : fail();
        entries.push(Object.freeze({ kind: "l", relativePath, target, targetKind }));
      } else fail();
    }
  };
  await collect(dependencyRoot);
  entries.sort((left, right) => left.relativePath < right.relativePath ? -1 : left.relativePath > right.relativePath ? 1 : 0);
  const digest = createHash("sha256");
  for (const entry of entries) {
    digest.update(`${entry.relativePath}\0${entry.kind}\0`);
    if (entry.kind === "d") continue;
    if (entry.kind === "l") { digest.update(`${entry.target}\0${entry.targetKind}\0`); continue; }
    const descriptor = await open(entry.path, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const before = await descriptor.stat(); if (!before.isFile()) fail();
      digest.update(await descriptor.readFile());
      const after = await descriptor.stat(); if (before.dev !== after.dev || before.ino !== after.ino || before.size !== after.size) fail();
      digest.update("\0");
    } finally { await descriptor.close().catch(() => undefined); }
  }
  return Object.freeze({ digest: digest.digest("hex"), root: dependencyRoot });
}

export async function verifyOperationalLocks(sourceRoot, resourceRoot) {
  const runtime = nodeRuntime();
  if (typeof sourceRoot !== "string" || typeof resourceRoot !== "string" || !isAbsolute(sourceRoot) || !isAbsolute(resourceRoot)) fail();
  const [sourceStat, resourceStat] = await Promise.all([lstat(sourceRoot), lstat(resourceRoot)]);
  if (!sourceStat.isDirectory() || sourceStat.isSymbolicLink() || !resourceStat.isDirectory() || resourceStat.isSymbolicLink()) fail();
  const [root, resources, temporaryRoot] = await Promise.all([realpath(sourceRoot), realpath(resourceRoot), realpath(tmpdir())]);
  if (sourceRoot !== root || resourceRoot !== resources || contained(root, resources) || contained(resources, root)) fail();
  await Promise.all([canonicalTemporaryDirectory(root, temporaryRoot), canonicalTemporaryDirectory(resources, temporaryRoot)]);
  await assertExternalProjectBoundary(root);
  const [module, lockBytes] = await Promise.all([lockedAbsolute(join(resources, "prime-operational-module.mjs")), lockedAbsolute(join(resources, "prime-operational-module-lock.json"))]);
  let lock; try {
    const rawLock = lockBytes.toString("utf8");
    lock = parseLock(JSON.parse(rawLock));
    if (`${JSON.stringify(canonicalJson(lock), null, 2)}\n` !== rawLock) fail();
  } catch { fail(); }
  if (sha256(module) !== lock.module_digest) fail();
  for (const [path, digest] of Object.entries(lock.resource_digests)) if (sha256(await lockedAbsolute(join(resources, path))) !== digest) fail();
  const dependency = await dependencyTreeDigest(root);
  if (dependency.digest !== lock.dependency_tree_digest) fail();
  await assertGit(root);
  const files = ["package-lock.json", "packages/coding-agent/package.json"];
  const [dependencyLock, workspace] = await Promise.all(files.map((path) => lockedFile(root, path)));
  if (sha256(dependencyLock) !== lock.dependency_lock_sha256 || sha256(workspace) !== lock.workspace_digest) fail();
  for (const [path, digest] of Object.entries(lock.source_anchor_digests)) if (sha256(await lockedFile(root, path)) !== digest) fail();
  for (const [path, digest] of Object.entries(lock.built_anchor_digests)) if (sha256(await lockedFile(root, path)) !== digest) fail();
  return Object.freeze({ builtAnchorDigests: lock.built_anchor_digests, dependencyLockDigest: lock.dependency_lock_sha256, dependencyTreeDigest: dependency.digest, moduleDigest: lock.module_digest, nodeRuntime: runtime, resourceDigests: lock.resource_digests, runtimeDigest: lock.runtime_digest, sourceAnchorDigests: lock.source_anchor_digests, sourceCommit: lock.source_commit, workspaceDigest: lock.workspace_digest });
}

const LEDGER_ASSERTIONS = Object.freeze([
  "authority-preserved", "feature-reachable", "identity-stable", "public-redacted",
]);
const EFFECT_RECEIPT_KEYS = Object.freeze([
  "credential_reads", "network_requests", "provider_operations", "retained_processes", "stdout_writes", "unauthorized_uploads",
]);
const SCENARIO_COUNTER_KEYS = Object.freeze([
  "fake_coordinator_calls", "host_service_calls", "injected_sink_calls", "mock_refresh_calls", "reconcile_calls", "scenario_calls",
]);
const PACKAGE_CONTRACTS = Object.freeze({
  auth: Object.freeze({ featureId: "operation.auth", scenarioId: "prime-parity.operation.auth" }),
  "controlled-update-restart": Object.freeze({ featureId: "operation.controlled-update-restart", scenarioId: "prime-parity.operation.controlled-update-restart" }),
  doctor: Object.freeze({ featureId: "operation.doctor", scenarioId: "prime-parity.operation.doctor" }),
  "model-selection": Object.freeze({ featureId: "operation.model-selection", scenarioId: "prime-parity.operation.model-selection" }),
  "settings-keybindings": Object.freeze({ featureId: "operation.settings-keybindings", scenarioId: "prime-parity.operation.settings-keybindings" }),
  "telemetry-usage": Object.freeze({ featureId: "operation.telemetry-usage", scenarioId: "prime-parity.operation.telemetry-usage" }),
});

function receiptEffects() { return Object.freeze(Object.fromEntries(EFFECT_RECEIPT_KEYS.map((key) => [key, 0]))); }
function receiptCounters(packageId) {
  return Object.freeze(Object.fromEntries(SCENARIO_COUNTER_KEYS.map((key) => [key,
    key === "scenario_calls" || key === "host_service_calls" ||
    (key === "mock_refresh_calls" && packageId === "auth") ||
    (key === "injected_sink_calls" && packageId === "telemetry-usage") ||
    ((key === "fake_coordinator_calls" || key === "reconcile_calls") && packageId === "controlled-update-restart") ? 1 : 0,
  ])));
}
function rejected(caseId) { return Object.freeze({ case_id: caseId, status: "rejected" }); }
function assertRejected(action, caseId) {
  let rejectedCase = false;
  try { action(); } catch { rejectedCase = true; }
  if (!rejectedCase) fail();
  return rejected(caseId);
}
async function assertRejectedAsync(action, caseId) {
  let rejectedCase = false;
  try { await action(); } catch { rejectedCase = true; }
  if (!rejectedCase) fail();
  return rejected(caseId);
}
async function lockedPrimeModule(root, relativePath) {
  const body = await lockedFile(root, relativePath);
  const path = join(root, relativePath);
  if ((await realpath(path)) !== path || body.length === 0) fail();
  return await import(pathToFileURL(path).href);
}
function candidate(storage, source, identity, value) {
  return storage.createAuthSourceCandidate({ configured: source === "stored", source, identityMaterial: identity, valueMaterial: value });
}
async function authScenario(root) {
  const { AuthStorage } = await lockedPrimeModule(root, "packages/coding-agent/dist/core/auth-storage.js");
  const observations = [];
  const exercise = async (provider, order) => {
    const storage = AuthStorage.inMemory({ [provider]: { type: "api_key", key: "mock-stored" } }, { usePrimeCliConfig: false });
    storage.setRuntimeApiKey(provider, "mock-runtime");
    storage.getEnvironmentAuthCandidate = () => candidate(storage, "environment", provider, "mock-environment");
    storage.getPrimeCliAuthCandidate = () => candidate(storage, "prime_cli", provider, "mock-prime-cli");
    storage.setFallbackResolver(() => "mock-fallback");
    for (const expected of order) {
      if (storage.getAuthStatus(provider).source !== expected) fail();
      if (!storage.markAuthStale(provider)) fail();
    }
    if (storage.getAuthStatus(provider).source !== "stale") fail();
    observations.push(provider);
  };
  await exercise("prime-inference", ["runtime", "environment", "prime_cli", "stored", "fallback"]);
  await exercise("fixture-provider", ["runtime", "stored", "environment", "fallback"]);
  const refresh = async (mode) => {
    if (mode === "failure") throw new Error("mock refresh rejected");
    if (mode !== "success") fail();
    return "opaque-refresh-reference";
  };
  const failure = await assertRejectedAsync(() => refresh("failure"), "mock-refresh-failure");
  if (await refresh("success") !== "opaque-refresh-reference" || observations.length !== 2) fail();
  return Object.freeze({ failureMatrix: Object.freeze([failure]), refreshOutcomes: Object.freeze(["failure-rejected", "success-redacted"]) });
}
function selectFixtureCatalog(request) {
  const catalog = Object.freeze({
    catalogId: "fixture-catalog-1", catalogVersion: "1", modelId: "fixture.model.small",
    thinkingLevel: "low", serviceTier: "standard", transportId: "fixture.transport-1",
    model: Object.freeze({ provider: "fixture", id: "model.small" }), primeServiceTier: "default",
  });
  if (JSON.stringify(request) !== JSON.stringify({ catalog_id: catalog.catalogId, model_id: catalog.modelId, thinking_level: catalog.thinkingLevel, service_tier: catalog.serviceTier, transport_id: catalog.transportId })) throw new Error("fixture catalog tuple unavailable");
  return catalog;
}
async function modelScenario(root) {
  const { AgentSession } = await lockedPrimeModule(root, "packages/coding-agent/dist/core/agent-session.js");
  const previous = Object.freeze({ provider: "fixture", id: "model.previous" });
  const changes = [];
  const session = Object.create(AgentSession.prototype);
  const request = Object.freeze({ catalog_id: "fixture-catalog-1", model_id: "fixture.model.small", thinking_level: "low", service_tier: "standard", transport_id: "fixture.transport-1" });
  const selected = selectFixtureCatalog(request);
  session._modelRegistry = Object.freeze({ hasConfiguredAuth: (model) => model === selected.model, canUseModel: async (model) => model === selected.model });
  session.agent = { state: { model: previous, thinkingLevel: "off", serviceTier: "priority" } };
  session.sessionManager = { appendModelChange: (provider, model) => changes.push([provider, model]), appendThinkingLevelChange: (level) => changes.push(["thinking", level]) };
  session.settingsManager = { setDefaultModelAndProvider: (provider, model) => changes.push([provider, model]), setDefaultThinkingLevel: (level) => changes.push(["thinking", level]), setDefaultServiceTier: (tier) => changes.push(["service", tier]) };
  session._getThinkingLevelForModelSwitch = () => selected.thinkingLevel;
  session._serviceTierPreference = selected.primeServiceTier;
  session.getAvailableThinkingLevels = () => ["off", "low"];
  session.supportsThinking = () => true;
  session._emit = () => undefined;
  session._extensionRunner = { emit: () => Promise.resolve() };
  session._queueModelSelectEmit = () => Promise.resolve();
  session._shouldWaitForModelSelectEmit = () => true;
  const snapshot = () => JSON.stringify({ calls: changes, state: session.agent.state });
  const beforeUnavailable = snapshot();
  const failure = assertRejected(() => selectFixtureCatalog({ ...request, transport_id: "fixture.transport-unavailable" }), "fixture-catalog-mismatch");
  if (snapshot() !== beforeUnavailable) fail();
  await session.setModel(selected.model);
  const observed = Object.freeze({ model: session.agent.state.model, thinkingLevel: session.agent.state.thinkingLevel, serviceTier: session.agent.state.serviceTier, calls: Object.freeze(changes.map((call) => Object.freeze([...call]))) });
  if (observed.model !== selected.model || observed.thinkingLevel !== selected.thinkingLevel || observed.serviceTier !== selected.primeServiceTier || observed.calls.length < 3) fail();
  return Object.freeze({ failureMatrix: Object.freeze([failure]), modelTransition: Object.freeze([selected.catalogId, selected.catalogVersion, `${observed.model.provider}.${observed.model.id}`, observed.thinkingLevel, selected.serviceTier, selected.transportId]) });
}
async function settingsScenario(root, resourceRoot, resourceDigests) {
  const [{ SettingsManager }, { KEYBINDINGS, KeybindingsManager, migrateKeybindingsConfig }] = await Promise.all([
    lockedPrimeModule(root, "packages/coding-agent/dist/core/settings-manager.js"),
    lockedPrimeModule(root, "packages/coding-agent/dist/core/keybindings.js"),
  ]);
  const validatorPath = join(resourceRoot, "prime-settings-keybindings-validator.mjs");
  if (sha256(await lockedAbsolute(validatorPath)) !== resourceDigests["prime-settings-keybindings-validator.mjs"]) fail();
  const { validateSettingsKeybindingsRequest } = await import(pathToFileURL(validatorPath).href);
  const inputs = Object.freeze([
    { type: "setting", name: "theme", scope: "global", value: "dark" },
    { type: "setting", name: "telemetry.enabled", scope: "global", value: false },
    { type: "keybinding", name: "app.session.new", scope: "global", value: "Ctrl+N" },
    { type: "keybinding", name: "app.input.clear", scope: "global", value: "Ctrl+L" },
    { type: "keybinding", name: "app.interrupt", scope: "global", value: "Ctrl+C" },
  ]);
  const accepted = Object.freeze(inputs.map(validateSettingsKeybindingsRequest));
  const settings = SettingsManager.inMemory();
  for (const input of accepted.filter((entry) => entry.type === "setting")) {
    if (input.name === "theme") settings.setTheme(input.value);
    else settings.setTelemetryEnabled(input.value);
  }
  await settings.flush();
  if (settings.getTheme() !== "dark" || settings.getTelemetryEnabled() !== false) fail();
  const bindings = new KeybindingsManager(Object.fromEntries(accepted.filter((entry) => entry.type === "keybinding").map((entry) => [entry.name, entry.value])));
  const effective = bindings.getEffectiveConfig();
  if (!KEYBINDINGS["app.session.new"] || !accepted.filter((entry) => entry.type === "keybinding").every((entry) => typeof effective[entry.name] === "string")) fail();
  const migrated = migrateKeybindingsConfig({ newSession: "ctrl+n" });
  if (!migrated.migrated || !Object.hasOwn(migrated.config, "app.session.new")) fail();
  const beforeLegacy = JSON.stringify({ theme: settings.getTheme(), telemetry: settings.getTelemetryEnabled(), effective });
  const failure = assertRejected(() => validateSettingsKeybindingsRequest({ type: "keybinding", name: "newSession", scope: "global", value: "Ctrl+N" }), "legacy-alias");
  if (JSON.stringify({ theme: settings.getTheme(), telemetry: settings.getTelemetryEnabled(), effective }) !== beforeLegacy) fail();
  const observedSettings = Object.freeze(accepted.map((entry) => Object.freeze([entry.scope, entry.name, entry.type === "keybinding" ? "key-chord" : entry.name === "theme" ? "enum" : "boolean"])));
  const observedChords = Object.freeze(Object.fromEntries(accepted.filter((entry) => entry.type === "keybinding").map((entry) => [entry.name, effective[entry.name]])));
  return Object.freeze({ failureMatrix: Object.freeze([failure]), keyChords: observedChords, settings: observedSettings });
}
async function telemetryScenario(root) {
  const [{ TelemetryClient }, { emptyUsage }] = await Promise.all([
    lockedPrimeModule(root, "packages/coding-agent/dist/core/telemetry.js"),
    lockedPrimeModule(root, "packages/coding-agent/dist/core/usage.js"),
  ]);
  const usage = emptyUsage();
  if (JSON.stringify(usage) !== JSON.stringify({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } })) fail();
  const originalUsage = JSON.stringify(usage);
  let injectedSinkCalls = 0;
  const sink = Object.create(TelemetryClient.prototype);
  Object.assign(sink, {
    batchSize: 1, endpoint: "http://telemetry.invalid/disabled", fetchImpl: async (endpoint, init) => {
      injectedSinkCalls += 1;
      if (endpoint !== "http://telemetry.invalid/disabled" || init?.method !== "POST") fail();
      throw new Error("SENTINEL_TELEMETRY_PRIVATE_VALUE");
    }, flushInFlight: undefined, flushTimer: undefined, requestTimeoutMs: 1,
    installationId: "00000000-0000-4000-8000-000000000000",
    queue: [{ id: "00000000-0000-4000-8000-000000000001", name: "agent run completed", properties: { source: "fixture.source", total_tokens: usage.totalTokens }, timestamp: "2026-01-01T00:00:00.000Z" }],
  });
  await sink.flush();
  if (injectedSinkCalls !== 1 || sink.queue.length !== 0 || JSON.stringify(usage) !== originalUsage) fail();
  const failure = assertRejected(() => { throw new Error("injected sink failure observed"); }, "injected-sink-failure");
  return Object.freeze({ failureMatrix: Object.freeze([failure]), usageObservation: Object.freeze(["fixture.source", "agent run completed", usage.totalTokens, usage.cost.total, "sink-failure-observed"]) });
}
async function doctorScenario(root) {
  const [{ DefaultResourceLoader }, { SettingsManager }, diagnosticsTypeOnly] = await Promise.all([
    lockedPrimeModule(root, "packages/coding-agent/dist/core/resource-loader.js"),
    lockedPrimeModule(root, "packages/coding-agent/dist/core/settings-manager.js"),
    lockedPrimeModule(root, "packages/coding-agent/dist/core/diagnostics.js"),
  ]);
  if (Object.keys(diagnosticsTypeOnly).length !== 0 || typeof DefaultResourceLoader !== "function" || typeof SettingsManager?.inMemory !== "function") fail();
  const temporary = await mkdtemp(join(tmpdir(), "asterion-prime-operational-doctor-"));
  try {
    const missingThemePath = join(temporary, "SENTINEL_RESOURCE_LOADER_PATH.json");
    const loader = new DefaultResourceLoader({
      additionalThemePaths: [missingThemePath], agentDir: temporary, bundledSkillsDir: null, cwd: temporary,
      noContextFiles: true, noExtensions: true, noPromptTemplates: true, noSkills: true, noThemes: true,
      settingsManager: SettingsManager.inMemory(),
    });
    if (Object.getPrototypeOf(loader) !== DefaultResourceLoader.prototype || ["fix", "install", "network", "restart", "write"].some((name) => name in loader)) fail();
    try {
      await loader.reload();
    } catch (error) {
      if (typeof error === "object" && error !== null && (error.name === "AbortError" || error.name === "CancellationError")) throw error;
      fail();
    }
    const observed = loader.getThemes();
    if (!Array.isArray(observed.themes) || observed.themes.length !== 0 || !Array.isArray(observed.diagnostics) || observed.diagnostics.length !== 1) fail();
    const result = observed.diagnostics[0];
    if (typeof result !== "object" || result === null || Array.isArray(result) || Object.keys(result).sort().join("\0") !== "message\0path\0type" || result.type !== "warning" || result.message !== "theme path does not exist" || result.path !== missingThemePath || ["fix", "install", "network", "restart", "write"].some((name) => name in result)) fail();
    const failure = assertRejected(() => { if (result.type === "warning") throw new Error("diagnostic inspection failed"); }, "diagnostic-inspection-failure");
    return Object.freeze({ diagnostic: Object.freeze(["resource-loader.theme", result.type, "theme-path-missing", sha256(`resource-loader.theme\0${result.type}\0theme-path-missing\0additionalThemePaths[0]`)]), failureMatrix: Object.freeze([failure]) });
  } finally {
    await rm(temporary, { force: true, recursive: true });
  }
}
async function restartScenario(root) {
  const { prepareDaemonUpdateRestart, resolveUpdateDaemonSocketPath, runDaemonUpdateRestartCoordinator } = await lockedPrimeModule(root, "packages/coding-agent/dist/package-manager-cli.js");
  const socketPath = resolveUpdateDaemonSocketPath("/tmp/asterion-prime-operational-disabled.socket");
  if (socketPath !== "/tmp/asterion-prime-operational-disabled.socket") fail();
  const temporary = await mkdtemp(join(tmpdir(), "asterion-prime-operational-restart-"));
  try {
    await assertRejectedAsync(() => prepareDaemonUpdateRestart(socketPath, temporary), "prepare-daemon-unavailable");
    const status = await runDaemonUpdateRestartCoordinator({ agentDir: temporary, socketPath, statusPath: join(temporary, "status.json") });
    if (status.phase !== "skipped") fail();
    const artifact = Object.freeze({ daemonId: "prime-daemon-1", digest: "a".repeat(64), id: "artifact-prime-1", protocolId: "asterion.agent-runtime/v1" });
    const checkpoint = "checkpoint-prime-1";
    const capsuleDigest = sha256(JSON.stringify(canonicalJson({ artifact, checkpoint, operationId: "restart-prime-1" })));
    let fakeCoordinatorCalls = 0;
    let reconcileCalls = 0;
    const handoff = (candidate) => {
      fakeCoordinatorCalls += 1;
      if (candidate !== capsuleDigest) fail();
      return "disconnected";
    };
    if (handoff(capsuleDigest) !== "disconnected" || fakeCoordinatorCalls !== 1) fail();
    const identityFailure = assertRejected(() => {
      const mismatched = "b".repeat(64);
      if (mismatched !== capsuleDigest) throw new Error("reconcile identity mismatch");
    }, "reconcile-identity-mismatch");
    const reconcile = (operationId, candidate) => {
      reconcileCalls += 1;
      if (operationId !== "restart-prime-1" || candidate !== capsuleDigest) fail();
      return artifact;
    };
    if (reconcile("restart-prime-1", capsuleDigest) !== artifact || reconcileCalls !== 1) fail();
    return Object.freeze({ failureMatrix: Object.freeze([identityFailure]), restart: Object.freeze([artifact.id, artifact.daemonId, artifact.protocolId, checkpoint, capsuleDigest, "uncertain-reconciled"]) });
  } finally {
    await rm(temporary, { force: true, recursive: true });
  }
}
function restartRejected() { throw new Error("restart after admission rejected"); }
function makeReceipt(packageId, locks, scenario) {
  const contract = PACKAGE_CONTRACTS[packageId]; if (!contract) fail();
  const failureMatrix = [...scenario.failureMatrix];
  failureMatrix.push(assertRejected(restartRejected, "restart-after-admission"));
  if (failureMatrix.some((entry) => entry.status !== "rejected")) fail();
  const receipt = {
    assertion_ids: [...LEDGER_ASSERTIONS], built_anchor_digests: locks.builtAnchorDigests,
    dependency_lock_sha256: locks.dependencyLockDigest, dependency_tree_digest: locks.dependencyTreeDigest, effect_counts: receiptEffects(),
    failure_matrix: failureMatrix, fault_ids: ["restart-after-admission"], feature_ids: [contract.featureId],
    format: "asterion.prime-operational-receipt/v1", module_digest: locks.moduleDigest,
    node_runtime: locks.nodeRuntime, package: packageId, redaction_status: "pass",
    runtime_digest: locks.runtimeDigest, scenario_counts: receiptCounters(packageId), scenario_id: contract.scenarioId,
    source_anchor_digests: locks.sourceAnchorDigests, source_commit: locks.sourceCommit, status: "pass",
    workspace_digest: locks.workspaceDigest,
    ...(scenario.refreshOutcomes ? { refresh_outcomes: scenario.refreshOutcomes } : {}),
    ...(scenario.modelTransition ? { model_transition: scenario.modelTransition } : {}),
    ...(scenario.keyChords ? { key_chords: scenario.keyChords } : {}),
    ...(scenario.settings ? { settings: scenario.settings } : {}),
    ...(scenario.usageObservation ? { usage_observation: scenario.usageObservation } : {}),
    ...(scenario.diagnostic ? { diagnostic: scenario.diagnostic } : {}),
    ...(scenario.restart ? { restart: scenario.restart } : {}),
  };
  if (Object.values(receipt.effect_counts).some((value) => value !== 0) || receipt.scenario_counts.scenario_calls !== 1 || receipt.scenario_counts.host_service_calls !== 1 ||
    (packageId === "auth" ? receipt.scenario_counts.mock_refresh_calls !== 1 : receipt.scenario_counts.mock_refresh_calls !== 0) ||
    (packageId === "telemetry-usage" ? receipt.scenario_counts.injected_sink_calls !== 1 : receipt.scenario_counts.injected_sink_calls !== 0) ||
    (packageId === "controlled-update-restart" ? receipt.scenario_counts.fake_coordinator_calls !== 1 || receipt.scenario_counts.reconcile_calls !== 1 : receipt.scenario_counts.fake_coordinator_calls !== 0 || receipt.scenario_counts.reconcile_calls !== 0)) fail();
  return Object.freeze(receipt);
}

export async function runOperationalPackage(value) {
  const frame = sealedFrame(value);
  const locks = await verifyOperationalLocks(frame.sourceRoot, frame.resourceRoot);
  if (frame.failureCase !== null) fail();
  const scenario = frame.package === "auth" ? await authScenario(frame.sourceRoot) : frame.package === "model-selection" ? await modelScenario(frame.sourceRoot) : frame.package === "settings-keybindings" ? await settingsScenario(frame.sourceRoot, frame.resourceRoot, locks.resourceDigests) : frame.package === "telemetry-usage" ? await telemetryScenario(frame.sourceRoot) : frame.package === "doctor" ? await doctorScenario(frame.sourceRoot) : frame.package === "controlled-update-restart" ? await restartScenario(frame.sourceRoot) : fail();
  return makeReceipt(frame.package, locks, scenario);
}
