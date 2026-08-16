import {
  createHash,
  randomBytes,
  timingSafeEqual,
} from "node:crypto";
import { chmod, lstat, unlink } from "node:fs/promises";
import {
  createServer,
  type Server,
  type Socket,
} from "node:net";
import { join } from "node:path";

import {
  validateControlEvent,
} from "@dci/agent-runtime";
import type {
  ControlEvent,
} from "@dci/agent-runtime";

import {
  canonicalJsonBytes,
  ensurePrivateDirectory,
} from "./durable-store.js";
import type {
  PrivateResultProjection,
  PrivateValueRef,
} from "./private-store.js";
import {
  PrivateValueStore,
} from "./private-store.js";

export const SKILL_CONTROL_PROTOCOL = "asterion.skill-control/v1";
export const MAX_SKILL_FRAME_BYTES = 64 * 1024;
const MAX_AUTH_FRAME_BYTES = 1024;
const TOKEN_PATTERN = /^[0-9a-f]{64}$/u;
const OPAQUE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const IDENTIFIER_PATTERN = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/u;
const VERSION_PATTERN = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/u;
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;

const OPERATIONS = new Set([
  "portfolio.get",
  "budget.get",
  "application.invoke",
  "child.spawn",
  "child.message",
  "child.cancel",
  "checkpoint.request",
  "goal.complete",
  "goal.fail",
  "action.status",
]);

const EFFECT_OPERATIONS = new Set([
  "application.invoke",
  "child.spawn",
  "child.message",
  "child.cancel",
  "checkpoint.request",
  "goal.complete",
  "goal.fail",
]);

export interface SkillBudget {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
  readonly deadline_ms: number;
}

export interface SkillApplicationTarget {
  readonly kind: "application";
  readonly provider_id: string;
  readonly application_id: string;
  readonly version: string;
  readonly runtime_id: string;
}

export interface SkillEventIdentity {
  readonly eventId: string;
  readonly sequence: number;
  readonly emittedAt: string;
}

export interface SkillAdmission {
  readonly resolution: "admitted" | "rejected";
  readonly reasonCode: string;
}

export interface SkillTerminal {
  readonly resolution: "succeeded" | "failed" | "cancelled" | "uncertain";
  readonly reasonCode: string;
  readonly resultRef?: PrivateValueRef;
}

export interface AsterionSkillBridgeOptions {
  readonly root: string;
  readonly sessionId: string;
  readonly authorityRevision: number;
  readonly generation: number;
  readonly goalId: string;
  readonly causalParentIds: readonly string[];
  readonly token: string;
  readonly portfolio: readonly SkillApplicationTarget[];
  readonly remainingBudget: SkillBudget;
  readonly privateValues: PrivateValueStore;
  readonly beforeEffect?: () => Promise<void>;
  readonly nextEventIdentity: () => SkillEventIdentity;
  readonly emitActionProposal: (event: ControlEvent) => Promise<void>;
  readonly waitForAdmission: (actionId: string) => Promise<SkillAdmission>;
  readonly afterAdmission?: (
    event: ControlEvent,
    admission: SkillAdmission,
  ) => Promise<void>;
  readonly waitForTerminal: (actionId: string) => Promise<SkillTerminal>;
  readonly actionStatus: (actionId: string) => Promise<unknown>;
}

interface SkillRequest {
  readonly protocol: typeof SKILL_CONTROL_PROTOCOL;
  readonly request_id: string;
  readonly session_id: string;
  readonly operation: string;
  readonly payload: Readonly<Record<string, unknown>>;
}

interface EffectRecord {
  readonly requestDigest: string;
  readonly promise: Promise<unknown>;
}

interface ConnectionState {
  readonly socket: Socket;
  buffer: Buffer;
  phase: "authentication" | "request" | "processing" | "closed";
}

export class SkillBridgeConfigurationError extends Error {
  constructor() {
    super("Asterion skill bridge configuration is invalid");
    this.name = "SkillBridgeConfigurationError";
  }
}

export class SkillBridgeConflictError extends Error {
  constructor() {
    super("Asterion skill request conflicts");
    this.name = "SkillBridgeConflictError";
  }
}

export function generateSkillBridgeToken(): string {
  return randomBytes(32).toString("hex");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}

function nonEmptyOpaqueId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID_PATTERN.test(value);
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function sortedUnique(values: readonly string[]): boolean {
  return values.every(
    (value, index) => index === 0 || String(values[index - 1]) < value,
  );
}

function deepFreeze<T>(value: T): T {
  if (
    (Array.isArray(value) || isRecord(value)) &&
    !Object.isFrozen(value)
  ) {
    for (const child of Object.values(value)) {
      deepFreeze(child);
    }
    Object.freeze(value);
  }
  return value;
}

function validateBudget(
  value: unknown,
  allowZeroDeadline = false,
): SkillBudget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "controller_tokens",
      "application_tokens",
      "child_tokens",
      "aggregate_tokens",
      "cost_micros",
      "deadline_ms",
    ]) ||
    !nonNegativeInteger(value.controller_tokens) ||
    !nonNegativeInteger(value.application_tokens) ||
    !nonNegativeInteger(value.child_tokens) ||
    !nonNegativeInteger(value.aggregate_tokens) ||
    !nonNegativeInteger(value.cost_micros) ||
    !(
      allowZeroDeadline
        ? nonNegativeInteger(value.deadline_ms)
        : positiveInteger(value.deadline_ms)
    )
  ) {
    throw new SkillBridgeConfigurationError();
  }
  return deepFreeze({
    controller_tokens: value.controller_tokens,
    application_tokens: value.application_tokens,
    child_tokens: value.child_tokens,
    aggregate_tokens: value.aggregate_tokens,
    cost_micros: value.cost_micros,
    deadline_ms: Number(value.deadline_ms),
  });
}

function validateTarget(value: unknown): SkillApplicationTarget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "kind",
      "provider_id",
      "application_id",
      "version",
      "runtime_id",
    ]) ||
    value.kind !== "application" ||
    typeof value.provider_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.provider_id) ||
    typeof value.application_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.application_id) ||
    typeof value.version !== "string" ||
    !VERSION_PATTERN.test(value.version) ||
    typeof value.runtime_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.runtime_id)
  ) {
    throw new SkillBridgeConfigurationError();
  }
  return Object.freeze({
    kind: "application",
    provider_id: value.provider_id,
    application_id: value.application_id,
    version: value.version,
    runtime_id: value.runtime_id,
  });
}

function validateStringArray(
  value: unknown,
  pattern: RegExp,
): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || !pattern.test(item)) ||
    !sortedUnique(value as string[])
  ) {
    throw new SkillBridgeConfigurationError();
  }
  return Object.freeze([...(value as string[])]);
}

function validText(value: unknown): value is string {
  return typeof value === "string" && Buffer.byteLength(value, "utf8") <= 1024 * 1024;
}

function validateRequest(
  value: unknown,
  sessionId: string,
  goalId: string,
): SkillRequest {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "protocol",
      "request_id",
      "session_id",
      "operation",
      "payload",
    ]) ||
    value.protocol !== SKILL_CONTROL_PROTOCOL ||
    !nonEmptyOpaqueId(value.request_id) ||
    value.session_id !== sessionId ||
    typeof value.operation !== "string" ||
    !OPERATIONS.has(value.operation) ||
    !isRecord(value.payload)
  ) {
    throw new SkillBridgeConfigurationError();
  }
  const payload = value.payload;
  if (value.operation === "portfolio.get" || value.operation === "budget.get") {
    if (!hasExactKeys(payload, [])) {
      throw new SkillBridgeConfigurationError();
    }
  } else if (value.operation === "action.status") {
    if (
      !hasExactKeys(payload, ["action_id"]) ||
      !nonEmptyOpaqueId(payload.action_id)
    ) {
      throw new SkillBridgeConfigurationError();
    }
  } else {
    validateEffectPayload(value.operation, payload);
    if (
      (value.operation === "goal.complete" || value.operation === "goal.fail") &&
      payload.goal_id !== goalId
    ) {
      throw new SkillBridgeConfigurationError();
    }
  }
  return deepFreeze({
    protocol: SKILL_CONTROL_PROTOCOL,
    request_id: value.request_id,
    session_id: sessionId,
    operation: value.operation,
    payload: { ...payload },
  });
}

function validateEffectPayload(
  operation: string,
  payload: Record<string, unknown>,
): void {
  const shared = ["idempotency_key", "budget"];
  const fields: Record<string, readonly string[]> = {
    "application.invoke": [
      ...shared,
      "target",
      "input_text",
      "expected_artifacts",
    ],
    "child.spawn": [...shared, "child_id", "goal_text"],
    "child.message": [...shared, "child_id", "message"],
    "child.cancel": [...shared, "child_id"],
    "checkpoint.request": [...shared, "checkpoint_id"],
    "goal.complete": [...shared, "goal_id", "summary"],
    "goal.fail": [...shared, "goal_id", "reason"],
  };
  const expected = fields[operation];
  if (
    expected === undefined ||
    !hasExactKeys(payload, expected) ||
    !nonEmptyOpaqueId(payload.idempotency_key)
  ) {
    throw new SkillBridgeConfigurationError();
  }
  validateBudget(payload.budget);
  if (operation === "application.invoke") {
    validateTarget(payload.target);
    if (!validText(payload.input_text)) {
      throw new SkillBridgeConfigurationError();
    }
    validateStringArray(payload.expected_artifacts, IDENTIFIER_PATTERN);
    return;
  }
  const identityField = operation.startsWith("child.")
    ? "child_id"
    : operation === "checkpoint.request"
      ? "checkpoint_id"
      : "goal_id";
  if (!nonEmptyOpaqueId(payload[identityField])) {
    throw new SkillBridgeConfigurationError();
  }
  const textField = {
    "child.spawn": "goal_text",
    "child.message": "message",
    "goal.complete": "summary",
    "goal.fail": "reason",
  }[operation];
  if (textField !== undefined && !validText(payload[textField])) {
    throw new SkillBridgeConfigurationError();
  }
}

function parseJson(line: Buffer): unknown {
  try {
    return JSON.parse(line.toString("utf8"));
  } catch {
    throw new SkillBridgeConfigurationError();
  }
}

export function deriveControlActionId(sessionId: string, idempotencyKey: string): string {
  const digest = createHash("sha256")
    .update(sessionId)
    .update("\0")
    .update(idempotencyKey)
    .digest("hex");
  return `action-${digest.slice(0, 40)}`;
}

function requestDigest(request: SkillRequest): string {
  return createHash("sha256")
    .update(canonicalJsonBytes({
      operation: request.operation,
      payload: request.payload,
    }))
    .digest("hex");
}

function errorResponse(requestId: string, code: string): Record<string, unknown> {
  return {
    protocol: SKILL_CONTROL_PROTOCOL,
    request_id: requestId,
    status: "error",
    code,
  };
}

function successResponse(requestId: string, result: unknown): Record<string, unknown> {
  return {
    protocol: SKILL_CONTROL_PROTOCOL,
    request_id: requestId,
    status: "ok",
    result,
  };
}

async function existingPath(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (isRecord(error) && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

export class AsterionSkillBridge {
  private readonly sockets = new Set<Socket>();
  private readonly activeHandlers = new Set<Promise<void>>();
  private readonly closeWaiters = new Set<() => void>();
  private readonly effects = new Map<string, EffectRecord>();
  private closed = false;

  private constructor(
    readonly socketPath: string,
    private readonly server: Server,
    private readonly options: AsterionSkillBridgeOptions,
    private readonly portfolio: readonly SkillApplicationTarget[],
    private remainingBudget: SkillBudget,
  ) {}

  static async listen(
    candidateOptions: AsterionSkillBridgeOptions,
  ): Promise<AsterionSkillBridge> {
    const options = AsterionSkillBridge.validateOptions(candidateOptions);
    const socketPath = join(options.root, "c.sock");
    try {
      await ensurePrivateDirectory(options.root);
      if (await existingPath(socketPath)) {
        throw new SkillBridgeConfigurationError();
      }
      const server = createServer();
      const bridge = new AsterionSkillBridge(
        socketPath,
        server,
        options,
        options.portfolio,
        options.remainingBudget,
      );
      server.on("connection", (socket) => bridge.accept(socket));
      await new Promise<void>((resolve, reject) => {
        server.once("error", reject);
        server.listen(socketPath, resolve);
      });
      server.removeAllListeners("error");
      server.on("error", () => undefined);
      await chmod(socketPath, 0o600);
      return bridge;
    } catch (error) {
      if (error instanceof SkillBridgeConfigurationError) {
        throw error;
      }
      throw new SkillBridgeConfigurationError();
    }
  }

  toString(): string {
    return "[Asterion private skill bridge]";
  }

  toJSON(): Readonly<Record<string, string>> {
    return Object.freeze({ kind: "asterion-private-skill-bridge" });
  }

  updateRemainingBudget(value: unknown): void {
    this.throwIfClosed();
    this.remainingBudget = validateBudget(value, true);
  }

  async close(): Promise<void> {
    if (this.closed) {
      return;
    }
    this.closed = true;
    for (const waiter of this.closeWaiters) {
      waiter();
    }
    this.closeWaiters.clear();
    for (const socket of this.sockets) {
      socket.destroy();
    }
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
    await Promise.allSettled([...this.activeHandlers]);
    try {
      const metadata = await lstat(this.socketPath);
      if (metadata.isSocket()) {
        await unlink(this.socketPath);
      }
    } catch {
      // The private root owner may already have removed the closed socket.
    }
  }

  private static validateOptions(
    options: AsterionSkillBridgeOptions,
  ): AsterionSkillBridgeOptions {
    if (
      !isRecord(options) ||
      !nonEmptyOpaqueId(options.sessionId) ||
      !positiveInteger(options.authorityRevision) ||
      !positiveInteger(options.generation) ||
      !nonEmptyOpaqueId(options.goalId) ||
      !TOKEN_PATTERN.test(options.token) ||
      !(options.privateValues instanceof PrivateValueStore) ||
      (
        options.beforeEffect !== undefined &&
        typeof options.beforeEffect !== "function"
      ) ||
      typeof options.nextEventIdentity !== "function" ||
      typeof options.emitActionProposal !== "function" ||
      typeof options.waitForAdmission !== "function" ||
      typeof options.waitForTerminal !== "function" ||
      typeof options.actionStatus !== "function"
    ) {
      throw new SkillBridgeConfigurationError();
    }
    const causalParentIds = validateStringArray(
      options.causalParentIds,
      OPAQUE_ID_PATTERN,
    );
    const portfolio = Object.freeze(options.portfolio.map(validateTarget));
    const remainingBudget = validateBudget(options.remainingBudget, true);
    return Object.freeze({
      ...options,
      causalParentIds,
      portfolio,
      remainingBudget,
    });
  }

  private accept(socket: Socket): void {
    if (this.closed) {
      socket.destroy();
      return;
    }
    this.sockets.add(socket);
    const state: ConnectionState = {
      socket,
      buffer: Buffer.alloc(0),
      phase: "authentication",
    };
    socket.on("data", (chunk: Buffer) => this.handleData(state, chunk));
    socket.on("error", () => undefined);
    socket.on("close", () => {
      state.phase = "closed";
      this.sockets.delete(socket);
    });
  }

  private handleData(state: ConnectionState, chunk: Buffer): void {
    if (state.phase === "closed" || state.phase === "processing") {
      return;
    }
    state.buffer = Buffer.concat([state.buffer, chunk]);
    let newline = state.buffer.indexOf(0x0a);
    while (newline !== -1 && state.phase !== "processing") {
      const limit = state.phase === "authentication"
        ? MAX_AUTH_FRAME_BYTES
        : MAX_SKILL_FRAME_BYTES;
      if (newline > limit) {
        this.respondAndClose(
          state.socket,
          errorResponse(
            state.phase === "authentication" ? "authentication" : "unknown",
            state.phase === "authentication"
              ? "authentication-failed"
              : "request-too-large",
          ),
        );
        state.phase = "closed";
        return;
      }
      const line = state.buffer.subarray(0, newline);
      state.buffer = state.buffer.subarray(newline + 1);
      if (state.phase === "authentication") {
        if (!this.authenticate(line)) {
          this.respondAndClose(
            state.socket,
            errorResponse("authentication", "authentication-failed"),
          );
          state.phase = "closed";
          return;
        }
        state.phase = "request";
      } else {
        state.phase = "processing";
        const handler = this.processRequest(state.socket, line);
        this.activeHandlers.add(handler);
        void handler.finally(() => this.activeHandlers.delete(handler));
      }
      newline = state.buffer.indexOf(0x0a);
    }
    const limit = state.phase === "authentication"
      ? MAX_AUTH_FRAME_BYTES
      : MAX_SKILL_FRAME_BYTES;
    if (
      (state.phase === "authentication" || state.phase === "request") &&
      state.buffer.byteLength > limit
    ) {
      this.respondAndClose(
        state.socket,
        errorResponse(
          state.phase === "authentication" ? "authentication" : "unknown",
          state.phase === "authentication"
            ? "authentication-failed"
            : "request-too-large",
        ),
      );
      state.phase = "closed";
    }
  }

  private authenticate(line: Buffer): boolean {
    if (line.byteLength > MAX_AUTH_FRAME_BYTES) {
      return false;
    }
    try {
      const value = parseJson(line);
      if (
        !isRecord(value) ||
        !hasExactKeys(value, ["protocol", "type", "token", "session_id"]) ||
        value.protocol !== SKILL_CONTROL_PROTOCOL ||
        value.type !== "authenticate" ||
        typeof value.token !== "string" ||
        !TOKEN_PATTERN.test(value.token) ||
        value.session_id !== this.options.sessionId
      ) {
        return false;
      }
      return timingSafeEqual(
        Buffer.from(value.token, "hex"),
        Buffer.from(this.options.token, "hex"),
      );
    } catch {
      return false;
    }
  }

  private async processRequest(socket: Socket, line: Buffer): Promise<void> {
    let requestId = "unknown";
    let raw: unknown;
    let requestValidated = false;
    try {
      if (line.byteLength > MAX_SKILL_FRAME_BYTES) {
        this.respondAndClose(socket, errorResponse(requestId, "request-too-large"));
        return;
      }
      raw = parseJson(line);
      if (isRecord(raw) && typeof raw.request_id === "string") {
        requestId = raw.request_id;
      }
      const request = validateRequest(
        raw,
        this.options.sessionId,
        this.options.goalId,
      );
      requestValidated = true;
      requestId = request.request_id;
      const result = await this.dispatch(request);
      this.respondAndClose(socket, successResponse(requestId, result));
    } catch (error) {
      privateDiagnosticSkillRequestFailure(raw, requestValidated);
      const code = error instanceof SkillBridgeConflictError
        ? "request-conflicts"
        : "request-invalid";
      this.respondAndClose(socket, errorResponse(requestId, code));
    }
  }

  private async dispatch(request: SkillRequest): Promise<unknown> {
    this.throwIfClosed();
    if (request.operation === "portfolio.get") {
      return this.portfolio;
    }
    if (request.operation === "budget.get") {
      return this.remainingBudget;
    }
    if (request.operation === "action.status") {
      return this.options.actionStatus(String(request.payload.action_id));
    }
    return this.dispatchEffect(request);
  }

  private dispatchEffect(request: SkillRequest): Promise<unknown> {
    if (!EFFECT_OPERATIONS.has(request.operation)) {
      return Promise.reject(new SkillBridgeConfigurationError());
    }
    const idempotencyKey = String(request.payload.idempotency_key);
    const derivedActionId = deriveControlActionId(this.options.sessionId, idempotencyKey);
    const digest = requestDigest(request);
    const existing = this.effects.get(derivedActionId);
    if (existing !== undefined) {
      if (existing.requestDigest !== digest) {
        return Promise.reject(new SkillBridgeConflictError());
      }
      return existing.promise;
    }
    const promise = this.runEffect(request, derivedActionId);
    this.effects.set(derivedActionId, { requestDigest: digest, promise });
    return promise;
  }

  private async runEffect(
    request: SkillRequest,
    derivedActionId: string,
  ): Promise<unknown> {
    await this.failOnClose(
      Promise.resolve().then(() => this.options.beforeEffect?.()),
    );
    this.throwIfClosed();
    const inputRef = await this.options.privateValues.putInput(
      this.privateInput(request),
    );
    this.throwIfClosed();
    const identity = this.options.nextEventIdentity();
    const event = validateControlEvent({
      protocol: "asterion.agent-control/v1",
      event_id: identity.eventId,
      session_id: this.options.sessionId,
      generation: this.options.generation,
      sequence: identity.sequence,
      emitted_at: identity.emittedAt,
      type: "action.proposed",
      payload: {
        action_id: derivedActionId,
        authority_revision: this.options.authorityRevision,
        idempotency_key: request.payload.idempotency_key,
        kind: this.actionKind(request.operation),
        target: this.actionTarget(request),
        input_ref: inputRef,
        expected_artifacts:
          request.operation === "application.invoke"
            ? request.payload.expected_artifacts
            : [],
        budget: request.payload.budget,
        causal_parent_ids: this.options.causalParentIds,
      },
    });
    await this.failOnClose(this.options.emitActionProposal(event));
    const admission = await this.failOnClose(
      this.options.waitForAdmission(derivedActionId),
    );
    this.validateAdmission(admission);
    const result: Record<string, unknown> = {
      action_id: derivedActionId,
      admission: {
        resolution: admission.resolution,
        reason_code: admission.reasonCode,
      },
    };
    if (admission.resolution === "rejected") {
      return deepFreeze(result);
    }
    await this.failOnClose(this.options.afterAdmission?.(event, admission) ?? Promise.resolve());
    const terminal = await this.failOnClose(
      this.options.waitForTerminal(derivedActionId),
    );
    this.validateTerminal(terminal);
    result.terminal = {
      resolution: terminal.resolution,
      reason_code: terminal.reasonCode,
    };
    if (terminal.resultRef !== undefined) {
      const projection = await this.options.privateValues.readResult(
        terminal.resultRef,
      );
      result.result = this.projectResult(projection);
    }
    return deepFreeze(result);
  }

  private async failOnClose<T>(operation: Promise<T>): Promise<T> {
    this.throwIfClosed();
    let release: () => void = () => undefined;
    const closed = new Promise<never>((_, reject) => {
      release = () => reject(new SkillBridgeConfigurationError());
    });
    this.closeWaiters.add(release);
    try {
      return await Promise.race([operation, closed]);
    } finally {
      this.closeWaiters.delete(release);
    }
  }

  private throwIfClosed(): void {
    if (this.closed) {
      throw new SkillBridgeConfigurationError();
    }
  }

  private privateInput(request: SkillRequest): string {
    const textField = {
      "application.invoke": "input_text",
      "child.spawn": "goal_text",
      "child.message": "message",
      "goal.complete": "summary",
      "goal.fail": "reason",
    }[request.operation];
    if (textField !== undefined) {
      return String(request.payload[textField]);
    }
    return canonicalJsonBytes({
      operation: request.operation,
      target: this.actionTarget(request),
    }).toString("utf8");
  }

  private actionKind(operation: string): string {
    return operation === "checkpoint.request" ? "checkpoint.create" : operation;
  }

  private actionTarget(request: SkillRequest): Record<string, unknown> {
    if (request.operation === "application.invoke") {
      return request.payload.target as Record<string, unknown>;
    }
    if (request.operation.startsWith("child.")) {
      return { kind: "child", child_id: request.payload.child_id };
    }
    if (request.operation === "checkpoint.request") {
      return {
        kind: "checkpoint",
        checkpoint_id: request.payload.checkpoint_id,
      };
    }
    return { kind: "goal", goal_id: request.payload.goal_id };
  }

  private validateAdmission(value: SkillAdmission): void {
    if (
      !isRecord(value) ||
      (value.resolution !== "admitted" && value.resolution !== "rejected") ||
      typeof value.reasonCode !== "string" ||
      !IDENTIFIER_PATTERN.test(value.reasonCode)
    ) {
      throw new SkillBridgeConfigurationError();
    }
  }

  private validateTerminal(value: SkillTerminal): void {
    if (
      !isRecord(value) ||
      !["succeeded", "failed", "cancelled", "uncertain"].includes(
        String(value.resolution),
      ) ||
      typeof value.reasonCode !== "string" ||
      !IDENTIFIER_PATTERN.test(value.reasonCode) ||
      (value.resultRef !== undefined &&
        (typeof value.resultRef !== "string" ||
          !OPAQUE_ID_PATTERN.test(value.resultRef)))
    ) {
      throw new SkillBridgeConfigurationError();
    }
  }

  private projectResult(
    projection: PrivateResultProjection,
  ): Record<string, unknown> {
    if (
      !projection.mediaTypes.every((value) => MEDIA_TYPE_PATTERN.test(value))
    ) {
      throw new SkillBridgeConfigurationError();
    }
    return {
      receipt_ref: projection.receiptRef,
      artifact_ids: projection.artifactIds,
      media_types: projection.mediaTypes,
    };
  }

  private respondAndClose(socket: Socket, response: Record<string, unknown>): void {
    let bytes: Buffer;
    try {
      bytes = Buffer.concat([canonicalJsonBytes(response), Buffer.from("\n")]);
    } catch {
      bytes = Buffer.concat([
        canonicalJsonBytes(errorResponse("unknown", "request-invalid")),
        Buffer.from("\n"),
      ]);
    }
    if (bytes.byteLength > MAX_SKILL_FRAME_BYTES) {
      const requestId = typeof response.request_id === "string"
        ? response.request_id
        : "unknown";
      bytes = Buffer.concat([
        canonicalJsonBytes(errorResponse(requestId, "response-too-large")),
        Buffer.from("\n"),
      ]);
    }
    if (!socket.destroyed && socket.writable) {
      socket.end(bytes);
    }
  }
}

function privateDiagnosticSkillRequestFailure(
  value: unknown,
  requestValidated: boolean,
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS !== "1") {
    return;
  }
  const stage = requestValidated
    ? "dispatch"
    : !isRecord(value)
    ? "shape"
    : !hasExactKeys(value, ["protocol", "request_id", "session_id", "operation", "payload"])
      ? "fields"
      : value.protocol !== SKILL_CONTROL_PROTOCOL
        ? "protocol"
        : !nonEmptyOpaqueId(value.request_id)
          ? "request-id"
          : !isRecord(value.payload)
            ? "payload"
            : value.operation === "child.spawn"
              ? "child-spawn"
              : "other";
  process.stderr.write(`asterion-prime-skill-request:${stage}\n`);
}
