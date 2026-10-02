import { closeSync, read, write } from "node:fs";
import { TextDecoder } from "node:util";
import { discardContextWitnessEnvironment, registerContextWitnessFromEnvironment, type ContextWitness } from "./context-witness.js";
export { registerContextWitness, ContextWitness, composeSummarizationRequest, summarizeInstruction } from "./context-witness.js";
export { canonicalJson, projectPrimeContext, countRebuiltContext } from "./context-counter.js";
import {
  Array as TypeArray,
  Integer as TypeInteger,
  Null as TypeNull,
  Number as TypeNumber,
  Object as TypeObject,
  String as TypeString,
  Union as TypeUnion,
  Optional as TypeOptional,
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

const EMPTY_PARAMETERS = TypeObject({}, { additionalProperties: false });
const LEVEL_PARAMETERS = TypeObject(
  {
    level: TypeOptional(TypeUnion([
      TypeInteger({ minimum: 0 }),
      TypeNull(),
    ])),
  },
  { additionalProperties: false },
);
const HISTORY_PARAMETERS = TypeObject(
  {
    start: TypeNumber({ minimum: 0 }),
    limit: TypeNumber({ minimum: 1 }),
  },
  { additionalProperties: false },
);
const FRAME_PARAMETERS = TypeObject(
  { sequence: TypeNumber({ minimum: 0 }) },
  { additionalProperties: false },
);
const HYPOTHESIS_PARAMETERS = TypeObject(
  {
    layer: TypeString({ minLength: 1 }),
    key: TypeString({ minLength: 1 }),
    value: TypeObject(
      {
        mechanism: TypeObject({}, { additionalProperties: true }),
        probe: TypeObject({}, { additionalProperties: true }),
        dependencies: TypeArray(TypeString()),
      },
      { additionalProperties: false },
    ),
  },
  { additionalProperties: false },
);
const PROMOTION_PARAMETERS = TypeObject(
  {
    key: TypeString({ minLength: 1 }),
    evidence_kind: TypeString({ minLength: 1 }),
  },
  { additionalProperties: false },
);

interface MethodTool {
  name: string;
  label: string;
  description: string;
  parameters: unknown;
  execute(
    id: string,
    input: unknown,
    signal?: AbortSignal,
  ): Promise<AppToolResult>;
}

interface AppToolResult {
  content: Array<{ type: "text"; text: string }>;
  details: unknown;
}

interface AppToolSpec {
  name: string;
  method: string;
  description: string;
  parameters: unknown;
  inputKey?: string;
}

const P7_TOOL_SPECS: readonly AppToolSpec[] = Object.freeze([
  {
    name: "p7_act_checked",
    method: "act_checked",
    description:
      "Dispatch a checked batch of actions. `plan` is a list of {action, expect} dicts. "
      + "The broker stops at the first prediction mismatch / no-effect / unavailable action. "
      + "Read feedback and learning_hint in the result: changed_cell_count and changed_cells describe observed frame effects. A frame change does not prove objective progress; only an increased levels_completed or authoritative terminal state does. Use the effects to form the next falsifiable probe. "
      + "If the result has stop_reason 'invalid-checked-plan', do not submit another batch: "
      + "inspect the settled observation once, then use a one-item probe or RESET with one valid expect object.",
    parameters: TypeObject(
      {
        plan: TypeArray(
          TypeObject({ action: TypeObject({}), expect: TypeObject({}) }),
        ),
      },
      { additionalProperties: false },
    ),
  },
  {
    name: "p7_action_effects",
    method: "action_effects",
    description: "Read bounded per-action effect summaries learned in this run.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_cognition",
    method: "cognition",
    description: "Read advisory type cognition and exact-game experience.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_cognition_update",
    method: "cognition_update",
    description:
      "Propose or analyze semantic game-cognition hypotheses. Use {op, proposal|experiment|analysis|reason}; this updates the persisted language ledger only and never dispatches an action or grants execution authority.",
    parameters: TypeObject(
      { payload: TypeObject({}) },
      { additionalProperties: false },
    ),
  },
  {
    name: "p7_counterfactual_search",
    method: "counterfactual_search",
    description: "Compare candidate mechanics and subgoal progress without dispatching actions.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_frame_at",
    method: "frame_at",
    description: "Read the settled frame at history sequence `sequence`.",
    parameters: FRAME_PARAMETERS,
  },
  {
    name: "p7_game_mechanics",
    method: "game_mechanics",
    description: "Read persistent game-wide mechanisms; this is advisory memory only.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_history",
    method: "history",
    description: "Read a page of session history records starting at index `start` with up to `limit` records.",
    parameters: HISTORY_PARAMETERS,
  },
  {
    name: "p7_last_outcome_summary",
    method: "last_outcome_summary",
    description: "Read bounded per-action outcome counts for one level or the whole run.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_mechanism_candidates",
    method: "mechanism_candidates",
    description: "Read mechanism candidates and their evidence lifecycle.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_mechanics_prior",
    method: "mechanics_prior",
    description: "Read bounded mechanics evidence inferred from prior actions. This is evidence for reasoning, not a route or action prescription.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_model_search",
    method: "model_search",
    description: "Search a verified same-game mechanism without dispatching actions.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_observation_state",
    method: "observation_state",
    description: "Read the unified immutable observation with optional game metadata.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_observe",
    method: "observe",
    description: "Read the current observation: available_actions, settled frame or animation frames, levels_completed, state, win_levels, tried_summary, learning_hint, and remaining action budget. A changed_cell_count in action feedback does not prove objective progress while levels_completed is unchanged. Use feedback and the settled frame to form the next falsifiable probe. Call this after a level boundary or when an action result omitted the board you need.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_playbook",
    method: "playbook",
    description: "Read the bounded same-game Playbook projection.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_probe_plan",
    method: "probe_plan",
    description: "Read one safe probe suggestion without dispatching it.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_promote_hypothesis",
    method: "promote_hypothesis",
    description: "Promote a visual candidate only after broker-verified action evidence.",
    parameters: PROMOTION_PARAMETERS,
  },
  {
    name: "p7_record_hypothesis",
    method: "record_hypothesis",
    description: "Submit one bounded hypothesis with an application-owned probe.",
    parameters: HYPOTHESIS_PARAMETERS,
  },
  {
    name: "p7_retrodiction_status",
    method: "retrodiction_status",
    description: "Read scalar transition-model verification status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_simulator_status",
    method: "simulator_status",
    description: "Read simulator coverage and certificate status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_status",
    method: "status",
    description: "Read the current action budget and terminal status.",
    parameters: EMPTY_PARAMETERS,
  },
  {
    name: "p7_tried_actions",
    method: "tried_actions",
    description: "Enumerate every dispatched action and its bounded count for one level or the whole run.",
    parameters: LEVEL_PARAMETERS,
    inputKey: "level",
  },
  {
    name: "p7_world_model",
    method: "world_model",
    description: "Read the bounded same-game confirmed model projection.",
    parameters: EMPTY_PARAMETERS,
  },
]);

export function toolNames(): string[] {
  return ["ipython", ...P7_TOOL_SPECS.map((spec) => spec.name)].sort();
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
    label: name,
    description,
    parameters: inputType,
    execute: async (
      id: string,
      input: unknown,
      signal?: AbortSignal,
    ): Promise<AppToolResult> => {
      const params = inputKey
        ? (input as Record<string, unknown> | null | undefined)?.[inputKey] ?? null
        : input;
      const result = await bridge.callMethod(id, method, params, signal);
      let text: string;
      try {
        const serialized = JSON.stringify(result);
        text = serialized === undefined ? String(result) : serialized;
      } catch {
        text = String(result);
      }
      return {
        content: [{ type: "text", text }],
        details: result,
      };
    },
  };
}

export function createAppLevelTools(bridge: IpythonBridge): MethodTool[] {
  return [...P7_TOOL_SPECS]
    .sort((left, right) => left.name < right.name ? -1 : left.name > right.name ? 1 : 0)
    .map((spec) =>
    makeMethodTool(
      bridge,
      spec.name,
      spec.description,
      spec.parameters,
      spec.method,
      spec.inputKey,
    )
  );
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
