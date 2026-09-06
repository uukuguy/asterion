import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { realpath } from "node:fs/promises";
import { isAbsolute, join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { inspect } from "node:util";

const MAX_MODEL_CALLS = 10;
const MAX_TOOL_CALLS = 4;
const CHILD_WAIT_DEADLINE_MS = 60_000;
const CHILD_WAIT_POLL_MS = 20;

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
  runRlmChild(
    prompt: string,
    kwargs?: Record<string, unknown>,
  ): Promise<{ readonly rlm_child_id: string; readonly [key: string]: unknown }>;
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
  readonly childSessions: ReadonlyMap<string, PrimeSdkSession>;
  readonly childRoles: ReadonlyMap<string, Exclude<PrimeP3DevelopmentRole, "root">>;
  readonly childSelectors: Readonly<Record<"implementation" | "review", string>>;
  roleModelCalls(): Readonly<Record<PrimeP3DevelopmentRole, number>>;
  roleUsage(): Promise<Readonly<Record<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage>>>;
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
  const providers = Object.freeze({
    root: `asterion-p3-root-${identity}`,
    implementation: `asterion-p3-implementation-${identity}`,
    review: `asterion-p3-review-${identity}`,
  });
  const modelIds = Object.freeze({ root: `root-${identity}`, implementation: `implementation-${identity}`, review: `review-${identity}` });
  const control: { state: "open" | "cancelled" | "closed" } = { state: "open" };
  let shared = sharedRegistries.get(primeSourceRoot);
  if (!shared) {
    const auth = modules.AuthStorage.inMemory();
    shared = { auth, registry: modules.ModelRegistry.inMemory(auth) };
    sharedRegistries.set(primeSourceRoot, shared);
  }
  const registry = shared.registry;
  const modelCalls: Record<PrimeP3DevelopmentRole, number> = { root: 0, implementation: 0, review: 0 };
  const streamedUsage: Record<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage> = {
    root: { input_tokens: 0, output_tokens: 0, total_tokens: 0 }, implementation: { input_tokens: 0, output_tokens: 0, total_tokens: 0 }, review: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  };
  const usageSettled: Promise<void>[] = [];
  let toolCalls = 0;
  const childRoles = new Map<string, Exclude<PrimeP3DevelopmentRole, "root">>();
  const childSessions = new Map<string, PrimeSdkSession>();
  const deleted = new Set<string>();
  let rootSession: PrimeSdkSession | undefined;
  const register = (role: PrimeP3DevelopmentRole) => {
    const provider = providers[role], modelId = modelIds[role];
    shared.auth.setRuntimeApiKey(provider, "in-memory-development-provider");
    registry.registerProvider(provider, {
    api: `asterion-p3-${role}-${identity}`, baseUrl: "http://127.0.0.1:0", apiKey: "in-memory-development-provider",
    streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
      assertCallbackAllowed(control);
      if (modelCalls[role] >= ({ root: 4, implementation: 2, review: 4 } as const)[role]) throw new Error("Prime P3 role callback limit exceeded");
      modelCalls[role] += 1;
      const stream = options.model(role, model, context, streamOptions);
      assertAssistantEventStream(stream);
      usageSettled.push(stream.result().then((message) => {
        const usage = usageFromMessage(message);
        streamedUsage[role] = addUsage(streamedUsage[role], usage);
      }));
      return stream;
    },
    models: [{ id: modelId, name: modelId, reasoning: false, input: ["text"], contextWindow: 16_384, maxTokens: 4_096, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
  });
  };
  register("root"); register("implementation"); register("review");
  const model = registry.find(providers.root, modelIds.root);
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
      if (toolCalls >= limits.tool) throw new Error("Prime P3 development ipython callback limit exceeded");
      toolCalls += 1;
      return options.ipython("root", toolCallId, Object.freeze({ code: input.code }), signal);
    },
  };
  const created = await modules.createAgentSession({
    cwd: options.workspace, agentDir, authStorage: shared.auth, modelRegistry: registry, model,
    sessionManager: modules.SessionManager.inMemory(options.workspace), settingsManager, resourceLoader,
    tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], customTools: [customIpython],
    rlmDepth: 0, rlmMaxDepth: 1, rlmSessionDir: agentDir,
    subagentRuntimeHost: {
      createRlmSubagentRuntime: async (child: Record<string, unknown>) => {
        const id = child.id;
        const depth = child.rlmDepth;
        const name = child.sessionName;
        const role = name as Exclude<PrimeP3DevelopmentRole, "root">;
        if (typeof id !== "string" || depth !== 1 || (name !== "implementation" && name !== "review") ||
          child.parentSession !== rootSession || child.rlmParentNodeId !== id ||
          !exactRoleModel(child.model, modelIds[role]) ||
          !privateChildSessionDir(child.sessionDir, agentDir) ||
          !onlyIpython(child.activeToolNames) || !onlyIpython(child.allowedToolNames) ||
          !Array.isArray(child.customTools) || child.customTools.length !== 1 ||
          (child.customTools[0] as { name?: unknown }).name !== "ipython")
          throw new Error("invalid P3 RLM child runtime");
        if (childRoles.has(id) || [...childRoles.values()].includes(name as Exclude<PrimeP3DevelopmentRole, "root">) || childRoles.size >= 2) throw new Error("invalid P3 RLM child publication");
        childRoles.set(id, role);
        const inherited = child.customTools[0] as Record<string, unknown>;
        const childTool = Object.freeze({
          ...inherited,
          execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
            assertCallbackAllowed(control);
            if (toolCalls >= limits.tool) throw new Error("Prime P3 development ipython callback limit exceeded");
            toolCalls += 1;
            return options.ipython(role, toolCallId, Object.freeze({ code: input.code }), signal);
          },
        });
        const childSettings = modules.SettingsManager.inMemory(settings);
        const childLoader = new modules.DefaultResourceLoader({
          cwd: child.sessionDir as string, agentDir: child.sessionDir as string, settingsManager: childSettings,
          noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
          noContextFiles: true, bundledSkillsDir: null,
        });
        await childLoader.reload();
        const childCreated = await modules.createAgentSession({
          cwd: options.workspace, agentDir: child.sessionDir as string, authStorage: shared.auth, modelRegistry: registry,
          model: child.model, sessionManager: modules.SessionManager.inMemory(child.sessionDir as string), settingsManager: childSettings, resourceLoader: childLoader,
          initialActiveToolNames: child.activeToolNames, allowedToolNames: child.allowedToolNames, customTools: [childTool],
          includeGoals: child.includeGoals, includeCompactSkill: child.includeCompactSkill, thinkingLevel: child.thinkingLevel,
          serviceTier: child.serviceTier, scopedModels: child.scopedModels, prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
          rlmDepth: child.rlmDepth, rlmMaxDepth: child.rlmMaxDepth, rlmSessionDir: child.sessionDir, rlmParentNodeId: child.rlmParentNodeId,
        });
        const childSession = childCreated.session;
        childSessions.set(id, childSession);
        (child.onSessionPublished as ((session: PrimeSdkSession) => void) | undefined)?.(childSession);
        return { session: childSession };
      },
      completeRlmSubagentRuntime: () => true,
      deleteRlmSubagentRuntime: async (id: string, child?: PrimeSdkSession) => { await child?.disposeAsync(); deleted.add(id); childSessions.delete(id); },
      disposeRlmSubagentRuntimes: async () => {},
    },
    includeGoals: false, includeCompactSkill: false, prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
  });
  rootSession = created.session;
  const unsubscribe = created.session.subscribe(() => {});
  return Object.freeze({
    session: created.session,
    control,
    unregister: () => {
      unsubscribe();
      for (const provider of Object.values(providers)) registry.unregisterProvider(provider);
    },
    observations: () =>
      Object.freeze({
        child_count: childRoles.size,
        max_depth: childRoles.size ? 1 : 0,
        model_callback_count: modelCalls.root + modelCalls.implementation + modelCalls.review,
        remaining_child_count: childRoles.size - deleted.size,
        retained_follow_up_count: 0,
        tool_call_count: toolCalls,
      }),
    childSessions, childRoles,
    childSelectors: Object.freeze({ implementation: `${providers.implementation}/${modelIds.implementation}`, review: `${providers.review}/${modelIds.review}` }),
    roleModelCalls: () => Object.freeze({ ...modelCalls }),
    roleUsage: async () => { await Promise.all(usageSettled); return Object.freeze({ ...streamedUsage }); },
  });
}

/** A deliberately narrow development-only bridge to a caller-owned Prime SDK checkout. */
export class PrimeP3DevelopmentSession {
  #state: "open" | "cancelled" | "closed" = "open";
  readonly #session: PrimeSdkSession;
  readonly #unregister: () => void;
  readonly #control: { state: "open" | "cancelled" | "closed" };
  readonly #observations: () => PrimeP3DevelopmentResult["observations"];
  readonly #childSessions: ReadonlyMap<string, PrimeSdkSession>;
  readonly #childRoles: ReadonlyMap<string, Exclude<PrimeP3DevelopmentRole, "root">>;
  readonly #childSelectors: Readonly<Record<"implementation" | "review", string>>;
  readonly #roleModelCalls: () => Readonly<Record<PrimeP3DevelopmentRole, number>>;
  readonly #roleUsage: () => Promise<Readonly<Record<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage>>>;
  readonly #usageByRole = new Map<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage>();
  #followedUpReview: string | undefined;

  private constructor(
    session: PrimeSdkSession,
    unregister: () => void,
    control: { state: "open" | "cancelled" | "closed" },
    observations: () => PrimeP3DevelopmentResult["observations"],
    childSessions: ReadonlyMap<string, PrimeSdkSession>,
    childRoles: ReadonlyMap<string, Exclude<PrimeP3DevelopmentRole, "root">>,
    childSelectors: Readonly<Record<"implementation" | "review", string>>,
    roleModelCalls: () => Readonly<Record<PrimeP3DevelopmentRole, number>>,
    roleUsage: () => Promise<Readonly<Record<PrimeP3DevelopmentRole, PrimeP3DevelopmentUsage>>>,
  ) {
    this.#session = session;
    this.#unregister = unregister;
    this.#control = control;
    this.#observations = observations;
    this.#childSessions = childSessions;
    this.#childRoles = childRoles;
    this.#childSelectors = childSelectors;
    this.#roleModelCalls = roleModelCalls;
    this.#roleUsage = roleUsage;
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
      sdk.childSessions,
      sdk.childRoles,
      sdk.childSelectors,
      sdk.roleModelCalls,
      sdk.roleUsage,
    );
  }

  async prompt(prompt: string): Promise<PrimeP3DevelopmentResult> {
    this.assertDispatchable();
    await this.#session.prompt(prompt);
    await this.#session.waitForIdle();
    if (this.#state !== "open") return this.result("cancelled");
    return this.completedResult();
  }

  async cancel(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "cancelled";
    this.#control.state = "cancelled";
    this.#session.requestAbort();
    await this.#session.abort();
    await this.cleanupChildren();
  }

  async spawn(role: "implementation" | "review", prompt: string): Promise<{ rlm_child_id: string }> {
    this.assertDispatchable();
    if ([...this.#childRoles.values()].includes(role)) throw new Error("P3 child role already exists");
    const child = await this.#session.runRlmChild(prompt, { name: role, model: this.#childSelectors[role] });
    return Object.freeze({ rlm_child_id: child.rlm_child_id });
  }

  async wait(childId: string): Promise<void> {
    this.assertDispatchable();
    const role = this.#childRoles.get(childId);
    if (!role) throw new Error("P3 RLM child identity is unavailable");
    const deadline = Date.now() + CHILD_WAIT_DEADLINE_MS;
    while (Date.now() < deadline) {
      this.assertDispatchable();
      const child = this.#session.getRlmChildSession(childId);
      if (!child || child !== this.#childSessions.get(childId) || this.#childRoles.get(childId) !== role)
        throw new Error("P3 RLM child identity is unavailable");
      const roster = await this.#session.listRlmSubagents();
      const entries = roster.subagents.filter((value) =>
        (value as { rlm_child_id?: unknown }).rlm_child_id === childId,
      ) as { status?: unknown }[];
      if (entries.length !== 1) throw new Error("P3 RLM child identity is unavailable");
      if (entries[0]?.status === "completed") {
        await child.waitForIdle();
        return;
      }
      if (entries[0]?.status === "error" || entries[0]?.status === "cancelled")
        throw new Error("P3 RLM child failed");
      await delay(CHILD_WAIT_POLL_MS);
    }
    throw new Error("P3 RLM child did not complete");
  }

  async followUp(childId: string, prompt: string): Promise<void> {
    this.assertDispatchable();
    if (this.#childRoles.get(childId) !== "review" || this.#followedUpReview !== undefined)
      throw new Error("P3 follow-up requires the retained review child");
    const child = this.#session.getRlmChildSession(childId);
    if (!child || child !== this.#childSessions.get(childId)) throw new Error("P3 retained RLM child is unavailable");
    await child.prompt(prompt);
    await child.waitForIdle();
    if (latestAssistant(child).stopReason !== "stop")
      throw new Error("P3 review follow-up did not complete");
    this.#usageByRole.set("review", usageOf(child));
    this.#followedUpReview = childId;
  }

  async list(): Promise<{ subagents: readonly unknown[] }> {
    this.assertDispatchable();
    return this.#session.listRlmSubagents();
  }

  async delete(childId: string): Promise<unknown> {
    this.assertDispatchable();
    const role = this.#childRoles.get(childId);
    const child = this.#childSessions.get(childId);
    if (!role || !child) throw new Error("P3 child deletion target is unavailable");
    this.#usageByRole.set(role, usageOf(child));
    const result = await this.#session.deleteRlmSubagent(childId);
    if (!(result && typeof result === "object")) throw new Error("P3 child deletion failed");
    return result;
  }

  async close(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "closed";
    this.#control.state = "closed";
    try {
      await this.cleanupChildren();
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
          retained_follow_up_count: this.#followedUpReview === undefined ? 0 : 1,
        });
      })(),
    });
  }

  private async completedResult(): Promise<PrimeP3DevelopmentResult> {
    const roleUsage = await this.#roleUsage();
    const latest = latestAssistant(this.#session);
    const calls = this.#roleModelCalls();
    const roster = await this.#session.listRlmSubagents();
    const observations = this.#observations();
    if (latest.stopReason !== "stop" || calls.root !== 4 || calls.implementation !== 2 || calls.review !== 4 ||
      observations.child_count !== 2 || observations.max_depth !== 1 || observations.tool_call_count !== 4 ||
      this.#followedUpReview === undefined || this.#usageByRole.size !== 2 || roster.subagents.length !== 0)
      throw new Error(`P3 development completion invariant failed: ${calls.root}/${calls.implementation}/${calls.review}/${latest.stopReason}/${roster.subagents.length}`);
    return Object.freeze({ lifecycle: "completed", usage: roleUsage,
      assistant: Object.freeze({ completed: true, stop_reason: "stop" }),
      observations: Object.freeze({ ...observations, model_callback_count: calls.root + calls.implementation + calls.review,
        remaining_child_count: roster.subagents.length, retained_follow_up_count: 1 }), });
  }

  private async cleanupChildren(): Promise<void> {
    const roster = await this.#session.listRlmSubagents();
    for (const entry of roster.subagents) {
      const id = (entry as { rlm_child_id?: unknown }).rlm_child_id;
      if (typeof id !== "string") throw new Error("P3 cleanup roster is invalid");
      await this.#session.deleteRlmSubagent(id);
    }
    if ((await this.#session.listRlmSubagents()).subagents.length !== 0)
      throw new Error("P3 cleanup is uncertain");
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

function latestAssistant(session: PrimeSdkSession): {
  stopReason?: PrimeP3DevelopmentResult["assistant"]["stop_reason"];
  usage?: Record<string, number>;
} {
  const value = session.agent.state.messages.filter(isAssistant).at(-1);
  if (!value) throw new Error("P3 assistant usage is missing");
  return value;
}

function usageOf(session: PrimeSdkSession): PrimeP3DevelopmentUsage {
  const messages = session.agent.state.messages.filter(isAssistant);
  if (messages.length === 0) throw new Error("P3 assistant usage is missing");
  return messages.reduce<PrimeP3DevelopmentUsage>((total, message) => {
    const input = message.usage?.input ?? message.usage?.inputTokens,
      output = message.usage?.output ?? message.usage?.outputTokens,
      totalTokens = message.usage?.totalTokens ?? message.usage?.total;
    if (![input, output, totalTokens].every((value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0))
      throw new Error("P3 assistant usage is invalid");
    return { input_tokens: total.input_tokens + input!, output_tokens: total.output_tokens + output!, total_tokens: total.total_tokens + totalTokens! };
  }, { input_tokens: 0, output_tokens: 0, total_tokens: 0 });
}

function usageFromMessage(message: unknown): PrimeP3DevelopmentUsage {
  if (!message || typeof message !== "object") throw new Error("P3 assistant usage is missing");
  const usage = (message as { usage?: Record<string, unknown> }).usage;
  const input = usage?.input, output = usage?.output, total = usage?.totalTokens;
  if (![input, output, total].every((value) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0) || (input as number) + (output as number) !== total)
    throw new Error("P3 assistant usage is invalid");
  return { input_tokens: input as number, output_tokens: output as number, total_tokens: total as number };
}

function addUsage(a: PrimeP3DevelopmentUsage, b: PrimeP3DevelopmentUsage): PrimeP3DevelopmentUsage {
  return { input_tokens: a.input_tokens + b.input_tokens, output_tokens: a.output_tokens + b.output_tokens, total_tokens: a.total_tokens + b.total_tokens };
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

function onlyIpython(value: unknown): value is string[] {
  return Array.isArray(value) && value.length === 1 && value[0] === "ipython";
}

function privateChildSessionDir(value: unknown, root: string): value is string {
  if (typeof value !== "string" || !isAbsolute(value)) return false;
  const path = relative(root, value);
  return path.length > 0 && !path.startsWith("..") && !isAbsolute(path);
}

function exactRoleModel(value: unknown, modelId: string): boolean {
  return !!value && typeof value === "object" &&
    (value as { id?: unknown }).id === modelId &&
    (value as { name?: unknown }).name === modelId;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
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
