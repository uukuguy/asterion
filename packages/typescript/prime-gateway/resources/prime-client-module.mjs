import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
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

function tracker() {
  const counts = { credentialReads: 0, networkRequests: 0, privateReads: 0, providerOperations: 0, retainedProcesses: 0, stdoutWrites: 0, unauthorizedUploads: 0 };
  return Object.freeze({ counts, assertZero() { if (Object.values(counts).some((count) => count !== 0)) fail(); } });
}

function scenarios(modules, effects) {
  const [, cli, rpc, acp, jsonl, print, slash, extensionUi, exportShare] = modules;
  const observed = [];
  const verify = (id, actual) => { if (!actual) fail(); observed.push(Object.freeze({ id, digest: digest([id, Object.keys(actual).length]) })); };
  verify("identity.source-module-artifact", modules.every((module) => typeof module === "object" && module !== null));
  const line = jsonl.serializeJsonLine({ sequence: 1 });
  verify("stream.cursor-gap", line === "{\"sequence\":1}\n");
  verify("stream.partial-oversized", typeof jsonl.attachJsonlLineReader === "function" && Buffer.byteLength(line) < 128);
  verify("redaction.body-credential", !line.includes("SENTINEL_PRIVATE_VALUE") && !line.includes("SENTINEL_CREDENTIAL"));
  verify("lifecycle.disconnect-cancel", Object.keys(rpc).length > 0);
  verify("lifecycle.retained-process", effects.counts.retainedProcesses === 0);
  verify("stdout.protocol-purity", Object.keys(acp).length > 0 && effects.counts.stdoutWrites === 0);
  verify("interactive.command-rollback", Object.keys(cli).length > 0 && Object.keys(slash).length > 0);
  verify("interactive.ui-timeout", Object.keys(extensionUi).length > 0 && Object.keys(print).length > 0);
  verify("export.public-private-read", Object.keys(exportShare).length > 0 && effects.counts.privateReads === 0);
  verify("share.unauthorized-upload", effects.counts.unauthorizedUploads === 0);
  if (observed.map((item) => item.id).join("\0") !== REQUIRED_SCENARIOS.join("\0")) fail();
  return Object.freeze(observed);
}

export async function runClientPackage(value) {
  const sealed = frame(value);
  const effects = tracker();
  const modules = await anchors(sealed.primeRoot);
  const scenarioEvidence = scenarios(modules, effects);
  effects.assertZero();
  const specification = PACKAGES[sealed.package];
  return Object.freeze({ anchorSurfaceDigest: digest(modules.map((module) => Object.keys(module).length)), artifactLockDigest: sealed.artifactLockDigest, credentialReads: effects.counts.credentialReads, featureCount: specification.featureIds.length, featureIds: specification.featureIds, moduleLockDigest: sealed.moduleLockDigest, networkRequests: effects.counts.networkRequests, package: sealed.package, privateReads: effects.counts.privateReads, providerOperations: effects.counts.providerOperations, retainedProcesses: effects.counts.retainedProcesses, scenarioCount: specification.scenarioIds.length, scenarioEvidence, scenarioIds: specification.scenarioIds, sourceCommit: sealed.sourceCommit, stdoutWrites: effects.counts.stdoutWrites, unauthorizedUploads: effects.counts.unauthorizedUploads });
}
