import { closeSync, read, write } from "node:fs";
import { TextDecoder } from "node:util";
import { Object as TypeObject, String as TypeString } from "typebox";
import { memoryRecord } from "./context-memory.js";
export const PROTOCOL = "asterion.prime-ipython/v1";

const DEFAULT_CODE_CAP = 16 * 1024;
const DEFAULT_OUTPUT_CAP = 64 * 1024;
const DEFAULT_LINE_CAP = 256 * 1024;
const DEFAULT_DEADLINE_MS = 60_000;
const FD_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_FD";
const OUTPUT_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_OUTPUT_BYTES";
// Pi passes OpenAI's call_id|item_id verbatim. Require the actual end of
// input as JavaScript's bare $ also matches before a final newline.
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const RESULT_KEYS = ["output", "protocol", "request_id", "status", "type"];
const REQUEST_KEYS = ["code", "protocol", "request_id", "type"];
const METHOD_REQUEST_KEYS = ["method", "params", "protocol", "request_id", "type"];

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
  type: "result" | "method_result";
  status: ResultStatus;
  output: string;
}

export interface IpythonToolResult {
  content: Array<{ type: "text"; text: string }>;
  details: Record<string, unknown>;
  isError?: boolean;
}

export type ToolExecutionMode = "sequential" | "parallel";

export const IPYTHON_PARAMETERS = TypeObject(
  { code: TypeString({ minLength: 1 }) },
  { additionalProperties: false },
);

interface BridgeOptions {
  maxCodeBytes?: number;
  maxOutputBytes?: number;
  maxLineBytes?: number;
  deadlineMs?: number;
}

export function unavailable(): Error {
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

export function descriptorFromEnvironment(): number {
  const raw = process.env[FD_ENVIRONMENT];
  delete process.env[FD_ENVIRONMENT];
  if (raw === undefined || !/^[1-9][0-9]*$/.test(raw)) throw unavailable();
  const descriptor = Number(raw);
  if (!Number.isSafeInteger(descriptor) || descriptor < 3) throw unavailable();
  return descriptor;
}

export function bridgeOptionsFromEnvironment(): BridgeOptions {
  const raw = process.env[OUTPUT_ENVIRONMENT];
  delete process.env[OUTPUT_ENVIRONMENT];
  if (raw === undefined) return {};
  if (!/^[1-9][0-9]*$(?![\s\S])/.test(raw)) throw unavailable();
  const maxOutputBytes = Number(raw);
  // JSON can escape one output byte as six ASCII bytes. Keep protocol and
  // request identity overhead outside the application's exact output capacity.
  const maxLineBytes = Math.max(DEFAULT_LINE_CAP, 6 * maxOutputBytes + 8192);
  if (!Number.isSafeInteger(maxOutputBytes) || maxOutputBytes < 256
    || !Number.isSafeInteger(maxLineBytes)) throw unavailable();
  return { maxOutputBytes, maxLineBytes };
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
  #methodTail: Promise<void> = Promise.resolve();

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
      if (response.type !== "result" || response.status === "uncertain") throw unavailable();
      let output = response.output;
      if (response.status === "error") {
        // A settled cell rejection does not invalidate the actor's shared FD.
        // Preserve genuine kernel metadata; redact non-kernel host failures.
        let metadata: unknown;
        try { metadata = JSON.parse(output); } catch { metadata = undefined; }
        if (typeof metadata !== "object" || metadata === null || Array.isArray(metadata)
          || !["python-error", "interrupted", "lost"].includes((metadata as Record<string, unknown>).execution_status as string)) {
          output = JSON.stringify({execution_status: "python-error", error: "IPython cell rejected"});
        }
      }
      return {
        content: [{ type: "text", text: output }],
        details: {},
      };
    } catch {
      if (possiblyDispatched) this.#poison();
      throw Object.assign(unavailable(),{context_effect:possiblyDispatched?'unknown':'settled'});
    } finally {
      this.#active = false;
    }
  }

  async #exchange(raw: Buffer, requestId: string): Promise<ExecuteResult> {
    await writeAll(this.#descriptor, raw);
    return await this.#readResult(requestId);
  }

  async callMethod(
    requestId: string,
    method: string,
    params: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
    let release!: () => void;
    const previous = this.#methodTail;
    this.#methodTail = new Promise<void>((resolve) => { release = resolve; });
    let waitingForPrevious = true;
    let possiblyDispatched = false;
    let applicationError: Error | undefined;
    try {
      await this.#withCancellation(previous, signal);
      waitingForPrevious = false;
      if (this.#closed || signal?.aborted === true) throw unavailable();
      const request = JSON.stringify(
        {
          method,
          params,
          protocol: PROTOCOL,
          request_id: requestId,
          type: "method_call",
        },
        (_key: string, value: unknown): unknown =>
          typeof value === "bigint" ? value.toString() : value,
      );
      const raw = Buffer.from(`${request}\n`, "utf8");
      if (raw.length > this.#maxLineBytes) throw unavailable();
      possiblyDispatched = true;
      try {
        await this.#withCancellation(writeAll(this.#descriptor, raw), signal);
      } catch {
        this.#poison();
        throw unavailable();
      }
      let executeResult: ExecuteResult;
      try {
        executeResult = await this.#withCancellation(
          this.#readResult(requestId),
          signal,
        );
      } catch {
        // A timed-out or malformed response leaves the single descriptor
        // unreadable. Close it so a late result cannot poison a later call.
        this.#poison();
        throw unavailable();
      }
      if (executeResult.type !== "method_result") {
        this.#poison();
        throw new Error("expected method_result, got " + executeResult.type);
      }
      if (executeResult.status === "error") {
        // A validated application rejection is recoverable. Keep the bridge
        // usable so cognition can repair its payload and retry.
        applicationError = new Error(executeResult.output || "method call failed");
        throw applicationError;
      }
      if (executeResult.status !== "ok") {
        this.#poison();
        throw new Error("method call was uncertain");
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(executeResult.output);
      } catch {
        parsed = executeResult.output;
      }
      return parsed;
    } catch (error) {
      if (applicationError !== undefined) throw Object.assign(applicationError,{context_effect:'settled'});
      if (waitingForPrevious || possiblyDispatched) this.#poison();
      throw Object.assign(unavailable(),{context_effect:possiblyDispatched?'unknown':'settled'});
    } finally {
      release();
    }
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
      (result.type !== "result" && result.type !== "method_result") ||
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

export interface MethodTool {
  name: string;
  label: string;
  description: string;
  parameters: unknown;
  executionMode?: ToolExecutionMode;
  execute(
    id: string,
    input: unknown,
    signal?: AbortSignal,
    onUpdate?: unknown,
    context?: unknown,
  ): Promise<AppToolResult>;
}

export interface AppToolResult {
  content: Array<{ type: "text"; text: string }>;
  details: unknown;
  isError?: boolean;
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
      input: unknown,
      signal?: AbortSignal,
    ): Promise<IpythonToolResult> => {
      const code = memoryRecord(input)?.code;
      if(typeof code!=='string') throw unavailable();
      try {
        const result=await bridge.execute(id,code,signal);
        let metadata:Record<string,unknown>|undefined;
        try {metadata=memoryRecord(JSON.parse(result.content[0]?.text??''));} catch {}
        if(metadata && ['python-error','interrupted','lost'].includes(String(metadata.execution_status))
          && typeof metadata.generation==='string' && typeof metadata.stdout==='string' && Array.isArray(metadata.kernel_exports)) {
          return {...result,details:{...result.details,context_interaction:{version:'asterion.prime-context-interaction/v1',
            effect:metadata.execution_status==='python-error'?'settled':'unknown',feedback:'negative'}}};
        }
        return result;
      } catch(error) {
        return {content:[{type:'text',text:unavailable().message}],isError:true,details:{context_interaction:{version:'asterion.prime-context-interaction/v1',
          effect:memoryRecord(error)?.context_effect==='settled'?'settled':'unknown',feedback:'negative'}}};
      }
    },
  };
}
