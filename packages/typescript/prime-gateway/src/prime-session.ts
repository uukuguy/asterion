import { isAbsolute } from "node:path";

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

export interface PrimeDaemonTransport {
  readonly hello: PrimeDaemonHello | undefined;
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
  readonly supervisorGeneration: string;
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
  readonly bindIdentity: (identity: PrimeSessionIdentity) => Promise<void>;
}

export type PrimeInputDelivery = "direct" | "steer" | "follow_up";
export type PrimePromptCancellation = "cancelled" | "owned";

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

function activeSessionIdFromCreate(response: PrimeDaemonResponse): string {
  if (
    !response.success ||
    response.command !== "create" ||
    !isRecord(response.data) ||
    typeof response.data.activeSessionId !== "string" ||
    !OPAQUE_ID.test(response.data.activeSessionId)
  ) {
    throw new PrimeSessionError();
  }
  return response.data.activeSessionId;
}

export class PrimeSession {
  private commandSequence = 0;
  private readonly pendingAdmissions = new Set<string>();

  private constructor(
    private readonly transport: PrimeDaemonTransport,
    private readonly sessionId: string,
    readonly activeSessionId: string,
    readonly supervisorGeneration: string,
  ) {}

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
      const activeSessionId = activeSessionIdFromCreate(deferredCreate.response);
      await options.bindIdentity(Object.freeze({
        activeSessionId,
        supervisorGeneration: generation,
      }));
      deferredCreate.acknowledge();
      const session = new PrimeSession(
        options.transport,
        options.sessionId,
        activeSessionId,
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

  subscribe(listener: PrimeDaemonListener): () => void {
    try {
      return this.transport.subscribe(listener);
    } catch {
      throw new PrimeSessionError();
    }
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
  ): Promise<void> {
    const response = await this.request({
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
    }, commandId);
    if (
      !isRecord(response.data) ||
      response.data.activeSessionId !== this.activeSessionId
    ) {
      throw new PrimeSessionError();
    }
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
}
