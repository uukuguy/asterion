import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { inspect } from "node:util";

const MAX_MODEL_CALLBACKS = 128;
const MAX_TOOL_CALLBACKS = 128;

export type PrimeSolvingModelCallback = (
  model: unknown,
  context: unknown,
  options: unknown,
) => PrimeSolvingAssistantMessageEventStream;

export interface PrimeSolvingAssistantMessageEventStream extends AsyncIterable<unknown> {
  result(): Promise<unknown>;
}

export type PrimeSolvingIpythonCallback = (
  toolCallId: string,
  input: Readonly<{ code: string }>,
  signal: AbortSignal | undefined,
) => Promise<unknown>;

export type PrimeSolvingCompactionCallback = (
  transition: PrimeSolvingCompactionTransition,
) => void;

export interface PrimeSolvingCompactionTransition {
  readonly replaced_messages: readonly unknown[];
  readonly replacement_messages: readonly unknown[];
  readonly summary_spans: readonly PrimeSolvingCompactionSummarySpan[];
}

export interface PrimeSolvingCompactionSummarySpan {
  readonly kind: "history" | "turn-prefix";
  readonly transcript: string;
  readonly previous_summary: string | null;
}

export interface PrimeP7SolvingSessionOptions {
  readonly primeSourceRoot: string;
  readonly workspace: string;
  readonly model: PrimeSolvingModelCallback;
  readonly ipython: PrimeSolvingIpythonCallback;
  readonly compaction?: PrimeSolvingCompactionCallback;
}

export interface PrimeP7SolvingResult {
  readonly lifecycle: "completed" | "cancelled";
  readonly usage: Readonly<{
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
  }>;
  readonly assistant: Readonly<{
    completed: boolean;
    stop_reason: "stop" | "length" | "toolUse" | "error" | "aborted" | null;
  }>;
  readonly observations: Readonly<{
    active_tool_names: readonly string[];
    compact_count: number;
    normal_model_callback_count: number;
    summary_model_callback_count: number;
    rlm_child_count: number;
    tool_call_count: number;
    solved_latched: boolean;
  }>;
}

interface PrimeSdkSession {
  readonly agent: {
    readonly state: { readonly messages: readonly unknown[] };
    shouldStopAfterTurn?: (context: unknown) => boolean | Promise<boolean>;
  };
  getActiveToolNames(): string[];
  prompt(prompt: string): Promise<void>;
  waitForIdle(): Promise<void>;
  requestAbort(): void;
  disposeAsync(): Promise<void>;
  subscribe(listener: (event: unknown) => void): () => void;
}

interface PrimeSdkModules {
  readonly createAgentSession: (options: Record<string, unknown>) => Promise<{ session: PrimeSdkSession }>;
  readonly SessionManager: { inMemory(workspace: string): unknown };
  readonly AuthStorage: { inMemory(): { setRuntimeApiKey(provider: string, apiKey: string): void } };
  readonly ModelRegistry: { inMemory(auth: unknown): PrimeSdkRegistry };
  readonly DefaultResourceLoader: new (options: Record<string, unknown>) => { reload(): Promise<void> };
  readonly SettingsManager: { inMemory(settings?: unknown): unknown };
  readonly Type: { Object(properties: Record<string, unknown>): unknown; String(): unknown };
}
interface PrimeSdkRegistry {
  registerProvider(provider: string, config: unknown): void;
  unregisterProvider(provider: string): void;
  find(provider: string, model: string): unknown;
}
interface SharedRegistry {
  auth: { setRuntimeApiKey(provider: string, apiKey: string): void };
  registry: PrimeSdkRegistry;
}
const sharedRegistries = new Map<string, SharedRegistry>();

interface OpenedSolvingSession {
  session: PrimeSdkSession;
  control: { state: "open" | "cancelled" | "closed" };
  unregister(): void;
  observations(): PrimeP7SolvingResult["observations"];
}

export async function openPrimeP7SolvingSdkSession(
  options: PrimeP7SolvingSessionOptions,
  limits: Readonly<{ model: number; tool: number }> = {
    model: MAX_MODEL_CALLBACKS,
    tool: MAX_TOOL_CALLBACKS,
  },
): Promise<OpenedSolvingSession> {
  if (!isAbsolute(options.primeSourceRoot) || !isAbsolute(options.workspace))
    throw new Error("primeSourceRoot and workspace must be absolute paths");
  const primeSourceRoot = await canonicalPrimeSourceRoot(options.primeSourceRoot);
  const modules = await loadPrimeSdk(primeSourceRoot);
  const identity = randomUUID();
  const provider = `asterion-p7-solving-${identity}`;
  const modelId = `p7-solving-${identity}`;
  const control: { state: "open" | "cancelled" | "closed" } = { state: "open" };
  let shared = sharedRegistries.get(primeSourceRoot);
  if (!shared) {
    const auth = modules.AuthStorage.inMemory();
    shared = { auth, registry: modules.ModelRegistry.inMemory(auth) };
    sharedRegistries.set(primeSourceRoot, shared);
  }
  shared.auth.setRuntimeApiKey(provider, "in-memory-solving-provider");
  const registry = shared.registry;
  let normalModelCalls = 0;
  let summaryModelCalls = 0;
  let toolCalls = 0;
  let compactCount = 0;
  let solved = false;
  const childIds = new Set<string>();
  let preCompactionMessages: readonly unknown[] | undefined;
  let compactionSummarySpans: PrimeSolvingCompactionSummarySpan[] = [];
  registry.registerProvider(provider, {
    api: `asterion-p7-solving-${identity}`,
    baseUrl: "http://127.0.0.1:0",
    apiKey: "in-memory-solving-provider",
    streamSimple: (model: unknown, context: unknown, streamOptions: unknown) => {
      assertCallbackAllowed(control);
      const summary = isSummaryContext(context);
      if (normalModelCalls + summaryModelCalls >= limits.model)
        throw new Error("Prime P7 solving model callback limit exceeded");
      if (summary) summaryModelCalls += 1;
      else normalModelCalls += 1;
      if (summary) compactionSummarySpans.push(parseSummarySpan(context));
      const stream = options.model(model, context, streamOptions);
      assertAssistantEventStream(stream);
      return stream;
    },
    models: [{
      id: modelId, name: modelId, reasoning: false, input: ["text"],
      contextWindow: 131_072, maxTokens: 4_096,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    }],
  });
  const model = registry.find(provider, modelId);
  if (!model) throw new Error("Prime P7 solving model registration failed");
  const agentDir = join(options.workspace, ".asterion-prime-p7-solving");
  const settingsManager = modules.SettingsManager.inMemory({
    retry: { enabled: false, provider: { maxRetries: 0 } },
    autoRefine: { enabled: false },
    compaction: { enabled: true, reserveTokens: 8_192, keepRecentTokens: 32_768, agentCallable: false },
  });
  const resourceLoader = new modules.DefaultResourceLoader({
    cwd: options.workspace, agentDir, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true,
    noThemes: true, noContextFiles: true, bundledSkillsDir: null,
  });
  const customIpython = {
    name: "ipython",
    label: "ipython",
    description: "Persistent IPython for programmatic frame analysis and broker actions. Outputs and state persist across calls. Inspect observations, revise the world model, and act only through the injected p7_client module.",
    parameters: modules.Type.Object({ code: modules.Type.String() }),
    executionMode: "sequential",
    execute: async (toolCallId: string, input: { code: string }, signal: AbortSignal) => {
      assertCallbackAllowed(control);
      if (++toolCalls > limits.tool)
        throw new Error("Prime P7 solving ipython callback limit exceeded");
      const result = await options.ipython(toolCallId, Object.freeze({ code: input.code }), signal);
      if (isBrokerSolvedResult(result)) solved = true;
      return result;
    },
  };
  const created = await modules.createAgentSession({
    cwd: options.workspace, agentDir, authStorage: shared.auth,
    modelRegistry: registry, model,
    sessionManager: modules.SessionManager.inMemory(options.workspace),
    settingsManager, resourceLoader,
    tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"],
    customTools: [customIpython], includeGoals: false, includeCompactSkill: false,
    prewarmIpythonKernel: false, serializedRefine: true, telemetryDisabled: true,
  });
  const priorShouldStop = created.session.agent.shouldStopAfterTurn;
  created.session.agent.shouldStopAfterTurn = async (context: unknown) => {
    if (solved) return true;
    return priorShouldStop ? await priorShouldStop(context) : false;
  };
  const unsubscribe = created.session.subscribe((event: unknown) => {
    if (!event || typeof event !== "object") return;
    const value = event as { type?: unknown; child?: { id?: unknown } };
    if (value.type === "compaction_start") {
      compactCount += 1;
      preCompactionMessages = snapshotMessages(created.session.agent.state.messages);
      compactionSummarySpans = [];
    }
    if (value.type === "compaction_end") {
      const eventValue = value as { aborted?: unknown; result?: unknown };
      if (eventValue.aborted === false && eventValue.result && preCompactionMessages) {
        options.compaction?.(Object.freeze({
          replaced_messages: preCompactionMessages,
          replacement_messages: snapshotMessages(created.session.agent.state.messages),
          summary_spans: Object.freeze([...compactionSummarySpans]),
        }));
      }
      preCompactionMessages = undefined;
      compactionSummarySpans = [];
    }
    if (value.type === "rlm_child_update" && typeof value.child?.id === "string")
      childIds.add(value.child.id);
  });
  return Object.freeze({
    session: created.session,
    control,
    unregister: () => { unsubscribe(); registry.unregisterProvider(provider); },
    observations: () => Object.freeze({
      active_tool_names: Object.freeze([...created.session.getActiveToolNames()].sort()),
      compact_count: compactCount,
      normal_model_callback_count: normalModelCalls,
      summary_model_callback_count: summaryModelCalls,
      rlm_child_count: childIds.size,
      tool_call_count: toolCalls,
      solved_latched: solved,
    }),
  });
}

export class PrimeP7SolvingSession {
  #state: "open" | "completed" | "cancelled" | "closed" = "open";
  readonly #sdk: OpenedSolvingSession;
  private constructor(sdk: OpenedSolvingSession) { this.#sdk = sdk; }
  static async open(options: PrimeP7SolvingSessionOptions): Promise<PrimeP7SolvingSession> {
    return new PrimeP7SolvingSession(await openPrimeP7SolvingSdkSession(options));
  }
  async prompt(prompt: string): Promise<PrimeP7SolvingResult> {
    if (this.#state !== "open" || typeof prompt !== "string" || !prompt)
      throw new Error("Prime P7 solving session accepts one prompt");
    await this.#sdk.session.prompt(prompt);
    await this.#sdk.session.waitForIdle();
    if (this.currentState() === "cancelled") return this.result("cancelled");
    this.#state = "completed";
    return this.result("completed");
  }
  async cancel(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "cancelled"; this.#sdk.control.state = "cancelled";
    this.#sdk.session.requestAbort();
  }
  async close(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "closed"; this.#sdk.control.state = "closed";
    try { await this.#sdk.session.disposeAsync(); } finally { this.#sdk.unregister(); }
  }
  private result(lifecycle: "completed" | "cancelled"): PrimeP7SolvingResult {
    const assistants = this.#sdk.session.agent.state.messages.filter(isAssistant);
    const usage = assistants.reduce((total, message) => ({
      input_tokens: total.input_tokens + count(message.usage?.input),
      output_tokens: total.output_tokens + count(message.usage?.output),
      total_tokens: total.total_tokens + count(message.usage?.totalTokens),
    }), { input_tokens: 0, output_tokens: 0, total_tokens: 0 });
    const latest = assistants.at(-1);
    const observations = this.#sdk.observations();
    return Object.freeze({
      lifecycle, usage: Object.freeze(usage),
      assistant: Object.freeze({
        completed: lifecycle === "completed" && observations.solved_latched,
        stop_reason: lifecycle === "cancelled" ? "aborted" : safeStopReason(latest?.stopReason),
      }),
      observations,
    });
  }
  toJSON(): PrimeP7SolvingResult {
    return this.result(this.#state === "cancelled" ? "cancelled" : "completed");
  }
  [inspect.custom](): string { return "PrimeP7SolvingSession { lifecycle: safe }"; }
  private currentState(): "open" | "completed" | "cancelled" | "closed" { return this.#state; }
}

async function loadPrimeSdk(root: string): Promise<PrimeSdkModules> {
  const coding = join(root, "packages/coding-agent/dist");
  const required = ["core/sdk.js", "core/session-manager.js", "core/model-registry.js", "core/auth-storage.js", "core/resource-loader.js", "core/settings-manager.js"];
  if (!required.every((path) => existsSync(join(coding, path))))
    throw new Error("Prime SDK dist is unavailable at primeSourceRoot");
  const load = (path: string) => import(pathToFileURL(join(coding, path)).href);
  const [sdk, sessions, models, auth, resources, settings, typebox] = await Promise.all([
    load("core/sdk.js"), load("core/session-manager.js"), load("core/model-registry.js"),
    load("core/auth-storage.js"), load("core/resource-loader.js"), load("core/settings-manager.js"),
    import(pathToFileURL(join(root, "node_modules/typebox/build/index.mjs")).href),
  ]);
  return { createAgentSession: sdk.createAgentSession, SessionManager: sessions.SessionManager,
    ModelRegistry: models.ModelRegistry, AuthStorage: auth.AuthStorage,
    DefaultResourceLoader: resources.DefaultResourceLoader, SettingsManager: settings.SettingsManager,
    Type: typebox.Type } as PrimeSdkModules;
}
async function canonicalPrimeSourceRoot(root: string): Promise<string> {
  try { return await realpath(root); } catch { throw new Error("Prime SDK source root is unavailable"); }
}
function assertAssistantEventStream(value: unknown): asserts value is PrimeSolvingAssistantMessageEventStream {
  if (!value || typeof value !== "object" || typeof (value as { result?: unknown }).result !== "function" || typeof (value as { [Symbol.asyncIterator]?: unknown })[Symbol.asyncIterator] !== "function")
    throw new Error("model callback must return a Prime AssistantMessageEventStream");
}
function assertCallbackAllowed(control: { state: "open" | "cancelled" | "closed" }): void {
  if (control.state !== "open") throw new Error("Prime P7 solving session is unavailable");
}
function isSummaryContext(value: unknown): boolean {
  return !!value && typeof value === "object" && !Array.isArray((value as { tools?: unknown }).tools);
}
function isBrokerSolvedResult(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const details = (value as { details?: unknown }).details;
  return !!details && typeof details === "object" &&
    (details as { broker_terminal?: unknown }).broker_terminal === "LEVEL_SOLVED";
}
function isAssistant(message: unknown): message is { stopReason?: unknown; usage?: Record<string, unknown> } {
  return !!message && typeof message === "object" && (message as { role?: unknown }).role === "assistant";
}
function count(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}
function safeStopReason(value: unknown): PrimeP7SolvingResult["assistant"]["stop_reason"] {
  return value === "stop" || value === "length" || value === "toolUse" || value === "error" || value === "aborted" ? value : "error";
}
function snapshotMessages(messages: readonly unknown[]): readonly unknown[] {
  const value = jsonValue(messages);
  if (!Array.isArray(value)) throw new Error("Prime P7 solving compaction messages are invalid");
  return Object.freeze(value);
}
function parseSummarySpan(context: unknown): PrimeSolvingCompactionSummarySpan {
  if (!context || typeof context !== "object" || Array.isArray(context)) throw new Error("invalid compaction context");
  const messages = (context as { messages?: unknown }).messages;
  if (!Array.isArray(messages) || messages.length !== 1 || !messages[0] || typeof messages[0] !== "object")
    throw new Error("invalid compaction summary source");
  const source = readText((messages[0] as { content?: unknown }).content);
  const opening = "<conversation>\n";
  const closing = "\n</conversation>\n\n";
  if (!source.startsWith(opening)) throw new Error("invalid compaction summary source");
  const closeAt = source.lastIndexOf(closing);
  if (closeAt <= opening.length) throw new Error("invalid compaction summary source");
  let instructions = source.slice(closeAt + closing.length);
  let previous_summary: string | null = null;
  const previousOpen = "<previous-summary>\n";
  const previousClose = "\n</previous-summary>\n\n";
  if (instructions.startsWith(previousOpen)) {
    const previousEnd = instructions.indexOf(previousClose, previousOpen.length);
    if (previousEnd <= previousOpen.length) throw new Error("invalid compaction summary source");
    previous_summary = instructions.slice(previousOpen.length, previousEnd);
    instructions = instructions.slice(previousEnd + previousClose.length);
  }
  if (!instructions) throw new Error("invalid compaction summary source");
  const kind = instructions.startsWith("This is the PREFIX of a turn that was too large to keep.") ? "turn-prefix" : "history";
  return Object.freeze({ kind, transcript: source.slice(opening.length, closeAt), previous_summary });
}
function readText(value: unknown): string {
  if (typeof value === "string" && value) return value;
  if (!Array.isArray(value) || !value.length) throw new Error("invalid compaction summary content");
  let text = "";
  for (const item of value) {
    if (!item || typeof item !== "object" || Array.isArray(item) || (item as { type?: unknown }).type !== "text" || typeof (item as { text?: unknown }).text !== "string")
      throw new Error("invalid compaction summary content");
    text += (item as { text: string }).text;
  }
  if (!text) throw new Error("invalid compaction summary content");
  return text;
}
function jsonValue(value: unknown): unknown {
  const encoded = JSON.stringify(value);
  if (typeof encoded !== "string") throw new Error("non-JSON compaction value");
  return JSON.parse(encoded);
}
