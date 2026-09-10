/** Build or verify the exact, external Pi closure used by the P1 witness. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { builtinModules, findPackageJSON, registerHooks } from "node:module";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO_ROOT = import.meta.url.startsWith("file:") ? resolve(dirname(fileURLToPath(import.meta.url)), "..") : null;
export const ARTIFACT_LOCK = REPO_ROOT === null ? null : join(REPO_ROOT, "packages/typescript/prime-gateway/resources/prime-artifact-lock.json");
export const COMPACTION_LOCK = REPO_ROOT === null ? null : join(REPO_ROOT, "packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json");
export const ENTRY_POINTS = Object.freeze([
  "packages/ai/dist/index.js",
  "packages/coding-agent/dist/core/agent-session.js",
  "packages/coding-agent/dist/core/compaction/compaction.js",
  "packages/coding-agent/dist/core/session-manager.js",
  "packages/coding-agent/dist/index.js",
  "packages/coding-agent/dist/modes/rpc/rpc-mode.js",
]);
const FORMAT = "asterion.pi-compaction-lock/v1";
const fail = () => { throw new Error("Pi compaction closure is incompatible"); };
export const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const sortObject = (value) => Array.isArray(value) ? value.map(sortObject)
  : value !== null && typeof value === "object"
    ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortObject(value[key])])) : value;
export const canonicalEvidence = (value) => JSON.stringify(sortObject(value));
const lockBytes = (input) => input instanceof Uint8Array ? Buffer.from(input) : readFileSync(input);

function beneath(root, path) {
  const name = relative(root, path);
  return name !== "" && !isAbsolute(name) && name !== ".." && !name.startsWith(`..${sep}`);
}

function exactFile(root, name) {
  if (typeof name !== "string" || name.includes("\\") || isAbsolute(name)
      || name.split("/").some((part) => !part || part === "." || part === "..")) fail();
  const path = join(root, name);
  if (!beneath(root, path) || realpathSync(path) !== path || !lstatSync(path).isFile()) fail();
  return path;
}

function verifyFiles(root, files) {
  if (!files || Object.keys(files).length === 0) fail();
  for (const [name, digest] of Object.entries(files)) {
    if (!/^[0-9a-f]{64}$/u.test(digest) || sha256(readFileSync(exactFile(root, name))) !== digest) fail();
  }
}

export function verifyArtifactRoot(sourceRoot, artifactLockPath = ARTIFACT_LOCK) {
  try {
    if (!isAbsolute(sourceRoot) || realpathSync(sourceRoot) !== sourceRoot
        || !lstatSync(sourceRoot).isDirectory()) fail();
    const bytes = lockBytes(artifactLockPath);
    const artifact = JSON.parse(bytes);
    if (artifact.format !== "asterion.prime-artifact-lock/v1"
        || artifact.package_name !== "@earendil-works/pi-coding-agent"
        || artifact.package_version !== "0.7.1") fail();
    verifyFiles(sourceRoot, artifact.files);
    const git = (...args) => execFileSync("git", args, {
      cwd: sourceRoot, encoding: "utf8", timeout: 10_000,
      env: { PATH: process.env.PATH, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" },
    }).trim();
    if (realpathSync(git("rev-parse", "--show-toplevel")) !== sourceRoot
        || git("rev-parse", "HEAD") !== artifact.source_commit
        || git("status", "--porcelain", "--untracked-files=normal") !== "") fail();
    // package.json itself is not a public export. Resolve the package's public
    // entry, then read the digest-verified package.json at that exact package root.
    const manifestPath = findPackageJSON(artifact.package_name, pathToFileURL(join(sourceRoot, "package.json")));
    const packageRoot = dirname(realpathSync(manifestPath));
    if (packageRoot !== join(sourceRoot, "packages/coding-agent")) fail();
    const pkg = JSON.parse(readFileSync(exactFile(sourceRoot, "packages/coding-agent/package.json")));
    if (pkg.name !== artifact.package_name || pkg.version !== "0.7.1"
        || pkg.exports["."].import !== "./dist/index.js") fail();
    return Object.freeze({ root: sourceRoot, packageRoot, pkg, artifact, artifactDigest: sha256(bytes) });
  } catch { fail(); }
}

async function esbuild() {
  return import(pathToFileURL(join(REPO_ROOT, "packages/typescript/asterion-prime-extension/node_modules/esbuild/lib/main.js")).href);
}

export async function buildCompactionLock(sourceRoot) {
  const verified = verifyArtifactRoot(sourceRoot);
  const { build } = await esbuild();
  const result = await build({
    absWorkingDir: sourceRoot, entryPoints: [...ENTRY_POINTS], outdir: "compaction-lock-metafile-output",
    bundle: true, platform: "node", format: "esm", metafile: true,
    write: false, logLevel: "silent", treeShaking: false,
    // Match Node resolution, not the external repo's development TS path aliases.
    tsconfigRaw: {}, mainFields: ["main"], conditions: ["node"],
  });
  assert.equal(result.warnings.length, 0);
  const files = {};
  const addFile = (name) => { files[name] = sha256(readFileSync(exactFile(sourceRoot, name))); };
  for (const input of Object.keys(result.metafile.inputs)) {
    const name = relative(sourceRoot, realpathSync(resolve(sourceRoot, input))).split(sep).join("/");
    addFile(name);
    // Node's package type/exports and CJS resolution depend on these manifests.
    for (let directory = dirname(join(sourceRoot, name)); directory.startsWith(sourceRoot); directory = dirname(directory)) {
      const manifest = join(directory, "package.json");
      if (existsSync(manifest)) addFile(relative(sourceRoot, manifest).split(sep).join("/"));
      if (directory === sourceRoot) break;
    }
  }
  const builtins = new Set(builtinModules.flatMap((name) => [name, `node:${name}`]));
  const optionalImports = [...new Set(Object.values(result.metafile.inputs).flatMap((input) =>
    input.imports.filter((item) => item.external && !builtins.has(item.path) && item.path !== "<runtime>").map((item) => item.path)))].sort();
  assert.deepEqual(optionalImports, ["bufferutil", "utf-8-validate"]);
  const publicOutputs = Object.values(result.metafile.outputs).filter((output) => output.entryPoint === "packages/coding-agent/dist/index.js");
  assert.equal(publicOutputs.length, 1);
  const publicExports = publicOutputs[0].exports.sort();
  assert(!publicExports.includes("prepareCompaction"));
  assert(publicExports.includes("buildSessionContext"));
  // The pinned ./hooks export points at a missing file; it cannot export a symbol.
  assert.deepEqual(Object.keys(verified.pkg.exports).sort(), [".", "./hooks"]);
  assert.equal(verified.pkg.exports["./hooks"].import, "./dist/core/hooks/index.js");
  assert(!existsSync(join(verified.packageRoot, "dist/core/hooks/index.js")));
  return sortObject({
    artifact_lock_sha256: verified.artifactDigest,
    entry_points: ENTRY_POINTS,
    files,
    format: FORMAT,
    package_name: verified.pkg.name,
    package_version: verified.pkg.version,
    public_exports: publicExports,
    source_commit: verified.artifact.source_commit,
    unresolved_optional_imports: optionalImports,
  });
}

/** Shared preflight verifier. No Pi code is loaded before every digest passes. */
export function verifyCompactionLock(sourceRoot, lockPath = COMPACTION_LOCK, artifactLockPath = ARTIFACT_LOCK) {
  try {
    const verified = verifyArtifactRoot(sourceRoot, artifactLockPath);
    const lock = JSON.parse(lockBytes(lockPath));
    if (lock.format !== FORMAT || lock.package_version !== "0.7.1"
        || lock.package_name !== verified.pkg.name
        || lock.source_commit !== verified.artifact.source_commit
        || lock.artifact_lock_sha256 !== verified.artifactDigest
        || JSON.stringify(lock.entry_points) !== JSON.stringify(ENTRY_POINTS)
        || lock.public_exports.includes("prepareCompaction")
        || !lock.public_exports.includes("buildSessionContext")
        || JSON.stringify(Object.keys(lock.files)) !== JSON.stringify(Object.keys(lock.files).sort())
        || existsSync(join(verified.packageRoot, "dist/core/hooks/index.js"))) fail();
    for (const entry of ENTRY_POINTS) if (!Object.hasOwn(lock.files, entry)) fail();
    verifyFiles(sourceRoot, lock.files);
    Object.freeze(lock.files);
    Object.freeze(lock.entry_points);
    Object.freeze(lock.public_exports);
    Object.freeze(lock.unresolved_optional_imports);
    Object.freeze(lock);
    return Object.freeze({ ...verified, lock });
  } catch { fail(); }
}

/** Enforce the metafile closure at actual ESM/CJS load time, including dynamics. */
export function guardCompactionImports(verified) {
  return registerHooks({
    load(url, context, nextLoad) {
      if (url.startsWith("node:")) return nextLoad(url, context);
      if (!url.startsWith("file:")) fail();
      const path = realpathSync(fileURLToPath(url));
      const name = relative(verified.root, path).split(sep).join("/");
      if (!beneath(verified.root, path) || !Object.hasOwn(verified.lock.files, name)
          || sha256(readFileSync(path)) !== verified.lock.files[name]) fail();
      return nextLoad(url, context);
    },
  });
}

/** Generic loader provider: verify only, before constructing any Pi dependencies. */
export function verifyDependencies(context) {
  return verifyCompactionLock(context.sourceRoot, context.lockBytes, context.artifactLockBytes);
}

/** Application-owned exact exports; the loader owns the returned guard lifetime. */
export async function createDependencies(context) {
  const verified = verifyDependencies(context);
  const guard = guardCompactionImports(verified);
  try {
    const load = (name) => import(pathToFileURL(join(verified.root, name)).href);
    const compactionPath = "packages/coding-agent/dist/core/compaction/compaction.js";
    const source = readFileSync(exactFile(verified.root, compactionPath), "utf8");
    if (sha256(source) !== verified.lock.files[compactionPath]) fail();
    const matches = [...source.matchAll(/const TURN_PREFIX_SUMMARIZATION_PROMPT = `([^`]+)`;/gu)];
    if (matches.length !== 1 || matches[0][1].includes("${") || matches[0][1].includes("\\")) fail();
    const compaction = await load(compactionPath);
    const session = await load("packages/coding-agent/dist/core/session-manager.js");
    const messages = await load("packages/coding-agent/dist/core/messages.js");
    const utils = await load("packages/coding-agent/dist/core/compaction/utils.js");
    const dependencies = Object.freeze({
      buildSessionContext: session.buildSessionContext,
      prepareCompaction: compaction.prepareCompaction,
      convertToLlm: messages.convertToLlm,
      serializeConversation: utils.serializeConversation,
      buildSummarizationPrompt: compaction.buildSummarizationPrompt,
      summarizationSystemPrompt: utils.SUMMARIZATION_SYSTEM_PROMPT,
      turnPrefixPrompt: matches[0][1],
    });
    for (const [name, value] of Object.entries(dependencies)) {
      if (typeof value !== (name === "summarizationSystemPrompt" || name === "turnPrefixPrompt" ? "string" : "function")) fail();
    }
    let closed = false;
    return Object.freeze({dependencies, close() {
      if (!closed) {closed = true; guard.deregister();}
    }});
  } catch { guard.deregister(); fail(); }
}

/** The probe compiles the same TypeScript counter later bundled in the witness. */
export async function loadContextCounter() {
  const { build } = await esbuild();
  const result = await build({
    entryPoints: [join(REPO_ROOT, "packages/typescript/asterion-prime-extension/src/context-counter.ts")],
    bundle: true, platform: "node", format: "esm", write: false, logLevel: "silent",
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`);
}

if (import.meta.url.startsWith("file:") && process.argv[1] && pathToFileURL(realpathSync(process.argv[1])).href === import.meta.url) {
  try {
    if (process.argv[2] === "--verify" && process.argv.length === 6) {
      const result = verifyCompactionLock(process.argv[3], process.argv[4], process.argv[5]);
      process.stdout.write(`${canonicalEvidence({ format: FORMAT, package_version: result.pkg.version,
        locked_file_count: Object.keys(result.lock.files).length })}\n`);
    } else {
      if (process.argv.length !== 3) fail();
      const lock = await buildCompactionLock(process.argv[2]);
      writeFileSync(COMPACTION_LOCK, `${JSON.stringify(lock, null, 2)}\n`);
      process.stdout.write(`Pi compaction closure locked: ${Object.keys(lock.files).length} files\n`);
    }
  } catch { process.stderr.write("Pi compaction closure is incompatible\n"); process.exitCode = 1; }
}
