import { Socket } from "node:net";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

import { PrimeP1DevelopmentSession } from "./p1-development-session.js";
import type { PrimeSdkAssistantMessageEventStream } from "./p1-development-session.js";

export const P1_DEVELOPMENT_GATEWAY_PROTOCOL = "asterion.prime-p1-development-gateway/v1";
export const P1_DEVELOPMENT_MAX_FRAME_BYTES = 1024 * 1024;

type CommandKind = "open" | "prompt" | "cancel" | "close" | "model.response" | "tool.response";
type EventKind = "ready" | "model.request" | "tool.request" | "command.result" | "error";
type Identity = Readonly<{ run_id: string; session_id: string; runtime_id: "prime.agent"; generation: number }>;
type Frame = Readonly<Identity & { protocol: typeof P1_DEVELOPMENT_GATEWAY_PROTOCOL; sequence: number; request_id: string; kind: string; payload: Record<string, unknown> }>;

/** Incrementally decodes the bridge's fixed-size-prefixed canonical JSON transport. */
export class P1DevelopmentFrameDecoder {
  private buffered = Buffer.alloc(0);

  push(chunk: Uint8Array): Frame[] {
    this.buffered = Buffer.concat([this.buffered, chunk]);
    const frames: Frame[] = [];
    while (this.buffered.length >= 4) {
      const length = this.buffered.readUInt32BE(0);
      if (length > P1_DEVELOPMENT_MAX_FRAME_BYTES) throw new Error("frame exceeds limit");
      if (this.buffered.length < length + 4) break;
      const bytes = this.buffered.subarray(4, length + 4);
      this.buffered = this.buffered.subarray(length + 4);
      const value = parseCanonicalFrame(bytes);
      frames.push(value);
    }
    return frames;
  }

  finish(): void {
    if (this.buffered.length !== 0) throw new Error("truncated frame");
  }
}

/** Runs the development-only, inherited-FD bridge. It has no public gateway envelope. */
export class P1DevelopmentBridge {
  private readonly decoder = new P1DevelopmentFrameDecoder();
  private inboundSequence = 0;
  private outboundSequence = 0;
  private identity: Identity | undefined;
  private session: PrimeP1DevelopmentSession | undefined;
  private closed = false;
  private readonly pendingModels = new Map<string, (message: unknown) => void>();
  private readonly pendingTools = new Map<string, (result: unknown) => void>();
  private nextRequest = 0;

  constructor(private readonly stream: Socket) {}

  async run(): Promise<void> {
    try {
      for await (const chunk of this.stream) {
        for (const frame of this.decoder.push(chunk)) this.dispatch(frame);
      }
      this.decoder.finish();
      if (!this.closed) throw new Error("bridge EOF");
    } catch {
      await this.failClosed("bridge");
    } finally {
      await this.dispose();
    }
  }

  private dispatch(frame: Frame): void {
    this.validateInbound(frame);
    if (frame.kind === "model.response") return this.resolveModel(frame);
    if (frame.kind === "tool.response") return this.resolveTool(frame);
    void this.command(frame).catch(() => this.safeError(frame.request_id));
  }

  private validateInbound(frame: Frame): asserts frame is Frame & { kind: CommandKind } {
    if (!frame || typeof frame !== "object" || frame.protocol !== P1_DEVELOPMENT_GATEWAY_PROTOCOL || frame.runtime_id !== "prime.agent" || !Number.isSafeInteger(frame.generation) || frame.generation < 0 || !validText(frame.run_id) || !validText(frame.session_id) || !validText(frame.request_id) || !Number.isSafeInteger(frame.sequence) || frame.sequence !== ++this.inboundSequence || !isRecord(frame.payload)) throw new Error("invalid bridge frame");
    if (!isCommandKind(frame.kind)) throw new Error("invalid bridge command");
    const received: Identity = { run_id: frame.run_id, session_id: frame.session_id, runtime_id: frame.runtime_id, generation: frame.generation };
    if (!this.identity) {
      if (frame.kind !== "open") throw new Error("bridge must open first");
      this.identity = received;
    } else if (!sameIdentity(this.identity, received)) throw new Error("bridge identity mismatch");
  }

  private async command(frame: Frame): Promise<void> {
    switch (frame.kind) {
      case "open": {
        if (this.session) throw new Error("bridge already open");
        if (!hasOnly(frame.payload, ["prime_source_root", "workspace"])) throw new Error("invalid private payload");
        const root = pathAt(frame.payload, "prime_source_root");
        const workspace = pathAt(frame.payload, "workspace");
        const createStream = await loadAssistantEventStreamFactory(root);
        this.session = await PrimeP1DevelopmentSession.open({
          primeSourceRoot: root, workspace,
          model: (model, context, options) => this.modelStream(model, context, options, createStream),
          ipython: (toolCallId, input) => this.toolResult(toolCallId, input.code),
        });
        this.emit("ready", frame.request_id, {});
        return;
      }
      case "prompt": {
        const session = this.requireSession();
        const prompt = exactText(frame.payload, "prompt");
        const result = await session.prompt(prompt);
        this.emit("command.result", frame.request_id, { result });
        return;
      }
      case "cancel":
        await this.requireSession().cancel();
        this.emit("command.result", frame.request_id, { result: { lifecycle: "cancelled" } });
        return;
      case "close":
        {
          const session = this.session; this.session = undefined;
          if (session) await session.close();
        }
        this.emit("command.result", frame.request_id, { result: { lifecycle: "closed" } });
        this.closed = true;
        this.stream.end();
        return;
      default:
        throw new Error("invalid command direction");
    }
  }

  private modelStream(model: unknown, context: unknown, options: unknown, createStream: AssistantStreamFactory): PrimeSdkAssistantMessageEventStream {
    const requestId = this.requestId("model");
    const response = new Promise<unknown>((resolve) => this.pendingModels.set(requestId, resolve));
    const stream = createStream();
    void (async () => {
      try {
        this.emit("model.request", requestId, { model, context, options });
        const message = await response;
        if (!isRecord(message) || message.role !== "assistant") throw new Error("invalid assistant response");
        queueMicrotask(() => {
          stream.push({ type: "start", partial: { ...message, content: [] } });
          stream.push({ type: "done", reason: message.stopReason, message });
        });
      } catch (error) {
        stream.push({ type: "error", error: error instanceof Error ? error : new Error("model response rejected") });
      }
    })();
    return stream;
  }

  private toolResult(toolCallId: string, code: string): Promise<unknown> {
    const requestId = this.requestId("tool");
    return new Promise((resolve) => {
      this.pendingTools.set(requestId, resolve);
      this.emit("tool.request", requestId, { tool_call_id: toolCallId, code });
    });
  }

  private resolveModel(frame: Frame): void {
    const resolve = this.pendingModels.get(frame.request_id);
    if (!resolve || !hasOnly(frame.payload, ["message"])) throw new Error("unexpected model response");
    this.pendingModels.delete(frame.request_id);
    resolve(frame.payload.message);
  }

  private resolveTool(frame: Frame): void {
    const resolve = this.pendingTools.get(frame.request_id);
    if (!resolve || !hasOnly(frame.payload, ["result"])) throw new Error("unexpected tool response");
    this.pendingTools.delete(frame.request_id);
    resolve(frame.payload.result);
  }

  private emit(kind: EventKind, request_id: string, payload: Record<string, unknown>): void {
    if (!this.identity || this.closed) throw new Error("bridge unavailable");
    const body = canonicalJson({ protocol: P1_DEVELOPMENT_GATEWAY_PROTOCOL, ...this.identity, sequence: ++this.outboundSequence, request_id, kind, payload: jsonValue(payload) });
    const bytes = Buffer.from(body);
    if (bytes.length > P1_DEVELOPMENT_MAX_FRAME_BYTES) throw new Error("frame exceeds limit");
    const length = Buffer.alloc(4); length.writeUInt32BE(bytes.length);
    if (!this.stream.write(Buffer.concat([length, bytes]))) this.stream.once("drain", () => undefined);
  }

  private safeError(requestId: string): void {
    void this.failClosed(requestId);
  }

  private async failClosed(requestId: string): Promise<void> {
    try { this.emit("error", requestId, { code: "bridge_failed" }); } catch { /* no identity to bind */ }
    await this.dispose();
    this.stream.destroy();
  }

  private requireSession(): PrimeP1DevelopmentSession {
    if (!this.session || this.closed) throw new Error("bridge session unavailable");
    return this.session;
  }

  private requestId(prefix: "model" | "tool"): string { return `${prefix}-${++this.nextRequest}`; }

  private async dispose(): Promise<void> {
    const session = this.session; this.session = undefined;
    for (const resolve of this.pendingModels.values()) resolve(null);
    for (const resolve of this.pendingTools.values()) resolve(null);
    this.pendingModels.clear(); this.pendingTools.clear();
    if (session) await session.close();
    this.closed = true;
  }
}

export function inheritedP1DevelopmentSocket(fd: number): Socket {
  if (!Number.isSafeInteger(fd) || fd < 3) throw new Error("invalid inherited FD");
  return new Socket({ fd, readable: true, writable: true });
}

type AssistantStream = PrimeSdkAssistantMessageEventStream & { push(event: unknown): void };
type AssistantStreamFactory = () => AssistantStream;
async function loadAssistantEventStreamFactory(root: string): Promise<AssistantStreamFactory> {
  const module = await import(pathToFileURL(join(root, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js")).href) as { createAssistantMessageEventStream?: AssistantStreamFactory };
  if (typeof module.createAssistantMessageEventStream !== "function") throw new Error("Prime event stream factory is unavailable");
  return module.createAssistantMessageEventStream;
}

function parseCanonicalFrame(bytes: Buffer): Frame {
  let value: unknown;
  try { value = JSON.parse(bytes.toString("utf8")); } catch { throw new Error("invalid frame JSON"); }
  if (!isRecord(value) || canonicalJson(value) !== bytes.toString("utf8")) throw new Error("noncanonical frame");
  return value as Frame;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") { if (!Number.isFinite(value)) throw new Error("nonfinite JSON value"); return JSON.stringify(value); }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (!isRecord(value)) throw new Error("unsupported JSON value");
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
}
function jsonValue(value: unknown): unknown {
  const encoded = JSON.stringify(value);
  if (typeof encoded !== "string") throw new Error("non-JSON bridge value");
  return JSON.parse(encoded) as unknown;
}
function isRecord(value: unknown): value is Record<string, unknown> { return !!value && typeof value === "object" && !Array.isArray(value); }
function validText(value: unknown): value is string { return typeof value === "string" && value.length > 0 && value.length <= 256; }
function isCommandKind(value: string): value is CommandKind { return ["open", "prompt", "cancel", "close", "model.response", "tool.response"].includes(value); }
function sameIdentity(a: Identity, b: Identity): boolean { return a.run_id === b.run_id && a.session_id === b.session_id && a.runtime_id === b.runtime_id && a.generation === b.generation; }
function exactText(payload: Record<string, unknown>, key: string): string { if (!hasOnly(payload, [key]) || !validText(payload[key])) throw new Error("invalid private payload"); return payload[key]; }
function pathAt(payload: Record<string, unknown>, key: string): string { const value = payload[key]; if (!validText(value) || !isAbsolute(value)) throw new Error("private path must be absolute"); return value; }
function hasOnly(value: Record<string, unknown>, keys: readonly string[]): boolean { return Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key)); }
