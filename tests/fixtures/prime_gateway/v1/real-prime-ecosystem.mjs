import { createHash } from "node:crypto";
import { lstat, readFile, realpath, readdir, rm } from "node:fs/promises";
import { basename, dirname, isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

const PINNED_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c";
const MODULE_IDS = Object.freeze([
  "diagnostics",
  "extension-loader",
  "extension-runner",
  "mcp-manager",
  "mcp-oauth",
  "model-registry",
  "package-manager",
  "prompt-templates",
  "resource-loader",
  "skills",
]);
const REQUIRED_EXPORTS = Object.freeze([
  "inspectResources",
  "resolvePackage",
  "runExtensionLifecycle",
  "runMcpFixture",
]);
const MODEL_CREDENTIAL_NAME = /(?:API_KEY|OAUTH_TOKEN|AUTH_TOKEN|ACCESS_TOKEN|BEARER_TOKEN|SECRET_ACCESS_KEY|SESSION_TOKEN|APPLICATION_CREDENTIALS)$/u;
const MODEL_CREDENTIAL_NAMES = new Set([
  "AWS_ACCESS_KEY_ID",
  "AWS_CONTAINER_CREDENTIALS_FULL_URI",
  "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
  "AWS_PROFILE",
  "AWS_WEB_IDENTITY_TOKEN_FILE",
  "GCLOUD_PROJECT",
  "GOOGLE_CLOUD_LOCATION",
  "GOOGLE_CLOUD_PROJECT",
  "PRIME_TEAM_ID",
]);
const ALLOWED_ARGUMENTS = new Set([
  "--artifact-lock",
  "--module-lock",
  "--scenario-package",
  "--sealed-root",
]);

function fail() {
  throw new Error("Prime ecosystem harness failed");
}

function record(value) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail();
  return value;
}

function exactKeys(value, keys) {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail();
}

function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  const item = record(value);
  return `{${Object.keys(item).sort().map((key) => `${JSON.stringify(key)}:${canonical(item[key])}`).join(",")}}`;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function argumentsMap(argv) {
  if (argv.length !== 8) fail();
  const parsed = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!ALLOWED_ARGUMENTS.has(name) || parsed.has(name) || typeof value !== "string" || value.length === 0) fail();
    parsed.set(name, value);
  }
  if (parsed.size !== ALLOWED_ARGUMENTS.size) fail();
  return parsed;
}

async function lockedFile(path) {
  if (!isAbsolute(path)) fail();
  const metadata = await lstat(path);
  if (metadata.isSymbolicLink() || !metadata.isFile() || (metadata.mode & 0o002) !== 0) fail();
  if (await realpath(path) !== path) fail();
  return await readFile(path);
}

async function requireSealedTree(root) {
  if (!isAbsolute(root) || await realpath(root) !== root) fail();
  const visit = async (path) => {
    const metadata = await lstat(path);
    if (metadata.isSymbolicLink()) fail();
    if (metadata.isDirectory()) {
      if ((metadata.mode & 0o7777) !== 0o700) fail();
      for (const name of (await readdir(path)).sort()) await visit(join(path, name));
      return;
    }
    if (!metadata.isFile() || (metadata.mode & 0o7777) !== 0o600) fail();
  };
  await visit(root);
}

function parseModuleLock(bytes) {
  const value = record(JSON.parse(bytes.toString("utf8")));
  exactKeys(value, ["artifact_lock_sha256", "bundle_sha256", "format", "modules", "source_commit"]);
  if (
    value.format !== "asterion.prime-ecosystem-module-lock/v1" ||
    value.source_commit !== PINNED_COMMIT ||
    !/^[0-9a-f]{64}$/u.test(value.artifact_lock_sha256) ||
    !/^[0-9a-f]{64}$/u.test(value.bundle_sha256) ||
    !Array.isArray(value.modules) ||
    value.modules.length !== MODULE_IDS.length
  ) fail();
  value.modules.forEach((item, index) => {
    const module = record(item);
    exactKeys(module, ["built_path", "module_id", "sha256", "source_path"]);
    if (
      module.module_id !== MODULE_IDS[index] ||
      typeof module.source_path !== "string" ||
      typeof module.built_path !== "string" ||
      !/^[0-9a-f]{64}$/u.test(module.sha256)
    ) fail();
  });
  return value;
}

async function main() {
  const argumentsValue = argumentsMap(process.argv.slice(2));
  for (const name of Object.keys(process.env)) {
    if (MODEL_CREDENTIAL_NAME.test(name) || MODEL_CREDENTIAL_NAMES.has(name)) {
      delete process.env[name];
    }
  }
  if (Object.keys(process.env).some((name) => MODEL_CREDENTIAL_NAME.test(name) || MODEL_CREDENTIAL_NAMES.has(name))) fail();
  process.env.PI_OFFLINE = "1";

  const moduleLockPath = argumentsValue.get("--module-lock");
  const artifactLockPath = argumentsValue.get("--artifact-lock");
  const sealedRoot = argumentsValue.get("--sealed-root");
  const scenarioPackage = argumentsValue.get("--scenario-package");
  if (scenarioPackage !== "lock-boundary") fail();
  await requireSealedTree(sealedRoot);

  const moduleLockBytes = await lockedFile(moduleLockPath);
  const artifactLockBytes = await lockedFile(artifactLockPath);
  const moduleLock = parseModuleLock(moduleLockBytes);
  if (sha256(artifactLockBytes) !== moduleLock.artifact_lock_sha256) fail();
  const bundlePath = join(dirname(moduleLockPath), "prime-ecosystem-module.mjs");
  const bundleBytes = await lockedFile(bundlePath);
  if (sha256(bundleBytes) !== moduleLock.bundle_sha256) fail();

  const bundle = await import(`${pathToFileURL(bundlePath).href}?sha256=${moduleLock.bundle_sha256}`);
  if (Object.keys(bundle).sort().join("\0") !== REQUIRED_EXPORTS.join("\0")) fail();

  const gatewayUrl = new URL("../../../../packages/typescript/prime-gateway/dist/src/index.js", import.meta.url);
  const mainUrl = new URL("../../../../packages/typescript/prime-gateway/dist/src/main.js", import.meta.url);
  const gateway = await import(gatewayUrl.href);
  const { loadPrimeEcosystemModule, PrimeGatewaySidecar } = await import(mainUrl.href);
  const binding = await loadPrimeEcosystemModule({
    artifactLockPath,
    bundlePath,
    moduleLockPath,
  });
  const artifactLockDigest = sha256(artifactLockBytes);
  const moduleLockDigest = sha256(moduleLockBytes);
  if (
    gateway.PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST !== artifactLockDigest ||
    gateway.PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST !== moduleLockDigest ||
    binding.lock.artifactLockDigest !== artifactLockDigest ||
    binding.lock.moduleLockDigest !== moduleLockDigest ||
    binding.lock.bundleDigest !== moduleLock.bundle_sha256
  ) fail();
  const storeRoot = join(dirname(sealedRoot), `.gateway-${basename(sealedRoot)}`);
  let privateObservation;
  let output;
  try {
    const store = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-lock-boundary");
    const adapter = new gateway.PrimeEcosystemAdapter({
      lock: binding.lock,
      module: binding.module,
      store,
    });
    const sidecar = new PrimeGatewaySidecar({
      currentGeneration: 1,
      gateway: {
        activateEcosystem: (frame) => adapter.activate(frame),
        close: async () => {},
      },
      privateValues: {},
    });
    const portfolioDigest = basename(sealedRoot);
    if (!/^[0-9a-f]{64}$/u.test(portfolioDigest)) fail();
    const frame = Object.freeze({
      artifactLockDigest,
      authorityDigest: sha256("ecosystem-lock-boundary-authority"),
      effectId: `ecosystem:lock-boundary:${portfolioDigest.slice(0, 32)}`,
      features: Object.freeze([]),
      format: "asterion.prime-ecosystem-frame/v1",
      limits: Object.freeze({ deadlineMs: 30_000, maxBytes: 8 * 1024 * 1024, maxEntries: 4096, maxProcesses: 1 }),
      mcpCredentialLeaseId: "mcp-lease:lock-boundary",
      moduleLockDigest,
      portfolioDigest,
      projectionRoot: sealedRoot,
      registrations: Object.freeze([]),
      resources: Object.freeze([]),
    });
    privateObservation = await bundle.inspectResources(frame);
    const response = await sidecar.handleEnvelope({
      frame,
      id: "ecosystem-lock-boundary",
      protocol: "asterion.prime-gateway-ipc/v1",
      type: "ecosystem_activate",
    });
    if (response.type !== "ecosystem_receipt" || privateObservation === undefined) fail();
    const surface = record(record(privateObservation).moduleSurface);
    exactKeys(surface, [
      "diagnostics",
      "extensionLoader",
      "extensionRunner",
      "mcpManager",
      "mcpOAuth",
      "modelRegistry",
      "packageManager",
      "promptTemplates",
      "resourceLoader",
      "skills",
    ]);
    if (
      !Number.isSafeInteger(surface.diagnostics) ||
      surface.diagnostics < 0 ||
      Object.entries(surface).some(([name, available]) => name !== "diagnostics" && available !== true)
    ) fail();
    const publicObservation = Object.freeze({
      format: "asterion.prime-ecosystem-observation/v1",
      model_credential_reads: response.receipt.modelCredentialReads,
      module_count: moduleLock.modules.length,
      owned_process_count_after_close: response.receipt.ownedProcessCount,
      provider_operations: response.receipt.providerOperations,
      real_prime_runtime: true,
      scenario_package: scenarioPackage,
      status: "PASS",
    });
    if (
      publicObservation.model_credential_reads !== 0 ||
      publicObservation.owned_process_count_after_close !== 0 ||
      publicObservation.provider_operations !== 0
    ) fail();
    output = Object.freeze({
      ...publicObservation,
      observation_digest: sha256(canonical(publicObservation)),
    });
  } finally {
    await rm(storeRoot, { force: true, recursive: true });
  }
  if (output === undefined) fail();
  process.stdout.write(`${canonical(output)}\n`);
}

main().catch(() => {
  process.stderr.write("Prime ecosystem harness failed\n");
  process.exitCode = 1;
});
