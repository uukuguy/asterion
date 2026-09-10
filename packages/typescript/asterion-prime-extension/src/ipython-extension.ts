import { closeSync, read, write } from "node:fs";
import { TextDecoder } from "node:util";
import { discardContextWitnessEnvironment, registerContextWitnessFromEnvironment, type ContextWitness } from "./context-witness.js";
export { registerContextWitness, ContextWitness } from "./context-witness.js";
export { canonicalJson, projectPrimeContext, countRebuiltContext } from "./context-counter.js";
import {
  Object as TypeObject,
  String as TypeString,
  type Static,
} from "typebox";

export const PROTOCOL = "asterion.prime-ipython/v1";

const DEFAULT_CODE_CAP = 16 * 1024;
const DEFAULT_OUTPUT_CAP = 64 * 1024;
const DEFAULT_LINE_CAP = 128 * 1024;
const DEFAULT_DEADLINE_MS = 60_000;
const FD_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_FD";
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const RESULT_KEYS = ["output", "protocol", "request_id", "status", "type"];
const REQUEST_KEYS = ["code", "protocol", "request_id", "type"];

type ResultStatus = "ok" | "error" | "uncertain";

interface ExecuteRequest {
  protocol: typeof PROTOCOL;
  request_id: string;
  type: "execute";
  code: string;
}

interface ExecuteResult {
  protocol: typeof PROTOCOL;
  request_id: string;
  type: "result";
  status: ResultStatus;
  output: string;
}

export interface IpythonToolResult {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, never>;
}

export const IPYTHON_PARAMETERS = TypeObject(
  { code: TypeString({ minLength: 1 }) },
  { additionalProperties: false },
);

type IpythonInput = Static<typeof IPYTHON_PARAMETERS>;

interface BridgeOptions {
  maxCodeBytes?: number;
  maxOutputBytes?: number;
  maxLineBytes?: number;
  deadlineMs?: number;
}

function unavailable(): Error {
  return new Error("Asterion ipython bridge is unavailable");
}

function byteLength(value: string): number {
  return Buffer.byteLength(value, "utf8");
}

function isWellFormed(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const unit = value.charCodeAt(index);
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const following = value.charCodeAt(index + 1);
      if (following < 0xdc00 || following > 0xdfff) return false;
      index += 1;
    } else if (unit >= 0xdc00 && unit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function exactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  return JSON.stringify(Object.keys(value).sort()) === JSON.stringify(expected);
}

function positiveLimit(value: number | undefined, fallback: number): number {
  const selected = value ?? fallback;
  if (!Number.isSafeInteger(selected) || selected <= 0) throw unavailable();
  return selected;
}

function descriptorFromEnvironment(): number {
  const raw = process.env[FD_ENVIRONMENT];
  delete process.env[FD_ENVIRONMENT];
  if (raw === undefined || !/^[1-9][0-9]*$/.test(raw)) throw unavailable();
  const descriptor = Number(raw);
  if (!Number.isSafeInteger(descriptor) || descriptor < 3) throw unavailable();
  return descriptor;
}

function readChunk(descriptor: number, size: number): Promise<Buffer> {
  return new Promise((resolveRead, reject) => {
    const buffer = Buffer.allocUnsafe(size);
    const attempt = (): void => {
      read(descriptor, buffer, 0, size, null, (error, bytesRead) => {
        if (error !== null) {
          if (error.code === "EAGAIN" || error.code === "EWOULDBLOCK") {
            setTimeout(attempt, 1);
            return;
          }
          reject(error);
          return;
        }
        resolveRead(buffer.subarray(0, bytesRead));
      });
    };
    attempt();
  });
}

function writeAll(descriptor: number, value: Buffer): Promise<void> {
  return new Promise((resolveWrite, reject) => {
    let offset = 0;
    const next = (): void => {
      write(descriptor, value, offset, value.length - offset, null, (error, count) => {
        if (error?.code === "EAGAIN" || error?.code === "EWOULDBLOCK") {
          setTimeout(next, 1);
          return;
        }
        if (error !== null || count <= 0) {
          reject(error ?? unavailable());
          return;
        }
        offset += count;
        if (offset === value.length) resolveWrite();
        else next();
      });
    };
    next();
  });
}

export class IpythonBridge {
  readonly #descriptor: number;
  readonly #maxCodeBytes: number;
  readonly #maxOutputBytes: number;
  readonly #maxLineBytes: number;
  readonly #deadlineMs: number;
  readonly #seen = new Set<string>();
  #active = false;
  #closed = false;
  #pending = Buffer.alloc(0);

  constructor(descriptor: number, options: BridgeOptions = {}) {
    if (!Number.isSafeInteger(descriptor) || descriptor < 3) throw unavailable();
    this.#descriptor = descriptor;
    this.#maxCodeBytes = positiveLimit(options.maxCodeBytes, DEFAULT_CODE_CAP);
    this.#maxOutputBytes = positiveLimit(options.maxOutputBytes, DEFAULT_OUTPUT_CAP);
    this.#maxLineBytes = positiveLimit(options.maxLineBytes, DEFAULT_LINE_CAP);
    this.#deadlineMs = positiveLimit(options.deadlineMs, DEFAULT_DEADLINE_MS);
    if (this.#maxOutputBytes >= this.#maxLineBytes) throw unavailable();
  }

  async execute(
    requestId: string,
    code: string,
    signal?: AbortSignal,
  ): Promise<IpythonToolResult> {
    return await this.handle(
      { protocol: PROTOCOL, request_id: requestId, type: "execute", code },
      signal,
    );
  }

  async handle(value: unknown, signal?: AbortSignal): Promise<IpythonToolResult> {
    if (!this.#validRequest(value) || signal?.aborted === true) throw unavailable();
    const request = value as ExecuteRequest;
    if (this.#closed || this.#active || this.#seen.has(request.request_id)) {
      throw unavailable();
    }
    this.#active = true;
    this.#seen.add(request.request_id);
    let possiblyDispatched = false;
    try {
      const raw = Buffer.from(JSON.stringify({
        code: request.code,
        protocol: request.protocol,
        request_id: request.request_id,
        type: request.type,
      }) + "\n", "utf8");
      if (raw.length > this.#maxLineBytes) throw unavailable();
      possiblyDispatched = true;
      const response = await this.#withCancellation(
        this.#exchange(raw, request.request_id),
        signal,
      );
      if (response.status !== "ok") throw unavailable();
      return {
        content: [{ type: "text", text: response.output }],
        details: {},
      };
    } catch {
      if (possiblyDispatched) this.#poison();
      throw unavailable();
    } finally {
      this.#active = false;
    }
  }

  async #exchange(raw: Buffer, requestId: string): Promise<ExecuteResult> {
    await writeAll(this.#descriptor, raw);
    return await this.#readResult(requestId);
  }

  #validRequest(value: unknown): value is ExecuteRequest {
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const request = value as Record<string, unknown>;
    return exactKeys(request, REQUEST_KEYS) &&
      request.protocol === PROTOCOL &&
      request.type === "execute" &&
      typeof request.request_id === "string" &&
      IDENTIFIER.test(request.request_id) &&
      typeof request.code === "string" &&
      request.code.length > 0 &&
      isWellFormed(request.code) &&
      byteLength(request.code) <= this.#maxCodeBytes;
  }

  async #readResult(requestId: string): Promise<ExecuteResult> {
    while (true) {
      const newline = this.#pending.indexOf(10);
      if (newline >= 0) {
        const line = this.#pending.subarray(0, newline);
        const trailing = this.#pending.subarray(newline + 1);
        this.#pending = Buffer.alloc(0);
        if (trailing.length !== 0 || line.length === 0 || line.length > this.#maxLineBytes) {
          throw unavailable();
        }
        return this.#parseResult(line, requestId);
      }
      if (this.#pending.length > this.#maxLineBytes) throw unavailable();
      const remaining = this.#maxLineBytes + 1 - this.#pending.length;
      const chunk = await readChunk(this.#descriptor, Math.min(4096, remaining));
      if (chunk.length === 0) throw unavailable();
      this.#pending = Buffer.concat([this.#pending, chunk]);
    }
  }

  #parseResult(raw: Buffer, requestId: string): ExecuteResult {
    let value: unknown;
    try {
      if (raw.includes(13)) throw unavailable();
      value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
    } catch {
      throw unavailable();
    }
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw unavailable();
    }
    const result = value as Record<string, unknown>;
    if (
      !exactKeys(result, RESULT_KEYS) ||
      result.protocol !== PROTOCOL ||
      result.request_id !== requestId ||
      result.type !== "result" ||
      !["ok", "error", "uncertain"].includes(result.status as string) ||
      typeof result.output !== "string" ||
      !isWellFormed(result.output) ||
      byteLength(result.output) > this.#maxOutputBytes
    ) {
      throw unavailable();
    }
    return result as unknown as ExecuteResult;
  }

  async #withCancellation<T>(operation: Promise<T>, signal?: AbortSignal): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abort: (() => void) | undefined;
    const stopped = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => reject(unavailable()), this.#deadlineMs);
      if (signal !== undefined) {
        abort = () => reject(unavailable());
        signal.addEventListener("abort", abort, { once: true });
        if (signal.aborted) abort();
      }
    });
    try {
      return await Promise.race([operation, stopped]);
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (signal !== undefined && abort !== undefined) {
        signal.removeEventListener("abort", abort);
      }
    }
  }

  #poison(): void {
    if (this.#closed) return;
    this.#closed = true;
    try {
      closeSync(this.#descriptor);
    } catch {
      return;
    }
  }
}

export function createIpythonBridge(
  descriptor: number,
  options: BridgeOptions = {},
): IpythonBridge {
  return new IpythonBridge(descriptor, options);
}

export function toolNames(): string[] {
  return ["ipython"];
}

export function createIpythonTool(bridge: IpythonBridge) {
  return {
    name: "ipython" as const,
    label: "ipython",
    description: "Execute one bounded persistent Python cell using only the symbols and imports permitted by the active application.",
    parameters: IPYTHON_PARAMETERS,
    executionMode: "sequential" as const,
    execute: async (
      id: string,
      input: IpythonInput,
      signal?: AbortSignal,
    ): Promise<IpythonToolResult> => {
      try {
        return await bridge.execute(id, input.code, signal);
      } catch {
        throw unavailable();
      }
    },
  };
}

interface ExtensionApi {
  registerTool(tool: ReturnType<typeof createIpythonTool>): void;
}

export function register(pi: ExtensionApi, dependencies?: unknown): void {
  let descriptor: number | undefined;
  let witness: ContextWitness | undefined;
  try {
    descriptor = descriptorFromEnvironment();
    if (typeof pi !== "object" || pi === null || typeof pi.registerTool !== "function") throw unavailable();
    const bridge = createIpythonBridge(descriptor);
    witness = registerContextWitnessFromEnvironment(pi, dependencies);
    pi.registerTool(createIpythonTool(bridge));
  } catch {
    witness?.close();
    discardContextWitnessEnvironment();
    try {
      if (descriptor !== undefined) closeSync(descriptor);
    } catch {}
    throw unavailable();
  }
}
