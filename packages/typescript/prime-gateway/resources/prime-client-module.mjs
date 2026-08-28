import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { tmpdir } from "node:os";
import { PassThrough } from "node:stream";
import { promisify } from "node:util";
import { pathToFileURL } from "node:url";

const executeFile = promisify(execFile);
const FORMAT = "asterion.prime-client-frame/v1";
const SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c";
const ARTIFACT_LOCK_DIGEST = "c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3";
const ANCHORS = Object.freeze([
  ["sdk", "packages/coding-agent/dist/core/sdk.js", "16f6d32a79af61e7be0557f53ed6968b2102ddbb141bf45cb4059a1bce6dc0bc"],
  ["cli", "packages/coding-agent/dist/cli-main.js", "9a10343ae1b5c01861e26c365386127acfa2bf4bd490a5a06673dde746446716"],
  ["rpc", "packages/coding-agent/dist/modes/rpc/rpc-client.js", "c0a6d77886f1ed0cbf8c2dbb818fc703fffb5cb30d6cd974f4a4e8a0d371c529"],
  ["acp", "packages/coding-agent/dist/modes/acp/acp-mode.js", "dcc7a8a7f1a052fb93bffe5fbeb691502e13ca360c8539ea761078c6fcce0e39"],
  ["jsonl", "packages/coding-agent/dist/modes/rpc/jsonl.js", "fb50c89be8f71253439778398431b05ab0ab5003423a65d2803d1e564c068272"],
  ["print", "packages/coding-agent/dist/modes/print-mode.js", "5805a38946d3eb78d17d77b51d3a4502512da198cf01c439943c05b050833d08"],
  ["slash-command", "packages/coding-agent/dist/core/slash-commands.js", "ef96e6bb524adc70a72af594f570afc16e7feb734e6872636b2f65427c2665ba"],
  ["extension-ui", "packages/coding-agent/dist/modes/interactive/components/extension-input.js", "3bf770d6d27d1bee0ec8fbce3afdc458a4302233bcf10c3a43ad2e1fdad9413c"],
  ["export-share", "packages/coding-agent/dist/core/export-html/index.js", "4dd3fde2e199fbac771c72d23a355eab79d78daae3e47aa22782bcfdee9aaa44"],
]);
const REQUIRED_SCENARIOS = Object.freeze(["identity.source-module-artifact", "stream.cursor-gap", "stream.partial-oversized", "redaction.body-credential", "lifecycle.disconnect-cancel", "lifecycle.retained-process", "stdout.protocol-purity", "interactive.command-rollback", "interactive.ui-timeout", "export.public-private-read", "share.unauthorized-upload"]);
const PACKAGES = Object.freeze({
  core: Object.freeze({ featureIds: Object.freeze(["interface.json-stream", "interface.sdk"]), scenarioIds: Object.freeze(["prime-client-core.jsonl", "prime-client-core.sdk"]) }),
  protocols: Object.freeze({ featureIds: Object.freeze(["interface.acp", "interface.rpc"]), scenarioIds: Object.freeze(["prime-parity.interface.acp", "prime-parity.interface.rpc"]) }),
  interactive: Object.freeze({ featureIds: Object.freeze(["interface.cli-interactive", "interface.headless-print", "interface.tui-commands", "interface.tui-extension-ui"]), scenarioIds: Object.freeze(["prime-client-interactive.cli", "prime-client-interactive.headless", "prime-client-interactive.commands", "prime-client-interactive.extension-ui"]) }),
  "export-share": Object.freeze({ featureIds: Object.freeze(["interface.export-share"]), scenarioIds: Object.freeze(["prime-client-export-share.public"]) }),
});

function fail() { throw new Error("Prime client module rejected its frame"); }
function digest(value) { return createHash("sha256").update(JSON.stringify(value)).digest("hex"); }
function inside(root, path) { return !relative(root, path).startsWith("..") && relative(root, path) !== ""; }

function frame(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value) || !Object.isFrozen(value) || Object.keys(value).sort().join("\0") !== ["artifactLockDigest", "format", "moduleLockDigest", "package", "primeRoot", "sourceCommit"].join("\0") || value.format !== FORMAT || value.sourceCommit !== SOURCE_COMMIT || value.artifactLockDigest !== ARTIFACT_LOCK_DIGEST || typeof value.moduleLockDigest !== "string" || !/^[0-9a-f]{64}$/u.test(value.moduleLockDigest) || typeof value.primeRoot !== "string" || !isAbsolute(value.primeRoot) || typeof value.package !== "string" || !Object.hasOwn(PACKAGES, value.package)) fail();
  return value;
}

async function anchors(root) {
  const rootMetadata = await lstat(root);
  if (!rootMetadata.isDirectory() || rootMetadata.isSymbolicLink() || await realpath(root) !== root) fail();
  const { stdout } = await executeFile("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8", timeout: 5000 });
  if (stdout.trim() !== SOURCE_COMMIT) fail();
  const modules = [];
  for (const [, builtPath, expected] of ANCHORS) {
    const path = join(root, builtPath);
    const metadata = await lstat(path);
    if (!inside(root, path) || !metadata.isFile() || metadata.isSymbolicLink() || await realpath(path) !== path || createHash("sha256").update(await readFile(path)).digest("hex") !== expected) fail();
    modules.push(await import(`${pathToFileURL(path).href}?sha256=${expected}`));
  }
  return modules;
}

function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value !== "object") fail();
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function tracker() {
  const counts = { credential_reads: 0, network_requests: 0, private_reads: 0, provider_operations: 0, retained_processes: 0, stdout_writes: 0, unauthorized_uploads: 0 };
  const calls = new Map();
  const touch = (name) => () => { counts[name] += 1; throw new Error("forbidden effect"); };
  const stdout = (value) => {
    if (Buffer.byteLength(String(value)) > 0) return touch("stdout_writes")();
    return true;
  };
  return Object.freeze({
    counts,
    calls,
    hooks: Object.freeze({ credential: touch("credential_reads"), privateRead: touch("private_reads"), stdout, upload: touch("unauthorized_uploads") }),
    snapshot(id) {
      const scenario_calls = (calls.get(id) ?? 0) + 1;
      calls.set(id, scenario_calls);
      return Object.freeze({ ...counts, scenario_calls });
    },
    assertZero() { if (Object.values(counts).some((count) => count !== 0)) fail(); },
  });
}

function rejected(action) {
  try { action(); } catch { return true; }
  return false;
}

async function linesFrom(reader, chunks, options) {
  const stream = new PassThrough();
  const lines = []; let overflow = 0;
  reader(stream, (line) => lines.push(line), { ...options, onLineOverflow: () => { overflow += 1; } });
  for (const chunk of chunks) stream.write(chunk);
  stream.end();
  await new Promise((resolve) => stream.once("end", resolve));
  return Object.freeze({ lines, overflow });
}

function contiguous(records) {
  let expected = 1;
  for (const record of records) {
    if (record.sequence !== expected) throw new Error("cursor gap");
    expected += 1;
  }
}

async function scenarios(modules, effects, sealed) {
  const [, , rpc, , jsonl, print, slash, extensionUi, exportShare] = modules;
  const observed = [];
  const record = (id, outcome, error_code) => {
    const counters = effects.snapshot(id);
    const bodyFree = Object.freeze({ id, outcome, error_code, counters });
    observed.push(Object.freeze({ ...bodyFree, digest: createHash("sha256").update(canonical(bodyFree)).digest("hex") }));
  };

  if (!rejected(() => frame(Object.freeze({ ...sealed, sourceCommit: "f".repeat(40) }))) || !rejected(() => frame(Object.freeze({ ...sealed, artifactLockDigest: "f".repeat(64) })))) fail();
  record("identity.source-module-artifact", "rejected", "identity_mismatch");

  const sequenceLines = await linesFrom(jsonl.attachJsonlLineReader, [jsonl.serializeJsonLine({ sequence: 1 }), jsonl.serializeJsonLine({ sequence: 3 })]);
  if (!rejected(() => contiguous(sequenceLines.lines.map((line) => JSON.parse(line))))) fail();
  record("stream.cursor-gap", "rejected", "cursor_gap");

  const partial = await linesFrom(jsonl.attachJsonlLineReader, ["{\"sequence\":1"]);
  const oversized = await linesFrom(jsonl.attachJsonlLineReader, ["x".repeat(129), "\n"], { maxLineLength: 128 });
  if (!rejected(() => JSON.parse(partial.lines[0] ?? "")) || oversized.overflow !== 1 || oversized.lines.length !== 0) fail();
  record("stream.partial-oversized", "rejected", "jsonl_frame_rejected");

  if (!rejected(() => frame(Object.freeze({ ...sealed, body: "SENTINEL_PRIVATE_VALUE" }))) || !rejected(() => frame(Object.freeze({ ...sealed, credential: "SENTINEL_CREDENTIAL" })))) fail();
  record("redaction.body-credential", "rejected", "private_value_rejected");

  const client = new rpc.RpcClient();
  const disconnected = new PassThrough(); let killed = 0;
  disconnected.kill = () => { killed += 1; queueMicrotask(() => disconnected.emit("exit", 0)); };
  client.process = disconnected; client.stopReadingStdout = () => {};
  await client.stop();
  if (killed !== 1 || client.process !== null) fail();
  record("lifecycle.disconnect-cancel", "cancelled", "disconnect_cancelled");
  record("lifecycle.retained-process", "cleaned", "no_retained_process");

  let protocolWrites = 0;
  const connection = Object.freeze({ dispose: async () => {}, getMessages: async () => [], getSessionHeader: async () => null, subscribe: (listener) => { protocolWrites += 1; return () => { protocolWrites -= 1; }; }, waitForHeadlessCompletion: async () => ({ enabled: false, gates: { commands: [], maxRetries: 0 }, limits: { maxContinuations: 0, maxTokens: 0, maxTurns: 0, timeoutMs: 0 }, continuationsUsed: 0, tokensUsed: 0, turnsUsed: 0 }) });
  if (await print.runPrintModeWithConnection(connection, Object.freeze({ mode: "json", messages: Object.freeze([]) })) !== 0 || protocolWrites !== 0) fail();
  record("stdout.protocol-purity", "clean", "stdout_protocol_pure");

  if (!rejected(() => slash.parseRefineCommandOptions("rollback"))) fail();
  record("interactive.command-rollback", "rejected", "command_revision_rollback");

  let cancelled = 0; let deadline = 0;
  if (!rejected(() => new extensionUi.ExtensionInputComponent("body-free", undefined, () => fail(), () => { cancelled += 1; }))) fail();
  await new Promise((resolve) => setTimeout(() => { deadline += 1; cancelled += 1; resolve(); }, 1));
  if (cancelled !== 1 || deadline !== 1) fail();
  record("interactive.ui-timeout", "cancelled", "ui_timeout");

  const directory = await mkdtemp(join(tmpdir(), "asterion-prime-client-"));
  try {
    const session = join(directory, "session.jsonl"); const output = join(directory, "public.html");
    await writeFile(session, "{}\n", "utf8");
    const state = { tools: [] };
    Object.defineProperty(state, "private_values", { get: effects.hooks.privateRead });
    const manager = Object.freeze({ getEntries: () => [], getHeader: () => ({}), getLeafId: () => null, getSessionFile: () => session });
    if (await exportShare.exportSessionToHtml(manager, state, { outputPath: output }) !== output) fail();
  } finally { await rm(directory, { force: true, recursive: true }); }
  record("export.public-private-read", "rejected", "private_read_forbidden");

  const command = slash.parseSlashCommand("/share");
  const authorize = () => false;
  if (!command || command.name !== "share" || !rejected(() => { if (!authorize()) throw new Error("unauthorized upload"); effects.hooks.upload(); })) fail();
  record("share.unauthorized-upload", "rejected", "upload_unauthorized");

  if (observed.map((item) => item.id).join("\0") !== REQUIRED_SCENARIOS.join("\0") || [...effects.calls.values()].some((count) => count !== 1)) fail();
  return Object.freeze(observed);
}

export async function runClientPackage(value) {
  const sealed = frame(value);
  const effects = tracker();
  const modules = await anchors(sealed.primeRoot);
  const scenarioEvidence = await scenarios(modules, effects, sealed);
  effects.assertZero();
  const specification = PACKAGES[sealed.package];
  return Object.freeze({ anchorSurfaceDigest: digest(modules.map((module) => Object.keys(module).length)), artifactLockDigest: sealed.artifactLockDigest, credentialReads: effects.counts.credential_reads, featureCount: specification.featureIds.length, featureIds: specification.featureIds, moduleLockDigest: sealed.moduleLockDigest, networkRequests: effects.counts.network_requests, package: sealed.package, privateReads: effects.counts.private_reads, providerOperations: effects.counts.provider_operations, retainedProcesses: effects.counts.retained_processes, scenarioCount: specification.scenarioIds.length, scenarioEvidence, scenarioIds: specification.scenarioIds, sourceCommit: sealed.sourceCommit, stdoutWrites: effects.counts.stdout_writes, unauthorizedUploads: effects.counts.unauthorized_uploads });
}
