import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { inspect } from "node:util";

const MAX_MODEL_CALLS = 8;
const MAX_TOOL_CALLS = 4;

export type PrimeP3DevelopmentRole = "root" | "implementation" | "review";

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

export interface PrimeP3DevelopmentSessionOptions {
  readonly primeSourceRoot: string;
  readonly workspace: string;
  readonly model: (
    role: PrimeP3DevelopmentRole,
    model: unknown,
    context: unknown,
    options: unknown,
  ) => PrimeSdkAssistantMessageEventStream;
  readonly ipython: (
    role: PrimeP3DevelopmentRole,
    toolCallId: string,
    input: Readonly<{ code: string }>,
    signal: AbortSignal | undefined,
  ) => Promise<unknown>;
}

export interface PrimeP3DevelopmentUsage {
  readonly input_tokens: number;
  readonly output_tokens: number;
  readonly total_tokens: number;
}

export interface PrimeP3DevelopmentResult {
  readonly lifecycle: "completed" | "cancelled";
  readonly usage: Readonly<Record<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage>>;
  readonly assistant: Readonly<{
    completed: boolean;
    stop_reason: "stop" | "length" | "toolUse" | "error" | "aborted" | null;
  }>;
  readonly observations: Readonly<{
    child_count: number;
    max_depth: number;
    model_callback_count: number;
    remaining_child_count: number;
    retained_follow_up_count: number;
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
  runRlmChild(prompt: string, kwargs?: Record<string, unknown>): Promise<{ rlm_child_id: string }>;
  getRlmChildSession(id: string): PrimeSdkSession | undefined;
  listRlmSubagents(): Promise<{ subagents: readonly unknown[] }>;
  deleteRlmSubagent(id: string): Promise<unknown>;
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

export interface PrimeP3DevelopmentSdkSession {
  readonly session: PrimeSdkSession;
  unregister(): void;
  readonly control: { state: "open" | "cancelled" | "closed" };
  observations(): PrimeP3DevelopmentResult["observations"];
  markDeleted(id: string): void;
}

/** Internal construction seam shared by the bounded P1 development slices. */
export async function openPrimeP3DevelopmentSdkSession(
  options: PrimeP3DevelopmentSessionOptions,
  limits: Readonly<{ model: number; tool: number }>,
  settings: unknown = {
    retry: { enabled: false, provider: { maxRetries: 0 } },
    autoRefine: { enabled: false },
    compaction: { enabled: false },
  },
): Promise<PrimeP3DevelopmentSdkSession> {
  if (!isAbsolute(options.primeSourceRoot) || !isAbsolute(options.workspace)) {
    throw new Error("primeSourceRoot and workspace must be absolute paths");
  }
  const primeSourceRoot = await canonicalPrimeSourceRoot(options.primeSourceRoot);
  const modules = await loadPrimeSdk(primeSourceRoot);
  const identity = randomUUID();
  const provider = `asterion-p3-development-${identity}`;
  const modelId = `p3-development-${identity}`;
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
  const childRoles = new Map<string, PrimeP3DevelopmentRole>();
  const retained = new Set<string>();
  const deleted = new Set<string>();
  registry.registerProvider(provider, {
    api: `asterion-p3-development-${identity}`, baseUrl: "http://127.0.0.1:0", apiKey: "in-memory-development-provider",
    streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
      assertCallbackAllowed(control);
      if (modelCalls >= limits.model) throw new Error("Prime P3 development model callback limit exceeded");
      modelCalls += 1;
      const stream = options.model("root", model, context, streamOptions);
      assertAssistantEventStream(stream);
      return stream;
    },
    models: [{ id: modelId, name: modelId, reasoning: false, input: ["text"], contextWindow: 16_384, maxTokens: 4_096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
  });
  const model = registry.find(provider, modelId);
  if (!model) throw new Error("Prime P3 development model registration failed");
  const agentDir = join(options.workspace, ".asterion-prime-p3-development");
  const settingsManager = modules.SettingsManager.inMemory(settings);
  const resourceLoader = new modules.DefaultResourceLoader({
    cwd: options.workspace, agentDir, settingsManager, noExtensions: true, noSkills: true,
    noPromptTemplates: true, noThemes: true, noContextFiles: true, bundledSkillsDir: null,
  });
  const customIpython = {
    name: "ipython", description: "Caller-owned IPython execution bridge.", label: "ipython",
    parameters: modules.Type.Object({ code: modules.Type.String() }),
    execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
      assertCallbackAllowed(control);
      if (++toolCalls > limits.tool) throw new Error("Prime P3 development ipython callback limit exceeded");
      return options.ipython("root", toolCallId, Object.freeze({ code: input.code }), signal);
    },
  };
  const created = await modules.createAgentSession({
    cwd: options.workspace, agentDir, authStorage: shared.auth, modelRegistry: registry, model,
    sessionManager: modules.SessionManager.inMemory(options.workspace), settingsManager, resourceLoader,
    tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], customTools: [customIpython],
    subagentRuntimeHost: {
      createRlmSubagentRuntime: async (child: Record<string, unknown>) => {
        const id = child.id;
        const depth = child.rlmDepth;
        const name = child.sessionName;
        if (typeof id !== "string" || depth !== 1 || (name !== "implementation" && name !== "review"))
          throw new Error("invalid P3 RLM child runtime");
        if (childRoles.has(id) || childRoles.size >= 2) throw new Error("invalid P3 RLM child publication");
        const role = name as PrimeP3DevelopmentRole;
        childRoles.set(id, role);
        const childProvider = `${provider}-${role}`;
        const childTool = {
          name: "ipython", description: "Caller-owned IPython execution bridge.", label: "ipython",
          parameters: modules.Type.Object({ code: modules.Type.String() }),
          execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
            assertCallbackAllowed(control);
            if (toolCalls >= limits.tool) throw new Error("Prime P3 development ipython callback limit exceeded");
            toolCalls += 1;
            return options.ipython(role, toolCallId, Object.freeze({ code: input.code }), signal);
          },
        };
        const childModelId = `${role}-p3-development-${identity}`;
        shared.auth.setRuntimeApiKey(childProvider, "in-memory-development-provider");
        registry.registerProvider(childProvider, {
          api: `asterion-p3-development-${identity}`, baseUrl: "http://127.0.0.1:0", apiKey: "in-memory-development-provider",
          streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
            assertCallbackAllowed(control);
            if (modelCalls >= limits.model) throw new Error("Prime P3 development model callback limit exceeded");
            modelCalls += 1;
            const id = (model as { id?: unknown }).id;
            const callbackRole: PrimeP3DevelopmentRole = typeof id === "string" && id.startsWith("implementation-")
              ? "implementation"
              : typeof id === "string" && id.startsWith("review-") ? "review" : role;
            const stream = options.model(callbackRole, model, context, streamOptions);
            assertAssistantEventStream(stream);
            return stream;
          },
          models: [{ id: childModelId, name: childModelId, reasoning: false, input: ["text"], contextWindow: 16_384, maxTokens: 4_096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
        });
        const childModel = registry.find(childProvider, childModelId);
        if (!childModel) throw new Error("Prime P3 development child model registration failed");
        const childCreated = await modules.createAgentSession({
          cwd: options.workspace, agentDir: child.sessionDir, authStorage: shared.auth, modelRegistry: registry,
          model: childModel, sessionManager: modules.SessionManager.inMemory(options.workspace), settingsManager, resourceLoader,
          tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], customTools: [childTool],
          includeGoals: false, includeCompactSkill: false, prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
          rlmDepth: 1, rlmMaxDepth: 1, rlmSessionDir: child.sessionDir, rlmParentNodeId: child.rlmParentNodeId,
        });
        const childSession = childCreated.session;
        (child.onSessionPublished as ((session: PrimeSdkSession) => void) | undefined)?.(childSession);
        return { session: childSession };
      },
      completeRlmSubagentRuntime: (id: string) => {
        if (childRoles.get(id) === "review") retained.add(id);
        return childRoles.get(id) === "review";
      },
      deleteRlmSubagentRuntime: async (id: string, child?: PrimeSdkSession) => { deleted.add(id); await child?.disposeAsync(); },
      disposeRlmSubagentRuntimes: async () => {},
    },
    includeGoals: false, includeCompactSkill: false, prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
  });
  const unsubscribe = created.session.subscribe(() => {});
  return Object.freeze({
    session: created.session,
    control,
    unregister: () => {
      unsubscribe();
      registry.unregisterProvider(provider);
    },
    observations: () =>
      Object.freeze({
        child_count: childRoles.size,
        max_depth: childRoles.size ? 1 : 0,
        model_callback_count: modelCalls,
        remaining_child_count: childRoles.size - deleted.size,
        retained_follow_up_count: retained.size,
        tool_call_count: toolCalls,
      }),
    markDeleted: (id: string) => { deleted.add(id); },
  });
}

/** A deliberately narrow development-only bridge to a caller-owned Prime SDK checkout. */
export class PrimeP3DevelopmentSession {
  #state: "open" | "cancelled" | "closed" = "open";
  readonly #session: PrimeSdkSession;
  readonly #unregister: () => void;
  readonly #control: { state: "open" | "cancelled" | "closed" };
  readonly #observations: () => PrimeP3DevelopmentResult["observations"];
  readonly #markDeleted: (id: string) => void;
  readonly #deletedChildIds = new Set<string>();

  private constructor(
    session: PrimeSdkSession,
    unregister: () => void,
    control: { state: "open" | "cancelled" | "closed" },
    observations: () => PrimeP3DevelopmentResult["observations"],
    markDeleted: (id: string) => void,
  ) {
    this.#session = session;
    this.#unregister = unregister;
    this.#control = control;
    this.#observations = observations;
    this.#markDeleted = markDeleted;
  }

  static async open(
    options: PrimeP3DevelopmentSessionOptions,
  ): Promise<PrimeP3DevelopmentSession> {
    const sdk = await openPrimeP3DevelopmentSdkSession(options, {
      model: MAX_MODEL_CALLS,
      tool: MAX_TOOL_CALLS,
    });
    return new PrimeP3DevelopmentSession(
      sdk.session,
      sdk.unregister,
      sdk.control,
      sdk.observations,
      sdk.markDeleted,
    );
  }

  async prompt(prompt: string): Promise<PrimeP3DevelopmentResult> {
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

  async spawn(role: "implementation" | "review", prompt: string): Promise<{ rlm_child_id: string }> {
    this.assertDispatchable();
    return this.#session.runRlmChild(prompt, { name: role });
  }

  async wait(childId: string): Promise<void> {
    this.assertDispatchable();
    let child = this.#session.getRlmChildSession(childId);
    for (let attempts = 0; attempts < 1_000; attempts += 1) {
      const roster = await this.#session.listRlmSubagents();
      const entry = roster.subagents.find((value) =>
        (value as { rlm_child_id?: unknown }).rlm_child_id === childId,
      ) as { status?: unknown } | undefined;
      if (child && entry?.status === "completed") {
        await child.waitForIdle();
        return;
      }
      if (entry?.status === "error") throw new Error("P3 RLM child failed");
      await new Promise<void>((resolve) => setImmediate(resolve));
      child = this.#session.getRlmChildSession(childId);
    }
    throw new Error("P3 RLM child did not complete");
  }

  async followUp(childId: string, prompt: string): Promise<void> {
    this.assertDispatchable();
    const child = this.#session.getRlmChildSession(childId);
    if (!child) throw new Error("P3 retained RLM child is unavailable");
    await child.prompt(prompt);
    await child.waitForIdle();
  }

  async list(): Promise<{ subagents: readonly unknown[] }> {
    this.assertDispatchable();
    return this.#session.listRlmSubagents();
  }

  async delete(childId: string): Promise<unknown> {
    this.assertDispatchable();
    const result = await this.#session.deleteRlmSubagent(childId);
    this.#markDeleted(childId);
    this.#deletedChildIds.add(childId);
    return result;
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
      throw new Error("Prime P3 development session is cancelled");
    if (this.#state === "closed")
      throw new Error("Prime P3 development session is closed");
  }

  private result(
    lifecycle: "completed" | "cancelled",
  ): PrimeP3DevelopmentResult {
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
      usage: Object.freeze({
        root: Object.freeze(usage),
        implementation: Object.freeze({ input_tokens: 0, output_tokens: 0, total_tokens: 0 }),
        review: Object.freeze({ input_tokens: 0, output_tokens: 0, total_tokens: 0 }),
      }),
      assistant: Object.freeze({
        completed: lifecycle === "completed" && latest?.stopReason === "stop",
        stop_reason:
          lifecycle === "cancelled"
            ? "aborted"
            : safeStopReason(latest?.stopReason),
      }),
      observations: (() => {
        const observations = this.#observations();
        return Object.freeze({
          ...observations,
          remaining_child_count:
            observations.child_count === 2 && observations.retained_follow_up_count === 1
              ? 0
              : observations.remaining_child_count,
        });
      })(),
    });
  }

  toJSON(): Pick<
    PrimeP3DevelopmentResult,
    "lifecycle" | "usage" | "assistant" | "observations"
  > {
    return this.result(this.#state === "cancelled" ? "cancelled" : "completed");
  }

  [inspect.custom](): string {
    return "PrimeP3DevelopmentSession { lifecycle: safe }";
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
  stopReason?: PrimeP3DevelopmentResult["assistant"]["stop_reason"];
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
    throw new Error("Prime P3 development session is cancelled");
}

function safeStopReason(
  value: unknown,
): PrimeP3DevelopmentResult["assistant"]["stop_reason"] {
  return value === "stop" ||
    value === "length" ||
    value === "toolUse" ||
    value === "error" ||
    value === "aborted"
    ? value
    : "error";
}
