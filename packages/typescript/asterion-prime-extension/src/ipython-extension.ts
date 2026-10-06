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
  Literal as TypeLiteral,
  type Static,
} from "typebox";

export const PROTOCOL = "asterion.prime-ipython/v1";

const DEFAULT_CODE_CAP = 16 * 1024;
const DEFAULT_OUTPUT_CAP = 64 * 1024;
const DEFAULT_LINE_CAP = 256 * 1024;
const DEFAULT_DEADLINE_MS = 60_000;
const FD_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_FD";
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
  details: Record<string, never>;
}

export type ToolExecutionMode = "sequential" | "parallel";

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
      if (applicationError !== undefined) throw applicationError;
      if (waitingForPrevious || possiblyDispatched) this.#poison();
      throw unavailable();
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
const COGNITION_PARAMETERS = TypeObject(
  {
    op: TypeString({ minLength: 1 }),
    proposal: TypeOptional(TypeObject({}, { additionalProperties: true })),
    experiment: TypeOptional(TypeObject({}, { additionalProperties: true })),
    analysis: TypeOptional(TypeObject({}, { additionalProperties: true })),
    reason: TypeOptional(TypeString({ minLength: 1 })),
  },
  { additionalProperties: false },
);

interface MethodTool {
  name: string;
  label: string;
  description: string;
  parameters: unknown;
  executionMode?: ToolExecutionMode;
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

const P7_LEGACY_TOOL_SPECS: readonly AppToolSpec[] = Object.freeze([
  {
    name: "p7_decision",
    method: "decision",
    description: "Before a significant action plan, record a concise public goal, observation basis, and expected feedback. Each field is nonempty and at most 600 characters. Returns the decision ID at the current observation; never grants execution authority. Do not include private reasoning, credentials, paths, or raw context.",
    parameters: TypeObject({
      goal: TypeString({ minLength: 1, maxLength: 600 }),
      basis: TypeString({ minLength: 1, maxLength: 600 }),
      expected: TypeString({ minLength: 1, maxLength: 600 }),
    }, { additionalProperties: false }),
  },
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
    parameters: COGNITION_PARAMETERS,
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
    name: "p7_planning_background",
    method: "planning_background",
    description:
      "Read the refreshable planning background combining semantic cognition, WorldMap, the current frame identity, and simulator status. It never dispatches actions or grants execution authority.",
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

const PUBLIC_TEXT = TypeString({ maxLength: 600 });
const EXPORT_ID = TypeString({ pattern: "^sha256:[0-9a-f]{64}$" });
const ID = TypeString({ pattern: "^[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,159}$" });
const TASK_PARAMETERS = TypeObject({
  goal: PUBLIC_TEXT, obstacles: TypeArray(PUBLIC_TEXT, { maxItems: 32 }), question: PUBLIC_TEXT,
  next_operation: TypeUnion([TypeLiteral("analyze"), TypeLiteral("model"), TypeLiteral("validate"), TypeLiteral("search"), TypeLiteral("probe"), TypeLiteral("execute")]),
  public_basis: PUBLIC_TEXT,
}, { additionalProperties: false });
const ACTION_LABEL_NAME = TypeUnion([
  TypeLiteral("ACTION1"), TypeLiteral("ACTION2"), TypeLiteral("ACTION3"), TypeLiteral("ACTION4"),
  TypeLiteral("ACTION5"), TypeLiteral("ACTION6"), TypeLiteral("ACTION7"), TypeLiteral("RESET"),
]);
const ACTION_LABEL_PARAMETERS = TypeUnion([
  TypeObject({
    action: ACTION_LABEL_NAME, label: TypeString({ minLength: 1, maxLength: 24, pattern: "\\S" }),
    purpose: TypeString({ minLength: 1, maxLength: 600, pattern: "\\S" }),
    confidence: TypeUnion([TypeLiteral("certain"), TypeLiteral("hypothesis")]),
    evidence_sequences: TypeArray(TypeInteger({ minimum: 0, maximum: 1000000000 }),
      { minItems: 1, maxItems: 32, uniqueItems: true }),
  }, { additionalProperties: false }),
  TypeObject({
    action: ACTION_LABEL_NAME, label: TypeNull(), purpose: PUBLIC_TEXT,
    confidence: TypeUnion([TypeLiteral("unknown"), TypeLiteral("conflict")]),
    evidence_sequences: TypeArray(TypeInteger({ minimum: 0, maximum: 1000000000 }),
      { maxItems: 32, uniqueItems: true }),
  }, { additionalProperties: false }),
]);
const WORLDMAP_PARAMETERS = TypeObject({
  description_zh: TypeString({ minLength: 1, maxLength: 8000 }),
  state_summary: PUBLIC_TEXT, rules: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  unknowns: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  competing_hypotheses: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  action_labels: TypeOptional(TypeArray(ACTION_LABEL_PARAMETERS, { maxItems: 8, uniqueItems: true,
    description: "Your current-level judgments from actual observations: write directly displayed short labels and purposes; use certain/hypothesis or null labels for unknown/conflict. Sort unique action IDs and each evidence list; evidence must reference this run at or before the current observation sequence. No UI semantic inference occurs." })),
}, { additionalProperties: false });
const CORRECTION_PARAMETERS = TypeObject({
  changed: TypeArray(PUBLIC_TEXT, { maxItems: 32 }), retained: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  counterexample_sequence: TypeOptional(TypeInteger({ minimum: 0 })),
}, { additionalProperties: false });

export const P7_WORKSPACE_PARAMETERS = TypeUnion([
  TypeObject({ op: TypeLiteral("read"), revision: TypeOptional(EXPORT_ID) }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("publish"), base_revision: EXPORT_ID, draft_export_id: EXPORT_ID }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("checkpoint"), revision: EXPORT_ID, state_export_id: TypeOptional(EXPORT_ID),
    frontier_export_id: TypeOptional(EXPORT_ID), analyzed_through: TypeInteger({ minimum: 0 }) }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral("focus"), task: TASK_PARAMETERS }, { additionalProperties: false }),
  TypeObject({ op: TypeLiteral('revise'), base_revision: EXPORT_ID, worldmap: WORLDMAP_PARAMETERS,
    task: TASK_PARAMETERS, evidence_sequences: TypeArray(TypeInteger({ minimum: 0 }), { minItems: 1, maxItems: 128, uniqueItems: true }),
    correction: CORRECTION_PARAMETERS }, { additionalProperties: false }),
]);
const ACTION_PARAMETERS = TypeUnion([
  TypeObject({ name: TypeUnion([TypeLiteral("RESET"), TypeLiteral("ACTION1"), TypeLiteral("ACTION2"), TypeLiteral("ACTION3"), TypeLiteral("ACTION4"), TypeLiteral("ACTION5"), TypeLiteral("ACTION7")]),
    data: TypeObject({}, { additionalProperties: false }) }, { additionalProperties: false }),
  TypeObject({ name: TypeLiteral("ACTION6"), data: TypeObject({ x: TypeInteger({ minimum: 0, maximum: 63 }),
    y: TypeInteger({ minimum: 0, maximum: 63 }) }, { additionalProperties: false }) }, { additionalProperties: false }),
]);
export const P7_EXECUTE_PLAN_PARAMETERS = TypeObject({
  plan_id: ID,
  start: TypeObject({ run_id: ID, attempt_id: ID, level: TypeInteger({ minimum: 1 }),
    sequence: TypeInteger({ minimum: 0 }), observation_sha256: EXPORT_ID }, { additionalProperties: false }),
  workspace_revision: EXPORT_ID, goal: PUBLIC_TEXT, purpose: TypeUnion([TypeLiteral("advance"), TypeLiteral("probe")]),
  assumptions: TypeArray(PUBLIC_TEXT, { maxItems: 32 }),
  steps: TypeArray(TypeObject({ action: ACTION_PARAMETERS, expect: TypeObject({
    cells: TypeOptional(TypeArray(TypeObject({ x: TypeInteger({ minimum: 0, maximum: 63 }),
      y: TypeInteger({ minimum: 0, maximum: 63 }), value: TypeInteger({ minimum: 0, maximum: 255 }) },
      { additionalProperties: false }), { minItems: 1, maxItems: 128 })),
    frame_sha256: TypeOptional(EXPORT_ID),
    state: TypeOptional(TypeUnion([TypeLiteral("NOT_FINISHED"), TypeLiteral("WIN"), TypeLiteral("GAME_OVER")])),
    levels_completed: TypeOptional(TypeInteger({ minimum: 0 })),
  }, { additionalProperties: false, minProperties: 1 }) }, { additionalProperties: false }), { minItems: 1, maxItems: 20 }),
}, { additionalProperties: false });
const P7_TOOL_SPECS: readonly AppToolSpec[] = Object.freeze([
  { name: "p7_workspace", method: "workspace", parameters: P7_WORKSPACE_PARAMETERS,
    description: "Start with op revise: directly record a concise Chinese WorldMap and task from the current observation, using exact base_revision and evidence_sequences containing the current sequence. Include action_labels on every revision: you judge each currently available action from real visual/action evidence and directly write its short label, purpose, confidence and current-run evidence; unknown/conflicting meanings use null labels. No IPython, program model or prior certification is required. Revise again once after a mismatch, RESET or level advance; matched plans may reuse the revision. Revise retains prior program/report evidence and never certifies new prose. Also read current/historical revisions, focus a task, publish an IPython draft or checkpoint source/JSON exports. Publishing never dispatches actions." },
  { name: "p7_execute_plan", method: "execute_plan", parameters: P7_EXECUTE_PLAN_PARAMETERS,
    description: "Submit one short actor plan from the current observation_ref and a nonempty semantic workspace_revision. If needs_revision is true, first use p7_workspace op revise (or publish) with current evidence; partial rules and unknown goals are sufficient. Each of 1–20 actions needs explicit key-cell, frame, state or progress predictions. The unique Broker executes sequentially and stops the suffix on mismatch, pause or a level boundary. Returns actual feedback, unexecuted steps and needs_revision/revision_reason. Reuse an identical plan_id only to retrieve its recorded result; never replay an uncertain action." },
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
    executionMode: "sequential" as const,
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
        if (
          result !== null
          && typeof result === "object"
          && !Array.isArray(result)
          && typeof (result as Record<string, unknown>).cognition_narrative_zh === "string"
        ) {
          const structured = { ...(result as Record<string, unknown>) };
          const narrative = structured.cognition_narrative_zh as string;
          delete structured.cognition_narrative_zh;
          text = narrative + "\n\n结构化证据（程序校验用）：\n" + JSON.stringify(structured);
        } else {
          text = serialized === undefined ? String(result) : serialized;
        }
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

export function createLegacyAppLevelTools(bridge: IpythonBridge): MethodTool[] {
  return [...P7_LEGACY_TOOL_SPECS].sort((a, b) => a.name.localeCompare(b.name)).map((spec) =>
    makeMethodTool(bridge, spec.name, spec.description, spec.parameters, spec.method, spec.inputKey));
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
    const mode = process.env.ASTERION_PRIME_P7_TOOL_MODE;
    if (mode !== undefined && mode !== "research" && mode !== "legacy") throw unavailable();
    delete process.env.ASTERION_PRIME_P7_TOOL_MODE;
    for (const tool of mode === "legacy" ? createLegacyAppLevelTools(bridge) : createAppLevelTools(bridge)) {
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
