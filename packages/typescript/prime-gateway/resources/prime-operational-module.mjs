import { execFile as execFileCallback } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, open, readFile, realpath } from "node:fs/promises";
import { constants } from "node:fs";
import { isAbsolute, join, normalize, relative, sep } from "node:path";
import { tmpdir } from "node:os";
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
  "packages/coding-agent/src/core/settings-manager.ts",
  "packages/coding-agent/src/core/telemetry.ts",
  "packages/coding-agent/src/core/usage.ts",
  "packages/coding-agent/src/package-manager-cli.ts",
]);
const BUILT_ANCHORS = Object.freeze(SOURCE_ANCHORS.map((path) => path.replace("/src/", "/dist/").replace(/\.ts$/u, ".js")));
const PACKAGE_IDS = Object.freeze(["auth", "doctor", "model-selection", "settings-keybindings", "telemetry", "update-restart"]);
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
  exactKeys(lock, ["built_anchor_digests", "dependency_lock_sha256", "format", "module_digest", "node_runtime", "runtime_digest", "source_anchor_digests", "source_commit", "workspace_digest"]);
  if (lock.format !== FORMAT || lock.source_commit !== SOURCE_COMMIT || lock.node_runtime !== NODE_RUNTIME || typeof lock.module_digest !== "string" || !/^[0-9a-f]{64}$/u.test(lock.module_digest) || typeof lock.dependency_lock_sha256 !== "string" || !/^[0-9a-f]{64}$/u.test(lock.dependency_lock_sha256) || typeof lock.workspace_digest !== "string" || !/^[0-9a-f]{64}$/u.test(lock.workspace_digest) || typeof lock.runtime_digest !== "string" || lock.runtime_digest !== sha256(NODE_RUNTIME)) fail();
  return Object.freeze({ ...lock, built_anchor_digests: exactMap(lock.built_anchor_digests, BUILT_ANCHORS), source_anchor_digests: exactMap(lock.source_anchor_digests, SOURCE_ANCHORS) });
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
  await assertGit(root);
  const files = ["package-lock.json", "packages/coding-agent/package.json"];
  const [dependencyLock, workspace] = await Promise.all(files.map((path) => lockedFile(root, path)));
  if (sha256(dependencyLock) !== lock.dependency_lock_sha256 || sha256(workspace) !== lock.workspace_digest) fail();
  for (const [path, digest] of Object.entries(lock.source_anchor_digests)) if (sha256(await lockedFile(root, path)) !== digest) fail();
  for (const [path, digest] of Object.entries(lock.built_anchor_digests)) if (sha256(await lockedFile(root, path)) !== digest) fail();
  return Object.freeze({ builtAnchorDigests: lock.built_anchor_digests, dependencyLockDigest: lock.dependency_lock_sha256, moduleDigest: lock.module_digest, nodeRuntime: runtime, runtimeDigest: lock.runtime_digest, sourceAnchorDigests: lock.source_anchor_digests, sourceCommit: lock.source_commit, workspaceDigest: lock.workspace_digest });
}

function runWithDeterministicEffects(packageId, locks, failureCase) {
  const effects = Object.fromEntries(EFFECT_KEYS.map((key) => [key, 0]));
  const counters = Object.freeze({ ...effects, scenario_calls: 1 });
  if (!Number.isSafeInteger(counters.scenario_calls) || Object.values(effects).some((value) => !Number.isSafeInteger(value) || value !== 0)) fail();
  return Object.freeze({ effect_counts: Object.freeze(effects), failure_case: failureCase, format: "asterion.prime-operational-infrastructure-receipt/v1", node_runtime: locks.nodeRuntime, package: packageId, scenario_counters: counters, source_commit: locks.sourceCommit, status: "infrastructure-ready" });
}

export async function runOperationalPackage(value) {
  const frame = sealedFrame(value);
  const locks = await verifyOperationalLocks(frame.sourceRoot, frame.resourceRoot);
  return runWithDeterministicEffects(frame.package, locks, frame.failureCase);
}
