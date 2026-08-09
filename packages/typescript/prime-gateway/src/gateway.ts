import {
  validateControlCommand,
  validateControlEvent,
} from "@dci/agent-runtime";
import type {
  ActionResolution,
  ControlCommand,
  ControlEvent,
} from "@dci/agent-runtime";

import type {
  GatewayDurableStore,
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
  PrivateValueRef,
  PrivateValueStore,
} from "./private-store.js";
import type {
  PrimeDaemonListener,
} from "./daemon-client.js";
import type {
  PrimeDaemonCursor,
  PrimeDaemonOutbound,
} from "./daemon-wire.js";
import type {
  PrimeInputDelivery,
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
  readonly supervisorGeneration: string;
  subscribe(listener: PrimeDaemonListener): () => void;
  submitInput(
    inputId: string,
    delivery: PrimeInputDelivery,
    body: string,
  ): Promise<void>;
  pause(commandId: string): Promise<void>;
  resume(commandId: string): Promise<void>;
  attach(commandId: string, cursor?: PrimeDaemonCursor): Promise<void>;
  detach(commandId: string): Promise<void>;
  cancel(commandId: string): Promise<void>;
}

export interface PrimeGatewayOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly authorityId: string;
  readonly store: GatewayDurableStore;
  readonly privateValues: PrivateValueStore;
  readonly createSession: (
    goal: string,
    bindIdentity: (identity: {
      readonly activeSessionId: string;
      readonly supervisorGeneration: string;
    }) => Promise<void>,
  ) => Promise<PrimeGatewaySession>;
  readonly createCheckpoint: (
    checkpointId: string,
    coveredSequence: number,
  ) => Promise<CheckpointPayload>;
  readonly now?: () => string;
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

function requirePrivateRef(value: string): PrivateValueRef {
  if (!isPrivateRef(value)) {
    throw new PrimeGatewayError();
  }
  return value;
}

export class PrimeGateway {
  private readonly actions = new Map<string, ActionRecord>();
  private readonly commandExecutions = new Map<string, CommandExecution>();
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
  private sessionStatus: GatewaySessionStatus | undefined;
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
      } else if (event.type === "action.proposed") {
        this.actions.set(event.payload.action_id, { status: "proposed" });
      }
      this.updateSessionStatus(event);
    }
  }

  static async open(options: PrimeGatewayOptions): Promise<PrimeGateway> {
    if (
      !OPAQUE_ID.test(options.sessionId) ||
      !positiveInteger(options.generation) ||
      !OPAQUE_ID.test(options.authorityId) ||
      typeof options.createSession !== "function" ||
      typeof options.createCheckpoint !== "function" ||
      options.store.snapshot().sessionId !== options.sessionId
    ) {
      throw new PrimeGatewayError();
    }
    return new PrimeGateway(options);
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
    const digest = sha256Hex(canonicalJsonBytes(command));
    const existing = this.commandExecutions.get(command.command_id);
    if (existing !== undefined) {
      if (existing.digest !== digest) {
        throw new PrimeGatewayError();
      }
      return existing.promise;
    }
    const promise = this.persistAndHandle(command);
    this.commandExecutions.set(command.command_id, { digest, promise });
    return promise;
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
      throw new PrimeGatewayError();
    }
    await this.append(event);
    this.actions.set(event.payload.action_id, { status: "proposed" });
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
    if (this.terminal) {
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
          await this.options.privateValues.readInput(
            requirePrivateRef(command.payload.content_ref),
          ),
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
        await this.requireSession().attach(
          command.command_id,
          this.options.store.snapshot().primeCursor,
        );
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
        this.requireSessionStatus("running");
        await this.checkpoint(command.payload.checkpoint_id);
        return;
      case "action.resolve":
        this.resolveAction(command);
        return;
    }
  }

  private async persistAndHandle(command: ControlCommand): Promise<void> {
    await this.enqueueDurable(() => this.options.store.acceptCommand(command));
    await this.handleCommand(command);
  }

  private async create(
    command: Extract<ControlCommand, { type: "session.create" }>,
  ): Promise<void> {
    if (this.session !== undefined || this.goalId !== undefined) {
      throw new PrimeGatewayError();
    }
    const goal = await this.options.privateValues.readInput(
      requirePrivateRef(command.payload.goal_ref),
    );
    let boundIdentity: {
      readonly activeSessionId: string;
      readonly supervisorGeneration: string;
    } | undefined;
    const session = await this.options.createSession(goal, async (identity) => {
      if (
        boundIdentity !== undefined ||
        !OPAQUE_ID.test(identity.activeSessionId) ||
        !OPAQUE_ID.test(identity.supervisorGeneration)
      ) {
        throw new PrimeGatewayError();
      }
      await this.enqueueDurable(() => this.options.store.bindPrimeIdentity(identity));
      boundIdentity = Object.freeze({ ...identity });
    });
    if (
      boundIdentity === undefined ||
      !OPAQUE_ID.test(session.activeSessionId) ||
      !OPAQUE_ID.test(session.supervisorGeneration) ||
      session.activeSessionId !== boundIdentity.activeSessionId ||
      session.supervisorGeneration !== boundIdentity.supervisorGeneration
    ) {
      throw new PrimeGatewayError();
    }
    this.session = session;
    this.goalId = command.payload.goal_id;
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
    const coveredSequence = this.nextSequence - 1;
    const payload = await this.options.createCheckpoint(
      checkpointId,
      coveredSequence,
    );
    if (
      payload.checkpoint_id !== checkpointId ||
      payload.covered_sequence !== coveredSequence
    ) {
      throw new PrimeGatewayError();
    }
    await this.append(this.event("checkpoint.created", payload));
  }

  private resolveAction(
    command: Extract<ControlCommand, { type: "action.resolve" }>,
  ): void {
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
    action.status = resolution;
    action.reasonCode = reasonCode;
    if (command.payload.receipt_ref !== null) {
      if (!isPrivateRef(command.payload.receipt_ref)) {
        throw new PrimeGatewayError();
      }
      action.resultRef = command.payload.receipt_ref;
    }
    action.resolveTerminal?.(this.terminalResult(action));
    delete action.resolveTerminal;
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
    } else if (event.type === "session.running") {
      this.sessionStatus = "running";
    } else if (event.type === "session.paused") {
      this.sessionStatus = "paused";
    } else if (event.type === "session.recovery-required") {
      this.sessionStatus = "recovery_required";
    } else if ([
      "session.budget-limited",
      "session.cancelled",
      "session.completed",
      "session.failed",
    ].includes(event.type)) {
      this.sessionStatus = "terminal";
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
