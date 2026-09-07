import { Socket } from "node:net";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { PrimeP7SolvingSession } from "./p7-solving-session.js";
import type { PrimeSolvingAssistantMessageEventStream } from "./p7-solving-session.js";

export const P7_SOLVING_GATEWAY_PROTOCOL = "asterion.prime-p7-solving-gateway/v1";
export const P7_SOLVING_MAX_FRAME_BYTES = 16_777_216;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const KEYS = ["generation", "kind", "payload", "protocol", "request_id", "run_id", "runtime_id", "sequence", "session_id"];
type Kind = "open" | "prompt" | "cancel" | "close" | "model.response" | "tool.response";
type Identity = Readonly<{ run_id: string; session_id: string; runtime_id: "prime.agent"; generation: number }>;
type Frame = Readonly<Identity & { protocol: typeof P7_SOLVING_GATEWAY_PROTOCOL; sequence: number; request_id: string; kind: Kind; payload: Record<string, unknown> }>;
type Stream = PrimeSolvingAssistantMessageEventStream & { push(event: unknown): void };
type StreamFactory = () => Stream;
type Pending = { resolve(value: unknown): void; reject(error: Error): void };

export class P7SolvingBridgeError extends Error {
  constructor() { super("P7 solving bridge failed"); }
}
const SAFE = Object.freeze({
  role: "assistant", api: "anthropic-messages", provider: "asterion-p7-solving", model: "p7-solving", content: [],
  usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
  stopReason: "error", timestamp: 0,
});

class Decoder {
  #buffer = Buffer.alloc(0);
  push(chunk: Uint8Array): Frame[] {
    if (this.#buffer.length + chunk.length > P7_SOLVING_MAX_FRAME_BYTES + 4)
      throw Error("frame exceeds limit");
    this.#buffer = Buffer.concat([this.#buffer, chunk]);
    const frames: Frame[] = [];
    while (this.#buffer.length >= 4) {
      const size = this.#buffer.readUInt32BE();
      if (size > P7_SOLVING_MAX_FRAME_BYTES) throw Error("frame exceeds limit");
      if (this.#buffer.length < size + 4) break;
      frames.push(parse(this.#buffer.subarray(4, size + 4)));
      this.#buffer = this.#buffer.subarray(size + 4);
    }
    return frames;
  }
  finish(): void { if (this.#buffer.length) throw Error("truncated frame"); }
  toJSON(): Record<string, never> { return {}; }
  ["nodejs.util.inspect.custom"](): string { return "P7SolvingFrameDecoder {}"; }
}

/** Private inherited-FD bridge. Its process entry point requires an empty environment. */
export class P7SolvingBridge {
  #decoder = new Decoder();
  #inputSequence = 0;
  #outputSequence = 0;
  #identity: Identity | undefined;
  #session: PrimeP7SolvingSession | undefined;
  #phase: "new" | "opening" | "open" | "prompt" | "completed" | "cancelling" | "cancelled" | "closing" | "closed" | "failed" = "new";
  #models = new Map<string, Pending>();
  #tools = new Map<string, Pending>();
  #callbackCounter = 0;
  #requestIds = new Set<string>();
  #terminal = false;
  #activePrompt: string | undefined;
  readonly #socket: Socket;
  constructor(socket: Socket) { this.#socket = socket; }
  toJSON(): { phase: string } { return { phase: this.#phase }; }
  ["nodejs.util.inspect.custom"](): string { return `P7SolvingBridge { phase: ${this.#phase} }`; }
  async run(): Promise<void> {
    try {
      for await (const chunk of this.#socket)
        for (const frame of this.#decoder.push(chunk)) this.dispatch(frame);
      this.#decoder.finish();
      if (this.#phase !== "closed") throw Error("bridge EOF");
    } catch {
      await this.fail("bridge");
      throw new P7SolvingBridgeError();
    } finally { await this.dispose(); }
  }
  dispatch(frame: Frame): void {
    this.validate(frame);
    if (frame.kind === "model.response") return this.resolve(this.#models, frame, "message");
    if (frame.kind === "tool.response") return this.resolve(this.#tools, frame, "result");
    this.#requestIds.add(frame.request_id);
    if (frame.kind === "open") this.#phase = "opening";
    if (frame.kind === "prompt") { this.#phase = "prompt"; this.#activePrompt = frame.request_id; }
    if (frame.kind === "cancel") this.#phase = "cancelling";
    if (frame.kind === "close") this.#phase = "closing";
    void this.command(frame).catch(() => this.fail(frame.request_id));
  }
  private validate(frame: Frame): void {
    if (!record(frame) || !only(frame, KEYS) || frame.protocol !== P7_SOLVING_GATEWAY_PROTOCOL ||
      frame.runtime_id !== "prime.agent" || !Number.isSafeInteger(frame.generation) || frame.generation < 1 ||
      !opaque(frame.run_id) || !opaque(frame.session_id) || !opaque(frame.request_id) ||
      !Number.isSafeInteger(frame.sequence) || frame.sequence !== ++this.#inputSequence ||
      !record(frame.payload) || !kind(frame.kind)) throw Error("invalid bridge frame");
    const identity: Identity = { run_id: frame.run_id, session_id: frame.session_id, runtime_id: frame.runtime_id, generation: frame.generation };
    if (!this.#identity) {
      if (frame.kind !== "open") throw Error("bridge must open first");
      this.#identity = identity;
    } else if (!same(this.#identity, identity)) throw Error("bridge identity mismatch");
    if (frame.kind.endsWith("response")) {
      if (this.#phase !== "prompt") throw Error("unexpected bridge response");
      return;
    }
    if (this.#requestIds.has(frame.request_id)) throw Error("duplicate command request");
    if (this.#phase === "prompt" && frame.kind !== "cancel") throw Error("command interleaving is forbidden");
    const allowed =
      this.#phase === "new" ? frame.kind === "open" :
      this.#phase === "open" ? ["prompt", "cancel", "close"].includes(frame.kind) :
      this.#phase === "completed" || this.#phase === "cancelled" ? frame.kind === "close" :
      this.#phase === "prompt" ? frame.kind === "cancel" : false;
    if (!allowed) throw Error("invalid bridge phase");
  }
  private async command(frame: Frame): Promise<void> {
    if (frame.kind === "open") {
      if (!only(frame.payload, ["prime_source_root", "workspace"])) throw Error("invalid private payload");
      const root = absolute(frame.payload.prime_source_root);
      const workspace = absolute(frame.payload.workspace);
      const make = await eventStreamFactory(root);
      this.#session = await PrimeP7SolvingSession.open({
        primeSourceRoot: root, workspace,
        model: (model, context, options) => this.model(model, context, options, make),
        ipython: (id, input) => this.tool(id, input.code),
      });
      this.#phase = "open"; this.emit("ready", frame.request_id, {}); return;
    }
    if (frame.kind === "prompt") {
      const prompt = text(frame.payload, "prompt");
      const result = await this.current().prompt(prompt);
      if (this.#phase === "prompt") {
        this.#phase = "completed";
        const requestId = this.#activePrompt; this.#activePrompt = undefined;
        if (requestId) this.emit("command.result", requestId, { result });
      }
      return;
    }
    if (frame.kind === "cancel") {
      if (!only(frame.payload, [])) throw Error("invalid cancel payload");
      this.settle(Error("cancelled")); await this.current().cancel();
      const active = this.#activePrompt; this.#activePrompt = undefined;
      if (active) this.emit("command.result", active, { result: { lifecycle: "cancelled" } });
      this.#phase = "cancelled";
      this.emit("command.result", frame.request_id, { result: { lifecycle: "cancelled" } }); return;
    }
    if (frame.kind === "close") {
      if (!only(frame.payload, [])) throw Error("invalid close payload");
      this.settle(Error("closed")); const session = this.#session; this.#session = undefined;
      if (session) await session.close();
      this.emit("command.result", frame.request_id, { result: { lifecycle: "closed" } });
      this.#phase = "closed"; this.#socket.end(); return;
    }
    throw Error("invalid command");
  }
  private model(model: unknown, context: unknown, options: unknown, make: StreamFactory): PrimeSolvingAssistantMessageEventStream {
    const id = this.callback("model"); const stream = make();
    const response = new Promise<unknown>((resolve, reject) => this.#models.set(id, { resolve, reject }));
    void (async () => {
      try {
        this.emit("model.request", id, { model, context, options });
        const message = await response;
        if (!record(message) || message.role !== "assistant") throw Error("invalid assistant response");
        queueMicrotask(() => {
          stream.push({ type: "start", partial: { ...message, content: [] } });
          stream.push({ type: "done", reason: message.stopReason, message });
        });
      } catch (error) {
        const aborted = error instanceof Error && error.message === "cancelled";
        stream.push({ type: "error", reason: aborted ? "aborted" : "error", error: { ...SAFE, stopReason: aborted ? "aborted" : "error" } });
      }
    })();
    return stream;
  }
  private tool(toolCallId: string, code: string): Promise<unknown> {
    const id = this.callback("tool");
    return new Promise((resolve, reject) => {
      this.#tools.set(id, { resolve, reject });
      try { this.emit("tool.request", id, { tool_call_id: toolCallId, code }); }
      catch (error) { this.#tools.delete(id); reject(error instanceof Error ? error : Error("tool request failed")); }
    });
  }
  private resolve(map: Map<string, Pending>, frame: Frame, key: string): void {
    const pending = map.get(frame.request_id);
    if (!pending || !only(frame.payload, [key])) throw Error("unexpected bridge response");
    map.delete(frame.request_id); pending.resolve(frame.payload[key]);
  }
  private settle(error: Error): void {
    for (const pending of this.#models.values()) pending.reject(error);
    for (const pending of this.#tools.values()) pending.reject(error);
    this.#models.clear(); this.#tools.clear();
  }
  private callback(kind: "model" | "tool"): string {
    let id: string;
    do id = `bridge-${kind}-${++this.#callbackCounter}`;
    while (this.#requestIds.has(id) || this.#models.has(id) || this.#tools.has(id));
    this.#requestIds.add(id); return id;
  }
  private current(): PrimeP7SolvingSession {
    if (!this.#session) throw Error("bridge session unavailable"); return this.#session;
  }
  private emit(kind: "ready" | "model.request" | "tool.request" | "command.result" | "error", request_id: string, payload: Record<string, unknown>): void {
    if (!this.#identity || this.#phase === "closed" || this.#phase === "failed") throw Error("bridge unavailable");
    const body = Buffer.from(canonical({ protocol: P7_SOLVING_GATEWAY_PROTOCOL, ...this.#identity,
      sequence: ++this.#outputSequence, request_id, kind, payload: jsonValue(payload) }));
    if (body.length > P7_SOLVING_MAX_FRAME_BYTES) throw Error("frame exceeds limit");
    const header = Buffer.alloc(4); header.writeUInt32BE(body.length);
    this.#socket.write(Buffer.concat([header, body]));
  }
  private async fail(id: string): Promise<void> {
    if (this.#terminal) return; this.#terminal = true;
    try { this.emit("error", id, { code: "bridge_failed" }); } catch {}
    this.#phase = "failed"; this.settle(Error("failed")); await this.dispose(); this.#socket.destroy();
  }
  private async dispose(): Promise<void> {
    const session = this.#session; this.#session = undefined; this.settle(Error("closed"));
    if (session) await session.close();
  }
}

export function inheritedP7SolvingSocket(fd: number): Socket {
  if (!Number.isSafeInteger(fd) || fd < 3) throw Error("invalid inherited FD");
  return new Socket({ fd, readable: true, writable: true });
}
async function eventStreamFactory(root: string): Promise<StreamFactory> {
  const module = await import(pathToFileURL(join(root, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js")).href) as { createAssistantMessageEventStream?: StreamFactory };
  if (typeof module.createAssistantMessageEventStream !== "function") throw Error("Prime event stream factory is unavailable");
  return module.createAssistantMessageEventStream;
}
function parse(body: Buffer): Frame {
  let value: unknown; try { value = JSON.parse(body.toString("utf8")); } catch { throw Error("invalid frame JSON"); }
  if (!record(value) || canonical(value) !== body.toString("utf8")) throw Error("noncanonical frame");
  return value as Frame;
}
function canonical(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") { if (!Number.isFinite(value)) throw Error("nonfinite JSON"); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (!record(value)) throw Error("unsupported JSON");
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function jsonValue(value: unknown): unknown {
  const encoded = JSON.stringify(value); if (typeof encoded !== "string") throw Error("non-JSON bridge value"); return JSON.parse(encoded);
}
function record(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function only(value: Record<string, unknown>, keys: readonly string[]): boolean { return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)); }
function opaque(value: unknown): value is string { return typeof value === "string" && ID.test(value); }
function kind(value: unknown): value is Kind { return typeof value === "string" && ["open", "prompt", "cancel", "close", "model.response", "tool.response"].includes(value); }
function same(a: Identity, b: Identity): boolean { return a.run_id === b.run_id && a.session_id === b.session_id && a.runtime_id === b.runtime_id && a.generation === b.generation; }
function text(payload: Record<string, unknown>, key: string): string {
  if (!only(payload, [key]) || typeof payload[key] !== "string" || !payload[key]) throw Error("invalid private payload"); return payload[key];
}
function absolute(value: unknown): string { if (typeof value !== "string" || !isAbsolute(value)) throw Error("private path must be absolute"); return value; }
