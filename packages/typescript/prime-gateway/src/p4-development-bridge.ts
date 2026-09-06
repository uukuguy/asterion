import { createHash } from "node:crypto";
import { mkdir, realpath, lstat } from "node:fs/promises";
import { Socket } from "node:net";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

/** Private, development-only protocol.  It deliberately has no public projection. */
export const P4_DEVELOPMENT_GATEWAY_PROTOCOL = "asterion.prime-p4-development-gateway/v1";
export const P4_DEVELOPMENT_MAX_FRAME_BYTES = 1024 * 1024;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const KEYS = ["generation", "kind", "payload", "protocol", "request_id", "run_id", "runtime_id", "sequence", "session_id"];
type Identity = Readonly<{ run_id: string; session_id: string; runtime_id: "prime.agent"; generation: number }>;
type Kind = "open" | "prompt" | "recover" | "compact" | "close" | "cancel" | "model.response" | "tool.response";
type Frame = Readonly<Identity & { protocol: typeof P4_DEVELOPMENT_GATEWAY_PROTOCOL; sequence: number; request_id: string; kind: Kind; payload: Record<string, unknown> }>;
type Pending = { resolve(value: unknown): void; reject(error: Error): void };
type Stream = { push(event: unknown): void };

export class P4DevelopmentBridgeError extends Error { constructor() { super("P4 development bridge failed"); } }

/**
 * A strict native-daemon bridge.  The only values emitted across its inherited
 * FD are private protocol facts; prompts, model text, tool code and paths are
 * never placed in a command result.
 */
export class P4DevelopmentBridge {
  #socket: Socket; #buffer = Buffer.alloc(0); #in = 0; #out = 0; #identity: Identity | undefined;
  #phase: "new" | "opening" | "open" | "prompt1" | "recover" | "compact" | "prompt2" | "close_ready" | "cancelled" | "closed" | "failed" = "new";
  #requestIds = new Set<string>(); #model = new Map<string, Pending>(); #tool = new Map<string, Pending>(); #callback = 0;
  #native: any; #client: any; #activeSessionId = ""; #nativeSessionId = ""; #cursor: { generation: string; sequence: number } | undefined;
  #candidate: Record<string, unknown> | undefined; #modelCount = 0; #toolCount = 0; #runtime: any; #compactionStarts = 0; #compactionEnds = 0;
  #makeStream: (() => Stream) | undefined;
  constructor(socket: Socket) { this.#socket = socket; }
  toJSON() { return { phase: this.#phase }; }
  ["nodejs.util.inspect.custom"]() { return `P4DevelopmentBridge { phase: ${this.#phase} }`; }

  async run(): Promise<void> {
    try {
      for await (const chunk of this.#socket) for (const frame of this.#decode(chunk)) this.#dispatch(frame);
      if (this.#buffer.length || this.#phase !== "closed") throw Error("unexpected EOF");
    } catch {
      this.#fail("bridge");
      throw new P4DevelopmentBridgeError();
    } finally { await this.#dispose(); }
  }
  #decode(chunk: Uint8Array): Frame[] {
    this.#buffer = Buffer.concat([this.#buffer, chunk]); const result: Frame[] = [];
    while (this.#buffer.length >= 4) { const n = this.#buffer.readUInt32BE(); if (n > P4_DEVELOPMENT_MAX_FRAME_BYTES) throw Error("frame limit"); if (this.#buffer.length < n + 4) break; const body = this.#buffer.subarray(4, n + 4); this.#buffer = this.#buffer.subarray(n + 4); const value = parse(body); this.#validate(value); result.push(value); }
    return result;
  }
  #validate(f: Frame): void {
    if (!record(f) || !exact(f, KEYS) || f.protocol !== P4_DEVELOPMENT_GATEWAY_PROTOCOL || f.runtime_id !== "prime.agent" || !opaque(f.run_id) || !opaque(f.session_id) || !opaque(f.request_id) || !Number.isSafeInteger(f.generation) || f.generation < 1 || !Number.isSafeInteger(f.sequence) || f.sequence !== ++this.#in || !record(f.payload) || !kind(f.kind)) throw Error("invalid frame");
    const identity: Identity = { run_id: f.run_id, session_id: f.session_id, runtime_id: f.runtime_id, generation: f.generation };
    if (!this.#identity) { if (f.kind !== "open") throw Error("open required"); this.#identity = identity; } else if (canonical(this.#identity) !== canonical(identity)) throw Error("identity drift");
    if (f.kind.endsWith("response")) { if (!["prompt1", "compact", "prompt2"].includes(this.#phase)) throw Error("late callback"); return; }
    if (this.#requestIds.has(f.request_id)) throw Error("duplicate request");
    const allowed: Record<string, readonly Kind[]> = { new: ["open"], open: ["prompt", "cancel"], prompt1: ["cancel"], recover: ["recover", "cancel"], compact: ["compact", "cancel"], prompt2: ["prompt", "cancel"], close_ready: ["close"], cancelled: ["close"] };
    if (!allowed[this.#phase]?.includes(f.kind)) throw Error("invalid phase");
  }
  #dispatch(f: Frame): void {
    if (f.kind === "model.response") return this.#resolve(this.#model, f, "message");
    if (f.kind === "tool.response") return this.#resolve(this.#tool, f, "result");
    this.#requestIds.add(f.request_id);
    if (f.kind === "open") this.#phase = "opening";
    if (f.kind === "prompt") this.#phase = this.#phase === "open" ? "prompt1" : "prompt2";
    if (f.kind === "cancel") this.#phase = "cancelled";
    void this.#command(f).catch(() => this.#fail(f.request_id));
  }
  async #command(f: Frame): Promise<void> {
    if (f.kind === "open") { await this.#open(f); this.#phase = "open"; this.#emit("ready", f.request_id, {}); return; }
    if (f.kind === "prompt") { await this.#prompt(f); return; }
    if (f.kind === "recover") { await this.#recover(f); return; }
    if (f.kind === "compact") { await this.#compact(f); return; }
    if (f.kind === "cancel") { this.#settle(Error("cancelled")); await this.#client?.request({ type: "abort", activeSessionId: this.#activeSessionId }); this.#emit("command.result", f.request_id, { result: { lifecycle: "cancelled" } }); return; }
    if (f.kind === "close") { if (!exact(f.payload, [])) throw Error("close payload"); this.#settle(Error("closed")); await this.#client?.request({ type: "detach", activeSessionId: this.#activeSessionId }); this.#phase = "closed"; this.#emit("command.result", f.request_id, { result: this.#finalWitness() }); this.#socket.end(); return; }
    throw Error("command");
  }
  async #open(f: Frame): Promise<void> {
    if (!exact(f.payload, ["prime_source_root", "workspace"])) throw Error("open payload");
    const root = absolute(f.payload.prime_source_root), workspace = absolute(f.payload.workspace); await this.#startNative(root, workspace);
    const created = await this.#client.request({ type: "create", continueRecent: false, noSession: false, name: "p4-development", lifecycle: "resident", config: {} });
    this.#activeSessionId = created?.data?.id; if (!created?.success || !opaque(this.#activeSessionId)) throw Error("create");
    const attached = await this.#attach();
    this.#nativeSessionId = readSessionId(attached?.data?.snapshot) || this.#activeSessionId;
  }
  async #prompt(f: Frame): Promise<void> {
    const prompt = text(f.payload, "prompt"); await this.#client.request({ type: "prompt_and_wait", activeSessionId: this.#activeSessionId, message: prompt });
    if (this.#phase === "prompt1") {
      if (this.#modelCount !== 2 || this.#toolCount !== 1 || !this.#cursor) throw Error("first prompt witness");
      this.#candidate = await this.#checkpointCandidate(); this.#phase = "recover"; this.#emit("command.result", f.request_id, { result: { checkpoint_candidate: this.#candidate } });
    } else {
      if (this.#modelCount !== 5 || this.#toolCount !== 2) throw Error("second prompt witness");
      this.#phase = "close_ready"; this.#emit("command.result", f.request_id, { result: { lifecycle: "completed", model_callback_count: 5, tool_callback_count: 2 } });
    }
  }
  async #checkpointCandidate(): Promise<Record<string, unknown>> {
    const [header, tree, resources] = await Promise.all([this.#client.request({ type: "get_session_header", activeSessionId: this.#activeSessionId }), this.#client.request({ type: "get_context_tree", activeSessionId: this.#activeSessionId }), this.#client.request({ type: "get_resource_snapshot", activeSessionId: this.#activeSessionId })]);
    const cursor = this.#cursor!;
    return Object.freeze({ active_session_id: this.#activeSessionId, session_id: this.#nativeSessionId, cursor: Object.freeze({ ...cursor }), transcript_sha256: digest(header?.data), tree_sha256: digest(tree?.data), artifact_sha256: digest(resources?.data), settled_model_callback_count: 2, settled_tool_callback_count: 1 });
  }
  async #recover(f: Frame): Promise<void> {
    if (!exact(f.payload, ["checkpoint_candidate", "checkpoint_sha256"]) || !record(f.payload.checkpoint_candidate) || typeof f.payload.checkpoint_sha256 !== "string" || !/^sha256:[a-f0-9]{64}$/.test(f.payload.checkpoint_sha256) || !this.#candidate || canonical(f.payload.checkpoint_candidate) !== canonical(this.#candidate)) throw Error("checkpoint readback mismatch");
    const candidate = this.#candidate as any; await this.#client.request({ type: "detach", activeSessionId: this.#activeSessionId });
    const attached = await this.#attach(candidate.cursor); const snapshotCursor = attached?.data?.lastEventCursor;
    if (!attached?.success || attached.data?.activeSessionId !== candidate.active_session_id || (readSessionId(attached.data?.snapshot) || attached.data?.activeSessionId) !== candidate.session_id || !sameCursor(snapshotCursor, candidate.cursor) || attached.data?.replay?.status !== "complete") throw Error("reattach mismatch");
    this.#phase = "compact"; this.#emit("command.result", f.request_id, { result: { active_session_id: candidate.active_session_id, session_id: candidate.session_id, from_cursor: candidate.cursor, to_cursor: snapshotCursor, snapshot_cursor: snapshotCursor } });
  }
  async #compact(f: Frame): Promise<void> {
    if (!exact(f.payload, [])) throw Error("compact payload"); const before = new Set((this.#runtime?.session?.sessionManager?.getEntries?.() ?? []).filter((e: any) => e.type === "compaction").map((e: any) => e.id));
    this.#compactionStarts = 0; this.#compactionEnds = 0; const result = await this.#client.request({ type: "compact", activeSessionId: this.#activeSessionId }); const native = result?.data;
    const entries = (this.#runtime?.session?.sessionManager?.getEntries?.() ?? []).filter((e: any) => e.type === "compaction" && !before.has(e.id));
    const first = native?.firstKeptEntryId, tokens = native?.tokensBefore;
    if (!result?.success || this.#compactionStarts !== 1 || this.#compactionEnds !== 1 || entries.length !== 1 || typeof first !== "string" || !Number.isSafeInteger(tokens) || tokens < 0 || this.#modelCount !== 3 || this.#toolCount !== 1) throw Error("compaction witness");
    this.#phase = "prompt2"; this.#emit("command.result", f.request_id, { result: { compact_called: true, succeeded: true, start_count: 1, end_count: 1, new_entry_count: 1, active_path_sha256: digest(this.#runtime?.session?.sessionManager?.getFlatTree?.()), first_kept_entry_id_sha256: digest(first), tokens_before: tokens } });
  }
  async #attach(resumeCursor?: unknown): Promise<any> { const r = await this.#client.request({ type: "attach", activeSessionId: this.#activeSessionId, supportsExtensionUi: false, clientId: "asterion-p4", capabilities: ["attach_snapshot", "event_sequence"], ...(resumeCursor ? { resumeCursor: { activeSessionId: this.#activeSessionId, ...(resumeCursor as object) } } : {}), telemetryDisabled: true }); const c = r?.data?.lastEventCursor; if (!r?.success || !sameCursor(c, c)) throw Error("attach"); this.#cursor = { generation: c.generation, sequence: c.sequence }; return r; }
  async #startNative(root: string, workspace: string): Promise<void> {
    const fixed = async (path: string) => { const target = join(root, path), [base, actual, stat] = await Promise.all([realpath(root), realpath(target), lstat(target)]); if (!stat.isFile() || stat.isSymbolicLink() || !actual.startsWith(`${base}/`)) throw Error("unsafe module"); return actual; };
    const [daemonModule, clientModule, sdk, authModule, registryModule, settingsModule, streamModule] = await Promise.all(["node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-mode.js", "node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-client.js", "node_modules/@earendil-works/pi-coding-agent/dist/index.js", "packages/coding-agent/dist/core/auth-storage.js", "packages/coding-agent/dist/core/model-registry.js", "packages/coding-agent/dist/core/settings-manager.js", "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js"].map(async path => import(pathToFileURL(await fixed(path)).href) as any));
    if (![daemonModule.AgentDaemon, clientModule.DaemonClient, sdk.createAgentSessionServices, sdk.createAgentSessionFromServices, authModule.AuthStorage, registryModule.ModelRegistry, settingsModule.SettingsManager, streamModule.createAssistantMessageEventStream].every(v => typeof v === "function")) throw Error("native exports"); this.#makeStream = streamModule.createAssistantMessageEventStream;
    const agentDir = join(workspace, ".asterion-p4-development"); await mkdir(agentDir, { recursive: true, mode: 0o700 }); const auth = authModule.AuthStorage.inMemory(), registry = registryModule.ModelRegistry.inMemory(auth), settings = settingsModule.SettingsManager.inMemory({ retry: { enabled: false, provider: { maxRetries: 0 } }, autoRefine: { enabled: false }, compaction: { enabled: false, keepRecentTokens: 1, reserveTokens: 1536 } });
    const provider = "asterion-p4-development", modelId = "p4-development"; auth.setRuntimeApiKey(provider, "private-callback"); registry.registerProvider(provider, { api: provider, baseUrl: "http://127.0.0.1:0", apiKey: "private-callback", streamSimple: (model: unknown, context: unknown, options: unknown) => this.#modelStream(root, model, context, options), models: [{ id: modelId, name: modelId, reasoning: false, input: ["text"], contextWindow: 16384, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] }); const model = registry.find(provider, modelId); if (!model) throw Error("model");
    const runtime = async ({ cwd, agentDir: runtimeDir, sessionManager, sessionStartEvent }: any) => { if (cwd !== workspace || runtimeDir !== agentDir || !sessionManager) throw Error("daemon manager"); const services = await sdk.createAgentSessionServices({ cwd, agentDir, authStorage: auth, modelRegistry: registry, settingsManager: settings, telemetryDisabled: true, noBuiltinHerdrReporter: true, resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, bundledSkillsDir: null } }); const customTools = [this.#ipythonTool()]; const created = await sdk.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model, noTools: "all", customTools, initialActiveToolNames: ["ipython"], allowedToolNames: ["ipython"], telemetryDisabled: true, prewarmIpythonKernel: false, serializedRefine: true }); this.#runtime = { ...created, services }; created.session.subscribe((event: any) => { if (event?.type === "compaction_start") this.#compactionStarts += 1; if (event?.type === "compaction_end") this.#compactionEnds += 1; }); return { ...created, services, diagnostics: [] }; };
    const socket = join(workspace, "p4.sock"); this.#native = new daemonModule.AgentDaemon(socket, { defaultSessionConfig: { cwd: workspace, agentDir, sessionDir: agentDir, telemetryDisabled: true }, createRuntime: runtime }); await this.#native.start(); this.#client = new clientModule.DaemonClient(socket); this.#client.onMessage((message: any) => { const cursor = message?.meta?.cursor; if (typeof cursor?.generation === "string" && Number.isSafeInteger(cursor.sequence)) this.#cursor = { generation: cursor.generation, sequence: cursor.sequence }; }); await this.#client.connect(); const hello = await this.#client.waitForHello(); if (hello?.protocol?.version !== 7 || hello?.schemaId !== "protocol-7-schema-14-816309b1cd50" || hello?.schemaRevision !== 14 || !["attach_snapshot", "event_sequence"].every((x) => hello?.serverCapabilities?.includes(x)) || "supervisorGeneration" in hello) throw Error("hello");
  }
  #modelStream(_root: string, model: unknown, context: unknown, options: unknown): Stream { if (!this.#makeStream) throw Error("stream factory"); const stream = this.#makeStream(); const id = this.#callbackId("model"); this.#modelCount += 1; const response = new Promise<unknown>((resolve, reject) => this.#model.set(id, { resolve, reject })); void response.then(message => { if (!record(message) || message.role !== "assistant") throw Error("assistant response"); queueMicrotask(() => { stream.push({ type: "start", partial: { ...message, content: [] } }); stream.push({ type: "done", reason: message.stopReason, message }); }); }, () => stream.push({ type: "error", reason: "error", error: safeError() })); this.#emit("model.request", id, { model, context, options }); return stream; }
  #ipythonTool(): any { return { name: "ipython", label: "ipython", description: "private callback tool", promptSnippet: "ipython", executionMode: "sequential", parameters: { type: "object", properties: { code: { type: "string" } }, required: ["code"], additionalProperties: false }, execute: async (toolCallId: string, input: any) => { if (!input || typeof input.code !== "string") throw Error("tool input"); const id = this.#callbackId("tool"); this.#toolCount += 1; const result = new Promise<unknown>((resolve, reject) => this.#tool.set(id, { resolve, reject })); this.#emit("tool.request", id, { tool_call_id: toolCallId, code: input.code }); return result; } }; }
  #resolve(map: Map<string, Pending>, f: Frame, key: string): void { const pending = map.get(f.request_id); if (!pending || !exact(f.payload, [key])) throw Error("unexpected callback"); map.delete(f.request_id); pending.resolve(f.payload[key]); }
  #callbackId(kind: "model" | "tool"): string { const id = `p4-${kind}-${++this.#callback}`; this.#requestIds.add(id); return id; }
  #emit(kind: string, request_id: string, payload: Record<string, unknown>): void { if (!this.#identity || this.#phase === "failed") throw Error("bridge unavailable"); const body = Buffer.from(canonical({ protocol: P4_DEVELOPMENT_GATEWAY_PROTOCOL, ...this.#identity, sequence: ++this.#out, request_id, kind, payload: json(payload) })); if (body.length > P4_DEVELOPMENT_MAX_FRAME_BYTES) throw Error("frame limit"); const header = Buffer.alloc(4); header.writeUInt32BE(body.length); this.#socket.write(Buffer.concat([header, body])); }
  #finalWitness(): Record<string, unknown> { return { lifecycle: "closed", model_callback_count: this.#modelCount, tool_callback_count: this.#toolCount, active_session_id_sha256: digest(this.#activeSessionId), session_id_sha256: digest(this.#nativeSessionId), cursor_sha256: digest(this.#cursor) }; }
  #settle(error: Error): void { for (const value of [...this.#model.values(), ...this.#tool.values()]) value.reject(error); this.#model.clear(); this.#tool.clear(); }
  #fail(id: string): void { if (this.#phase === "failed" || this.#phase === "closed") return; this.#phase = "failed"; this.#settle(Error("failed")); try { this.#emit("error", id, { code: "bridge_failed" }); } catch {} this.#socket.destroy(); }
  async #dispose(): Promise<void> { this.#settle(Error("closed")); try { this.#client?.close(); } catch {} try { await this.#native?.stop?.(); } catch {} }
}

export function inheritedP4DevelopmentSocket(fd: number): Socket { if (!Number.isSafeInteger(fd) || fd < 3) throw Error("invalid inherited FD"); return new Socket({ fd, readable: true, writable: true }); }
function record(value: unknown): value is Record<string, any> { return !!value && typeof value === "object" && !Array.isArray(value); }
function exact(value: Record<string, unknown>, keys: readonly string[]): boolean { return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key)); }
function opaque(value: unknown): value is string { return typeof value === "string" && ID.test(value); }
function kind(value: unknown): value is Kind { return typeof value === "string" && ["open", "prompt", "recover", "compact", "close", "cancel", "model.response", "tool.response"].includes(value); }
function absolute(value: unknown): string { if (typeof value !== "string" || !isAbsolute(value)) throw Error("absolute path required"); return value; }
function text(value: Record<string, unknown>, key: string): string { if (!exact(value, [key]) || typeof value[key] !== "string" || !(value[key] as string)) throw Error("invalid private payload"); return value[key] as string; }
function parse(body: Buffer): Frame { let value: unknown; try { value = JSON.parse(body.toString("utf8")); } catch { throw Error("JSON"); } if (!record(value) || canonical(value) !== body.toString("utf8")) throw Error("noncanonical"); return value as Frame; }
function canonical(value: any): string { if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value); if (typeof value === "number") { if (!Number.isFinite(value)) throw Error("nonfinite"); return JSON.stringify(value); } if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`; if (!record(value)) throw Error("JSON value"); return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`; }
function json(value: unknown): any { const encoded = JSON.stringify(value); if (typeof encoded !== "string") throw Error("JSON"); return JSON.parse(encoded); }
function digest(value: unknown): string { const encoded = JSON.stringify(value ?? null); if (typeof encoded !== "string") throw Error("digest value"); return `sha256:${createHash("sha256").update(encoded).digest("hex")}`; }
function sameCursor(value: any, expected: any): boolean { return !!value && !!expected && typeof value.generation === "string" && Number.isSafeInteger(value.sequence) && value.generation === expected.generation && value.sequence === expected.sequence; }
function readSessionId(snapshot: any): string | undefined { for (const key of ["sessionId", "session_id"]) if (opaque(snapshot?.[key])) return snapshot[key]; return undefined; }
function safeError() { return { role: "assistant", api: "anthropic-messages", provider: "asterion-p4-development", model: "p4-development", content: [], usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } }, stopReason: "error", timestamp: 0 }; }
