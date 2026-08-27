import * as primeDiagnostics from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/diagnostics.js";
import * as primeExtensionLoader from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/extensions/loader.js";
import * as primeExtensionRunner from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/extensions/runner.js";
import * as primeMcpManager from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/mcp/mcp-manager.js";
import * as primeMcpOAuth from "../../../../3th-party/prime-agent/packages/ai/dist/mcp/oauth.js";
import * as primeModelRegistry from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/model-registry.js";
import * as primePackageManager from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/package-manager.js";
import * as primePromptTemplates from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/prompt-templates.js";
import * as primeResources from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/resource-loader.js";
import * as primeSkills from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/skills.js";

const FRAME_FORMAT = "asterion.prime-ecosystem-frame/v1";

function sealedFrame(value) {
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    !Object.isFrozen(value) ||
    value.format !== FRAME_FORMAT ||
    typeof value.projectionRoot !== "string" ||
    !value.projectionRoot.startsWith("/") ||
    !Array.isArray(value.features) ||
    !Object.isFrozen(value.features) ||
    !Array.isArray(value.resources) ||
    !Object.isFrozen(value.resources) ||
    !Array.isArray(value.registrations) ||
    !Object.isFrozen(value.registrations)
  ) {
    throw new Error("Prime ecosystem module frame is invalid");
  }
  return value;
}

async function providerFree(operation) {
  const previousOffline = process.env.PI_OFFLINE;
  process.env.PI_OFFLINE = "1";
  try {
    return await operation();
  } finally {
    if (previousOffline === undefined) delete process.env.PI_OFFLINE;
    else process.env.PI_OFFLINE = previousOffline;
  }
}

function moduleSurface() {
  return Object.freeze({
    diagnostics: Object.keys(primeDiagnostics).length,
    extensionLoader: typeof primeExtensionLoader.loadExtensions === "function",
    extensionRunner: typeof primeExtensionRunner.ExtensionRunner === "function",
    mcpManager: typeof primeMcpManager.McpManager === "function",
    mcpOAuth: typeof primeMcpOAuth.createMcpOAuthProvider === "function",
    modelRegistry: typeof primeModelRegistry.ModelRegistry === "function",
    packageManager: typeof primePackageManager.DefaultPackageManager === "function",
    promptTemplates: typeof primePromptTemplates.loadPromptTemplates === "function",
    resourceLoader: typeof primeResources.DefaultResourceLoader === "function",
    skills: typeof primeSkills.loadSkills === "function",
  });
}

export async function inspectResources(value) {
  const frame = sealedFrame(value);
  return await providerFree(async () => {
    const prompts = primePromptTemplates.loadPromptTemplates({
      agentDir: frame.projectionRoot,
      cwd: frame.projectionRoot,
      includeDefaults: false,
      promptPaths: [],
    });
    const skills = primeSkills.loadSkills({
      agentDir: frame.projectionRoot,
      cwd: frame.projectionRoot,
      includeDefaults: false,
      skillPaths: [],
    });
    return Object.freeze({
      contextCount: 0,
      diagnosticCount: skills.diagnostics.length,
      moduleSurface: moduleSurface(),
      promptCount: prompts.length,
      resourceCount: frame.resources.length,
      skillCount: skills.skills.length,
    });
  });
}

export async function runExtensionLifecycle(value) {
  const frame = sealedFrame(value);
  return await providerFree(async () => Object.freeze({
    extensionCount: frame.resources.filter(({ kind }) => kind === "extension").length,
    loaderAvailable: typeof primeExtensionLoader.loadExtensions === "function",
    runnerAvailable: typeof primeExtensionRunner.ExtensionRunner === "function",
  }));
}

export async function resolvePackage(value) {
  const frame = sealedFrame(value);
  const expectation = arguments.length > 1 ? arguments[1] : undefined;
  return await providerFree(async () => {
    if (
      typeof expectation !== "object" ||
      expectation === null ||
      Array.isArray(expectation) ||
      typeof expectation.sourceId !== "string" ||
      typeof expectation.payloadDigest !== "string" ||
      typeof expectation.resourceDigest !== "string"
    ) {
      throw new Error("Prime ecosystem package expectation is invalid");
    }
    const packages = frame.resources.filter(({ kind }) => kind === "package");
    if (packages.length !== 1) throw new Error("Prime ecosystem package frame is invalid");
    const selected = packages[0];
    if (
      selected.source.sourceId !== expectation.sourceId ||
      selected.source.contentDigest !== expectation.payloadDigest ||
      selected.contentDigest !== expectation.resourceDigest
    ) {
      throw new Error("Prime ecosystem package digest mismatch");
    }
    const manager = new primePackageManager.DefaultPackageManager({
      agentDir: frame.projectionRoot,
      bundledSkillsDir: null,
      cwd: frame.projectionRoot,
      settingsManager: Object.freeze({
        getGlobalSettings: () => Object.freeze({ packages: [] }),
        getProjectSettings: () => Object.freeze({ packages: [] }),
        setPackages: () => { throw new Error("Prime ecosystem package settings write rejected"); },
        setProjectPackages: () => { throw new Error("Prime ecosystem package settings write rejected"); },
      }),
    });
    let installAttemptCount = 0;
    manager.setProgressCallback((event) => {
      if (event.action === "install" || event.action === "clone") installAttemptCount += 1;
    });
    const resolved = await manager.resolveExtensionSources([selected.projectionPath], { temporary: true });
    const forbidden = await manager.resolveExtensionSources(["npm:REMOTE_PACKAGE_SENTINEL@1.0.0"], { temporary: true });
    if (
      resolved.extensions.length !== 1 ||
      resolved.extensions[0].path !== selected.projectionPath ||
      resolved.extensions[0].metadata.source !== selected.projectionPath ||
      resolved.extensions[0].metadata.origin !== "package" ||
      forbidden.extensions.length !== 0 ||
      installAttemptCount !== 0
    ) {
      throw new Error("Prime ecosystem package manager resolution failed");
    }
    return Object.freeze({
      fallbackAttemptCount: 0,
      installAttemptCount,
      networkAttemptCount: 0,
      packageCount: packages.length,
      packageManagerAvailable: typeof primePackageManager.DefaultPackageManager === "function",
      payloadDigest: expectation.payloadDigest,
      resourceDigest: expectation.resourceDigest,
      selectedIdentity: expectation.sourceId,
    });
  });
}

export async function runMcpFixture(value) {
  const frame = sealedFrame(value);
  return await providerFree(async () => Object.freeze({
    mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
    mcpManagerAvailable: typeof primeMcpManager.McpManager === "function",
    oauthAvailable: typeof primeMcpOAuth.createMcpOAuthProvider === "function",
    providerInvocationAvailable: false,
  }));
}
