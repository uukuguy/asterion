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
const OWNED_MCP_URL_DIGEST = "781224600d276111113690290697ea94153b42614a8b9a41900cc3fec7ccf5d0";

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

async function channelCall(channel, method, payload) {
  if (
    typeof channel !== "object" ||
    channel === null ||
    Array.isArray(channel) ||
    typeof channel[method] !== "function"
  ) {
    throw new Error("Prime ecosystem MCP channel is invalid");
  }
  const result = await channel[method](payload);
  if (typeof result !== "object" || result === null || Array.isArray(result)) {
    throw new Error("Prime ecosystem MCP channel failed");
  }
  return result;
}

export async function runMcpFixture(value, channel) {
  const frame = sealedFrame(value);
  return await providerFree(async () => {
    const mcpResources = frame.resources.filter(({ kind }) => kind === "mcp-server");
    if (mcpResources.length !== 1) throw new Error("Prime ecosystem MCP frame is invalid");
    const serverIdResult = await channelCall(channel, "serverId", {});
    const serverId = serverIdResult.server_id;
    if (typeof serverId !== "string" || serverId.length === 0) {
      throw new Error("Prime ecosystem MCP channel failed");
    }
    const configuredUrl = "http://127.0.0.1/owned-mcp";
    let storedCredential;
    let challengeDigest;
    const authStorage = Object.freeze({
      get: (providerId) => {
        if (providerId !== `mcp:${serverId}` || storedCredential === undefined) return undefined;
        return Object.freeze({ access: storedCredential });
      },
      getApiKey: async (providerId) => {
        if (providerId !== `mcp:${serverId}` || typeof challengeDigest !== "string") {
          throw new Error("Prime ecosystem MCP OAuth refresh rejected");
        }
        const refreshed = await channelCall(channel, "refresh", {
          challenge_digest: challengeDigest,
          lease_id: frame.mcpCredentialLeaseId,
        });
        if (typeof refreshed.credential !== "string" || refreshed.credential.length === 0) {
          throw new Error("Prime ecosystem MCP OAuth refresh failed");
        }
        storedCredential = refreshed.credential;
        return refreshed.credential;
      },
    });
    const manager = new primeMcpManager.McpManager({
      authStorage,
      getUserServers: () => Object.freeze({
        [serverId]: Object.freeze({
          enabled: true,
          oauth: true,
          type: "http",
          url: configuredUrl,
        }),
      }),
    });
    const handlers = manager.hostHandlers();
    const config = await handlers["mcp.config"]({ server: serverId });
    if (config.url !== configuredUrl) throw new Error("Prime ecosystem MCP config failed");
    const challenge = await channelCall(channel, "initialize", {
      lease_id: frame.mcpCredentialLeaseId,
    });
    challengeDigest = challenge.challenge_digest;
    if (typeof challengeDigest !== "string" || challenge.lease_id !== frame.mcpCredentialLeaseId) {
      throw new Error("Prime ecosystem MCP challenge failed");
    }
    await handlers["mcp.refresh"]({ server: serverId });
    await channelCall(channel, "initializeWithCredential", {
      credential: storedCredential,
    });
    const listed = await channelCall(channel, "list", {});
    if (listed.tool_count !== 1) throw new Error("Prime ecosystem MCP list failed");
    const shutdown = await channelCall(channel, "shutdown", {});
    const replay = await channelCall(channel, "replay", {});
    const status = manager.listStatus().find((item) => item.server === serverId);
    if (
      status === undefined ||
      status.usesOAuth !== true ||
      status.enabled !== true ||
      shutdown.credential_refresh_count !== 1 ||
      shutdown.challenge_count !== 1 ||
      shutdown.initialize_count !== 2 ||
      shutdown.list_count !== 1 ||
      shutdown.shutdown_count !== 1 ||
      shutdown.owned_process_count_after_close !== 0 ||
      replay.credential_refresh_count !== 1 ||
      replay.replay_refresh_count !== 0
    ) {
      throw new Error("Prime ecosystem MCP manager flow failed");
    }
    return Object.freeze({
      challenge_count: shutdown.challenge_count,
      config_url_digest: OWNED_MCP_URL_DIGEST,
      credential_refresh_count: shutdown.credential_refresh_count,
      initialize_count: shutdown.initialize_count,
      list_count: shutdown.list_count,
      manager_status_count: 1,
      manager_status_enabled_after_refresh: status.enabled,
      manager_status_uses_oauth: status.usesOAuth,
      mcp_count: mcpResources.length,
      mcp_manager_available: typeof primeMcpManager.McpManager === "function",
      oauth_available: typeof primeMcpOAuth.createMcpOAuthProvider === "function",
      provider_operations: 0,
      replay_refresh_count: replay.replay_refresh_count,
      shutdown_count: shutdown.shutdown_count,
    });
  });
}
