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
  return await providerFree(async () => Object.freeze({
    packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
    packageManagerAvailable: typeof primePackageManager.DefaultPackageManager === "function",
  }));
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
