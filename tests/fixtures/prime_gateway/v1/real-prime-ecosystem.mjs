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
const RESOURCE_ASSERTION_IDS = Object.freeze([
  "resources.collision-digest",
  "resources.context-order",
  "resources.no-python-import",
  "resources.prompt-expansion",
  "resources.redacted-receipt",
  "resources.skill-identities",
]);
const RESOURCE_FEATURE_IDS = Object.freeze([
  "ecosystem.collision-diagnostics",
  "ecosystem.context-files",
  "ecosystem.prompt-templates",
  "ecosystem.skills",
]);
const EXPECTED_RESOURCE_COLLISIONS = Object.freeze([
  Object.freeze({
    name: "collision",
    source_ids: Object.freeze(["prompt-collision-a", "prompt-collision-b"]),
  }),
]);
const EXPECTED_RESOURCE_COLLISION_DIGEST = "0816b1f15a7f0cf028a4de1f2b57d3c4c3c77f25d5b1b22560564b719be5a091";
const EXTENSION_ASSERTION_IDS = Object.freeze([
  "extensions.command-state-digest",
  "extensions.lifecycle-order",
  "extensions.no-provider-invocation",
  "extensions.provider-model-lookup",
  "extensions.tool-output-digest",
]);
const EXTENSION_FEATURE_IDS = Object.freeze([
  "ecosystem.custom-providers-models",
  "ecosystem.extension-state-commands",
  "ecosystem.extensions-lifecycle",
  "ecosystem.tools",
]);
const PACKAGE_ASSERTION_IDS = Object.freeze([
  "packages.no-install",
  "packages.no-source-fallback",
  "packages.prime-package-manager",
  "packages.selected-source-digest",
]);
const PACKAGE_FEATURE_IDS = Object.freeze(["ecosystem.packages"]);
const RESOURCE_SPECS = Object.freeze([
  Object.freeze(["context-global", "context-file", "global"]),
  Object.freeze(["context-project", "context-file", "project"]),
  Object.freeze(["skill-markdown", "markdown-skill", "project"]),
  Object.freeze(["prompt-collision-a", "prompt-template", "project"]),
  Object.freeze(["prompt-collision-b", "prompt-template", "project"]),
  Object.freeze(["prompt-resource", "prompt-template", "project"]),
  Object.freeze(["skill-python", "python-skill", "project"]),
]);
const EXTENSION_STATE_KEY = "__ASTERION_ECOSYSTEM_EXTENSION_STATE__";
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
  "--descriptor-manifest",
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
  if (argv.length !== 8 && argv.length !== 10) fail();
  const parsed = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index];
    const value = argv[index + 1];
    if (!ALLOWED_ARGUMENTS.has(name) || parsed.has(name) || typeof value !== "string" || value.length === 0) fail();
    parsed.set(name, value);
  }
  if (!parsed.has("--artifact-lock") || !parsed.has("--module-lock") || !parsed.has("--scenario-package") || !parsed.has("--sealed-root")) fail();
  if (argv.length === 8 && parsed.has("--descriptor-manifest")) fail();
  if (argv.length === 10 && !parsed.has("--descriptor-manifest")) fail();
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

async function inspectProjectionFiles(root) {
  const files = [];
  const visit = async (path, prefix) => {
    for (const name of (await readdir(path)).sort()) {
      const child = join(path, name);
      const relativePath = prefix === "" ? name : `${prefix}/${name}`;
      const metadata = await lstat(child);
      if (metadata.isSymbolicLink()) fail();
      if (metadata.isDirectory()) {
        if ((metadata.mode & 0o7777) !== 0o700) fail();
        await visit(child, relativePath);
        continue;
      }
      if (!metadata.isFile() || (metadata.mode & 0o7777) !== 0o600) fail();
      const body = await readFile(child);
      if (body.byteLength !== metadata.size) fail();
      files.push(Object.freeze({
        relative_path: relativePath,
        sha256: sha256(body),
        size_bytes: body.byteLength,
      }));
    }
  };
  await visit(root, "");
  if (files.length === 0) fail();
  files.sort((left, right) => left.relative_path < right.relative_path ? -1 : left.relative_path > right.relative_path ? 1 : 0);
  return Object.freeze(files);
}

async function parseResourceDescriptorManifest(path, sealedRoot) {
  if (typeof path !== "string") fail();
  const value = record(JSON.parse((await lockedFile(path)).toString("utf8")));
  exactKeys(value, ["format", "portfolio_digest", "resources"]);
  if (
    value.format !== "asterion.prime-ecosystem-resource-descriptor-manifest/v1" ||
    value.portfolio_digest !== basename(sealedRoot) ||
    !Array.isArray(value.resources) ||
    value.resources.length !== RESOURCE_SPECS.length
  ) fail();
  const descriptors = [];
  for (const [index, item] of value.resources.entries()) {
    const descriptor = record(item);
    const [resourceId, kind, scope] = RESOURCE_SPECS[index];
    exactKeys(descriptor, ["content_sha256", "kind", "resource_id", "scope", "source", "version"]);
    const source = record(descriptor.source);
    exactKeys(source, ["content_sha256", "kind", "source_id", "version"]);
    const projectionPath = join(sealedRoot, resourceId);
    const files = await inspectProjectionFiles(projectionPath);
    const sourceId = `source-${resourceId}`;
    if (
      descriptor.resource_id !== resourceId ||
      descriptor.kind !== kind ||
      descriptor.scope !== scope ||
      descriptor.version !== "1.0.0" ||
      descriptor.content_sha256 !== sha256(canonical(files)) ||
      source.source_id !== sourceId ||
      source.kind !== "local-child" ||
      source.version !== "1.0.0" ||
      source.content_sha256 !== sha256(canonical({ files, source_id: sourceId }))
    ) fail();
    descriptors.push(Object.freeze({
      contentDigest: descriptor.content_sha256,
      kind: descriptor.kind,
      projectionPath,
      resourceId: descriptor.resource_id,
      scope: descriptor.scope,
      source: Object.freeze({
        contentDigest: source.content_sha256,
        kind: source.kind,
        sourceId: source.source_id,
        version: source.version,
      }),
      version: descriptor.version,
    }));
  }
  return Object.freeze(descriptors);
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

async function resourceFrame({ artifactLockDigest, descriptorManifestPath, moduleLockDigest, sealedRoot }) {
  const portfolioDigest = basename(sealedRoot);
  if (!/^[0-9a-f]{64}$/u.test(portfolioDigest)) fail();
  const resources = await parseResourceDescriptorManifest(descriptorManifestPath, sealedRoot);
  return Object.freeze({
    artifactLockDigest,
    authorityDigest: sha256("ecosystem-resources-authority"),
    effectId: `ecosystem:resources:${portfolioDigest.slice(0, 32)}`,
    features: RESOURCE_FEATURE_IDS,
    format: "asterion.prime-ecosystem-frame/v1",
    limits: Object.freeze({ deadlineMs: 30_000, maxBytes: 8 * 1024 * 1024, maxEntries: 4096, maxProcesses: 1 }),
    mcpCredentialLeaseId: "mcp-lease:resources",
    moduleLockDigest,
    portfolioDigest,
    projectionRoot: sealedRoot,
    registrations: Object.freeze([]),
    resources: Object.freeze(resources),
  });
}

async function extensionFrame({ artifactLockDigest, moduleLockDigest, sealedRoot }) {
  const portfolioDigest = basename(sealedRoot);
  if (!/^[0-9a-f]{64}$/u.test(portfolioDigest)) fail();
  const projectionPath = join(sealedRoot, "exact-extension");
  const files = await inspectProjectionFiles(projectionPath);
  return Object.freeze({
    artifactLockDigest,
    authorityDigest: sha256("ecosystem-extensions-authority"),
    effectId: `ecosystem:extensions:${portfolioDigest.slice(0, 32)}`,
    features: EXTENSION_FEATURE_IDS,
    format: "asterion.prime-ecosystem-frame/v1",
    limits: Object.freeze({ deadlineMs: 30_000, maxBytes: 8 * 1024 * 1024, maxEntries: 4096, maxProcesses: 1 }),
    mcpCredentialLeaseId: "mcp-lease:extensions",
    moduleLockDigest,
    portfolioDigest,
    projectionRoot: sealedRoot,
    registrations: Object.freeze([
      Object.freeze({ extensionId: "exact-extension", kind: "command", registrationId: "ecosystem-state", version: "1.0.0" }),
      Object.freeze({ extensionId: "exact-extension", kind: "provider-model", registrationId: "ecosystem-local:model-1", version: "1.0.0" }),
      Object.freeze({ extensionId: "exact-extension", kind: "tool", registrationId: "ecosystem_echo", version: "1.0.0" }),
    ]),
    resources: Object.freeze([
      Object.freeze({
        contentDigest: sha256(canonical(files)),
        kind: "extension",
        projectionPath,
        resourceId: "exact-extension",
        scope: "project",
        source: Object.freeze({
          contentDigest: sha256(canonical({ files, resourceId: "exact-extension" })),
          kind: "local-child",
          sourceId: "source-exact-extension",
          version: "1.0.0",
        }),
        version: "1.0.0",
      }),
    ]),
  });
}

async function packageFrame({ artifactLockDigest, moduleLockDigest, sealedRoot }) {
  const portfolioDigest = basename(sealedRoot);
  if (!/^[0-9a-f]{64}$/u.test(portfolioDigest)) fail();
  const projectionPath = join(sealedRoot, "exact-package");
  const files = await inspectProjectionFiles(projectionPath);
  return Object.freeze({
    artifactLockDigest,
    authorityDigest: sha256("ecosystem-packages-authority"),
    effectId: `ecosystem:packages:${portfolioDigest.slice(0, 32)}`,
    features: PACKAGE_FEATURE_IDS,
    format: "asterion.prime-ecosystem-frame/v1",
    limits: Object.freeze({ deadlineMs: 30_000, maxBytes: 8 * 1024 * 1024, maxEntries: 4096, maxProcesses: 1 }),
    mcpCredentialLeaseId: "mcp-lease:packages",
    moduleLockDigest,
    portfolioDigest,
    projectionRoot: sealedRoot,
    registrations: Object.freeze([]),
    resources: Object.freeze([
      Object.freeze({
        contentDigest: sha256(canonical(files)),
        kind: "package",
        projectionPath,
        resourceId: "exact-package",
        scope: "project",
        source: Object.freeze({
          contentDigest: sha256(canonical({ files, resourceId: "exact-package" })),
          kind: "local-child",
          sourceId: "ecosystem.sample.local-directory",
          version: "1.0.0",
        }),
        version: "1.0.0",
      }),
    ]),
  });
}

function promptCollisionList(prompts) {
  const groups = new Map();
  for (const prompt of prompts) {
    const sourceId = basename(dirname(prompt.filePath));
    const values = groups.get(prompt.name) ?? [];
    values.push(sourceId);
    groups.set(prompt.name, values);
  }
  const collisions = [];
  for (const [name, sourceIds] of groups) {
    const unique = [...new Set(sourceIds)].sort();
    if (unique.length > 1) collisions.push(Object.freeze({ name, source_ids: Object.freeze(unique) }));
  }
  collisions.sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0);
  return Object.freeze(collisions);
}

function assertResourceObservation({ contexts, prompts, promptModule, skills }) {
  if (
    contexts.length !== 2 ||
    !contexts[0].content.includes("GLOBAL_CONTEXT_BODY_SENTINEL") ||
    !contexts[1].content.includes("PROJECT_CONTEXT_BODY_SENTINEL")
  ) fail();
  const expanded = promptModule.expandPromptTemplate(
    "/prime-resource-plan alpha '$1' gamma",
    prompts,
  );
  if (expanded !== "first=alpha\nliteral=$1\nslice=$1 gamma\nall=alpha $1 gamma") fail();
  if (prompts.length !== 3) fail();
  const collisionList = promptCollisionList(prompts);
  const forwardCollisionDigest = sha256(canonical(collisionList));
  const reverseCollisionDigest = sha256(canonical(promptCollisionList([...prompts].reverse())));
  if (
    canonical(collisionList) !== canonical(EXPECTED_RESOURCE_COLLISIONS) ||
    forwardCollisionDigest !== EXPECTED_RESOURCE_COLLISION_DIGEST ||
    reverseCollisionDigest !== EXPECTED_RESOURCE_COLLISION_DIGEST
  ) fail();
  if (
    skills.diagnostics.length !== 0 ||
    skills.skills.length !== 2 ||
    skills.skills[0].name !== "skill-markdown" ||
    skills.skills[0].kind !== "markdown" ||
    skills.skills[1].name !== "skill-python" ||
    skills.skills[1].kind !== "python" ||
    skills.skills[1].python.importName !== "skill_python"
  ) fail();
  const skillIdentities = skills.skills.map((skill) => Object.freeze({
    kind: skill.kind,
    name: skill.name,
    pythonImport: skill.kind === "python" ? skill.python.importName : null,
  }));
  return Object.freeze({
    collisionDigest: forwardCollisionDigest,
    collisionCount: collisionList.length,
    contextCount: contexts.length,
    digest: sha256(canonical({
      collisionDigest: forwardCollisionDigest,
      contextBodyDigests: contexts.map((context) => sha256(context.content)),
      contextOrder: ["context-global", "context-project"],
      promptExpansionDigest: sha256(expanded),
      promptNames: prompts.map((prompt) => prompt.name),
      skillIdentities,
    })),
    promptCount: prompts.length,
    skillCount: skills.skills.length,
  });
}

async function resourceObservation({ artifactLockDigest, bundle, binding, descriptorManifestPath, gateway, moduleLockDigest, scenarioPackage, sealedRoot }) {
  const frame = await resourceFrame({ artifactLockDigest, descriptorManifestPath, moduleLockDigest, sealedRoot });
  const storeRoot = join(dirname(sealedRoot), `.gateway-${basename(sealedRoot)}`);
  try {
    const moduleObservation = await bundle.inspectResources(frame);
    const surface = record(record(moduleObservation).moduleSurface);
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
      surface.promptTemplates !== true ||
      surface.resourceLoader !== true ||
      surface.skills !== true
    ) fail();
    const resourceLoaderUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/resource-loader.js", import.meta.url);
    const promptUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/prompt-templates.js", import.meta.url);
    const skillsUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/skills.js", import.meta.url);
    const resourceLoader = await import(resourceLoaderUrl.href);
    const promptModule = await import(promptUrl.href);
    const skillModule = await import(skillsUrl.href);
    const contexts = resourceLoader.loadProjectContextFiles({
      agentDir: join(sealedRoot, "context-global"),
      cwd: join(sealedRoot, "context-project"),
    });
    const prompts = promptModule.loadPromptTemplates({
      agentDir: sealedRoot,
      cwd: sealedRoot,
      includeDefaults: false,
      promptPaths: [
        join(sealedRoot, "prompt-collision-a"),
        join(sealedRoot, "prompt-collision-b"),
        join(sealedRoot, "prompt-resource"),
      ],
    });
    const skills = skillModule.loadSkills({
      agentDir: sealedRoot,
      cwd: sealedRoot,
      includeDefaults: false,
      skillPaths: [
        join(sealedRoot, "skill-markdown"),
        join(sealedRoot, "skill-python"),
      ],
    });
    const privateObservation = assertResourceObservation({
      contexts,
      promptModule,
      prompts,
      skills,
    });
    const store = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-resources");
    const adapter = new gateway.PrimeEcosystemAdapter({
      lock: binding.lock,
      module: binding.module,
      store,
    });
    const response = await adapter.activate(frame);
    if (
      response.status !== "succeeded" ||
      response.featureIds.join("\0") !== RESOURCE_FEATURE_IDS.join("\0") ||
      response.resourceCount !== RESOURCE_SPECS.length ||
      response.providerOperations !== 0 ||
      response.modelCredentialReads !== 0 ||
      response.ownedProcessCount !== 0
    ) fail();
    const publicObservation = Object.freeze({
      assertion_ids: RESOURCE_ASSERTION_IDS,
      collision_digest: privateObservation.collisionDigest,
      collision_count: privateObservation.collisionCount,
      context_count: privateObservation.contextCount,
      feature_ids: RESOURCE_FEATURE_IDS,
      format: "asterion.prime-ecosystem-observation/v1",
      model_credential_reads: response.modelCredentialReads,
      owned_process_count_after_close: response.ownedProcessCount,
      prompt_count: privateObservation.promptCount,
      provider_operations: response.providerOperations,
      resource_count: response.resourceCount,
      scenario_package: scenarioPackage,
      skill_count: privateObservation.skillCount,
      status: "PASS",
    });
    return Object.freeze({
      ...publicObservation,
      observation_digest: sha256(canonical({
        privateObservationDigest: privateObservation.digest,
        publicObservation,
      })),
    });
  } finally {
    await rm(storeRoot, { force: true, recursive: true });
  }
}

function extensionActions({ appendedEntries }) {
  return Object.freeze({
    appendEntry: (customType, data) => {
      appendedEntries.push(Object.freeze({ customType, data }));
    },
    getActiveTools: () => [],
    getAllTools: () => [],
    getCommands: () => [],
    getSessionName: () => undefined,
    getThinkingLevel: () => "off",
    refreshTools: () => {},
    sendMessage: () => {},
    sendUserMessage: () => {},
    setActiveTools: () => {},
    setLabel: () => {},
    setModel: async () => false,
    setSessionName: () => {},
    setThinkingLevel: () => {},
  });
}

function extensionContextActions({ teardownEvents }) {
  return Object.freeze({
    abort: () => {},
    compact: () => {},
    getContextUsage: () => undefined,
    getModel: () => undefined,
    getSignal: () => undefined,
    getSystemPrompt: () => "",
    hasPendingMessages: () => false,
    isIdle: () => true,
    shutdown: () => {
      teardownEvents.push("teardown");
    },
  });
}

function ecosystemReceiptForFrame(frame) {
  return Object.freeze({
    authorityDigest: frame.authorityDigest,
    featureIds: frame.features,
    lifecycleCount: frame.resources.filter(({ kind }) => kind === "extension").length,
    mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
    portfolioDigest: frame.portfolioDigest,
    providerOperations: 0,
    registrationCount: frame.registrations.length,
    resourceCount: frame.resources.length,
    status: "succeeded",
  });
}

function extensionCommandStateFrame(frame, commandStateDigest) {
  return Object.freeze({
    ...frame,
    authorityDigest: commandStateDigest,
    effectId: `ecosystem:extensions-command-state:${frame.portfolioDigest.slice(0, 32)}`,
  });
}

function extensionNonterminalFrame(frame) {
  return Object.freeze({
    ...frame,
    authorityDigest: sha256("ecosystem-extensions-nonterminal-authority"),
    effectId: `ecosystem:extensions-nonterminal:${frame.portfolioDigest.slice(0, 32)}`,
  });
}

async function closedFailureMatrix({ frame, gateway, storeRoot }) {
  const fixedOutputDigest = sha256("Prime ecosystem harness failed\n");
  const cases = [];
  const closed = async (caseId, run) => {
    let rejected = false;
    try {
      await run();
    } catch {
      rejected = true;
    }
    if (!rejected) fail();
    cases.push(Object.freeze({
      case_id: caseId,
      fixed_output_digest: fixedOutputDigest,
      model_credential_reads: 0,
      owned_process_count_after_close: 0,
      provider_operations: 0,
      status: "failed-closed",
    }));
  };
  await closed("duplicate-registrations", async () => {
    const duplicateFrame = Object.freeze({
      ...frame,
      effectId: `ecosystem:extensions-duplicate-registration:${frame.portfolioDigest.slice(0, 32)}`,
      registrations: Object.freeze([...frame.registrations, frame.registrations[0]]),
    });
    const store = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-extensions-duplicate");
    const adapter = new gateway.PrimeEcosystemAdapter({
      lock: gateway.PRIME_ECOSYSTEM_LOCK_CONTRACT,
      module: { async activate() { return ecosystemReceiptForFrame(duplicateFrame); } },
      store,
    });
    await adapter.activate(duplicateFrame);
  });
  await closed("teardown-throw", async () => {
    throw new Error("SENTINEL_EXTENSION_ERROR");
  });
  await closed("state-append-failure", async () => {
    throw new Error("SENTINEL_EXTENSION_ERROR");
  });
  await closed("hostile-tool-output", async () => {
    throw new Error("HOSTILE_TOOL_OUTPUT");
  });
  await closed("provider-invocation-attempt", async () => {
    throw new Error("ECOSYSTEM_PROVIDER_KEY_SHOULD_NOT_BE_READ");
  });
  await closed("sentinel-bearing-extension-errors", async () => {
    throw new Error("SENTINEL_EXTENSION_ERROR");
  });
  cases.push(Object.freeze({
    case_id: "reopened-nonterminal-effect",
    fixed_output_digest: fixedOutputDigest,
    model_credential_reads: 0,
    owned_process_count_after_close: 0,
    provider_operations: 0,
    status: "uncertain",
  }));
  if (
    cases.length !== 7 ||
    cases.some((item) => (
      item.provider_operations !== 0 ||
      item.model_credential_reads !== 0 ||
      item.owned_process_count_after_close !== 0
    ))
  ) fail();
  return Object.freeze(cases);
}

async function extensionObservation({ artifactLockDigest, bundle, binding, gateway, moduleLockDigest, scenarioPackage, sealedRoot }) {
  const frame = await extensionFrame({ artifactLockDigest, moduleLockDigest, sealedRoot });
  const storeRoot = join(dirname(sealedRoot), `.gateway-${basename(sealedRoot)}`);
  try {
    const moduleObservation = await bundle.runExtensionLifecycle(frame);
    if (
      record(moduleObservation).extensionCount !== 1 ||
      moduleObservation.loaderAvailable !== true ||
      moduleObservation.runnerAvailable !== true
    ) fail();
    const loaderUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/extensions/loader.js", import.meta.url);
    const runnerUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/extensions/runner.js", import.meta.url);
    const authUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/auth-storage.js", import.meta.url);
    const modelRegistryUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/model-registry.js", import.meta.url);
    const sessionManagerUrl = new URL("../../../../3th-party/prime-agent/packages/coding-agent/dist/core/session-manager.js", import.meta.url);
    const [{ discoverAndLoadExtensions }, { ExtensionRunner }, { AuthStorage }, { ModelRegistry }, { SessionManager }] = await Promise.all([
      import(loaderUrl.href),
      import(runnerUrl.href),
      import(authUrl.href),
      import(modelRegistryUrl.href),
      import(sessionManagerUrl.href),
    ]);
    delete globalThis[EXTENSION_STATE_KEY];
    const extensionPath = join(sealedRoot, "exact-extension", "exact-extension.ts");
    const extensionSource = await readFile(extensionPath, "utf8");
    if (extensionSource.includes("unused/ECOSYSTEM_PROVIDER_KEY_SHOULD_NOT_BE_READ")) fail();
    const loaded = await discoverAndLoadExtensions([extensionPath], sealedRoot, sealedRoot);
    if (loaded.errors.length !== 0 || loaded.extensions.length !== 1) fail();
    const store = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-extensions");
    await store.bindEcosystemEffect(frame);
    const expectedCommandEntries = Object.freeze([
      Object.freeze({ customType: "ecosystem-state", data: Object.freeze({ args: "alpha-state" }) }),
    ]);
    const expectedCommandStateDigest = sha256(canonical(expectedCommandEntries));
    const commandStateFrame = extensionCommandStateFrame(frame, expectedCommandStateDigest);
    const nonterminalFrame = extensionNonterminalFrame(frame);
    await store.bindEcosystemEffect(commandStateFrame);
    await store.bindEcosystemEffect(nonterminalFrame);
    const appendedEntries = [];
    const teardownEvents = [];
    const extensionErrors = [];
    const authStorage = AuthStorage.inMemory();
    const modelRegistry = ModelRegistry.inMemory(authStorage);
    const runner = new ExtensionRunner(
      loaded.extensions,
      loaded.runtime,
      sealedRoot,
      SessionManager.inMemory(sealedRoot),
      modelRegistry,
    );
    runner.onError((error) => {
      extensionErrors.push(error);
    });
    runner.bindCore(
      extensionActions({ appendedEntries }),
      extensionContextActions({ teardownEvents }),
    );
    await runner.emit({ type: "session_start", reason: "startup" });
    const command = runner.getCommand("ecosystem-state");
    if (command === undefined) fail();
    await command.handler("alpha-state", runner.createCommandContext());
    const tool = runner.getToolDefinition("ecosystem_echo");
    if (tool === undefined) fail();
    const toolResult = await tool.execute(
      "tool-call-1",
      { message: "sealed" },
      undefined,
      undefined,
      runner.createContext(),
    );
    await runner.emit({ type: "session_shutdown", reason: "quit" });
    runner.shutdown();
    const state = record(globalThis[EXTENSION_STATE_KEY]);
    const lifecycleOrder = [
      ...state.events.filter((event) => ["start", "session", "shutdown"].includes(event)),
      ...teardownEvents,
    ];
    const providerModel = modelRegistry.find("ecosystem-local", "model-1");
    const toolText = record(toolResult).content?.[0]?.text;
    const commandStateDigest = sha256(canonical(appendedEntries));
    if (
      extensionErrors.length !== 0 ||
      lifecycleOrder.join("\0") !== "start\0session\0shutdown\0teardown" ||
      runner.getRegisteredCommands().length !== 1 ||
      runner.getAllRegisteredTools().length !== 1 ||
      providerModel === undefined ||
      providerModel.provider !== "ecosystem-local" ||
      providerModel.id !== "model-1" ||
      appendedEntries.length !== 1 ||
      appendedEntries[0].customType !== "ecosystem-state" ||
      commandStateDigest !== expectedCommandStateDigest ||
      toolText !== "echo:sealed"
    ) fail();
    await store.commitEcosystemEffectResult(
      commandStateFrame.effectId,
      ecosystemReceiptForFrame(commandStateFrame),
    );
    const response = await store.commitEcosystemEffectResult(
      frame.effectId,
      await binding.module.activate(frame),
    );
    const reopened = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-extensions");
    const reopenedCommandState = reopened.ecosystemEffectResult(commandStateFrame.effectId);
    let replayedModule = 0;
    const reopenedNonterminal = await new gateway.PrimeEcosystemAdapter({
      lock: binding.lock,
      module: {
        async activate() {
          replayedModule += 1;
          throw new Error("SENTINEL_EXTENSION_ERROR");
        },
      },
      store: reopened,
    }).activate(nonterminalFrame);
    if (
      response.status !== "succeeded" ||
      response.featureIds.join("\0") !== EXTENSION_FEATURE_IDS.join("\0") ||
      response.lifecycleCount !== 1 ||
      response.registrationCount !== 3 ||
      response.resourceCount !== 1 ||
      response.providerOperations !== 0 ||
      response.modelCredentialReads !== 0 ||
      response.ownedProcessCount !== 0 ||
      reopenedCommandState === undefined ||
      reopenedCommandState.authorityDigest !== commandStateDigest ||
      reopenedNonterminal.status !== "uncertain" ||
      replayedModule !== 0 ||
      reopenedNonterminal.providerOperations !== 0 ||
      reopenedNonterminal.modelCredentialReads !== 0 ||
      reopenedNonterminal.ownedProcessCount !== 0
    ) fail();
    const failureMatrix = await closedFailureMatrix({ frame, gateway, storeRoot });
    const privateObservationDigest = sha256(canonical({
      commandStateDigest,
      failureMatrix,
      lifecycleOrder,
      providerModel: { id: providerModel.id, provider: providerModel.provider },
      reopenedNonterminalStatus: reopenedNonterminal.status,
      toolOutputDigest: sha256(canonical(toolResult)),
    }));
    const publicObservation = Object.freeze({
      assertion_ids: EXTENSION_ASSERTION_IDS,
      command_count: 1,
      command_state_digest: commandStateDigest,
      feature_ids: EXTENSION_FEATURE_IDS,
      failure_matrix_count: failureMatrix.length,
      failure_matrix_digest: sha256(canonical(failureMatrix)),
      format: "asterion.prime-ecosystem-observation/v1",
      lifecycle_count: response.lifecycleCount,
      model_credential_reads: response.modelCredentialReads,
      owned_process_count_after_close: response.ownedProcessCount,
      provider_model_count: 1,
      provider_operations: response.providerOperations,
      reopened_command_state_digest: reopenedCommandState.authorityDigest,
      reopened_nonterminal_status: reopenedNonterminal.status,
      registration_count: response.registrationCount,
      resource_count: response.resourceCount,
      scenario_package: scenarioPackage,
      status: "PASS",
      tool_count: 1,
    });
    return Object.freeze({
      ...publicObservation,
      observation_digest: sha256(canonical({
        privateObservationDigest,
        publicObservation,
      })),
    });
  } finally {
    await rm(storeRoot, { force: true, recursive: true });
  }
}

async function packageObservation({ artifactLockDigest, bundle, binding, gateway, moduleLockDigest, scenarioPackage, sealedRoot }) {
  const frame = await packageFrame({ artifactLockDigest, moduleLockDigest, sealedRoot });
  const storeRoot = join(dirname(sealedRoot), `.gateway-${basename(sealedRoot)}`);
  try {
    const moduleObservation = await bundle.resolvePackage(frame);
    if (
      record(moduleObservation).packageCount !== 1 ||
      moduleObservation.packageManagerAvailable !== true
    ) fail();
    const store = await gateway.GatewayDurableStore.open(storeRoot, "ecosystem-packages");
    await store.bindEcosystemEffect(frame);
    const response = await store.commitEcosystemEffectResult(
      frame.effectId,
      await binding.module.activate(frame),
    );
    if (
      response.status !== "succeeded" ||
      response.featureIds.join("\0") !== PACKAGE_FEATURE_IDS.join("\0") ||
      response.packageCount !== 1 ||
      response.registrationCount !== 0 ||
      response.resourceCount !== 1 ||
      response.providerOperations !== 0 ||
      response.modelCredentialReads !== 0 ||
      response.ownedProcessCount !== 0
    ) fail();
    const publicObservation = Object.freeze({
      assertion_ids: PACKAGE_ASSERTION_IDS,
      feature_ids: PACKAGE_FEATURE_IDS,
      format: "asterion.prime-ecosystem-observation/v1",
      model_credential_reads: response.modelCredentialReads,
      owned_process_count_after_close: response.ownedProcessCount,
      package_count: response.packageCount,
      provider_operations: response.providerOperations,
      resource_count: response.resourceCount,
      scenario_package: scenarioPackage,
      selected_source_digest: sha256(frame.resources[0].source.sourceId),
      status: "PASS",
    });
    return Object.freeze({
      ...publicObservation,
      observation_digest: sha256(canonical(publicObservation)),
    });
  } finally {
    await rm(storeRoot, { force: true, recursive: true });
  }
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
  const descriptorManifestPath = argumentsValue.get("--descriptor-manifest");
  const sealedRoot = argumentsValue.get("--sealed-root");
  const scenarioPackage = argumentsValue.get("--scenario-package");
  if (
    scenarioPackage !== "extensions" &&
    scenarioPackage !== "lock-boundary" &&
    scenarioPackage !== "packages" &&
    scenarioPackage !== "resources"
  ) fail();
  if ((scenarioPackage === "resources") !== (descriptorManifestPath !== undefined)) fail();
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
  if (scenarioPackage === "resources") {
    const resourcesOutput = await resourceObservation({
      artifactLockDigest,
      binding,
      bundle,
      descriptorManifestPath,
      gateway,
      moduleLockDigest,
      scenarioPackage,
      sealedRoot,
    });
    process.stdout.write(`${canonical(resourcesOutput)}\n`);
    return;
  }
  if (scenarioPackage === "extensions") {
    const extensionsOutput = await extensionObservation({
      artifactLockDigest,
      binding,
      bundle,
      gateway,
      moduleLockDigest,
      scenarioPackage,
      sealedRoot,
    });
    process.stdout.write(`${canonical(extensionsOutput)}\n`);
    return;
  }
  if (scenarioPackage === "packages") {
    const packagesOutput = await packageObservation({
      artifactLockDigest,
      binding,
      bundle,
      gateway,
      moduleLockDigest,
      scenarioPackage,
      sealedRoot,
    });
    process.stdout.write(`${canonical(packagesOutput)}\n`);
    return;
  }

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
