import { existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

const PROVIDER = "asterion-p1-development";
const MODEL = "p1-development";
const MAX_MODEL_CALLS = 2;
const MAX_TOOL_CALLS = 1;

export type PrimeSdkModelCallback = (
  model: unknown,
  context: unknown,
  options: unknown,
) => PrimeSdkAssistantMessageEventStream;

/** The runtime shape of Prime's AssistantMessageEventStream, kept private to its pinned checkout. */
export interface PrimeSdkAssistantMessageEventStream extends AsyncIterable<unknown> {
  result(): Promise<unknown>;
}

export type PrimeSdkIpythonCallback = (
  toolCallId: string,
  input: Readonly<{ code: string }>,
  signal: AbortSignal,
) => Promise<unknown>;

export interface PrimeP1DevelopmentSessionOptions {
  readonly primeSourceRoot: string;
  readonly workspace: string;
  readonly model: PrimeSdkModelCallback;
  readonly ipython: PrimeSdkIpythonCallback;
}

export interface PrimeP1DevelopmentUsage {
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly total_tokens: number;
}

export interface PrimeP1DevelopmentResult {
  readonly lifecycle: "completed" | "cancelled";
  readonly usage: PrimeP1DevelopmentUsage;
  readonly assistant: Readonly<{
    completed: boolean;
    stop_reason: "stop" | "length" | "toolUse" | "error" | "aborted" | null;
  }>;
}

interface PrimeSdkModules {
  readonly createAgentSession: (options: Record<string, unknown>) => Promise<{ session: PrimeSdkSession }>;
  readonly SessionManager: { inMemory(workspace: string): unknown };
  readonly AuthStorage: { inMemory(): { setRuntimeApiKey(provider: string, apiKey: string): void } };
  readonly ModelRegistry: { inMemory(auth: unknown): { registerProvider(provider: string, config: unknown): void; find(provider: string, model: string): unknown } };
  readonly DefaultResourceLoader: new (options: Record<string, unknown>) => { reload(): Promise<void> };
  readonly SettingsManager: { inMemory(settings?: unknown): unknown };
  readonly Type: { Object(properties: Record<string, unknown>): unknown; String(): unknown };
}

interface PrimeSdkSession {
  readonly agent: { readonly state: { readonly messages: readonly unknown[] }; continue(): Promise<void> };
  prompt(prompt: string): Promise<void>;
  waitForIdle(): Promise<void>;
  compact(): Promise<unknown>;
  abort(): Promise<void>;
  disposeAsync(): Promise<void>;
}

/** A deliberately narrow development-only bridge to a caller-owned Prime SDK checkout. */
export class PrimeP1DevelopmentSession {
  private state: "open" | "cancelled" | "closed" = "open";

  private constructor(private readonly session: PrimeSdkSession) {}

  static async open(options: PrimeP1DevelopmentSessionOptions): Promise<PrimeP1DevelopmentSession> {
    if (!isAbsolute(options.primeSourceRoot) || !isAbsolute(options.workspace)) {
      throw new Error("primeSourceRoot and workspace must be absolute paths");
    }
    const modules = await loadPrimeSdk(options.primeSourceRoot);
    const auth = modules.AuthStorage.inMemory();
    // Prime requires a configured model. This fixed marker is in-memory only and
    // is never supplied to a network provider because streamSimple is injected.
    auth.setRuntimeApiKey(PROVIDER, "in-memory-development-provider");
    const registry = modules.ModelRegistry.inMemory(auth);
    let modelCalls = 0;
    let toolCalls = 0;
    registry.registerProvider(PROVIDER, {
      api: "anthropic-messages",
      baseUrl: "http://127.0.0.1:0",
      apiKey: "in-memory-development-provider",
      streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
        if (++modelCalls > MAX_MODEL_CALLS) throw new Error("Prime P1 development model callback limit exceeded");
        const stream = options.model(model, context, streamOptions);
        assertAssistantEventStream(stream);
        return stream;
      },
      models: [{
        id: MODEL, name: MODEL, reasoning: false, input: ["text"],
        contextWindow: 16_384, maxTokens: 4_096,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      }],
    });
    const model = registry.find(PROVIDER, MODEL);
    if (!model) throw new Error("Prime P1 development model registration failed");
    const agentDir = join(options.workspace, ".asterion-prime-p1-development");
    const settingsManager = modules.SettingsManager.inMemory({
      retry: { enabled: false, provider: { maxRetries: 0 } },
      autoRefine: { enabled: false },
    });
    const resourceLoader = new modules.DefaultResourceLoader({
      cwd: options.workspace, agentDir, settingsManager,
      noExtensions: true, noSkills: true, noPromptTemplates: true,
      noThemes: true, noContextFiles: true, bundledSkillsDir: null,
    });
    await resourceLoader.reload();
    const customIpython = {
      name: "ipython",
      description: "Caller-owned IPython execution bridge.",
      label: "ipython",
      parameters: modules.Type.Object({ code: modules.Type.String() }),
      execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
        if (++toolCalls > MAX_TOOL_CALLS) throw new Error("Prime P1 development ipython callback limit exceeded");
        return options.ipython(toolCallId, Object.freeze({ code: input.code }), signal);
      },
    };
    const created = await modules.createAgentSession({
      cwd: options.workspace,
      agentDir,
      authStorage: auth,
      modelRegistry: registry,
      model,
      sessionManager: modules.SessionManager.inMemory(options.workspace),
      settingsManager,
      resourceLoader,
      tools: ["ipython"],
      allowedToolNames: ["ipython"],
      initialActiveToolNames: ["ipython"],
      customTools: [customIpython],
      includeGoals: false,
      includeCompactSkill: false,
      prewarmIpythonKernel: false,
      serializedRefine: true,
      telemetryDisabled: true,
    });
    return new PrimeP1DevelopmentSession(created.session);
  }

  async prompt(prompt: string): Promise<PrimeP1DevelopmentResult> {
    this.assertDispatchable();
    await this.session.prompt(prompt);
    await this.session.waitForIdle();
    for (let continuation = 0; continuation < MAX_MODEL_CALLS - 1; continuation += 1) {
      if (!latestAssistantUsesTool(this.session.agent.state.messages)) break;
      this.assertDispatchable();
      await this.session.agent.continue();
      await this.session.waitForIdle();
    }
    return this.result("completed");
  }

  async compact(): Promise<PrimeP1DevelopmentResult> {
    this.assertDispatchable();
    await this.session.compact();
    return this.result("completed");
  }

  async cancel(): Promise<void> {
    if (this.state === "closed") return;
    this.state = "cancelled";
    await this.session.abort();
  }

  async close(): Promise<void> {
    if (this.state === "closed") return;
    this.state = "closed";
    await this.session.disposeAsync();
  }

  private assertDispatchable(): void {
    if (this.state === "cancelled") throw new Error("Prime P1 development session is cancelled");
    if (this.state === "closed") throw new Error("Prime P1 development session is closed");
  }

  private result(lifecycle: "completed" | "cancelled"): PrimeP1DevelopmentResult {
    const assistants = this.session.agent.state.messages.filter(isAssistant);
    const usage = assistants.reduce((total, message) => ({
      input_tokens: total.input_tokens + numberAt(message, "usage", "input"),
      output_tokens: total.output_tokens + numberAt(message, "usage", "output"),
      total_tokens: total.total_tokens + numberAt(message, "usage", "totalTokens"),
    }), { input_tokens: 0, output_tokens: 0, total_tokens: 0 });
    const latest = assistants.at(-1);
    return {
      lifecycle,
      usage,
      assistant: {
        completed: latest?.stopReason === "stop",
        stop_reason: latest?.stopReason ?? null,
      },
    };
  }
}

async function loadPrimeSdk(root: string): Promise<PrimeSdkModules> {
  const coding = join(root, "packages/coding-agent/dist");
  const required = ["core/sdk.js", "core/session-manager.js", "core/model-registry.js", "core/auth-storage.js", "core/resource-loader.js", "core/settings-manager.js"];
  if (!required.every((path) => existsSync(join(coding, path)))) throw new Error("Prime SDK dist is unavailable at primeSourceRoot");
  const load = (path: string) => import(pathToFileURL(join(coding, path)).href);
  const [sdk, sessions, models, auth, resources, settings, typebox] = await Promise.all([
    load("core/sdk.js"), load("core/session-manager.js"), load("core/model-registry.js"),
    load("core/auth-storage.js"), load("core/resource-loader.js"), load("core/settings-manager.js"),
    import(pathToFileURL(join(root, "node_modules/typebox/build/index.mjs")).href),
  ]);
  return {
    createAgentSession: sdk.createAgentSession,
    SessionManager: sessions.SessionManager,
    ModelRegistry: models.ModelRegistry,
    AuthStorage: auth.AuthStorage,
    DefaultResourceLoader: resources.DefaultResourceLoader,
    SettingsManager: settings.SettingsManager,
    Type: typebox.Type,
  } as PrimeSdkModules;
}

function assertAssistantEventStream(value: unknown): asserts value is { [Symbol.asyncIterator](): AsyncIterator<unknown>; result(): Promise<unknown> } {
  if (!value || typeof value !== "object" || typeof (value as { result?: unknown }).result !== "function" || typeof (value as { [Symbol.asyncIterator]?: unknown })[Symbol.asyncIterator] !== "function") {
    throw new Error("model callback must return a Prime AssistantMessageEventStream");
  }
}

function isAssistant(message: unknown): message is { stopReason?: PrimeP1DevelopmentResult["assistant"]["stop_reason"]; usage?: Record<string, number> } {
  return !!message && typeof message === "object" && (message as { role?: unknown }).role === "assistant";
}

function numberAt(message: { usage?: Record<string, number> }, key: "usage", field: "input" | "output" | "totalTokens"): number {
  const value = message[key]?.[field];
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function latestAssistantUsesTool(messages: readonly unknown[]): boolean {
  const latest = messages.filter(isAssistant).at(-1) as { stopReason?: unknown } | undefined;
  return latest?.stopReason === "toolUse";
}
