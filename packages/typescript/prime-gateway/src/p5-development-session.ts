import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { inspect } from "node:util";

const MAX_MODEL_CALLS = 4;
const MAX_TOOL_CALLS = 2;

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
  signal: AbortSignal | undefined,
) => Promise<unknown>;

export interface PrimeP5DevelopmentSessionOptions {
  readonly primeSourceRoot: string;
  readonly workspace: string;
  readonly model: PrimeSdkModelCallback;
  readonly ipython: PrimeSdkIpythonCallback;
}

export interface PrimeP5DevelopmentUsage {
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly total_tokens: number;
}

export interface PrimeP5DevelopmentResult {
  readonly lifecycle: "completed" | "cancelled";
  readonly usage: PrimeP5DevelopmentUsage;
  readonly assistant: Readonly<{
    completed: boolean;
    stop_reason: "stop" | "length" | "toolUse" | "error" | "aborted" | null;
  }>;
  readonly observations: Readonly<{
    active_tool_names: readonly string[];
    compact_count: number;
    model_callback_count: number;
    rlm_child_count: number;
    tool_call_count: number;
  }>;
}

interface PrimeSdkModules {
  readonly createAgentSession: (
    options: Record<string, unknown>,
  ) => Promise<{ session: PrimeSdkSession }>;
  readonly SessionManager: { inMemory(workspace: string): unknown };
  readonly AuthStorage: {
    inMemory(): { setRuntimeApiKey(provider: string, apiKey: string): void };
  };
  readonly ModelRegistry: {
    inMemory(auth: unknown): {
      registerProvider(provider: string, config: unknown): void;
      unregisterProvider(provider: string): void;
      find(provider: string, model: string): unknown;
    };
  };
  readonly DefaultResourceLoader: new (options: Record<string, unknown>) => {
    reload(): Promise<void>;
  };
  readonly SettingsManager: { inMemory(settings?: unknown): unknown };
  readonly Type: {
    Object(properties: Record<string, unknown>): unknown;
    String(): unknown;
  };
}

export interface PrimeSdkSession {
  readonly agent: { readonly state: { readonly messages: readonly unknown[] } };
  readonly sessionManager: {
    getEntries(): readonly { readonly id?: unknown; readonly type?: unknown }[];
  };
  getActiveToolNames(): string[];
  prompt(prompt: string): Promise<void>;
  waitForIdle(): Promise<void>;
  compact(): Promise<unknown>;
  requestAbort(): void;
  abort(): Promise<void>;
  disposeAsync(): Promise<void>;
  subscribe(listener: (event: unknown) => void): () => void;
}
type PrimeSdkRegistry = {
  registerProvider(provider: string, config: unknown): void;
  unregisterProvider(provider: string): void;
  find(provider: string, model: string): unknown;
};
type SharedRegistry = {
  auth: { setRuntimeApiKey(provider: string, apiKey: string): void };
  registry: PrimeSdkRegistry;
};
const sharedRegistries = new Map<string, SharedRegistry>();

export interface PrimeP5DevelopmentSdkSession {
  readonly session: PrimeSdkSession;
  unregister(): void;
  readonly control: { state: "open" | "cancelled" | "closed" };
  observations(): PrimeP5DevelopmentResult["observations"];
}

/** Internal construction seam for P5's bounded repair session. */
export async function openPrimeP5DevelopmentSdkSession(
  options: PrimeP5DevelopmentSessionOptions,
  limits: Readonly<{ model: number; tool: number }>,
  settings: unknown = {
    retry: { enabled: false, provider: { maxRetries: 0 } },
    autoRefine: { enabled: false },
    compaction: { enabled: false },
  },
): Promise<PrimeP5DevelopmentSdkSession> {
  if (!isAbsolute(options.primeSourceRoot) || !isAbsolute(options.workspace)) {
    throw new Error("primeSourceRoot and workspace must be absolute paths");
  }
  const primeSourceRoot = await canonicalPrimeSourceRoot(options.primeSourceRoot);
  const modules = await loadPrimeSdk(primeSourceRoot);
  const identity = randomUUID();
  const provider = `asterion-p5-development-${identity}`;
  const modelId = `p5-development-${identity}`;
  const control: { state: "open" | "cancelled" | "closed" } = { state: "open" };
  let shared = sharedRegistries.get(primeSourceRoot);
  if (!shared) {
    const auth = modules.AuthStorage.inMemory();
    shared = { auth, registry: modules.ModelRegistry.inMemory(auth) };
    sharedRegistries.set(primeSourceRoot, shared);
  }
  shared.auth.setRuntimeApiKey(provider, "in-memory-development-provider");
  const registry = shared.registry;
  let modelCalls = 0;
  let toolCalls = 0;
  registry.registerProvider(provider, {
    api: `asterion-p5-development-${identity}`, baseUrl: "http://127.0.0.1:0", apiKey: "in-memory-development-provider",
    streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
      assertCallbackAllowed(control);
      if (++modelCalls > limits.model) throw new Error("Prime P5 development model callback limit exceeded");
      const stream = options.model(model, context, streamOptions);
      assertAssistantEventStream(stream);
      return stream;
    },
    models: [{ id: modelId, name: modelId, reasoning: false, input: ["text"], contextWindow: 16_384, maxTokens: 4_096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
  });
  const model = registry.find(provider, modelId);
  if (!model) throw new Error("Prime P5 development model registration failed");
  const agentDir = join(options.workspace, ".asterion-prime-p5-development");
  const settingsManager = modules.SettingsManager.inMemory(settings);
  const resourceLoader = new modules.DefaultResourceLoader({
    cwd: options.workspace, agentDir, settingsManager, noExtensions: true, noSkills: true,
    noPromptTemplates: true, noThemes: true, noContextFiles: true, bundledSkillsDir: null,
  });
  const customIpython = {
    name: "ipython", description: "P5 bounded-stage IPython bridge. The prompt supplies the fixed paths and known bytes. This one call must complete the required P5 filesystem mutation; do not spend it on inspection, printing, validation, or subprocess execution.", label: "ipython",
    parameters: modules.Type.Object({ code: modules.Type.String() }),
    execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
      assertCallbackAllowed(control);
      if (++toolCalls > limits.tool) throw new Error("Prime P5 development ipython callback limit exceeded");
      return options.ipython(toolCallId, Object.freeze({ code: input.code }), signal);
    },
  };
  const created = await modules.createAgentSession({
    cwd: options.workspace, agentDir, authStorage: shared.auth, modelRegistry: registry, model,
    sessionManager: modules.SessionManager.inMemory(options.workspace), settingsManager, resourceLoader,
    tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], customTools: [customIpython],
    includeGoals: false, includeCompactSkill: false, prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
  });
  let compactCount = 0;
  const childIds = new Set<string>();
  const unsubscribe = created.session.subscribe((event: unknown) => {
    if (!event || typeof event !== "object") return;
    const value = event as {
      type?: unknown;
      child?: { id?: unknown };
    };
    if (value.type === "compaction_start") compactCount += 1;
    if (
      value.type === "rlm_child_update" &&
      typeof value.child?.id === "string"
    )
      childIds.add(value.child.id);
  });
  return Object.freeze({
    session: created.session,
    control,
    unregister: () => {
      unsubscribe();
      registry.unregisterProvider(provider);
    },
    observations: () =>
      Object.freeze({
        active_tool_names: Object.freeze(
          [...created.session.getActiveToolNames()].sort(),
        ),
        compact_count: compactCount,
        model_callback_count: modelCalls,
        rlm_child_count: childIds.size,
        tool_call_count: toolCalls,
      }),
  });
}

/** A deliberately narrow development-only bridge to a caller-owned Prime SDK checkout. */
export class PrimeP5DevelopmentSession {
  #state: "open" | "cancelled" | "closed" = "open";
  readonly #session: PrimeSdkSession;
  readonly #unregister: () => void;
  readonly #control: { state: "open" | "cancelled" | "closed" };
  readonly #observations: () => PrimeP5DevelopmentResult["observations"];

  private constructor(
    session: PrimeSdkSession,
    unregister: () => void,
    control: { state: "open" | "cancelled" | "closed" },
    observations: () => PrimeP5DevelopmentResult["observations"],
  ) {
    this.#session = session;
    this.#unregister = unregister;
    this.#control = control;
    this.#observations = observations;
  }

  static async open(
    options: PrimeP5DevelopmentSessionOptions,
  ): Promise<PrimeP5DevelopmentSession> {
    const sdk = await openPrimeP5DevelopmentSdkSession(options, {
      model: MAX_MODEL_CALLS,
      tool: MAX_TOOL_CALLS,
    });
    return new PrimeP5DevelopmentSession(
      sdk.session,
      sdk.unregister,
      sdk.control,
      sdk.observations,
    );
  }

  async prompt(prompt: string): Promise<PrimeP5DevelopmentResult> {
    this.assertDispatchable();
    await this.#session.prompt(prompt);
    await this.#session.waitForIdle();
    if (this.#state !== "open") return this.result("cancelled");
    return this.result("completed");
  }

  async cancel(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "cancelled";
    this.#control.state = "cancelled";
    this.#session.requestAbort();
  }

  async close(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "closed";
    this.#control.state = "closed";
    try {
      await this.#session.disposeAsync();
    } finally {
      this.#unregister();
    }
  }

  private assertDispatchable(): void {
    if (this.#state === "cancelled")
      throw new Error("Prime P5 development session is cancelled");
    if (this.#state === "closed")
      throw new Error("Prime P5 development session is closed");
  }

  private result(
    lifecycle: "completed" | "cancelled",
  ): PrimeP5DevelopmentResult {
    const assistants = this.#session.agent.state.messages.filter(isAssistant);
    const usage = assistants.reduce(
      (total, message) => ({
        input_tokens: total.input_tokens + numberAt(message, "usage", "input"),
        output_tokens:
          total.output_tokens + numberAt(message, "usage", "output"),
        total_tokens:
          total.total_tokens + numberAt(message, "usage", "totalTokens"),
      }),
      { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
    );
    const latest = assistants.at(-1);
    return Object.freeze({
      lifecycle,
      usage: Object.freeze(usage),
      assistant: Object.freeze({
        completed: lifecycle === "completed" && latest?.stopReason === "stop",
        stop_reason:
          lifecycle === "cancelled"
            ? "aborted"
            : safeStopReason(latest?.stopReason),
      }),
      observations: this.#observations(),
    });
  }

  toJSON(): Pick<
    PrimeP5DevelopmentResult,
    "lifecycle" | "usage" | "assistant" | "observations"
  > {
    return this.result(this.#state === "cancelled" ? "cancelled" : "completed");
  }

  [inspect.custom](): string {
    return "PrimeP5DevelopmentSession { lifecycle: safe }";
  }
}

async function loadPrimeSdk(root: string): Promise<PrimeSdkModules> {
  const coding = join(root, "packages/coding-agent/dist");
  const required = [
    "core/sdk.js",
    "core/session-manager.js",
    "core/model-registry.js",
    "core/auth-storage.js",
    "core/resource-loader.js",
    "core/settings-manager.js",
  ];
  if (!required.every((path) => existsSync(join(coding, path))))
    throw new Error("Prime SDK dist is unavailable at primeSourceRoot");
  const load = (path: string) => import(pathToFileURL(join(coding, path)).href);
  const [sdk, sessions, models, auth, resources, settings, typebox] =
    await Promise.all([
      load("core/sdk.js"),
      load("core/session-manager.js"),
      load("core/model-registry.js"),
      load("core/auth-storage.js"),
      load("core/resource-loader.js"),
      load("core/settings-manager.js"),
      import(
        pathToFileURL(join(root, "node_modules/typebox/build/index.mjs")).href
      ),
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

async function canonicalPrimeSourceRoot(root: string): Promise<string> {
  try {
    return await realpath(root);
  } catch {
    throw new Error("Prime SDK source root is unavailable");
  }
}

function assertAssistantEventStream(
  value: unknown,
): asserts value is {
  [Symbol.asyncIterator](): AsyncIterator<unknown>;
  result(): Promise<unknown>;
} {
  if (
    !value ||
    typeof value !== "object" ||
    typeof (value as { result?: unknown }).result !== "function" ||
    typeof (value as { [Symbol.asyncIterator]?: unknown })[
      Symbol.asyncIterator
    ] !== "function"
  ) {
    throw new Error(
      "model callback must return a Prime AssistantMessageEventStream",
    );
  }
}

function isAssistant(
  message: unknown,
): message is {
  stopReason?: PrimeP5DevelopmentResult["assistant"]["stop_reason"];
  usage?: Record<string, number>;
} {
  return (
    !!message &&
    typeof message === "object" &&
    (message as { role?: unknown }).role === "assistant"
  );
}

function numberAt(
  message: { usage?: Record<string, number> },
  key: "usage",
  field: "input" | "output" | "totalTokens",
): number {
  const value = message[key]?.[field];
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : 0;
}

function assertCallbackAllowed(control: {
  state: "open" | "cancelled" | "closed";
}): void {
  if (control.state !== "open")
    throw new Error("Prime P5 development session is cancelled");
}

function safeStopReason(
  value: unknown,
): PrimeP5DevelopmentResult["assistant"]["stop_reason"] {
  return value === "stop" ||
    value === "length" ||
    value === "toolUse" ||
    value === "error" ||
    value === "aborted"
    ? value
    : "error";
}
