import { Socket } from "node:net";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import { PrimeP5DevelopmentSession } from "./p5-development-session.js";
import type { PrimeSdkAssistantMessageEventStream } from "./p5-development-session.js";

export const P5_DEVELOPMENT_GATEWAY_PROTOCOL =
  "asterion.prime-p5-development-gateway/v1";
export const P5_DEVELOPMENT_MAX_FRAME_BYTES = 1024 * 1024;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const KEYS = [
  "generation",
  "kind",
  "payload",
  "protocol",
  "request_id",
  "run_id",
  "runtime_id",
  "sequence",
  "session_id",
];
type K =
  "open" | "prompt" | "feedback" | "cancel" | "close" | "model.response" | "tool.response";
type I = Readonly<{
  run_id: string;
  session_id: string;
  runtime_id: "prime.agent";
  generation: number;
}>;
type F = Readonly<
  I & {
    protocol: typeof P5_DEVELOPMENT_GATEWAY_PROTOCOL;
    sequence: number;
    request_id: string;
    kind: K;
    payload: Record<string, unknown>;
  }
>;
type Stream = PrimeSdkAssistantMessageEventStream & {
  push(event: unknown): void;
};
type Factory = () => Stream;
type Pending = { resolve(v: unknown): void; reject(e: Error): void };
export class P5DevelopmentBridgeError extends Error {
  constructor() {
    super("P2 development bridge failed");
  }
}
const SAFE = Object.freeze({
  role: "assistant",
  api: "anthropic-messages",
  provider: "asterion-p5-development",
  model: "p5-development",
  content: [],
  usage: {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
    totalTokens: 0,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  },
  stopReason: "error",
  timestamp: 0,
});
class Decoder {
  #b = Buffer.alloc(0);
  push(c: Uint8Array): F[] {
    this.#b = Buffer.concat([this.#b, c]);
    const o: F[] = [];
    while (this.#b.length >= 4) {
      const n = this.#b.readUInt32BE();
      if (n > P5_DEVELOPMENT_MAX_FRAME_BYTES)
        throw Error("frame exceeds limit");
      if (this.#b.length < n + 4) break;
      const x = this.#b.subarray(4, n + 4);
      this.#b = this.#b.subarray(n + 4);
      o.push(parse(x));
    }
    return o;
  }
  finish() {
    if (this.#b.length) throw Error("truncated frame");
  }
  toJSON() {
    return {};
  }
  ["nodejs.util.inspect.custom"]() {
    return "P5DevelopmentFrameDecoder {}";
  }
}
/** Development-only inherited-FD bridge. The child must be launched with an empty environment. */
export class P5DevelopmentBridge {
  #d = new Decoder();
  #in = 0;
  #out = 0;
  #i: I | undefined;
  #s: PrimeP5DevelopmentSession | undefined;
  #p:
    | "new"
    | "opening"
    | "open"
    | "prompt"
    | "cancelling"
    | "cancelled"
    | "closing"
    | "closed"
    | "failed" = "new";
  #m = new Map<string, Pending>();
  #t = new Map<string, Pending>();
  #n = 0;
  #ids = new Set<string>();
  #terminal = false;
  #activePrompt: string | undefined;
  #feedback: string | undefined;
  #promptCount = 0;
  #socket: Socket;
  constructor(socket: Socket) {
    this.#socket = socket;
  }
  toJSON() {
    return { phase: this.#p };
  }
  ["nodejs.util.inspect.custom"]() {
    return `P5DevelopmentBridge { phase: ${this.#p} }`;
  }
  async run(): Promise<void> {
    try {
      for await (const c of this.#socket)
        for (const f of this.#d.push(c)) this.dispatch(f);
      this.#d.finish();
      if (this.#p !== "closed") throw Error("bridge EOF");
    } catch {
      await this.fail("bridge");
      throw new P5DevelopmentBridgeError();
    } finally {
      await this.dispose();
    }
  }
  #validate(f: F) {
    if (
      !rec(f) ||
      !only(f, KEYS) ||
      f.protocol !== P5_DEVELOPMENT_GATEWAY_PROTOCOL ||
      f.runtime_id !== "prime.agent" ||
      !Number.isSafeInteger(f.generation) ||
      f.generation < 1 ||
      !opaque(f.run_id) ||
      !opaque(f.session_id) ||
      !opaque(f.request_id) ||
      !Number.isSafeInteger(f.sequence) ||
      f.sequence !== ++this.#in ||
      !rec(f.payload) ||
      !kind(f.kind)
    )
      throw Error("invalid bridge frame");
    const i: I = {
      run_id: f.run_id,
      session_id: f.session_id,
      runtime_id: f.runtime_id,
      generation: f.generation,
    };
    if (!this.#i) {
      if (f.kind !== "open") throw Error("bridge must open first");
      this.#i = i;
    } else if (!same(this.#i, i)) throw Error("bridge identity mismatch");
    if (f.kind.endsWith("response")) {
      if (this.#p !== "prompt") throw Error("unexpected bridge response");
      return;
    }
    if (this.#ids.has(f.request_id)) throw Error("duplicate command request");
    if (this.#p === "prompt" && f.kind !== "cancel")
      throw Error("command interleaving is forbidden");
    if (
      (this.#p === "new" && f.kind !== "open") ||
      (this.#p === "open" &&
        !(["prompt", "feedback", "cancel", "close"] as string[]).includes(f.kind)) ||
      !["new", "open", "prompt", "cancelled"].includes(this.#p) ||
      (this.#p === "cancelled" && f.kind !== "close")
    )
      throw Error("invalid bridge phase");
  }
  dispatch(f: F) {
    this.#validate(f);
    if (f.kind === "model.response") return this.resolve(this.#m, f, "message");
    if (f.kind === "tool.response") return this.resolve(this.#t, f, "result");
    this.#ids.add(f.request_id);
    if (f.kind === "open") this.#p = "opening";
    if (f.kind === "prompt") this.#p = "prompt";
    if (f.kind === "prompt") this.#activePrompt = f.request_id;
    if (f.kind === "cancel") this.#p = "cancelling";
    if (f.kind === "close") this.#p = "closing";
    void this.command(f).catch(() => this.fail(f.request_id));
  }
  async command(f: F) {
    if (f.kind === "open") {
      if (!only(f.payload, ["prime_source_root", "workspace"]))
        throw Error("invalid private payload");
      const root = abs(f.payload.prime_source_root),
        workspace = abs(f.payload.workspace),
        make = await factory(root);
      this.#s = await PrimeP5DevelopmentSession.open({
        primeSourceRoot: root,
        workspace,
        model: (m, c, o) => this.#model(m, c, o, make),
        ipython: (id, input) => this.#tool(id, input.code),
      });
      this.#p = "open";
      this.#activePrompt = undefined;
      this.emit("ready", f.request_id, {});
      return;
    }
    if (f.kind === "prompt") {
      const prompt = text(f.payload, "prompt");
      const feedback = this.#feedback;
      if (++this.#promptCount > 2 || (this.#promptCount === 2 && feedback === undefined))
        throw Error("invalid P5 development prompt flow");
      const r = await this.session().prompt(
        feedback === undefined ? prompt : `${feedback}\n${prompt}`,
      );
      this.#feedback = undefined;
      if (this.#p === "prompt") {
        this.#p = "open";
        this.#settleActivePrompt(r);
      }
      return;
    }
    if (f.kind === "feedback") {
      if (!only(f.payload, ["feedback"]) || this.#promptCount !== 1 || this.#feedback !== undefined)
        throw Error("invalid P5 development feedback");
      this.#feedback = text(f.payload, "feedback");
      this.emit("command.result", f.request_id, { result: {} });
      return;
    }
    if (f.kind === "cancel") {
      if (!only(f.payload, [])) throw Error("invalid cancel payload");
      this.settle(Error("cancelled"));
      await this.session().cancel();
      this.#settleActivePrompt({ lifecycle: "cancelled" });
      this.#p = "cancelled";
      this.emit("command.result", f.request_id, {
        result: { lifecycle: "cancelled" },
      });
      return;
    }
    if (f.kind === "close") {
      if (!only(f.payload, [])) throw Error("invalid close payload");
      this.settle(Error("closed"));
      const s = this.#s;
      this.#s = undefined;
      if (s) await s.close();
      this.emit("command.result", f.request_id, {
        result: { lifecycle: "closed" },
      });
      this.#p = "closed";
      this.#socket.end();
      return;
    }
    throw Error("invalid command");
  }
  #model(
    model: unknown,
    context: unknown,
    options: unknown,
    make: Factory,
  ): PrimeSdkAssistantMessageEventStream {
    const id = this.callback("model"),
      s = make(),
      r = new Promise<unknown>((resolve, reject) =>
        this.#m.set(id, { resolve, reject }),
      );
    void (async () => {
      try {
        this.emit("model.request", id, { model, context, options });
        const message = await r;
        if (!rec(message) || message.role !== "assistant")
          throw Error("invalid assistant response");
        queueMicrotask(() => {
          s.push({ type: "start", partial: { ...message, content: [] } });
          s.push({ type: "done", reason: message.stopReason, message });
        });
      } catch (e) {
        const aborted = e instanceof Error && e.message === "cancelled";
        s.push({
          type: "error",
          reason: aborted ? "aborted" : "error",
          error: { ...SAFE, stopReason: aborted ? "aborted" : "error" },
        });
      }
    })();
    return s;
  }
  #tool(tool_call_id: string, code: string): Promise<unknown> {
    const id = this.callback("tool");
    return new Promise((resolve, reject) => {
      this.#t.set(id, { resolve, reject });
      try {
        this.emit("tool.request", id, { tool_call_id, code });
      } catch (e) {
        this.#t.delete(id);
        reject(e instanceof Error ? e : Error("tool request failed"));
      }
    });
  }
  resolve(map: Map<string, Pending>, f: F, key: string) {
    const p = map.get(f.request_id);
    if (!p || !only(f.payload, [key]))
      throw Error("unexpected bridge response");
    map.delete(f.request_id);
    p.resolve(f.payload[key]);
  }
  settle(e: Error) {
    for (const p of this.#m.values()) p.reject(e);
    for (const p of this.#t.values()) p.reject(e);
    this.#m.clear();
    this.#t.clear();
  }
  #settleActivePrompt(result: unknown) {
    const requestId = this.#activePrompt;
    this.#activePrompt = undefined;
    if (requestId) this.emit("command.result", requestId, { result });
  }
  callback(k: "model" | "tool") {
    let id: string;
    do id = `bridge-${k}-${++this.#n}`;
    while (this.#ids.has(id) || this.#m.has(id) || this.#t.has(id));
    this.#ids.add(id);
    return id;
  }
  session() {
    if (!this.#s) throw Error("bridge session unavailable");
    return this.#s;
  }
  emit(
    kind:
      "ready" | "model.request" | "tool.request" | "command.result" | "error",
    request_id: string,
    payload: Record<string, unknown>,
  ) {
    if (!this.#i || this.#p === "closed" || this.#p === "failed")
      throw Error("bridge unavailable");
    const b = Buffer.from(
      canon({
        protocol: P5_DEVELOPMENT_GATEWAY_PROTOCOL,
        ...this.#i,
        sequence: ++this.#out,
        request_id,
        kind,
        payload: json(payload),
      }),
    );
    if (b.length > P5_DEVELOPMENT_MAX_FRAME_BYTES)
      throw Error("frame exceeds limit");
    const h = Buffer.alloc(4);
    h.writeUInt32BE(b.length);
    this.#socket.write(Buffer.concat([h, b]));
  }
  async fail(id: string) {
    if (this.#terminal) return;
    this.#terminal = true;
    try {
      this.emit("error", id, { code: "bridge_failed" });
    } catch {}
    this.#p = "failed";
    this.settle(Error("failed"));
    await this.dispose();
    this.#socket.destroy();
  }
  async dispose() {
    const s = this.#s;
    this.#s = undefined;
    this.settle(Error("closed"));
    if (s) await s.close();
  }
}
export function inheritedP5DevelopmentSocket(fd: number) {
  if (!Number.isSafeInteger(fd) || fd < 3) throw Error("invalid inherited FD");
  return new Socket({ fd, readable: true, writable: true });
}
async function factory(root: string): Promise<Factory> {
  const m = (await import(
    pathToFileURL(
      join(
        root,
        "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js",
      ),
    ).href
  )) as { createAssistantMessageEventStream?: Factory };
  if (typeof m.createAssistantMessageEventStream !== "function")
    throw Error("Prime event stream factory is unavailable");
  return m.createAssistantMessageEventStream;
}
function parse(b: Buffer): F {
  let v: unknown;
  try {
    v = JSON.parse(b.toString("utf8"));
  } catch {
    throw Error("invalid frame JSON");
  }
  if (!rec(v) || canon(v) !== b.toString("utf8"))
    throw Error("noncanonical frame");
  return v as F;
}
function canon(v: unknown): string {
  if (v === null || typeof v === "string" || typeof v === "boolean")
    return JSON.stringify(v);
  if (typeof v === "number") {
    if (!Number.isFinite(v)) throw Error("nonfinite JSON");
    return JSON.stringify(v);
  }
  if (Array.isArray(v)) return `[${v.map(canon).join(",")}]`;
  if (!rec(v)) throw Error("unsupported JSON");
  return `{${Object.keys(v)
    .sort()
    .map((k) => `${JSON.stringify(k)}:${canon(v[k])}`)
    .join(",")}}`;
}
function json(v: unknown) {
  const x = JSON.stringify(v);
  if (typeof x !== "string") throw Error("non-JSON bridge value");
  return JSON.parse(x) as unknown;
}
function rec(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}
function only(v: Record<string, unknown>, k: readonly string[]) {
  return (
    Object.keys(v).length === k.length && k.every((x) => Object.hasOwn(v, x))
  );
}
function opaque(v: unknown): v is string {
  return typeof v === "string" && ID.test(v);
}
function kind(v: unknown): v is K {
  return (
    typeof v === "string" &&
    [
      "open",
      "prompt",
      "feedback",
      "cancel",
      "close",
      "model.response",
      "tool.response",
    ].includes(v)
  );
}
function same(a: I, b: I) {
  return (
    a.run_id === b.run_id &&
    a.session_id === b.session_id &&
    a.runtime_id === b.runtime_id &&
    a.generation === b.generation
  );
}
function text(p: Record<string, unknown>, k: string) {
  if (!only(p, [k]) || typeof p[k] !== "string")
    throw Error("invalid private payload");
  return p[k] as string;
}
function abs(v: unknown) {
  if (typeof v !== "string" || !isAbsolute(v))
    throw Error("private path must be absolute");
  return v;
}
