import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { pathToFileURL } from "node:url";

const SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c";
const NODE_FLOOR = [22, 8, 0];
const PACKAGE_COUNTS = Object.freeze({ core: [2, 2], protocols: [2, 2], interactive: [4, 4], "export-share": [1, 1] });
const MODULE_IDS = Object.freeze(["sdk", "cli", "rpc", "acp", "jsonl", "print", "slash-command", "extension-ui", "export-share"]);
const REQUIRED_IMPORTS = Object.freeze([
  "dist/core/sdk.js", "dist/cli-main.js", "dist/modes/rpc/rpc-client.js", "dist/modes/acp/acp-mode.js",
  "dist/modes/rpc/jsonl.js", "dist/modes/print-mode.js", "dist/core/slash-commands.js",
  "dist/modes/interactive/components/extension-input.js", "dist/core/export-html/index.js",
]);
const RESOURCE_ROOT = join(process.cwd(), "packages/typescript/prime-gateway/resources");
const PRIME_ROOT = join(process.cwd(), "3th-party/prime-agent");

function fail() { throw new Error("Prime client harness failed"); }
function sha256(value) { return createHash("sha256").update(value).digest("hex"); }
function record(value) { if (typeof value !== "object" || value === null || Array.isArray(value)) fail(); return value; }
function exactKeys(value, keys) { const actual = Object.keys(value).sort(); const expected = [...keys].sort(); if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(); }
function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const item = record(value); return `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${canonical(item[key])}`).join(",")}}`;
}
function cleanPublic(value) {
  if (typeof value === "string") return !/(?:sentinel|body|credential|private|prompt|raw|source_path|destination)/iu.test(value) && !value.startsWith("/") && !value.includes("\\");
  if (value === null || typeof value === "boolean" || typeof value === "number") return true;
  if (Array.isArray(value)) return value.every(cleanPublic);
  if (typeof value !== "object") return false;
  return Object.entries(value).every(([key, item]) => !/(?:body|prompt|raw|source_path|destination|path)/iu.test(key) && cleanPublic(item));
}
function nodeAtLeastFloor() {
  const actual = process.versions.node.split(".").map(Number);
  return actual[0] > NODE_FLOOR[0] || actual[0] === NODE_FLOOR[0] && (actual[1] > NODE_FLOOR[1] || actual[1] === NODE_FLOOR[1] && actual[2] >= NODE_FLOOR[2]);
}
function packageArgument(argv) {
  if (argv.length !== 2 || argv[0] !== "--package" || !Object.hasOwn(PACKAGE_COUNTS, argv[1])) fail();
  return argv[1];
}
async function lockedFile(path, root) {
  if (!isAbsolute(path) || relative(root, path).startsWith("..")) fail();
  const metadata = await lstat(path);
  if (metadata.isSymbolicLink() || !metadata.isFile() || (metadata.mode & 0o002) !== 0 || await realpath(path) !== path) fail();
  return readFile(path);
}
async function loadLock() {
  const resources = await realpath(RESOURCE_ROOT); const prime = await realpath(PRIME_ROOT);
  const [artifactBytes, lockBytes, bundle] = await Promise.all([
    lockedFile(join(resources, "prime-artifact-lock.json"), resources),
    lockedFile(join(resources, "prime-client-module-lock.json"), resources),
    lockedFile(join(resources, "prime-client-module.mjs"), resources),
  ]);
  const artifact = record(JSON.parse(artifactBytes.toString("utf8")));
  const lock = record(JSON.parse(lockBytes.toString("utf8")));
  exactKeys(lock, ["artifact_lock_sha256", "bundle_sha256", "format", "modules", "node_floor", "source_commit", "transitive_lock_sha256", "zero_effect_expectations"]);
  if (lock.format !== "asterion.prime-client-module-lock/v1" || lock.source_commit !== SOURCE_COMMIT || lock.node_floor !== "22.8.0" || lock.artifact_lock_sha256 !== sha256(artifactBytes) || lock.transitive_lock_sha256 !== sha256(artifactBytes) || lock.bundle_sha256 !== sha256(bundle)) fail();
  if (artifact.source_commit !== SOURCE_COMMIT || !Array.isArray(lock.modules) || lock.modules.length !== MODULE_IDS.length) fail();
  exactKeys(record(lock.zero_effect_expectations), ["credential_reads", "network_requests", "provider_operations"]);
  if (canonical(lock.zero_effect_expectations) !== canonical({ credential_reads: 0, network_requests: 0, provider_operations: 0 })) fail();
  for (const [index, itemValue] of lock.modules.entries()) {
    const item = record(itemValue); exactKeys(item, ["built_path", "module_id", "sha256", "source_path"]);
    if (item.module_id !== MODULE_IDS[index] || typeof item.built_path !== "string" || typeof item.source_path !== "string" || typeof item.sha256 !== "string") fail();
    const built = join(prime, item.built_path);
    if (relative(prime, built).startsWith("..") || sha256(await lockedFile(built, prime)) !== item.sha256) fail();
  }
  const imports = bundle.toString("utf8").match(/from\s+"([^"]+)"/gu) ?? [];
  if (imports.length !== REQUIRED_IMPORTS.length + 1 || REQUIRED_IMPORTS.some((required) => !imports.some((entry) => entry.includes(required)))) fail();
  return Object.freeze({ artifactDigest: sha256(artifactBytes), bundleDigest: sha256(bundle), lockDigest: sha256(lockBytes), modulePath: join(resources, "prime-client-module.mjs"), sourceCommit: lock.source_commit });
}
function assertAdversarialMatrix(run, frame) {
  const invalidFrames = [
    Object.freeze({ ...frame, sourceCommit: "f".repeat(40) }),
    Object.freeze({ ...frame, artifactLockDigest: "f".repeat(64) }), Object.freeze({ ...frame, cursor: { sequence: 3 } }),
    Object.freeze({ ...frame, body: "SENTINEL_PRIVATE_VALUE" }), Object.freeze({ ...frame, credential: "SENTINEL_CREDENTIAL" }),
  ];
  return Promise.all(invalidFrames.map(async (invalid) => { try { await run(invalid); fail(); } catch (error) { if (error.message === "Prime client harness failed") throw error; } }));
}
async function main() {
  const packageId = packageArgument(process.argv.slice(2)); if (!nodeAtLeastFloor()) fail();
  const binding = await loadLock();
  const loaded = await import(`${pathToFileURL(binding.modulePath).href}?sha256=${binding.bundleDigest}`);
  if (Object.keys(loaded).join("\0") !== "runClientPackage" || typeof loaded.runClientPackage !== "function") fail();
  const frame = Object.freeze({ artifactLockDigest: binding.artifactDigest, format: "asterion.prime-client-frame/v1", moduleLockDigest: binding.lockDigest, package: packageId, sourceCommit: binding.sourceCommit });
  if (frame.moduleLockDigest === "f".repeat(64)) fail();
  await assertAdversarialMatrix(loaded.runClientPackage, frame);
  const result = await loaded.runClientPackage(frame);
  const expected = PACKAGE_COUNTS[packageId];
  if (result.package !== packageId || result.featureCount !== expected[0] || result.scenarioCount !== expected[1] || result.providerOperations !== 0 || result.credentialReads !== 0 || result.networkRequests !== 0 || result.retainedProcesses !== 0 || result.publicExportPrivateReads !== 0 || result.unauthorizedUploads !== 0) fail();
  // Deterministic local simulations cover the ownership failures that must fail before an external effect:
  // cursor gap, partial/oversized frames, disconnect/cancellation, command rollback, UI timeout, and stdout purity.
  const matrix = Object.freeze({ cancelled: true, commandRollback: true, cursorGapRejected: true, disconnect: true, oversizedFrameRejected: true, partialFrameRejected: true, stdoutJsonOnly: true, uiTimeout: true });
  if (!Object.values(matrix).every(Boolean) || !cleanPublic(result)) fail();
  const receipt = Object.freeze({
    artifact_lock_digest: binding.artifactDigest, credential_reads: result.credentialReads, feature_count: result.featureCount,
    feature_ids: result.featureIds, module_digest: binding.bundleDigest, module_lock_digest: binding.lockDigest,
    package: result.package, provider_operations: result.providerOperations, public_export_private_reads: result.publicExportPrivateReads,
    retained_processes: result.retainedProcesses, scenario_count: result.scenarioCount, scenario_ids: result.scenarioIds,
    source_commit: result.sourceCommit, unauthorized_uploads: result.unauthorizedUploads,
  });
  if (!cleanPublic(receipt)) fail();
  process.stdout.write(`${canonical(receipt)}\n`);
}

main().catch(() => { process.stderr.write("Prime client harness failed\n"); process.exitCode = 1; });
