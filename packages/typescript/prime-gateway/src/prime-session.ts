import { createHash } from "node:crypto";
import { dirname, isAbsolute, resolve } from "node:path";

import type {
  PrimeDaemonDeferredResponse,
  PrimeDaemonListener,
} from "./daemon-client.js";
import type {
  PrimeDaemonCommand,
  PrimeDaemonCursor,
  PrimeDaemonHello,
  PrimeDaemonResponse,
} from "./daemon-wire.js";
import {
  projectPrimeSessionTree,
} from "./session-tree.js";
import type { PrimeSessionTreeProjection } from "./session-tree.js";

export interface PrimeDaemonTransport {
  readonly hello: PrimeDaemonHello | undefined;
  readonly isConnected?: boolean;
  reconnect?(): Promise<void>;
  acknowledgeResult(stableCommandId: string): boolean;
  request(
    command: PrimeDaemonCommand,
    stableCommandId: string,
    timeoutMs?: number,
  ): Promise<PrimeDaemonResponse>;
  requestDeferred(
    command: PrimeDaemonCommand,
    stableCommandId: string,
    timeoutMs?: number,
  ): Promise<PrimeDaemonDeferredResponse>;
  subscribe(listener: PrimeDaemonListener): () => void;
}

export interface PrimeSessionIdentity {
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly supervisorGeneration: string;
}

export interface PrimeSessionInitialBinding extends PrimeSessionIdentity {
  readonly continuationId: string;
  readonly sessionPath: string;
}

export interface PrimeSessionRecovery {
  readonly transport: PrimeDaemonTransport;
  readonly primeCursor: PrimeDaemonCursor;
  readonly transcriptSessionId: string;
  readonly supervisorGeneration: string;
  readonly sessionStatus: "running" | "paused";
}

export interface PrimePrivateSessionConfig {
  readonly workspace: string;
  readonly agentDir: string;
  readonly sessionDir: string;
  readonly provider: string;
  readonly model: string;
  readonly skillPath: string;
  readonly goal: string;
  readonly maxContinuations: number;
  readonly maxTurns: number;
  readonly maxControllerTokens: number;
  readonly timeoutMs: number;
}

export interface PrimeSessionCreateOptions {
  readonly transport: PrimeDaemonTransport;
  readonly sessionId: string;
  readonly privateConfig: PrimePrivateSessionConfig;
  readonly bindIdentity: (identity: PrimeSessionInitialBinding) => Promise<void>;
}

export interface PrimeSessionRestoreOptions {
  readonly transport: PrimeDaemonTransport;
  readonly sessionId: string;
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly continuationId?: string;
  readonly sessionPath?: string;
}

export type PrimeInputDelivery = "direct" | "steer" | "follow_up";
export type PrimePromptCancellation = "cancelled" | "owned";
export type PrimeContextStatus =
  | "cancelled"
  | "completed"
  | "creating"
  | "failed"
  | "idle"
  | "paused"
  | "recovery-required"
  | "running";

export interface PrimeContextUsage {
  readonly controller_tokens: number;
  readonly application_tokens: 0;
  readonly child_tokens: 0;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
}

export interface PrimeContextDescription {
  readonly continuationId: string;
  readonly status: PrimeContextStatus;
  readonly contextTokens: number;
  readonly turns: number;
  readonly usage: PrimeContextUsage;
  readonly nameSha256: string | null;
}

export interface PrimeContextNameResult {
  readonly result: Readonly<{
    readonly continuationId: string;
    readonly nameSha256: string;
  }>;
  acknowledge(): boolean;
}

export interface PrimeContinuationLocator extends PrimeSessionIdentity {
  readonly continuationId: string;
  readonly sessionPath: string;
}

export interface PrimeContinuationResumeResult {
  readonly locator: PrimeContinuationLocator;
  readonly result: Readonly<{
    readonly previousContinuationId: string;
    readonly currentContinuationId: string;
    readonly transitionSha256: string;
  }>;
  acknowledge(): boolean;
}

export interface PrimeContinuationDeleteResult {
  readonly result: Readonly<{
    readonly continuationId: string;
    readonly deletionSha256: string;
  }>;
  acknowledge(): boolean;
}

export interface PrimeTreeNavigationResult {
  readonly result: Readonly<{
    readonly continuationId: string;
    readonly previousLeafId: string | null;
    readonly currentLeafId: string | null;
    readonly transitionSha256: string;
  }>;
  acknowledge(): boolean;
}

export interface PrimeForkCloneResult {
  readonly locator: PrimeContinuationLocator;
  readonly result: Readonly<{
    readonly sourceContinuationId: string;
    readonly newContinuationId: string;
    readonly activeLeafId: string | null;
    readonly transitionSha256: string;
  }>;
  acknowledge(): boolean;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MAX_PRIVATE_TEXT_BYTES = 1024 * 1024;

export class PrimeSessionError extends Error {
  constructor() {
    super("Prime resident session operation failed");
    this.name = "PrimeSessionError";
  }
}

export class PrimePromptAdmissionUncertainError extends PrimeSessionError {
  constructor() {
    super();
    this.name = "PrimePromptAdmissionUncertainError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return (
    actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index])
  );
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const accepted = new Set(allowed);
  return Object.keys(value).every((key) => accepted.has(key));
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function validText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    Buffer.byteLength(value, "utf8") <= MAX_PRIVATE_TEXT_BYTES
  );
}

function validatePrivateConfig(
  value: PrimePrivateSessionConfig,
): PrimePrivateSessionConfig {
  if (
    !isRecord(value) ||
    ![value.workspace, value.agentDir, value.sessionDir, value.skillPath]
      .every((path) => typeof path === "string" && isAbsolute(path)) ||
    !validText(value.provider) ||
    !validText(value.model) ||
    !validText(value.goal) ||
    !positiveInteger(value.maxContinuations) ||
    !positiveInteger(value.maxTurns) ||
    !positiveInteger(value.maxControllerTokens) ||
    !positiveInteger(value.timeoutMs)
  ) {
    throw new PrimeSessionError();
  }
  return Object.freeze({ ...value });
}

function continuationIdFor(sessionId: string): string {
  return `continuation-${createHash("sha256")
    .update(sessionId, "utf8")
    .digest("hex")
    .slice(0, 32)}`;
}

function continuationIdForTranscript(
  sessionId: string,
  transcriptSessionId: string,
): string {
  return `continuation-${createHash("sha256")
    .update(JSON.stringify([
      "asterion.prime.continuation",
      sessionId,
      transcriptSessionId,
    ]), "utf8")
    .digest("hex")
    .slice(0, 32)}`;
}

function sha256Text(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function identityFromCreate(
  response: PrimeDaemonResponse,
  sessionDir: string,
): Readonly<{
  activeSessionId: string;
  transcriptSessionId: string;
  sessionPath: string;
}> {
  if (
    !response.success ||
    response.command !== "create" ||
    !isRecord(response.data) ||
    typeof response.data.activeSessionId !== "string" ||
    !OPAQUE_ID.test(response.data.activeSessionId) ||
    typeof response.data.sessionId !== "string" ||
    !OPAQUE_ID.test(response.data.sessionId) ||
    typeof response.data.sessionFile !== "string" ||
    resolve(response.data.sessionFile) !== response.data.sessionFile ||
    dirname(response.data.sessionFile) !== resolve(sessionDir)
  ) {
    throw new PrimeSessionError();
  }
  return Object.freeze({
    activeSessionId: response.data.activeSessionId,
    transcriptSessionId: response.data.sessionId,
    sessionPath: response.data.sessionFile,
  });
}

function validateSessionHeader(
  response: PrimeDaemonResponse,
  transcriptSessionId: string,
  workspace?: string,
): void {
  if (
    !response.success ||
    response.command !== "get_session_header" ||
    !isRecord(response.data) ||
    !hasExactKeys(response.data, ["header"]) ||
    !isRecord(response.data.header)
  ) {
    throw new PrimeSessionError();
  }
  const header = response.data.header;
  if (
    !hasOnlyKeys(header, [
      "type",
      "version",
      "id",
      "timestamp",
      "cwd",
      "parentSession",
      "rlmDepth",
      "git",
    ]) ||
    header.type !== "session" ||
    header.id !== transcriptSessionId ||
    typeof header.timestamp !== "string" ||
    Number.isNaN(Date.parse(header.timestamp)) ||
    (workspace === undefined
      ? typeof header.cwd !== "string" || !isAbsolute(header.cwd)
      : header.cwd !== workspace) ||
    (header.version !== undefined && !positiveInteger(header.version)) ||
    (header.parentSession !== undefined && typeof header.parentSession !== "string") ||
    (header.rlmDepth !== undefined && !nonNegativeInteger(header.rlmDepth))
  ) {
    throw new PrimeSessionError();
  }
  if (header.git !== undefined) {
    if (
      !isRecord(header.git) ||
      !hasOnlyKeys(header.git, ["repoUrl", "commit", "branch"]) ||
      Object.values(header.git).some((item) => typeof item !== "string")
    ) {
      throw new PrimeSessionError();
    }
  }
}

function transcriptIdFromSessionHeader(
  response: PrimeDaemonResponse,
): string {
  if (
    !response.success ||
    response.command !== "get_session_header" ||
    !isRecord(response.data) ||
    !hasExactKeys(response.data, ["header"]) ||
    !isRecord(response.data.header) ||
    typeof response.data.header.id !== "string" ||
    !OPAQUE_ID.test(response.data.header.id)
  ) {
    throw new PrimeSessionError();
  }
  const transcriptSessionId = response.data.header.id;
  validateSessionHeader(response, transcriptSessionId);
  return transcriptSessionId;
}

interface PrimeContextCounters {
  readonly turns: number;
  readonly input: number;
  readonly output: number;
  readonly cacheRead: number;
  readonly cacheWrite: number;
  readonly total: number;
  readonly costMicros: number;
}

function costMicros(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new PrimeSessionError();
  }
  const projected = Math.round(value * 1_000_000);
  if (!Number.isSafeInteger(projected)) {
    throw new PrimeSessionError();
  }
  return projected;
}

function validateStats(
  response: PrimeDaemonResponse,
  transcriptSessionId: string,
  sessionPath: string,
): Readonly<{
  counters: PrimeContextCounters;
  contextTokens: number;
  totalMessages: number;
}> {
  if (
    !response.success ||
    response.command !== "get_session_stats" ||
    !isRecord(response.data) ||
    !hasExactKeys(response.data, [
      "sessionFile",
      "sessionId",
      "userMessages",
      "assistantMessages",
      "toolCalls",
      "toolResults",
      "totalMessages",
      "tokens",
      "cost",
      "contextUsage",
    ]) ||
    response.data.sessionFile !== sessionPath ||
    response.data.sessionId !== transcriptSessionId ||
    ![
      response.data.userMessages,
      response.data.assistantMessages,
      response.data.toolCalls,
      response.data.toolResults,
      response.data.totalMessages,
    ].every(nonNegativeInteger) ||
    !isRecord(response.data.tokens) ||
    !hasExactKeys(response.data.tokens, [
      "input",
      "output",
      "cacheRead",
      "cacheWrite",
      "total",
    ]) ||
    !Object.values(response.data.tokens).every(nonNegativeInteger) ||
    !isRecord(response.data.contextUsage) ||
    !hasExactKeys(response.data.contextUsage, [
      "tokens",
      "contextWindow",
      "percent",
    ]) ||
    !positiveInteger(response.data.contextUsage.contextWindow) ||
    !(
      (nonNegativeInteger(response.data.contextUsage.tokens) &&
        typeof response.data.contextUsage.percent === "number" &&
        Number.isFinite(response.data.contextUsage.percent) &&
        response.data.contextUsage.percent >= 0) ||
      (response.data.contextUsage.tokens === null &&
        response.data.contextUsage.percent === null)
    )
  ) {
    throw new PrimeSessionError();
  }
  const turns = response.data.userMessages as number;
  const assistantMessages = response.data.assistantMessages as number;
  const toolResults = response.data.toolResults as number;
  const totalMessages = response.data.totalMessages as number;
  const tokens = response.data.tokens as Record<
    "input" | "output" | "cacheRead" | "cacheWrite" | "total",
    number
  >;
  const summed = tokens.input + tokens.output + tokens.cacheRead + tokens.cacheWrite;
  if (
    !Number.isSafeInteger(summed) ||
    summed !== tokens.total ||
    totalMessages < turns + assistantMessages + toolResults
  ) {
    throw new PrimeSessionError();
  }
  return Object.freeze({
    counters: Object.freeze({
      turns,
      input: tokens.input,
      output: tokens.output,
      cacheRead: tokens.cacheRead,
      cacheWrite: tokens.cacheWrite,
      total: tokens.total,
      costMicros: costMicros(response.data.cost),
    }),
    contextTokens: response.data.contextUsage.tokens === null
      ? 0
      : response.data.contextUsage.tokens,
    totalMessages,
  });
}

function validateState(
  response: PrimeDaemonResponse,
  activeSessionId: string,
  transcriptSessionId: string,
  sessionPath: string,
): Readonly<{
  active: boolean;
  messageCount: number;
  nameSha256: string | null;
}> {
  if (
    !response.success ||
    response.command !== "get_state" ||
    !isRecord(response.data) ||
    response.data.activeSessionId !== activeSessionId ||
    response.data.sessionId !== transcriptSessionId ||
    response.data.sessionFile !== sessionPath ||
    (response.data.activity !== "working" && response.data.activity !== "idle") ||
    typeof response.data.isSessionActive !== "boolean" ||
    typeof response.data.isStreaming !== "boolean" ||
    typeof response.data.isCompacting !== "boolean" ||
    !nonNegativeInteger(response.data.messageCount) ||
    (response.data.sessionName !== undefined && !validText(response.data.sessionName))
  ) {
    throw new PrimeSessionError();
  }
  return Object.freeze({
    active:
      response.data.activity === "working" ||
      response.data.isSessionActive ||
      response.data.isStreaming ||
      response.data.isCompacting,
    messageCount: response.data.messageCount,
    nameSha256:
      response.data.sessionName === undefined
        ? null
        : sha256Text(response.data.sessionName),
  });
}

function sessionPathFromState(
  response: PrimeDaemonResponse,
  activeSessionId: string,
  transcriptSessionId: string,
  sessionDir: string,
): string {
  if (
    !response.success ||
    response.command !== "get_state" ||
    !isRecord(response.data) ||
    typeof response.data.sessionFile !== "string" ||
    !isAbsolute(response.data.sessionFile) ||
    resolve(response.data.sessionFile) !== response.data.sessionFile ||
    dirname(response.data.sessionFile) !== resolve(sessionDir)
  ) {
    throw new PrimeSessionError();
  }
  validateState(
    response,
    activeSessionId,
    transcriptSessionId,
    response.data.sessionFile,
  );
  return response.data.sessionFile;
}

export class PrimeSession {
  private commandSequence = 0;
  private readonly pendingAdmissions = new Set<string>();
  private transport: PrimeDaemonTransport;
  private currentSupervisorGeneration: string;
  private latestAttachResponse: (PrimeDaemonResponse & { success: true }) | undefined;
  private lastContextCounters: PrimeContextCounters | undefined;
  private currentTranscriptSessionId: string;
  private currentContinuationId: string;
  private currentSessionPath: string | undefined;
  private readonly pendingContinuationResumes = new Map<
    string,
    PrimeContinuationResumeResult
  >();
  private readonly pendingTreeNavigations = new Map<
    string,
    Readonly<{
      continuationId: string;
      entryId: string;
      previousLeafId: string | null;
      value: PrimeTreeNavigationResult;
    }>
  >();
  private readonly pendingForkClones = new Map<
    string,
    Readonly<{
      operation: "session.fork" | "session.clone";
      sourceContinuationId: string;
      entryId: string;
      position: "at" | "before";
      value: PrimeForkCloneResult;
    }>
  >();

  private constructor(
    transport: PrimeDaemonTransport,
    private readonly sessionId: string,
    readonly activeSessionId: string,
    transcriptSessionId: string,
    continuationId: string,
    sessionPath: string | undefined,
    supervisorGeneration: string,
  ) {
    this.transport = transport;
    this.currentSupervisorGeneration = supervisorGeneration;
    this.currentTranscriptSessionId = transcriptSessionId;
    this.currentContinuationId = continuationId;
    this.currentSessionPath = sessionPath;
  }

  get supervisorGeneration(): string {
    return this.currentSupervisorGeneration;
  }

  get transcriptSessionId(): string {
    return this.currentTranscriptSessionId;
  }

  get continuationId(): string {
    return this.currentContinuationId;
  }

  get lastAttachResponse(): PrimeDaemonResponse | undefined {
    return this.latestAttachResponse;
  }

  static async create(options: PrimeSessionCreateOptions): Promise<PrimeSession> {
    try {
      if (!OPAQUE_ID.test(options.sessionId)) {
        throw new PrimeSessionError();
      }
      if (typeof options.bindIdentity !== "function") {
        throw new PrimeSessionError();
      }
      const privateConfig = validatePrivateConfig(options.privateConfig);
      const generation = options.transport.hello?.supervisorGeneration;
      if (typeof generation !== "string" || !OPAQUE_ID.test(generation)) {
        throw new PrimeSessionError();
      }
      const deferredCreate = await options.transport.requestDeferred(
        {
          type: "create",
          continueRecent: false,
          noSession: false,
          name: options.sessionId,
          lifecycle: "resident",
          config: Object.freeze({
            cwd: privateConfig.workspace,
            agentDir: privateConfig.agentDir,
            sessionDir: privateConfig.sessionDir,
            provider: privateConfig.provider,
            model: privateConfig.model,
            skills: Object.freeze([privateConfig.skillPath]),
            autonomous: Object.freeze({
              enabled: true,
              maxContinuations: privateConfig.maxContinuations,
              maxTurns: privateConfig.maxTurns,
              maxTokens: privateConfig.maxControllerTokens,
              timeoutMs: privateConfig.timeoutMs,
              gates: Object.freeze({
                commands: Object.freeze([]),
                maxRetries: 1,
                timeoutMs: privateConfig.timeoutMs,
              }),
            }),
            telemetryDisabled: true,
            initialGoal: Object.freeze({
              objective: privateConfig.goal,
              tokenBudget: privateConfig.maxControllerTokens,
            }),
          }),
        },
        `${options.sessionId}-create`,
        privateConfig.timeoutMs,
      );
      const { activeSessionId, transcriptSessionId, sessionPath } = identityFromCreate(
        deferredCreate.response,
        privateConfig.sessionDir,
      );
      validateSessionHeader(
        await options.transport.request(
          { type: "get_session_header", activeSessionId },
          `${options.sessionId}-create-header`,
          privateConfig.timeoutMs,
        ),
        transcriptSessionId,
        privateConfig.workspace,
      );
      const continuationId = continuationIdFor(options.sessionId);
      await options.bindIdentity(Object.freeze({
        activeSessionId,
        transcriptSessionId,
        supervisorGeneration: generation,
        continuationId,
        sessionPath,
      }));
      if (!deferredCreate.acknowledge()) {
        throw new PrimeSessionError();
      }
      const session = new PrimeSession(
        options.transport,
        options.sessionId,
        activeSessionId,
        transcriptSessionId,
        continuationId,
        sessionPath,
        generation,
      );
      await session.request(
        {
          type: "set_rlm_max_depth",
          activeSessionId,
          maxDepth: 0,
          global: false,
        },
        "disable-native-rlm",
      );
      await session.attach("initial-attach");
      return session;
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  static restore(options: PrimeSessionRestoreOptions): PrimeSession {
    try {
      const generation = options.transport.hello?.supervisorGeneration;
      if (
        !OPAQUE_ID.test(options.sessionId) ||
        !OPAQUE_ID.test(options.activeSessionId) ||
        !OPAQUE_ID.test(options.transcriptSessionId) ||
        (options.continuationId !== undefined &&
          !OPAQUE_ID.test(options.continuationId)) ||
        (options.sessionPath !== undefined &&
          (!isAbsolute(options.sessionPath) ||
            resolve(options.sessionPath) !== options.sessionPath)) ||
        typeof generation !== "string" ||
        !OPAQUE_ID.test(generation)
      ) {
        throw new PrimeSessionError();
      }
      return new PrimeSession(
        options.transport,
        options.sessionId,
        options.activeSessionId,
        options.transcriptSessionId,
        options.continuationId ?? continuationIdFor(options.sessionId),
        options.sessionPath,
        generation,
      );
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  subscribe(listener: PrimeDaemonListener): () => void {
    try {
      return this.transport.subscribe(listener);
    } catch {
      throw new PrimeSessionError();
    }
  }

  adoptRecovery(recovery: PrimeSessionRecovery): void {
    const generation = recovery.transport?.hello?.supervisorGeneration;
    if (
      this.pendingAdmissions.size !== 0 ||
      recovery.transcriptSessionId !== this.transcriptSessionId ||
      typeof generation !== "string" ||
      generation !== recovery.supervisorGeneration ||
      !OPAQUE_ID.test(generation) ||
      !OPAQUE_ID.test(recovery.primeCursor.generation) ||
      !Number.isSafeInteger(recovery.primeCursor.sequence) ||
      recovery.primeCursor.sequence < 0 ||
      (recovery.sessionStatus !== "running" && recovery.sessionStatus !== "paused")
    ) {
      throw new PrimeSessionError();
    }
    this.transport = recovery.transport;
    this.currentSupervisorGeneration = generation;
  }

  toString(): string {
    return "[Asterion Prime resident session]";
  }

  toJSON(): Readonly<Record<string, string>> {
    return Object.freeze({
      kind: "prime-resident-session",
      active_session_id: this.activeSessionId,
      supervisor_generation: this.supervisorGeneration,
    });
  }

  async submitInput(
    inputId: string,
    delivery: PrimeInputDelivery,
    body: string,
  ): Promise<void> {
    if (!OPAQUE_ID.test(inputId) || !validText(body)) {
      throw new PrimeSessionError();
    }
    const streamingBehavior = delivery === "direct"
      ? undefined
      : delivery === "steer"
        ? "steer" as const
        : delivery === "follow_up"
          ? "followUp" as const
          : undefined;
    if (delivery !== "direct" && streamingBehavior === undefined) {
      throw new PrimeSessionError();
    }
    this.pendingAdmissions.add(inputId);
    try {
      await this.request({
        type: "prompt",
        activeSessionId: this.activeSessionId,
        message: body,
        queueIfBusy: delivery !== "direct",
        expandPromptTemplates: false,
        source: "rpc",
        admissionId: inputId,
        ...(streamingBehavior === undefined ? {} : { streamingBehavior }),
      }, `input-${inputId}`);
    } finally {
      this.pendingAdmissions.delete(inputId);
    }
  }

  async cancelPromptAdmission(
    admissionId: string,
  ): Promise<PrimePromptCancellation> {
    if (!OPAQUE_ID.test(admissionId)) {
      throw new PrimeSessionError();
    }
    try {
      const response = await this.request({
        type: "cancel_prompt_admission",
        activeSessionId: this.activeSessionId,
        admissionId,
      }, `cancel-admission-${admissionId}`);
      if (!isRecord(response.data) || typeof response.data.status !== "string") {
        throw new PrimePromptAdmissionUncertainError();
      }
      if (response.data.status === "cancelled" || response.data.status === "owned") {
        return response.data.status;
      }
      throw new PrimePromptAdmissionUncertainError();
    } catch {
      throw new PrimePromptAdmissionUncertainError();
    }
  }

  async pause(commandId: string): Promise<void> {
    const admissionUncertain = await this.interruptPendingAdmissions();
    await this.request({
      type: "abort_and_clear_queue",
      activeSessionId: this.activeSessionId,
    }, commandId);
    if (admissionUncertain) {
      throw new PrimePromptAdmissionUncertainError();
    }
  }

  async resume(commandId: string): Promise<void> {
    await this.request({
      type: "wait_for_idle",
      activeSessionId: this.activeSessionId,
    }, `${commandId}-idle`);
    await this.request({
      type: "prompt",
      activeSessionId: this.activeSessionId,
      message: "Continue the active goal.",
      queueIfBusy: false,
      expandPromptTemplates: false,
      source: "rpc",
      admissionId: `${commandId}-resume`,
    }, `${commandId}-resume`);
  }

  async attach(
    commandId: string,
    cursor?: PrimeDaemonCursor,
  ): Promise<PrimeDaemonResponse & { success: true }> {
    const attachCommand: PrimeDaemonCommand = {
      type: "attach",
      activeSessionId: this.activeSessionId,
      supportsExtensionUi: false,
      clientId: `asterion-${this.sessionId}`,
      capabilities: [
        "attach_snapshot",
        "chunked_snapshot",
        "event_sequence",
        "slim_attach",
      ],
      ...(cursor === undefined ? {} : { resumeCursor: cursor }),
      telemetryDisabled: true,
    };
    let response: PrimeDaemonResponse & { success: true };
    try {
      response = await this.request(attachCommand, commandId);
    } catch (error) {
      if (
        this.transport.isConnected !== false ||
        typeof this.transport.reconnect !== "function"
      ) {
        throw error;
      }
      await this.transport.reconnect();
      const generation = this.transport.hello?.supervisorGeneration;
      if (typeof generation !== "string" || !OPAQUE_ID.test(generation)) {
        throw new PrimeSessionError();
      }
      this.currentSupervisorGeneration = generation;
      response = await this.request(attachCommand, `${commandId}-reconnect`);
    }
    if (
      !isRecord(response.data) ||
      response.data.activeSessionId !== this.activeSessionId
    ) {
      throw new PrimeSessionError();
    }
    this.latestAttachResponse = response;
    return response;
  }

  async detach(commandId: string): Promise<void> {
    await this.request({
      type: "detach",
      activeSessionId: this.activeSessionId,
    }, commandId);
  }

  async cancel(commandId: string): Promise<void> {
    await this.interruptPendingAdmissions();
    await this.request({
      type: "abort_and_clear_queue",
      activeSessionId: this.activeSessionId,
    }, `${commandId}-abort`);
    await this.request({
      type: "kill",
      activeSessionId: this.activeSessionId,
    }, `${commandId}-kill`);
  }

  async setContextName(
    commandId: string,
    name: string,
  ): Promise<PrimeContextNameResult> {
    const normalized = typeof name === "string" ? name.trim() : "";
    if (!OPAQUE_ID.test(commandId) || !validText(normalized)) {
      throw new PrimeSessionError();
    }
    const stableCommandId = this.contextCommandId(commandId, "set-name");
    try {
      const deferred = await this.transport.requestDeferred({
        type: "set_session_name",
        activeSessionId: this.activeSessionId,
        name,
      }, stableCommandId);
      if (
        !deferred.response.success ||
        deferred.response.command !== "set_session_name"
      ) {
        throw new PrimeSessionError();
      }
      return Object.freeze({
        result: Object.freeze({
          continuationId: this.continuationId,
          nameSha256: sha256Text(normalized),
        }),
        acknowledge: () => {
          try {
            return deferred.acknowledge() === true;
          } catch {
            return false;
          }
        },
      });
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  async resumeContinuation(
    commandId: string,
    targetValue: PrimeContinuationLocator,
  ): Promise<PrimeContinuationResumeResult> {
    const target = this.validateContinuationTarget(commandId, targetValue);
    const stableCommandId = this.contextCommandId(commandId, "resume");
    const pending = this.pendingContinuationResumes.get(stableCommandId);
    if (pending !== undefined) {
      if (
        pending.locator.continuationId !== target.continuationId ||
        pending.locator.transcriptSessionId !== target.transcriptSessionId ||
        pending.locator.sessionPath !== target.sessionPath
      ) {
        throw new PrimeSessionError();
      }
      return pending;
    }
    if (target.continuationId === this.continuationId) {
      throw new PrimeSessionError();
    }
    try {
      const deferred = await this.transport.requestDeferred({
        type: "switch_session",
        activeSessionId: this.activeSessionId,
        sessionPath: target.sessionPath,
      }, stableCommandId);
      if (
        !deferred.response.success ||
        deferred.response.command !== "switch_session" ||
        !isRecord(deferred.response.data) ||
        !hasExactKeys(deferred.response.data, ["cancelled"]) ||
        deferred.response.data.cancelled !== false
      ) {
        throw new PrimeSessionError();
      }
      validateSessionHeader(
        await this.request({
          type: "get_session_header",
          activeSessionId: this.activeSessionId,
        }, `context-${commandId}-resume-header`),
        target.transcriptSessionId,
      );
      validateState(
        await this.request({
          type: "get_state",
          activeSessionId: this.activeSessionId,
        }, `context-${commandId}-resume-state`),
        this.activeSessionId,
        target.transcriptSessionId,
        target.sessionPath,
      );
      const previousContinuationId = this.continuationId;
      const transitionSha256 = sha256Text(JSON.stringify([
        "session.continuation.resume",
        previousContinuationId,
        target.continuationId,
        commandId,
      ]));
      const resumed = Object.freeze({
        locator: target,
        result: Object.freeze({
          previousContinuationId,
          currentContinuationId: target.continuationId,
          transitionSha256,
        }),
        acknowledge: () => {
          try {
            return deferred.acknowledge() === true;
          } catch {
            return false;
          }
        },
      });
      this.pendingContinuationResumes.set(stableCommandId, resumed);
      return resumed;
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  async deleteContinuation(
    commandId: string,
    targetValue: PrimeContinuationLocator,
  ): Promise<PrimeContinuationDeleteResult> {
    const target = this.validateContinuationTarget(commandId, targetValue);
    if (target.continuationId === this.continuationId) {
      throw new PrimeSessionError();
    }
    const stableCommandId = this.contextCommandId(commandId, "delete");
    try {
      const deferred = await this.transport.requestDeferred({
        type: "delete_saved_session",
        activeSessionId: this.activeSessionId,
        sessionPath: target.sessionPath,
      }, stableCommandId);
      if (
        !deferred.response.success ||
        deferred.response.command !== "delete_saved_session" ||
        !isRecord(deferred.response.data) ||
        !hasExactKeys(deferred.response.data, ["method", "ok"]) ||
        deferred.response.data.ok !== true ||
        (deferred.response.data.method !== "trash" &&
          deferred.response.data.method !== "unlink")
      ) {
        throw new PrimeSessionError();
      }
      return Object.freeze({
        result: Object.freeze({
          continuationId: target.continuationId,
          deletionSha256: sha256Text(JSON.stringify([
            "session.continuation.delete",
            target.continuationId,
            commandId,
          ])),
        }),
        acknowledge: () => {
          try {
            return deferred.acknowledge() === true;
          } catch {
            return false;
          }
        },
      });
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  async readContextTree(
    commandId: string,
    continuationId: string,
  ): Promise<PrimeSessionTreeProjection> {
    this.validateCurrentContextTarget(commandId, continuationId);
    return this.readSessionTree(`context-${commandId}-tree-read`);
  }

  async navigateContextTree(
    commandId: string,
    continuationId: string,
    entryId: string,
    previousLeafId: string | null,
  ): Promise<PrimeTreeNavigationResult> {
    this.validateCurrentContextTarget(commandId, continuationId);
    if (
      !OPAQUE_ID.test(entryId) ||
      (previousLeafId !== null && !OPAQUE_ID.test(previousLeafId))
    ) {
      throw new PrimeSessionError();
    }
    const stableCommandId = this.contextCommandId(commandId, "tree-navigate");
    const pending = this.pendingTreeNavigations.get(stableCommandId);
    if (pending !== undefined) {
      if (
        pending.continuationId !== continuationId ||
        pending.entryId !== entryId ||
        pending.previousLeafId !== previousLeafId
      ) {
        throw new PrimeSessionError();
      }
      return pending.value;
    }
    try {
      const before = await this.readSessionTree(
        `context-${commandId}-tree-navigate-before`,
      );
      if (!before.nodes.some((node) => node.entry_id === entryId)) {
        throw new PrimeSessionError();
      }
      const deferred = await this.transport.requestDeferred({
        type: "navigate_tree",
        activeSessionId: this.activeSessionId,
        targetId: entryId,
        summarize: false,
      }, stableCommandId);
      if (
        !deferred.response.success ||
        deferred.response.command !== "navigate_tree" ||
        !isRecord(deferred.response.data) ||
        !hasOnlyKeys(deferred.response.data, ["cancelled", "editorText"]) ||
        !Object.hasOwn(deferred.response.data, "cancelled") ||
        deferred.response.data.cancelled !== false ||
        (Object.hasOwn(deferred.response.data, "editorText") &&
          !validText(deferred.response.data.editorText))
      ) {
        throw new PrimeSessionError();
      }
      const after = await this.readSessionTree(
        `context-${commandId}-tree-navigate-after`,
      );
      const value = Object.freeze({
        result: Object.freeze({
          continuationId,
          previousLeafId,
          currentLeafId: after.leafId,
          transitionSha256: sha256Text(JSON.stringify([
            "session.tree.navigate",
            continuationId,
            previousLeafId,
            after.leafId,
            entryId,
            commandId,
          ])),
        }),
        acknowledge: () => {
          try {
            return deferred.acknowledge() === true;
          } catch {
            return false;
          }
        },
      });
      this.pendingTreeNavigations.set(stableCommandId, Object.freeze({
        continuationId,
        entryId,
        previousLeafId,
        value,
      }));
      return value;
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  async forkContext(
    commandId: string,
    continuationId: string,
    entryId: string,
    position: "at" | "before",
  ): Promise<PrimeForkCloneResult> {
    return this.replaceContextByFork(
      "session.fork",
      commandId,
      continuationId,
      entryId,
      position,
    );
  }

  async cloneContext(
    commandId: string,
    continuationId: string,
    selectedLeafId: string,
  ): Promise<PrimeForkCloneResult> {
    return this.replaceContextByFork(
      "session.clone",
      commandId,
      continuationId,
      selectedLeafId,
      "at",
    );
  }

  adoptContinuation(targetValue: PrimeContinuationLocator): void {
    const target = this.validateContinuationTarget("adopt-continuation", targetValue);
    this.currentContinuationId = target.continuationId;
    this.currentTranscriptSessionId = target.transcriptSessionId;
    this.currentSessionPath = target.sessionPath;
    this.lastContextCounters = undefined;
  }

  async describeContext(
    commandId: string,
    sessionStatus: PrimeContextStatus,
  ): Promise<PrimeContextDescription> {
    if (
      !OPAQUE_ID.test(commandId) ||
      ![
        "cancelled",
        "completed",
        "creating",
        "failed",
        "idle",
        "paused",
        "recovery-required",
        "running",
      ].includes(sessionStatus) ||
      this.currentSessionPath === undefined
    ) {
      throw new PrimeSessionError();
    }
    const state = validateState(
      await this.request({
        type: "get_state",
        activeSessionId: this.activeSessionId,
      }, `context-${commandId}-state`),
      this.activeSessionId,
      this.transcriptSessionId,
      this.currentSessionPath,
    );
    const stats = validateStats(
      await this.request({
        type: "get_session_stats",
        activeSessionId: this.activeSessionId,
      }, `context-${commandId}-stats`),
      this.transcriptSessionId,
      this.currentSessionPath,
    );
    if (state.messageCount !== stats.totalMessages) {
      throw new PrimeSessionError();
    }
    if (
      this.lastContextCounters !== undefined &&
      (stats.counters.turns < this.lastContextCounters.turns ||
        stats.counters.input < this.lastContextCounters.input ||
        stats.counters.output < this.lastContextCounters.output ||
        stats.counters.cacheRead < this.lastContextCounters.cacheRead ||
        stats.counters.cacheWrite < this.lastContextCounters.cacheWrite ||
        stats.counters.total < this.lastContextCounters.total ||
        stats.counters.costMicros < this.lastContextCounters.costMicros)
    ) {
      throw new PrimeSessionError();
    }
    this.lastContextCounters = stats.counters;
    const projectedStatus = sessionStatus === "running"
      ? state.active ? "running" : "idle"
      : sessionStatus;
    return Object.freeze({
      continuationId: this.continuationId,
      status: projectedStatus,
      contextTokens: stats.contextTokens,
      turns: stats.counters.turns,
      usage: Object.freeze({
        controller_tokens: stats.counters.total,
        application_tokens: 0,
        child_tokens: 0,
        aggregate_tokens: stats.counters.total,
        cost_micros: stats.counters.costMicros,
      }),
      nameSha256: state.nameSha256,
    });
  }

  acknowledgeContext(commandId: string): boolean {
    if (!OPAQUE_ID.test(commandId)) {
      throw new PrimeSessionError();
    }
    try {
      return this.transport.acknowledgeResult(
        this.contextCommandId(commandId, "set-name"),
      );
    } catch {
      return false;
    }
  }

  acknowledgeContinuation(
    commandId: string,
    operation: "session.continuation.delete" | "session.continuation.resume",
  ): boolean {
    if (!OPAQUE_ID.test(commandId)) {
      throw new PrimeSessionError();
    }
    const purpose = operation === "session.continuation.resume"
      ? "resume"
      : "delete";
    try {
      return this.transport.acknowledgeResult(
        this.contextCommandId(commandId, purpose),
      );
    } catch {
      return false;
    }
  }

  acknowledgeTreeMutation(commandId: string): boolean {
    if (!OPAQUE_ID.test(commandId)) {
      throw new PrimeSessionError();
    }
    try {
      return this.transport.acknowledgeResult(
        this.contextCommandId(commandId, "tree-navigate"),
      );
    } catch {
      return false;
    }
  }

  acknowledgeForkClone(
    commandId: string,
    operation: "session.fork" | "session.clone",
  ): boolean {
    if (!OPAQUE_ID.test(commandId)) {
      throw new PrimeSessionError();
    }
    try {
      return this.transport.acknowledgeResult(
        this.contextCommandId(
          commandId,
          operation === "session.fork" ? "fork" : "clone",
        ),
      );
    } catch {
      return false;
    }
  }

  private async readSessionTree(
    commandPurpose: string,
  ): Promise<PrimeSessionTreeProjection> {
    try {
      return projectPrimeSessionTree(await this.request({
        type: "get_session_tree",
        activeSessionId: this.activeSessionId,
      }, commandPurpose));
    } catch {
      throw new PrimeSessionError();
    }
  }

  private async replaceContextByFork(
    operation: "session.fork" | "session.clone",
    commandId: string,
    continuationId: string,
    entryId: string,
    position: "at" | "before",
  ): Promise<PrimeForkCloneResult> {
    if (
      !OPAQUE_ID.test(commandId) ||
      !OPAQUE_ID.test(continuationId) ||
      !OPAQUE_ID.test(entryId) ||
      (position !== "at" && position !== "before")
    ) {
      throw new PrimeSessionError();
    }
    const purpose = operation === "session.fork" ? "fork" : "clone";
    const stableCommandId = this.contextCommandId(commandId, purpose);
    const pending = this.pendingForkClones.get(stableCommandId);
    if (pending !== undefined) {
      if (
        pending.operation !== operation ||
        pending.sourceContinuationId !== continuationId ||
        pending.entryId !== entryId ||
        pending.position !== position
      ) {
        throw new PrimeSessionError();
      }
      return pending.value;
    }
    if (
      continuationId !== this.continuationId ||
      this.currentSessionPath === undefined
    ) {
      throw new PrimeSessionError();
    }
    try {
      const sourceTranscriptSessionId = this.transcriptSessionId;
      const sourceSessionPath = this.currentSessionPath;
      const deferred = await this.transport.requestDeferred({
        type: "fork",
        activeSessionId: this.activeSessionId,
        entryId,
        position,
      }, stableCommandId);
      if (
        !deferred.response.success ||
        deferred.response.command !== "fork" ||
        !isRecord(deferred.response.data) ||
        !hasOnlyKeys(deferred.response.data, ["cancelled", "selectedText"]) ||
        !Object.hasOwn(deferred.response.data, "cancelled") ||
        deferred.response.data.cancelled !== false ||
        (Object.hasOwn(deferred.response.data, "selectedText") &&
          (typeof deferred.response.data.selectedText !== "string" ||
            Buffer.byteLength(deferred.response.data.selectedText, "utf8") >
              MAX_PRIVATE_TEXT_BYTES))
      ) {
        throw new PrimeSessionError();
      }
      const transcriptSessionId = transcriptIdFromSessionHeader(
        await this.request({
          type: "get_session_header",
          activeSessionId: this.activeSessionId,
        }, `context-${commandId}-${purpose}-header`),
      );
      const sessionPath = sessionPathFromState(
        await this.request({
          type: "get_state",
          activeSessionId: this.activeSessionId,
        }, `context-${commandId}-${purpose}-state`),
        this.activeSessionId,
        transcriptSessionId,
        dirname(sourceSessionPath),
      );
      if (
        transcriptSessionId === sourceTranscriptSessionId ||
        sessionPath === sourceSessionPath
      ) {
        throw new PrimeSessionError();
      }
      const tree = await this.readSessionTree(
        `context-${commandId}-${purpose}-tree`,
      );
      const newContinuationId = continuationIdForTranscript(
        this.sessionId,
        transcriptSessionId,
      );
      if (newContinuationId === continuationId) {
        throw new PrimeSessionError();
      }
      const locator = Object.freeze({
        continuationId: newContinuationId,
        activeSessionId: this.activeSessionId,
        transcriptSessionId,
        supervisorGeneration: this.supervisorGeneration,
        sessionPath,
      });
      const value = Object.freeze({
        locator,
        result: Object.freeze({
          sourceContinuationId: continuationId,
          newContinuationId,
          activeLeafId: tree.leafId,
          transitionSha256: sha256Text(JSON.stringify([
            operation,
            continuationId,
            newContinuationId,
            entryId,
            position,
            commandId,
          ])),
        }),
        acknowledge: () => {
          try {
            return deferred.acknowledge() === true;
          } catch {
            return false;
          }
        },
      });
      this.pendingForkClones.set(stableCommandId, Object.freeze({
        operation,
        sourceContinuationId: continuationId,
        entryId,
        position,
        value,
      }));
      return value;
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  private validateCurrentContextTarget(
    commandId: string,
    continuationId: string,
  ): void {
    if (
      !OPAQUE_ID.test(commandId) ||
      !OPAQUE_ID.test(continuationId) ||
      continuationId !== this.continuationId
    ) {
      throw new PrimeSessionError();
    }
  }

  acknowledgeCheckpoint(checkpointId: string): boolean {
    if (!OPAQUE_ID.test(checkpointId)) {
      throw new PrimeSessionError();
    }
    try {
      return this.transport.acknowledgeResult(
        `${this.sessionId}-checkpoint-${checkpointId}-prepare`,
      );
    } catch {
      return false;
    }
  }

  private async interruptPendingAdmissions(): Promise<boolean> {
    let uncertain = false;
    for (const admissionId of [...this.pendingAdmissions].sort()) {
      try {
        await this.cancelPromptAdmission(admissionId);
      } catch (error) {
        if (!(error instanceof PrimePromptAdmissionUncertainError)) {
          throw error;
        }
        uncertain = true;
      }
    }
    return uncertain;
  }

  private async request(
    command: PrimeDaemonCommand,
    commandPurpose: string,
  ): Promise<PrimeDaemonResponse & { success: true }> {
    this.commandSequence += 1;
    const commandId = `${this.sessionId}-${this.commandSequence}-${commandPurpose}`;
    try {
      const response = await this.transport.request(command, commandId);
      if (!response.success || response.command !== command.type) {
        throw new PrimeSessionError();
      }
      return response;
    } catch (error) {
      if (error instanceof PrimeSessionError) {
        throw error;
      }
      throw new PrimeSessionError();
    }
  }

  private contextCommandId(commandId: string, purpose: string): string {
    return `${this.sessionId}-context-${commandId}-${purpose}`;
  }

  private validateContinuationTarget(
    commandId: string,
    value: PrimeContinuationLocator,
  ): PrimeContinuationLocator {
    if (
      !OPAQUE_ID.test(commandId) ||
      !isRecord(value) ||
      !hasExactKeys(value, [
        "activeSessionId",
        "continuationId",
        "sessionPath",
        "supervisorGeneration",
        "transcriptSessionId",
      ]) ||
      ![
        value.activeSessionId,
        value.continuationId,
        value.supervisorGeneration,
        value.transcriptSessionId,
      ].every((item) => typeof item === "string" && OPAQUE_ID.test(item)) ||
      value.activeSessionId !== this.activeSessionId ||
      value.supervisorGeneration !== this.supervisorGeneration ||
      typeof value.sessionPath !== "string" ||
      !isAbsolute(value.sessionPath) ||
      resolve(value.sessionPath) !== value.sessionPath
    ) {
      throw new PrimeSessionError();
    }
    return Object.freeze({
      activeSessionId: value.activeSessionId,
      continuationId: value.continuationId,
      transcriptSessionId: value.transcriptSessionId,
      supervisorGeneration: value.supervisorGeneration,
      sessionPath: value.sessionPath,
    });
  }
}
