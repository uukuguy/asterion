import {
  validateControlCommand,
  validateControlEvent,
  validateSessionContextCommand,
  validateSessionContextReceipt,
} from "@dci/agent-runtime";
import type {
  ActionResolution,
  ControlCommand,
  ControlEvent,
  GoalStatus,
  SessionContextCommand,
  SessionContextReceipt,
} from "@dci/agent-runtime";

import type {
  GatewayDurableStore,
  GatewayContextBinding,
  PrimeIdentityBinding,
} from "./durable-store.js";
import {
  canonicalJsonBytes,
  sha256Hex,
} from "./durable-store.js";
import {
  PrimeEventMapper,
  PrimeEventMappingError,
} from "./event-mapper.js";
import type {
  PrimeMappedEventIdentity,
} from "./event-mapper.js";
import type {
  PrivateContinuationLocator,
  PrivateValueRef,
} from "./private-store.js";
import type {
  PrimeCheckpointCreated,
  PrimeCheckpointRecovery,
} from "./checkpoint.js";
import {
  recoveryFromAttach,
} from "./checkpoint.js";
import type {
  PrimeDaemonListener,
} from "./daemon-client.js";
import type {
  PrimeDaemonCursor,
  PrimeDaemonOutbound,
  PrimeDaemonResponse,
} from "./daemon-wire.js";
import type {
  PrimeContextDescription,
  PrimeContextNameResult,
  PrimeContextStatus,
  PrimeInputDelivery,
  PrimeSessionInitialBinding,
} from "./prime-session.js";
import {
  PrimePromptAdmissionUncertainError,
} from "./prime-session.js";

type CheckpointPayload = Extract<
  ControlEvent,
  { readonly type: "checkpoint.created" }
>["payload"];

export interface PrimeGatewaySession {
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly continuationId: string;
  readonly supervisorGeneration: string;
  readonly lastAttachResponse: PrimeDaemonResponse | undefined;
  adoptRecovery(recovery: PrimeCheckpointRecovery): void;
  acknowledgeCheckpoint(checkpointId: string): boolean;
  subscribe(listener: PrimeDaemonListener): () => void;
  submitInput(
    inputId: string,
    delivery: PrimeInputDelivery,
    body: string,
  ): Promise<void>;
  pause(commandId: string): Promise<void>;
  resume(commandId: string): Promise<void>;
  attach(commandId: string, cursor?: PrimeDaemonCursor): Promise<PrimeDaemonResponse>;
  detach(commandId: string): Promise<void>;
  cancel(commandId: string): Promise<void>;
  describeContext(
    commandId: string,
    status: PrimeContextStatus,
  ): Promise<PrimeContextDescription>;
  setContextName(
    commandId: string,
    name: string,
  ): Promise<PrimeContextNameResult>;
  acknowledgeContext(commandId: string): boolean;
}

export interface PrimeGatewayPrivateInputs {
  readInput(reference: string): Promise<string>;
  putContinuationLocator(
    locator: PrivateContinuationLocator,
  ): Promise<GatewayContextBinding>;
  readContinuationLocator(
    binding: GatewayContextBinding,
  ): Promise<PrivateContinuationLocator>;
}

export interface PrimeGatewayPrivateResults {
  readBoundResultReference(
    commandId: string,
    actionId: string,
    sourceReceiptRef: string,
  ): Promise<PrivateValueRef>;
}

export interface PrimeGatewayCreateContext {
  readonly goalId: string;
  readonly authorityRevision: number;
  readonly causalParentIds: readonly string[];
}

export interface PrimeGatewayOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly authorityId: string;
  readonly store: GatewayDurableStore;
  readonly privateValues: PrimeGatewayPrivateInputs;
  readonly privateResults?: PrimeGatewayPrivateResults;
  readonly createSession: (
    goal: string,
    bindIdentity: (identity: PrimeSessionInitialBinding) => Promise<void>,
    context: PrimeGatewayCreateContext,
  ) => Promise<PrimeGatewaySession>;
  readonly restoreSession?: (
    identity: PrimeIdentityBinding & Readonly<{
      continuationId: string;
      sessionPath: string;
    }>,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void>,
  ) => Promise<PrimeGatewaySession>;
  readonly createCheckpoint: (
    checkpointId: string,
    coveredSequence: number,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void>,
  ) => Promise<PrimeCheckpointCreated>;
  readonly sessionContext?: PrimeGatewaySessionContextExecutor;
  readonly onSessionReady?: (context: PrimeGatewayCreateContext) => void;
  readonly now?: () => string;
}

export interface PrimeGatewaySessionContextResult {
  readonly receipt: SessionContextReceipt;
  readonly nextBinding: GatewayContextBinding | null;
  readonly acknowledge?: () => boolean;
}

export interface PrimeGatewaySessionContextExecutor {
  execute(
    command: SessionContextCommand,
  ): Promise<PrimeGatewaySessionContextResult>;
  cancel(commandId: string): Promise<void>;
}

export interface GatewayAdmissionResult {
  readonly resolution: "admitted" | "rejected";
  readonly reasonCode: string;
}

export interface GatewayTerminalResult {
  readonly resolution: "succeeded" | "failed" | "cancelled" | "uncertain";
  readonly reasonCode: string;
  readonly resultRef?: PrivateValueRef;
}

type GatewayActionStatus = "proposed" | ActionResolution;
type GatewaySessionStatus =
  | "created"
  | "running"
  | "paused"
  | "recovery_required"
  | "terminal";

interface ActionRecord {
  status: GatewayActionStatus;
  kind: string;
  targetId: string;
  reasonCode?: string;
  resultRef?: PrivateValueRef;
  admissionPromise?: Promise<GatewayAdmissionResult>;
  resolveAdmission?: (value: GatewayAdmissionResult) => void;
  terminalPromise?: Promise<GatewayTerminalResult>;
  resolveTerminal?: (value: GatewayTerminalResult) => void;
}

interface CommandExecution {
  readonly digest: string;
  readonly promise: Promise<void>;
}

interface ContextExecution {
  readonly digest: string;
  readonly promise: Promise<SessionContextReceipt>;
  settled: boolean;
}

interface ReservedEventIdentity {
  readonly eventId: string;
  readonly emittedAt: string;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

export class PrimeGatewayError extends Error {
  constructor() {
    super("Prime gateway operation failed");
    this.name = "PrimeGatewayError";
  }
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function isPrivateRef(value: string): value is PrivateValueRef {
  return /^private:[A-Za-z0-9._:-]+$/u.test(value);
}

export class PrimeGateway {
  private readonly actions = new Map<string, ActionRecord>();
  private readonly checkpoints = new Set<string>();
  private readonly pendingCheckpointAcknowledgements = new Set<string>();
  private readonly commandExecutions = new Map<string, CommandExecution>();
  private readonly contextExecutions = new Map<string, ContextExecution>();
  private readonly reservedEvents = new Map<number, ReservedEventIdentity>();
  private readonly now: () => string;
  private nextSequence: number;
  private lastAppendedSequence: number;
  private session: PrimeGatewaySession | undefined;
  private mapper: PrimeEventMapper | undefined;
  private unsubscribe: (() => void) | undefined;
  private eventQueue: Promise<void> = Promise.resolve();
  private durableQueue: Promise<void> = Promise.resolve();
  private goalId: string | undefined;
  private goalStatus: GoalStatus | undefined;
  private sessionStatus: GatewaySessionStatus | undefined;
  private recoveryBaseStatus: GatewaySessionStatus | undefined;
  private terminal = false;
  private closed = false;

  private constructor(private readonly options: PrimeGatewayOptions) {
    this.now = options.now ?? (() => new Date().toISOString());
    const events = options.store
      .eventsAfter(0)
      .map(({ event }) => event)
      .filter((event) => event.generation === options.generation);
    this.nextSequence = (events.at(-1)?.sequence ?? 0) + 1;
    this.lastAppendedSequence = this.nextSequence - 1;
    for (const event of events) {
      if (event.type === "session.created") {
        this.goalId = event.payload.goal_id;
        this.goalStatus ??= "active";
      } else if (event.type === "goal.updated") {
        this.goalStatus = event.payload.status;
      } else if (event.type === "action.proposed") {
        this.actions.set(event.payload.action_id, {
          status: "proposed",
          kind: event.payload.kind,
          targetId: this.actionTargetId(event),
        });
      } else if (event.type === "checkpoint.created") {
        this.checkpoints.add(event.payload.checkpoint_id);
      }
      this.updateSessionStatus(event);
    }
    for (const operation of options.store.contextOperations()) {
      this.contextExecutions.set(operation.command.command_id, {
        digest: sha256Hex(canonicalJsonBytes(operation.command)),
        promise: Promise.resolve(operation.receipt),
        settled: true,
      });
    }
  }

  static async open(options: PrimeGatewayOptions): Promise<PrimeGateway> {
    if (
      !OPAQUE_ID.test(options.sessionId) ||
      !positiveInteger(options.generation) ||
      !OPAQUE_ID.test(options.authorityId) ||
      typeof options.createSession !== "function" ||
      typeof options.createCheckpoint !== "function" ||
      (options.restoreSession !== undefined &&
        typeof options.restoreSession !== "function") ||
      (options.sessionContext !== undefined &&
        (typeof options.sessionContext.execute !== "function" ||
          typeof options.sessionContext.cancel !== "function")) ||
      options.store.snapshot().sessionId !== options.sessionId
    ) {
      throw new PrimeGatewayError();
    }
    const gateway = new PrimeGateway(options);
    await gateway.restoreActionCommands();
    await gateway.restoreExistingSession();
    await gateway.restoreGoalTerminals();
    return gateway;
  }

  nextEventIdentity(): PrimeMappedEventIdentity {
    if (this.closed || this.terminal) {
      throw new PrimeGatewayError();
    }
    const sequence = this.nextSequence;
    const emittedAt = this.now();
    if (typeof emittedAt !== "string" || Number.isNaN(Date.parse(emittedAt))) {
      throw new PrimeGatewayError();
    }
    this.nextSequence += 1;
    const eventId = `prime-gateway-${this.options.generation}-${sequence}`;
    this.reservedEvents.set(sequence, { eventId, emittedAt });
    return Object.freeze({
      eventId,
      sequence,
      emittedAt,
    });
  }

  toString(): string {
    return "[Asterion Prime gateway]";
  }

  toJSON(): Readonly<Record<string, string | number>> {
    return Object.freeze({
      kind: "asterion-prime-gateway",
      session_id: this.options.sessionId,
      generation: this.options.generation,
      status: this.sessionStatus ?? "uninitialized",
    });
  }

  async accept(value: unknown): Promise<void> {
    this.assertOpen();
    let command: ControlCommand;
    try {
      command = validateControlCommand(value);
    } catch {
      throw new PrimeGatewayError();
    }
    if (command.session_id !== this.options.sessionId) {
      throw new PrimeGatewayError();
    }
    this.retryCheckpointAcknowledgements();
    const digest = sha256Hex(canonicalJsonBytes(command));
    const existing = this.commandExecutions.get(command.command_id);
    if (existing !== undefined) {
      if (existing.digest !== digest) {
        throw new PrimeGatewayError();
      }
      return existing.promise;
    }
    let promise: Promise<void>;
    promise = this.persistAndHandle(command).catch((error) => {
      const current = this.commandExecutions.get(command.command_id);
      if (current?.promise === promise) {
        this.commandExecutions.delete(command.command_id);
      }
      throw error;
    });
    this.commandExecutions.set(command.command_id, { digest, promise });
    return promise;
  }

  async executeSessionContext(
    value: unknown,
    preparePrivate: () => Promise<void>,
  ): Promise<SessionContextReceipt> {
    this.assertOpen();
    if (
      typeof preparePrivate !== "function" ||
      this.options.store.snapshot().primeIdentity === undefined
    ) {
      throw new PrimeGatewayError();
    }
    let command: SessionContextCommand;
    try {
      command = validateSessionContextCommand(value);
    } catch {
      throw new PrimeGatewayError();
    }
    if (
      command.session_id !== this.options.sessionId ||
      command.generation !== this.options.generation
    ) {
      throw new PrimeGatewayError();
    }
    const digest = sha256Hex(canonicalJsonBytes(command));
    const existing = this.contextExecutions.get(command.command_id);
    if (existing !== undefined) {
      if (existing.digest !== digest) {
        throw new PrimeGatewayError();
      }
      try {
        await preparePrivate();
      } catch {
        throw new PrimeGatewayError();
      }
      const receipt = await existing.promise;
      this.retryContextAcknowledgement(command);
      return receipt;
    }
    const executor = this.options.sessionContext ?? this.nativeContextExecutor();
    let execution: ContextExecution;
    const promise = this.persistAndExecuteSessionContext(
      command,
      executor,
      preparePrivate,
    )
      .then((receipt) => {
        execution.settled = true;
        return receipt;
      })
      .catch((error) => {
        if (this.contextExecutions.get(command.command_id) === execution) {
          this.contextExecutions.delete(command.command_id);
        }
        throw error;
      });
    execution = { digest, promise, settled: false };
    this.contextExecutions.set(command.command_id, execution);
    return promise;
  }

  async cancelSessionContext(commandId: string): Promise<void> {
    this.assertOpen();
    const executor = this.options.sessionContext;
    const execution = this.contextExecutions.get(commandId);
    if (
      executor === undefined ||
      !OPAQUE_ID.test(commandId) ||
      execution === undefined ||
      execution.settled
    ) {
      throw new PrimeGatewayError();
    }
    try {
      await executor.cancel(commandId);
    } catch {
      throw new PrimeGatewayError();
    }
  }

  async emitActionProposal(event: ControlEvent): Promise<void> {
    this.assertOpen();
    if (
      event.type !== "action.proposed" ||
      event.session_id !== this.options.sessionId ||
      event.generation !== this.options.generation ||
      this.sessionStatus !== "running" ||
      !this.matchesReservation(event) ||
      this.actions.has(event.payload.action_id)
    ) {
      if (
        event.type === "action.proposed" &&
        event.session_id === this.options.sessionId &&
        event.generation === this.options.generation &&
        this.matchesReservation(event)
      ) {
        this.releaseReservedEvent(event);
      }
      throw new PrimeGatewayError();
    }
    await this.append(event);
    this.actions.set(event.payload.action_id, {
      status: "proposed",
      kind: event.payload.kind,
      targetId: this.actionTargetId(event),
    });
  }

  waitForAdmission(actionId: string): Promise<GatewayAdmissionResult> {
    this.assertActionId(actionId);
    const action = this.requireAction(actionId);
    if (action.status === "admitted" || action.status === "rejected") {
      return Promise.resolve(Object.freeze({
        resolution: action.status,
        reasonCode: action.reasonCode ?? "resolved",
      }));
    }
    if (!["proposed"].includes(action.status)) {
      return Promise.reject(new PrimeGatewayError());
    }
    if (action.admissionPromise === undefined) {
      action.admissionPromise = new Promise((resolve) => {
        action.resolveAdmission = resolve;
      });
    }
    return action.admissionPromise;
  }

  waitForTerminal(actionId: string): Promise<GatewayTerminalResult> {
    this.assertActionId(actionId);
    const action = this.requireAction(actionId);
    if (["succeeded", "failed", "cancelled", "uncertain"].includes(action.status)) {
      return Promise.resolve(this.terminalResult(action));
    }
    if (action.terminalPromise === undefined) {
      action.terminalPromise = new Promise((resolve) => {
        action.resolveTerminal = resolve;
      });
    }
    return action.terminalPromise;
  }

  async actionStatus(actionId: string): Promise<unknown> {
    this.assertActionId(actionId);
    const action = this.requireAction(actionId);
    return Object.freeze({
      action_id: actionId,
      status: action.status,
      ...(action.reasonCode === undefined
        ? {}
        : { reason_code: action.reasonCode }),
    });
  }

  async detach(): Promise<void> {
    this.assertOpen();
    if (this.session !== undefined) {
      await this.session.detach("asterion-detach");
    }
  }

  async settle(): Promise<void> {
    await this.eventQueue;
    await this.durableQueue;
  }

  async close(): Promise<void> {
    if (this.closed) {
      return;
    }
    await this.settle();
    this.closed = true;
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  private async handleCommand(command: ControlCommand): Promise<void> {
    if (this.terminal && command.type !== "action.resolve") {
      throw new PrimeGatewayError();
    }
    switch (command.type) {
      case "session.create":
        this.requireSessionStatus(undefined);
        await this.create(command);
        return;
      case "input.submit":
        this.requireSessionStatus("running");
        await this.requireSession().submitInput(
          command.payload.input_id,
          command.payload.delivery,
          await this.options.privateValues.readInput(command.payload.content_ref),
        );
        return;
      case "session.pause":
        this.requireSessionStatus("running");
        try {
          await this.requireSession().pause(command.command_id);
        } catch (error) {
          if (!(error instanceof PrimePromptAdmissionUncertainError)) {
            throw error;
          }
          await this.append(this.event("fault.raised", {
            code: "prime-prompt-admission-uncertain",
            recoverable: true,
            evidence_ref: null,
          }));
          await this.append(this.reasonEvent(
            "session.recovery-required",
            "prime-prompt-admission-uncertain",
          ));
          this.mapper?.noteExternalRecoveryRequired();
          return;
        }
        await this.append(this.reasonEvent("session.paused", command.payload.reason_code));
        this.mapper?.noteExternalSessionStatus("paused");
        return;
      case "session.resume":
        this.requireSessionStatus("paused");
        await this.requireSession().resume(command.command_id);
        await this.append(this.reasonEvent("session.running", command.payload.reason_code));
        this.mapper?.noteExternalSessionStatus("running");
        return;
      case "session.attach":
        if (this.sessionStatus === undefined || this.sessionStatus === "terminal") {
          throw new PrimeGatewayError();
        }
        const attachedSession = this.requireSession();
        const previousSupervisorGeneration = attachedSession.supervisorGeneration;
        const fallbackCursor = this.options.store.snapshot().primeCursor;
        const attachResponse = await attachedSession.attach(
          command.command_id,
          fallbackCursor,
        );
        if (attachedSession.supervisorGeneration !== previousSupervisorGeneration) {
          const recovery = recoveryFromAttach(
            attachResponse,
            attachedSession.activeSessionId,
            attachedSession.transcriptSessionId,
            fallbackCursor ?? {
              generation: attachedSession.supervisorGeneration,
              sequence: 0,
            },
          );
          await this.append(this.reasonEvent(
            "session.recovery-required",
            "prime-supervisor-restart",
          ));
          await this.refreshContextBinding(
            attachedSession,
            attachedSession.supervisorGeneration,
          );
          await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
            activeSessionId: attachedSession.activeSessionId,
            transcriptSessionId: attachedSession.transcriptSessionId,
            supervisorGeneration: attachedSession.supervisorGeneration,
          }));
          await this.enqueueDurable(
            () => this.options.store.recordPrimeCursor(recovery.primeCursor),
          );
          this.mapper = this.recoveredMapper(recovery.primeCursor);
          const restoredStatus = recovery.sessionStatus;
          await this.append(this.reasonEvent(
            restoredStatus === "running" ? "session.running" : "session.paused",
            "prime-supervisor-restored",
          ));
          this.mapper.noteExternalSessionStatus(restoredStatus);
        }
        return;
      case "session.cancel":
        if (
          this.sessionStatus === undefined ||
          this.sessionStatus === "terminal"
        ) {
          throw new PrimeGatewayError();
        }
        await this.cancel(command);
        return;
      case "checkpoint.request":
        if (
          !this.checkpoints.has(command.payload.checkpoint_id) &&
          this.sessionStatus !== "running" &&
          this.sessionStatus !== "recovery_required"
        ) {
          throw new PrimeGatewayError();
        }
        await this.checkpoint(command.payload.checkpoint_id);
        return;
      case "action.resolve":
        await this.resolveAction(command);
        return;
    }
  }

  private async persistAndHandle(command: ControlCommand): Promise<void> {
    await this.enqueueDurable(() => this.options.store.acceptCommand(command));
    await this.handleCommand(command);
  }

  private async persistAndExecuteSessionContext(
    command: SessionContextCommand,
    executor: PrimeGatewaySessionContextExecutor,
    preparePrivate: () => Promise<void>,
  ): Promise<SessionContextReceipt> {
    try {
      await this.enqueueDurable(
        () => this.options.store.acceptContextCommand(command),
      );
      await preparePrivate();
      const result = await executor.execute(command);
      if (
        typeof result !== "object" ||
        result === null
      ) {
        throw new PrimeGatewayError();
      }
      const resultKeys = Object.keys(result).sort().join("\u0000");
      if (
        (resultKeys !== ["nextBinding", "receipt"].sort().join("\u0000") &&
          resultKeys !== ["acknowledge", "nextBinding", "receipt"]
            .sort()
            .join("\u0000")) ||
        !Object.hasOwn(result, "receipt") ||
        !Object.hasOwn(result, "nextBinding") ||
        (result.acknowledge !== undefined &&
          typeof result.acknowledge !== "function")
      ) {
        throw new PrimeGatewayError();
      }
      const receipt = validateSessionContextReceipt(result.receipt);
      if (
        receipt.command_id !== command.command_id ||
        receipt.session_id !== command.session_id ||
        receipt.generation !== command.generation ||
        receipt.operation !== command.operation
      ) {
        throw new PrimeGatewayError();
      }
      this.assertMonotonicContextReceipt(receipt);
      const committed = await this.enqueueDurable(
        () => this.options.store.commitContextOperation(
          receipt,
          result.nextBinding,
        ),
      );
      try {
        result.acknowledge?.();
      } catch {
        // Durable receipt wins; a stable command replay retries acknowledgement.
      }
      return committed.receipt;
    } catch {
      throw new PrimeGatewayError();
    }
  }

  private nativeContextExecutor(): PrimeGatewaySessionContextExecutor {
    const session = this.requireSession();
    return Object.freeze({
      execute: async (
        command: SessionContextCommand,
      ): Promise<PrimeGatewaySessionContextResult> => {
        if (command.operation === "session.describe") {
          const result = await session.describeContext(
            command.command_id,
            this.contextStatus(),
          );
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: result.continuationId,
              status: result.status,
              context_tokens: result.contextTokens,
              turns: result.turns,
              usage: result.usage,
              name_sha256: result.nameSha256,
            }),
            nextBinding: null,
          });
        }
        if (command.operation === "session.name.set") {
          const named = await session.setContextName(
            command.command_id,
            await this.options.privateValues.readInput(command.payload.name_ref),
          );
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: named.result.continuationId,
              name_sha256: named.result.nameSha256,
            }),
            nextBinding: null,
            acknowledge: named.acknowledge,
          });
        }
        throw new PrimeGatewayError();
      },
      cancel: async () => {
        throw new PrimeGatewayError();
      },
    });
  }

  private contextSuccessReceipt(
    command: SessionContextCommand,
    result: object,
  ): SessionContextReceipt {
    return validateSessionContextReceipt({
      protocol: "asterion.session-context/v1",
      receipt_id: `context-${sha256Hex(
        canonicalJsonBytes({ command_id: command.command_id }),
      ).slice(0, 32)}`,
      command_id: command.command_id,
      session_id: command.session_id,
      generation: command.generation,
      operation: command.operation,
      status: "succeeded",
      reason_code: "session-context-succeeded",
      payload: {
        evidence_ref: null,
        result,
      },
    });
  }

  private contextStatus(): PrimeContextStatus {
    if (this.sessionStatus === "created") {
      return "creating";
    }
    if (this.sessionStatus === "running") {
      return "running";
    }
    if (this.sessionStatus === "paused") {
      return "paused";
    }
    if (this.sessionStatus === "recovery_required") {
      return "recovery-required";
    }
    if (this.goalStatus === "completed") {
      return "completed";
    }
    if (this.goalStatus === "failed") {
      return "failed";
    }
    const terminal = this.options.store.eventsAfter(0).at(-1)?.event.type;
    return terminal === "session.cancelled" ? "cancelled" : "failed";
  }

  private assertMonotonicContextReceipt(receipt: SessionContextReceipt): void {
    if (receipt.status !== "succeeded" || receipt.operation !== "session.describe") {
      return;
    }
    const current = receipt.payload.result;
    const usageTotal =
      current.usage.controller_tokens +
      current.usage.application_tokens +
      current.usage.child_tokens;
    if (
      !Number.isSafeInteger(usageTotal) ||
      usageTotal !== current.usage.aggregate_tokens
    ) {
      throw new PrimeGatewayError();
    }
    const previous = [...this.options.store.contextOperations()]
      .reverse()
      .map(({ receipt: candidate }) => candidate)
      .find(
        (candidate): candidate is Extract<
          SessionContextReceipt,
          { readonly operation: "session.describe"; readonly status: "succeeded" }
        > =>
          candidate.status === "succeeded" &&
          candidate.operation === "session.describe",
      );
    if (previous === undefined) {
      return;
    }
    const prior = previous.payload.result;
    if (
      current.turns < prior.turns ||
      current.usage.controller_tokens < prior.usage.controller_tokens ||
      current.usage.application_tokens < prior.usage.application_tokens ||
      current.usage.child_tokens < prior.usage.child_tokens ||
      current.usage.aggregate_tokens < prior.usage.aggregate_tokens ||
      current.usage.cost_micros < prior.usage.cost_micros
    ) {
      throw new PrimeGatewayError();
    }
  }

  private retryContextAcknowledgement(command: SessionContextCommand): void {
    if (command.operation !== "session.name.set" || this.session === undefined) {
      return;
    }
    try {
      this.session.acknowledgeContext(command.command_id);
    } catch {
      // A later replay retries the stable acknowledgement.
    }
  }

  private async refreshContextBinding(
    session: PrimeGatewaySession,
    supervisorGeneration: string,
  ): Promise<void> {
    const current = this.options.store.currentContextBinding(
      session.continuationId,
    );
    if (current === undefined || !OPAQUE_ID.test(supervisorGeneration)) {
      throw new PrimeGatewayError();
    }
    const locator = await this.options.privateValues.readContinuationLocator(current);
    if (
      locator.continuationId !== session.continuationId ||
      locator.activeSessionId !== session.activeSessionId ||
      locator.transcriptSessionId !== session.transcriptSessionId
    ) {
      throw new PrimeGatewayError();
    }
    if (locator.supervisorGeneration === supervisorGeneration) {
      return;
    }
    const replacement = await this.options.privateValues.putContinuationLocator({
      ...locator,
      supervisorGeneration,
    });
    await this.enqueueDurable(
      () => this.options.store.rebindContextBinding(replacement),
    );
  }

  private async create(
    command: Extract<ControlCommand, { type: "session.create" }>,
  ): Promise<void> {
    if (this.session !== undefined || this.goalId !== undefined) {
      throw new PrimeGatewayError();
    }
    const goal = await this.options.privateValues.readInput(command.payload.goal_ref);
    let boundIdentity: PrimeSessionInitialBinding | undefined;
    const createContext = Object.freeze({
      goalId: command.payload.goal_id,
      authorityRevision: command.authority_revision,
      causalParentIds: Object.freeze([command.payload.goal_id]),
    });
    const session = await this.options.createSession(
      goal,
      async (identity) => {
        if (
          boundIdentity !== undefined ||
          !OPAQUE_ID.test(identity.activeSessionId) ||
          !OPAQUE_ID.test(identity.transcriptSessionId) ||
          !OPAQUE_ID.test(identity.supervisorGeneration) ||
          !OPAQUE_ID.test(identity.continuationId) ||
          typeof identity.sessionPath !== "string"
        ) {
          throw new PrimeGatewayError();
        }
        const locator = Object.freeze({
          continuationId: identity.continuationId,
          activeSessionId: identity.activeSessionId,
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: identity.supervisorGeneration,
          sessionPath: identity.sessionPath,
        });
        let contextBinding = this.options.store.currentContextBinding(
          identity.continuationId,
        );
        if (contextBinding === undefined) {
          contextBinding = await this.options.privateValues.putContinuationLocator(
            locator,
          );
          await this.enqueueDurable(
            () => this.options.store.initializeContextBinding(contextBinding!),
          );
        } else {
          const restored = await this.options.privateValues.readContinuationLocator(
            contextBinding,
          );
          if (
            restored.continuationId !== locator.continuationId ||
            restored.activeSessionId !== locator.activeSessionId ||
            restored.transcriptSessionId !== locator.transcriptSessionId ||
            restored.supervisorGeneration !== locator.supervisorGeneration ||
            restored.sessionPath !== locator.sessionPath
          ) {
            throw new PrimeGatewayError();
          }
        }
        await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
          activeSessionId: identity.activeSessionId,
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: identity.supervisorGeneration,
        }));
        boundIdentity = Object.freeze({ ...identity });
      },
      createContext,
    );
    if (
      boundIdentity === undefined ||
      !OPAQUE_ID.test(session.activeSessionId) ||
      !OPAQUE_ID.test(session.transcriptSessionId) ||
      !OPAQUE_ID.test(session.continuationId) ||
      !OPAQUE_ID.test(session.supervisorGeneration) ||
      session.activeSessionId !== boundIdentity.activeSessionId ||
      session.transcriptSessionId !== boundIdentity.transcriptSessionId ||
      session.continuationId !== boundIdentity.continuationId ||
      session.supervisorGeneration !== boundIdentity.supervisorGeneration
    ) {
      throw new PrimeGatewayError();
    }
    this.session = session;
    this.goalId = command.payload.goal_id;
    this.goalStatus = "active";
    if (session.lastAttachResponse !== undefined) {
      const recovery = recoveryFromAttach(
        session.lastAttachResponse,
        session.activeSessionId,
        session.transcriptSessionId,
        { generation: session.supervisorGeneration, sequence: 0 },
      );
      await this.enqueueDurable(
        () => this.options.store.recordPrimeCursor(recovery.primeCursor),
      );
    }
    this.mapper = new PrimeEventMapper({
      sessionId: this.options.sessionId,
      generation: this.options.generation,
      goalId: this.goalId,
      activeSessionId: session.activeSessionId,
      nextEventIdentity: () => this.nextEventIdentity(),
      ...(this.options.store.snapshot().primeCursor === undefined
        ? {}
        : { primeCursor: this.options.store.snapshot().primeCursor }),
    });
    await this.append(this.event("session.created", {
      goal_id: this.goalId,
      authority_id: this.options.authorityId,
      authority_revision: command.authority_revision,
    }));
    await this.append(this.reasonEvent("session.running", "prime-resident-started"));
    this.options.onSessionReady?.(createContext);
    this.unsubscribe = session.subscribe((outbound) => this.enqueue(outbound));
  }

  private async cancel(
    command: Extract<ControlCommand, { type: "session.cancel" }>,
  ): Promise<void> {
    await this.requireSession().cancel(command.command_id);
    const goalId = this.requireGoalId();
    await this.append(this.event("goal.updated", {
      goal_id: goalId,
      status: "cancelled",
    }));
    await this.append(this.reasonEvent("session.cancelled", command.payload.reason_code));
    this.mapper?.noteExternalGoalStatus("cancelled");
    this.mapper?.noteExternalTerminal();
    this.terminal = true;
  }

  private async checkpoint(checkpointId: string): Promise<void> {
    if (this.checkpoints.has(checkpointId)) {
      this.retryCheckpointAcknowledgements();
      return;
    }
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    try {
      await this.eventQueue;
      if (this.sessionStatus === "running") {
        await this.append(this.reasonEvent(
          "session.recovery-required",
          "prime-checkpoint-restart",
        ));
        this.mapper?.noteExternalRecoveryRequired();
      } else if (this.sessionStatus !== "recovery_required") {
        throw new PrimeGatewayError();
      }
    } catch {
      this.unsubscribe = this.requireSession().subscribe(
        (outbound) => this.enqueue(outbound),
      );
      throw new PrimeGatewayError();
    }

    const runningEvent = this.reasonEvent(
      "session.running",
      "prime-checkpoint-restored",
    );
    const coveredSequence = runningEvent.sequence;
    let recovered: PrimeCheckpointRecovery | undefined;
    let adopted = false;
    let created: PrimeCheckpointCreated;
    try {
      created = await this.options.createCheckpoint(
        checkpointId,
        coveredSequence,
        async (recovery) => {
          if (
            recovered !== undefined ||
            this.sessionStatus !== "recovery_required" ||
            !this.validRecovery(recovery) ||
            recovery.sessionStatus !== "running"
          ) {
            throw new PrimeGatewayError();
          }
          const session = this.requireSession();
          const identity = this.options.store.snapshot().primeIdentity;
          if (
            identity === undefined ||
            session.activeSessionId !== identity.activeSessionId ||
            session.transcriptSessionId !== identity.transcriptSessionId ||
            session.supervisorGeneration !== identity.supervisorGeneration ||
            recovery.transcriptSessionId !== identity.transcriptSessionId
          ) {
            throw new PrimeGatewayError();
          }
          session.adoptRecovery(recovery);
          if (session.supervisorGeneration !== recovery.supervisorGeneration) {
            throw new PrimeGatewayError();
          }
          adopted = true;
          await this.refreshContextBinding(
            session,
            recovery.supervisorGeneration,
          );
          await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
            activeSessionId: session.activeSessionId,
            transcriptSessionId: recovery.transcriptSessionId,
            supervisorGeneration: recovery.supervisorGeneration,
          }));
          await this.enqueueDurable(
            () => this.options.store.recordPrimeCursor(recovery.primeCursor),
          );
          this.mapper = this.recoveredMapper(recovery.primeCursor);
          await this.append(runningEvent);
          this.mapper.noteExternalSessionStatus("running");
          recovered = recovery;
        },
      );
      if (
        recovered === undefined ||
        created.checkpointId !== checkpointId ||
        created.coveredSequence !== coveredSequence ||
        created.controlPlaneId !== "prime.gateway" ||
        created.controlPlaneVersion !== "0.1.0" ||
        created.checkpointVersion !== "1.0.0" ||
        typeof created.acknowledge !== "function" ||
        created.supervisorGeneration !== recovered.supervisorGeneration ||
        created.primeCursor.generation !== recovered.primeCursor.generation ||
        created.primeCursor.sequence !== recovered.primeCursor.sequence
      ) {
        throw new PrimeGatewayError();
      }
    } catch {
      if (recovered === undefined) {
        this.releaseReservedEvent(runningEvent);
      }
      if (recovered !== undefined || adopted) {
        this.unsubscribe = this.requireSession().subscribe(
          (outbound) => this.enqueue(outbound),
        );
      }
      throw new PrimeGatewayError();
    }

    const payload: CheckpointPayload = {
      checkpoint_id: created.checkpointId,
      capsule_id: created.capsuleId,
      capsule_digest: created.capsuleDigest,
      control_plane_id: created.controlPlaneId,
      control_plane_version: created.controlPlaneVersion,
      checkpoint_version: created.checkpointVersion,
      covered_sequence: created.coveredSequence,
      storage_ref: created.storageRef,
    };
    try {
      await this.append(this.event("checkpoint.created", payload));
      try {
        if (created.acknowledge()) {
          this.pendingCheckpointAcknowledgements.delete(checkpointId);
        }
      } catch {
        // The durable checkpoint remains authoritative; retry is idempotent.
      }
    } finally {
      this.unsubscribe = this.requireSession().subscribe(
        (outbound) => this.enqueue(outbound),
      );
    }
  }

  private recoveredMapper(primeCursor?: PrimeDaemonCursor): PrimeEventMapper {
    const mapper = new PrimeEventMapper({
      sessionId: this.options.sessionId,
      generation: this.options.generation,
      goalId: this.requireGoalId(),
      activeSessionId: this.requireSession().activeSessionId,
      nextEventIdentity: () => this.nextEventIdentity(),
      ...(primeCursor === undefined ? {} : { primeCursor }),
    });
    if (this.goalStatus !== undefined) {
      mapper.noteExternalGoalStatus(this.goalStatus);
    }
    return mapper;
  }

  private async restoreExistingSession(): Promise<void> {
    if (this.sessionStatus === undefined || this.sessionStatus === "terminal") {
      return;
    }
    const identity = this.options.store.snapshot().primeIdentity;
    const contextBinding = this.options.store.initialContextBinding();
    if (
      identity === undefined ||
      contextBinding === undefined ||
      this.goalId === undefined ||
      this.options.restoreSession === undefined
    ) {
      throw new PrimeGatewayError();
    }
    const previousStatus = this.sessionStatus === "recovery_required"
      ? this.recoveryBaseStatus ?? this.sessionStatus
      : this.sessionStatus;
    if (this.sessionStatus !== "recovery_required") {
      await this.append(this.reasonEvent(
        "session.recovery-required",
        "prime-gateway-restart",
      ));
    }
    let recovered: PrimeCheckpointRecovery | undefined;
    let restoredEvent: ControlEvent | undefined;
    try {
      const locator = await this.options.privateValues.readContinuationLocator(
        contextBinding,
      );
      if (
        locator.continuationId !== contextBinding.continuationId ||
        locator.activeSessionId !== identity.activeSessionId ||
        locator.transcriptSessionId !== identity.transcriptSessionId
      ) {
        throw new PrimeGatewayError();
      }
      const session = await this.options.restoreSession(Object.freeze({
        ...identity,
        continuationId: locator.continuationId,
        sessionPath: locator.sessionPath,
      }), async (recovery) => {
        if (
          recovered !== undefined ||
          this.sessionStatus !== "recovery_required" ||
          !this.validRecovery(recovery) ||
          recovery.transcriptSessionId !== identity.transcriptSessionId
        ) {
          throw new PrimeGatewayError();
        }
        recovered = recovery;
      });
      if (
        recovered === undefined ||
        session.activeSessionId !== identity.activeSessionId ||
        session.transcriptSessionId !== identity.transcriptSessionId ||
        session.continuationId !== locator.continuationId ||
        typeof session.adoptRecovery !== "function" ||
        typeof session.subscribe !== "function"
      ) {
        throw new PrimeGatewayError();
      }
      session.adoptRecovery(recovered);
      if (session.supervisorGeneration !== recovered.supervisorGeneration) {
        throw new PrimeGatewayError();
      }
      await this.refreshContextBinding(
        session,
        recovered.supervisorGeneration,
      );
      await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
        supervisorGeneration: recovered!.supervisorGeneration,
      }));
      await this.enqueueDurable(
        () => this.options.store.recordPrimeCursor(recovered!.primeCursor),
      );
      this.session = session;
      this.mapper = this.recoveredMapper(recovered.primeCursor);
      const restoredStatus = previousStatus === "paused"
        ? "paused"
        : recovered.sessionStatus;
      restoredEvent = this.reasonEvent(
        restoredStatus === "running" ? "session.running" : "session.paused",
        "prime-gateway-restored",
      );
      await this.append(restoredEvent);
      this.mapper.noteExternalSessionStatus(restoredStatus);
      this.unsubscribe = session.subscribe((outbound) => this.enqueue(outbound));
      this.retryCheckpointAcknowledgements();
    } catch (error) {
      if (restoredEvent !== undefined) {
        this.releaseReservedEvent(restoredEvent);
      }
      if (error instanceof PrimeGatewayError) {
        throw error;
      }
      throw new PrimeGatewayError();
    }
  }

  private validPrimeCursor(value: unknown): value is PrimeDaemonCursor {
    return (
      typeof value === "object" &&
      value !== null &&
      "generation" in value &&
      "sequence" in value &&
      typeof value.generation === "string" &&
      typeof value.sequence === "number" &&
      OPAQUE_ID.test(value.generation) &&
      Number.isSafeInteger(value.sequence) &&
      value.sequence >= 0
    );
  }

  private validRecovery(recovery: PrimeCheckpointRecovery): boolean {
    return (
      OPAQUE_ID.test(recovery.transcriptSessionId) &&
      OPAQUE_ID.test(recovery.supervisorGeneration) &&
      this.validPrimeCursor(recovery.primeCursor) &&
      (recovery.sessionStatus === "running" || recovery.sessionStatus === "paused") &&
      recovery.transport?.hello?.supervisorGeneration ===
        recovery.supervisorGeneration &&
      typeof recovery.transport.request === "function" &&
      typeof recovery.transport.requestDeferred === "function" &&
      typeof recovery.transport.acknowledgeResult === "function" &&
      typeof recovery.transport.subscribe === "function"
    );
  }

  private releaseReservedEvent(event: ControlEvent): void {
    if (!this.reservedEvents.delete(event.sequence)) {
      return;
    }
    if (this.nextSequence === event.sequence + 1) {
      this.nextSequence = event.sequence;
    }
  }

  private retryCheckpointAcknowledgements(): void {
    if (this.session === undefined) {
      return;
    }
    for (const checkpointId of [...this.pendingCheckpointAcknowledgements].sort()) {
      try {
        if (this.session.acknowledgeCheckpoint(checkpointId)) {
          this.pendingCheckpointAcknowledgements.delete(checkpointId);
        }
      } catch {
        // A later command or restored session retries the stable acknowledgement.
      }
    }
  }

  private actionTargetId(
    event: Extract<ControlEvent, { readonly type: "action.proposed" }>,
  ): string {
    const target = event.payload.target;
    if (target.kind === "application") {
      return [
        target.provider_id,
        target.application_id,
        target.version,
        target.runtime_id,
      ].join("@");
    }
    const field = {
      child: "child_id",
      checkpoint: "checkpoint_id",
      goal: "goal_id",
      input: "request_id",
      session: "session_id",
    }[target.kind] as keyof typeof target;
    const value = target[field];
    if (typeof value !== "string" || !OPAQUE_ID.test(value)) {
      throw new PrimeGatewayError();
    }
    return value;
  }

  private async restoreActionCommands(): Promise<void> {
    for (const { command } of this.options.store.commands()) {
      if (command.type !== "action.resolve") {
        continue;
      }
      const action = this.requireAction(command.payload.action_id);
      const { resolution, reason_code: reasonCode } = command.payload;
      if (resolution === "admitted" || resolution === "rejected") {
        if (action.status !== "proposed") {
          throw new PrimeGatewayError();
        }
        action.status = resolution;
        action.reasonCode = reasonCode;
        continue;
      }
      if (action.status !== "admitted") {
        throw new PrimeGatewayError();
      }
      if (resolution === "succeeded") {
        const receiptRef = command.payload.receipt_ref;
        if (receiptRef === null || this.options.privateResults === undefined) {
          throw new PrimeGatewayError();
        }
        const resultRef = await this.options.privateResults.readBoundResultReference(
          command.command_id,
          command.payload.action_id,
          receiptRef,
        );
        if (!isPrivateRef(resultRef)) {
          throw new PrimeGatewayError();
        }
        action.resultRef = resultRef;
      }
      action.status = resolution;
      action.reasonCode = reasonCode;
    }
  }

  private async resolveAction(
    command: Extract<ControlCommand, { type: "action.resolve" }>,
  ): Promise<void> {
    const { action_id: actionId, resolution, reason_code: reasonCode } =
      command.payload;
    const action = this.requireAction(actionId);
    if (resolution === "admitted" || resolution === "rejected") {
      if (action.status !== "proposed") {
        throw new PrimeGatewayError();
      }
      action.status = resolution;
      action.reasonCode = reasonCode;
      action.resolveAdmission?.(Object.freeze({
        resolution,
        reasonCode,
      }));
      delete action.resolveAdmission;
      return;
    }
    if (action.status !== "admitted") {
      throw new PrimeGatewayError();
    }
    let resultRef: PrivateValueRef | undefined;
    if (resolution === "succeeded") {
      if (command.payload.receipt_ref === null) {
        throw new PrimeGatewayError();
      }
      if (this.options.privateResults === undefined) {
        throw new PrimeGatewayError();
      }
      resultRef = await this.options.privateResults.readBoundResultReference(
        command.command_id,
        actionId,
        command.payload.receipt_ref,
      );
      if (!isPrivateRef(resultRef)) {
        throw new PrimeGatewayError();
      }
      await this.applyGoalTerminal(action);
    }
    action.status = resolution;
    action.reasonCode = reasonCode;
    if (resultRef === undefined) {
      delete action.resultRef;
    } else {
      action.resultRef = resultRef;
    }
    action.resolveTerminal?.(this.terminalResult(action));
    delete action.resolveTerminal;
  }

  private async restoreGoalTerminals(): Promise<void> {
    for (const action of this.actions.values()) {
      if (action.status === "succeeded") {
        await this.applyGoalTerminal(action);
      }
    }
  }

  private async applyGoalTerminal(action: ActionRecord): Promise<void> {
    if (action.kind !== "goal.complete" && action.kind !== "goal.fail") {
      return;
    }
    const goalId = this.requireGoalId();
    if (action.targetId !== goalId) {
      throw new PrimeGatewayError();
    }
    const completed = action.kind === "goal.complete";
    const goalStatus: GoalStatus = completed ? "completed" : "failed";
    const sessionType = completed ? "session.completed" : "session.failed";
    const reasonCode = completed
      ? "host-admitted-goal-complete"
      : "host-admitted-goal-fail";
    if (this.goalStatus === "active") {
      await this.append(this.event("goal.updated", {
        goal_id: goalId,
        status: goalStatus,
      }));
    } else if (this.goalStatus !== goalStatus) {
      throw new PrimeGatewayError();
    }
    if (this.sessionStatus !== "terminal") {
      await this.append(this.reasonEvent(sessionType, reasonCode));
    } else {
      const lastEvent = this.options.store.eventsAfter(0).at(-1)?.event;
      if (lastEvent?.type !== sessionType) {
        throw new PrimeGatewayError();
      }
    }
    this.mapper?.noteExternalGoalStatus(goalStatus);
    this.mapper?.noteExternalTerminal();
    this.terminal = true;
  }

  private terminalResult(action: ActionRecord): GatewayTerminalResult {
    if (!["succeeded", "failed", "cancelled", "uncertain"].includes(action.status)) {
      throw new PrimeGatewayError();
    }
    return Object.freeze({
      resolution: action.status as GatewayTerminalResult["resolution"],
      reasonCode: action.reasonCode ?? "resolved",
      ...(action.resultRef === undefined ? {} : { resultRef: action.resultRef }),
    });
  }

  private requireAction(actionId: string): ActionRecord {
    const action = this.actions.get(actionId);
    if (action === undefined) {
      throw new PrimeGatewayError();
    }
    return action;
  }

  private assertActionId(actionId: string): void {
    this.assertOpen();
    if (!OPAQUE_ID.test(actionId)) {
      throw new PrimeGatewayError();
    }
  }

  private enqueue(outbound: PrimeDaemonOutbound): void {
    this.eventQueue = this.eventQueue
      .then(() => this.handlePrimeOutbound(outbound))
      .catch(() => this.raiseMappingFault());
  }

  private async handlePrimeOutbound(outbound: PrimeDaemonOutbound): Promise<void> {
    if (this.mapper === undefined || this.terminal) {
      return;
    }
    const events = this.mapper.map(outbound);
    await Promise.all(events.map((event) => this.append(event)));
    if (this.mapper.primeCursor !== undefined) {
      await this.enqueueDurable(
        () => this.options.store.recordPrimeCursor(this.mapper!.primeCursor!),
      );
    }
  }

  private async raiseMappingFault(): Promise<void> {
    if (this.terminal || this.closed) {
      return;
    }
    try {
      await this.append(this.event("fault.raised", {
        code: "prime-event-invalid",
        recoverable: true,
        evidence_ref: null,
      }));
      await this.append(this.reasonEvent(
        "session.recovery-required",
        "prime-event-invalid",
      ));
      this.mapper?.noteExternalRecoveryRequired();
    } catch (error) {
      if (!(error instanceof PrimeEventMappingError)) {
        this.terminal = true;
      }
    }
  }

  private event(type: ControlEvent["type"], payload: object): ControlEvent {
    const identity = this.nextEventIdentity();
    return validateControlEvent({
      protocol: "asterion.agent-control/v1",
      event_id: identity.eventId,
      session_id: this.options.sessionId,
      generation: this.options.generation,
      sequence: identity.sequence,
      emitted_at: identity.emittedAt,
      type,
      payload,
    });
  }

  private reasonEvent(
    type:
      | "session.running"
      | "session.paused"
      | "session.recovery-required"
      | "session.completed"
      | "session.failed"
      | "session.cancelled",
    reasonCode: string,
  ): ControlEvent {
    return this.event(type, { reason_code: reasonCode });
  }

  private append(event: ControlEvent): Promise<void> {
    return this.enqueueDurable(async () => {
      if (
        event.sequence !== this.lastAppendedSequence + 1 ||
        !this.matchesReservation(event)
      ) {
        throw new PrimeGatewayError();
      }
      await this.options.store.appendEvent(event);
      this.reservedEvents.delete(event.sequence);
      this.lastAppendedSequence = event.sequence;
      this.updateSessionStatus(event);
    });
  }

  private enqueueDurable<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.durableQueue.then(operation);
    this.durableQueue = result.then(() => undefined);
    return result;
  }

  private matchesReservation(event: ControlEvent): boolean {
    const reservation = this.reservedEvents.get(event.sequence);
    return (
      reservation !== undefined &&
      reservation.eventId === event.event_id &&
      reservation.emittedAt === event.emitted_at
    );
  }

  private updateSessionStatus(event: ControlEvent): void {
    if (event.type === "session.created") {
      this.sessionStatus = "created";
      this.goalStatus ??= "active";
    } else if (event.type === "goal.updated") {
      this.goalStatus = event.payload.status;
    } else if (event.type === "session.running") {
      this.sessionStatus = "running";
      this.recoveryBaseStatus = undefined;
    } else if (event.type === "session.paused") {
      this.sessionStatus = "paused";
      this.recoveryBaseStatus = undefined;
    } else if (event.type === "session.recovery-required") {
      if (this.sessionStatus !== "recovery_required") {
        this.recoveryBaseStatus = this.sessionStatus;
      }
      this.sessionStatus = "recovery_required";
    } else if (event.type === "checkpoint.created") {
      this.checkpoints.add(event.payload.checkpoint_id);
      this.pendingCheckpointAcknowledgements.add(event.payload.checkpoint_id);
    } else if ([
      "session.budget-limited",
      "session.cancelled",
      "session.completed",
      "session.failed",
    ].includes(event.type)) {
      this.sessionStatus = "terminal";
      this.recoveryBaseStatus = undefined;
      this.terminal = true;
    }
  }

  private requireSessionStatus(expected: GatewaySessionStatus | undefined): void {
    if (this.sessionStatus !== expected) {
      throw new PrimeGatewayError();
    }
  }

  private requireSession(): PrimeGatewaySession {
    if (this.session === undefined) {
      throw new PrimeGatewayError();
    }
    return this.session;
  }

  private requireGoalId(): string {
    if (this.goalId === undefined) {
      throw new PrimeGatewayError();
    }
    return this.goalId;
  }

  private assertOpen(): void {
    if (this.closed) {
      throw new PrimeGatewayError();
    }
  }
}
