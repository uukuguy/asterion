import { closeSync, read, write } from "node:fs";
import { TextDecoder } from "node:util";
import { discardContextWitnessEnvironment, registerContextWitnessFromEnvironment, type ContextWitness } from "./context-witness.js";
export { registerContextWitness, ContextWitness, composeSummarizationRequest, summarizeInstruction } from "./context-witness.js";
export { canonicalJson, projectPrimeContext, countRebuiltContext } from "./context-counter.js";
import {
  Array as TypeArray,
  Null as TypeNull,
  Number as TypeNumber,
  Object as TypeObject,
  String as TypeString,
  Union as TypeUnion,
  type Static,
} from "typebox";

export const PROTOCOL = "asterion.prime-ipython/v1";

const DEFAULT_CODE_CAP = 16 * 1024;
const DEFAULT_OUTPUT_CAP = 512 * 1024;
const DEFAULT_LINE_CAP = 1024 * 1024;
const DEFAULT_DEADLINE_MS = 60_000;
const FD_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_FD";
const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const RESULT_KEYS = ["output", "protocol", "request_id", "status", "type"];
const REQUEST_KEYS = ["code", "protocol", "request_id", "type"];
const METHOD_RESULT_KEYS = ["error", "params", "protocol", "request_id", "status", "type", "value"];
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

  async callMethod(
    requestId: string,
    method: string,
    params: unknown,
    signal?: AbortSignal,
  ): Promise<unknown> {
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
    await writeAll(
      this.#descriptor,
      Buffer.from(`${request}\n`, "utf8"),
    );
    const executeResult = await this.#withCancellation(
      this.#readResult(requestId),
      signal,
    );
    if (executeResult.type !== "method_result") {
      throw new Error("expected method_result, got " + executeResult.type);
    }
    if (executeResult.status === "error") {
      throw new Error(executeResult.output || "method call failed");
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(executeResult.output);
    } catch {
      parsed = executeResult.output;
    }
    return parsed;
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

export function toolNames(): string[] {
  return [
    "ipython", "p7_observe", "p7_status", "p7_mechanics_prior",
    "p7_tried_actions", "p7_last_outcome_summary", "p7_history", "p7_frame_at",
    "p7_act_checked", "p7_world_model", "p7_playbook", "p7_retrodiction_status",
    "p7_record_hypothesis",
  ];
}

interface MethodToolInput {
  level?: number;
}

interface ActCheckedInput {
  plan: unknown;
}

interface HistoryInput {
  start: number;
  limit: number;
}

interface FrameAtInput {
  sequence: number;
}

interface MethodTool {
  name: string;
  description: string;
  parameters: unknown;
  executionMode: "sequential";
  execute(
    id: string,
    input: unknown,
    signal?: AbortSignal,
  ): Promise<unknown>;
}

function makeMethodTool(
  bridge: IpythonBridge,
  name: string,
  description: string,
  inputType: unknown,
  method: string,
  inputKey?: string,
): MethodTool {
  return {
    name,
    description,
    parameters: inputType,
    executionMode: "sequential",
    execute: async (
      id: string,
      input: unknown,
      signal?: AbortSignal,
    ): Promise<unknown> => {
      const params = inputKey
        ? (input as Record<string, unknown> | null | undefined)?.[inputKey] ?? null
        : input;
      return await bridge.callMethod(id, method, params, signal);
    },
  };
}

export function createAppLevelTools(bridge: IpythonBridge): MethodTool[] {
  return [
    makeMethodTool(
      bridge,
      "p7_observe",
      "Read the current game state: available_actions, last settled frame, levels_completed, state, win_levels. Call this *first* on a new level. The framework also injects a component summary and untried-clicks list into your observation-no-change responses, so you don't need to call p7_components or p7_untried_clicks manually.",
      TypeObject({}, { additionalProperties: false }),
      "observe",
    ),
    makeMethodTool(
      bridge,
      "p7_status",
      "Read the broker status: actions_remaining, levels_completed, primitive_actions, target_level, terminal_reason.",
      TypeObject({}, { additionalProperties: false }),
      "status",
    ),
    makeMethodTool(
      bridge,
      "p7_mechanics_prior",
      "Read bounded mechanics evidence inferred from prior actions.",
      TypeObject({}, { additionalProperties: false }),
      "mechanics_prior",
    ),
    makeMethodTool(
      bridge,
      "p7_tried_actions",
      "Enumerate every (level, action, position) tuple you have dispatched this run, with counts. Position is {\"x\": int, \"y\": int} for ACTION6 clicks and None for direction/interact actions. Cross-run: the broker records prefix-replay actions too, so this view spans prior verified levels. Call this before dispatching a probe you are unsure about; if the same (action, position) tuple already has a non-zero count at this level, the broker has already observed its outcome.",
      TypeObject(
        {
          level: TypeUnion([
            TypeNumber({ minimum: 0 }),
            TypeNull(),
          ]),
        },
        { additionalProperties: false },
      ),
      "tried_actions",
      "level",
    ),
    makeMethodTool(
      bridge,
      "p7_last_outcome_summary",
      "Aggregate per-action counts for the current run, split into {\"attempts\": {action: count}, \"no_effect\": {action: count}}. Useful for spotting an action that has been attempted many times at this level with no observed frame change.",
      TypeObject(
        {
          level: TypeUnion([
            TypeNumber({ minimum: 0 }),
            TypeNull(),
          ]),
        },
        { additionalProperties: false },
      ),
      "last_outcome_summary",
      "level",
    ),
    makeMethodTool(
      bridge,
      "p7_history",
      "Read a page of session history records starting at index `start` with up to `limit` records.",
      TypeObject(
        {
          start: TypeNumber({ minimum: 0 }),
          limit: TypeNumber({ minimum: 1 }),
        },
        { additionalProperties: false },
      ),
      "history",
    ),
    makeMethodTool(
      bridge,
      "p7_frame_at",
      "Read the settled frame at history sequence `sequence`.",
      TypeObject(
        { sequence: TypeNumber({ minimum: 0 }) },
        { additionalProperties: false },
      ),
      "frame_at",
    ),
    makeMethodTool(
      bridge,
      "p7_act_checked",
      "Dispatch a checked batch of actions. `plan` is a list of {action, expect} dicts. Each action has a name and data object. Each expect must contain exactly one falsifiable prediction: cell, frame_sha256, a strictly higher levels_completed, or state WIN/GAME_OVER. Never send an empty expect or the current levels_completed value. The broker stops at first prediction mismatch / no-effect / unavailable action.",
      TypeObject(
        {
          plan: TypeArray(
            TypeObject({
              action: TypeObject({
                name: TypeString({ pattern: "^(RESET|ACTION[1-7])$" }),
                data: TypeUnion([
                  TypeObject({}, { additionalProperties: false }),
                  TypeObject(
                    {
                      x: TypeNumber({ minimum: 0, maximum: 63 }),
                      y: TypeNumber({ minimum: 0, maximum: 63 }),
                    },
                    { additionalProperties: false },
                  ),
                ]),
              }),
              expect: TypeUnion([
                TypeObject(
                  {
                    cell: TypeObject({
                      x: TypeNumber({ minimum: 0, maximum: 63 }),
                      y: TypeNumber({ minimum: 0, maximum: 63 }),
                      value: TypeNumber({ minimum: 0, maximum: 255 }),
                    }),
                  },
                  { additionalProperties: false },
                ),
                TypeObject(
                  { frame_sha256: TypeString({ minLength: 1 }) },
                  { additionalProperties: false },
                ),
                TypeObject(
                  { levels_completed: TypeNumber({ minimum: 1 }) },
                  { additionalProperties: false },
                ),
                TypeObject(
                  { state: TypeString({ pattern: "^(WIN|GAME_OVER)$" }) },
                  { additionalProperties: false },
                ),
              ]),
            }),
          ),
        },
        { additionalProperties: false },
      ),
      "act_checked",
    ),
    makeMethodTool(
      bridge,
      "p7_world_model",
      "Read the bounded same-game world model projection.",
      TypeObject({}, { additionalProperties: false }),
      "world_model",
    ),
    makeMethodTool(
      bridge,
      "p7_playbook",
      "Read the bounded same-game Playbook projection.",
      TypeObject({ level: TypeUnion([TypeNumber({ minimum: 0 }), TypeNull()]) }, { additionalProperties: false }),
      "playbook",
      "level",
    ),
    makeMethodTool(
      bridge,
      "p7_retrodiction_status",
      "Read scalar transition-model verification status.",
      TypeObject({}, { additionalProperties: false }),
      "retrodiction_status",
    ),
    makeMethodTool(
      bridge,
      "p7_record_hypothesis",
      "Submit one canonical mechanism hypothesis and one distinguishing probe.",
      TypeObject({
        layer: TypeString({ minLength: 1 }),
        key: TypeString({ minLength: 1 }),
        value: TypeObject({}, { additionalProperties: true }),
      }, { additionalProperties: false }),
      "record_hypothesis",
    ),
  ];
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
    for (const tool of createAppLevelTools(bridge)) {
      pi.registerTool(tool as unknown as ReturnType<typeof createIpythonTool>);
    }
  } catch {
    witness?.close();
    discardContextWitnessEnvironment();
    try {
      if (descriptor !== undefined) closeSync(descriptor);
    } catch {}
    throw unavailable();
  }
}
