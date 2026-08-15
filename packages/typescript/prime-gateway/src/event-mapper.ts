import {
  validateControlEvent,
} from "@dci/agent-runtime";
import type {
  ControlEvent,
  GoalStatus,
} from "@dci/agent-runtime";

import {
  cursorFromPrimeDaemonOutbound,
} from "./daemon-wire.js";
import type {
  PrimeDaemonCursor,
  PrimeDaemonOutbound,
} from "./daemon-wire.js";

export interface PrimeMappedEventIdentity {
  readonly eventId: string;
  readonly sequence: number;
  readonly emittedAt: string;
}

export interface PrimeEventMapperOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly goalId: string;
  readonly activeSessionId: string;
  readonly nextEventIdentity: () => PrimeMappedEventIdentity;
  readonly primeCursor?: PrimeDaemonCursor;
}

type MapperSessionStatus =
  | "running"
  | "paused"
  | "recovery_required"
  | "terminal";

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

export class PrimeEventMappingError extends Error {
  constructor(
    readonly kind: "cursor-gap" | "cursor-generation" | "goal-invalid" | "session-mismatch" | "unknown" = "unknown",
  ) {
    super("Prime event mapping failed");
    this.name = "PrimeEventMappingError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function sessionScoped(outbound: PrimeDaemonOutbound): string | undefined {
  if (outbound.type === "daemon_hello" || outbound.type === "response") {
    return undefined;
  }
  return typeof outbound.activeSessionId === "string"
    ? outbound.activeSessionId
    : undefined;
}

export class PrimeEventMapper {
  private cursor: PrimeDaemonCursor | undefined;
  private controllerTokens = 0;
  private goalStatus: GoalStatus = "active";
  private sessionStatus: MapperSessionStatus = "running";

  constructor(private readonly options: PrimeEventMapperOptions) {
    if (
      !OPAQUE_ID.test(options.sessionId) ||
      !positiveInteger(options.generation) ||
      !OPAQUE_ID.test(options.goalId) ||
      !OPAQUE_ID.test(options.activeSessionId) ||
      typeof options.nextEventIdentity !== "function" ||
      (options.primeCursor !== undefined &&
        (!OPAQUE_ID.test(options.primeCursor.generation) ||
          !nonNegativeInteger(options.primeCursor.sequence)))
    ) {
      throw new PrimeEventMappingError();
    }
    this.cursor = options.primeCursor;
  }

  get primeCursor(): PrimeDaemonCursor | undefined {
    return this.cursor;
  }

  noteExternalGoalStatus(status: GoalStatus): void {
    this.goalStatus = status;
  }

  noteExternalSessionStatus(status: "running" | "paused"): void {
    this.sessionStatus = status;
  }

  noteExternalRecoveryRequired(): void {
    if (this.sessionStatus !== "terminal") {
      this.sessionStatus = "recovery_required";
    }
  }

  noteExternalTerminal(): void {
    this.sessionStatus = "terminal";
  }

  map(outbound: PrimeDaemonOutbound): readonly ControlEvent[] {
    try {
      const activeSessionId = sessionScoped(outbound);
      if (
        activeSessionId !== undefined &&
        activeSessionId !== this.options.activeSessionId
      ) {
        this.advanceCursor(outbound);
        return Object.freeze([]);
      }
      this.advanceCursor(outbound);
      if (this.sessionStatus === "terminal") {
        return Object.freeze([]);
      }
      return Object.freeze(this.mapOpenSession(outbound));
    } catch (error) {
      if (error instanceof PrimeEventMappingError) {
        throw error;
      }
      throw new PrimeEventMappingError();
    }
  }

  private advanceCursor(outbound: PrimeDaemonOutbound): void {
    const candidate = cursorFromPrimeDaemonOutbound(outbound);
    if (candidate === undefined) {
      return;
    }
    if (this.cursor === undefined) {
      if (candidate.sequence !== 1) {
        throw new PrimeEventMappingError("cursor-gap");
      }
    } else if (
      candidate.generation !== this.cursor.generation ||
      candidate.sequence !== this.cursor.sequence + 1
    ) {
      throw new PrimeEventMappingError("cursor-generation");
    }
    this.cursor = candidate;
  }

  private mapOpenSession(outbound: PrimeDaemonOutbound): ControlEvent[] {
    if (outbound.type === "session_event") {
      return this.mapSessionEvent(outbound.event);
    }
    if (outbound.type === "extension_error") {
      return [this.fault("prime-extension-error", true)];
    }
    if (outbound.type === "session_snapshot_failed") {
      return this.recovery("prime-snapshot-invalid", "prime-snapshot-failed");
    }
    if (outbound.type === "daemon_closing") {
      return this.recovery("prime-daemon-closing", "prime-daemon-closing");
    }
    if (outbound.type === "session_closed") {
      this.sessionStatus = "terminal";
      return [this.reasonEvent("session.failed", "prime-session-closed")];
    }
    if (
      (outbound.type === "session_resynced" ||
        outbound.type === "session_attached") &&
      this.sessionStatus === "recovery_required"
    ) {
      this.sessionStatus = "running";
      return [this.reasonEvent("session.running", "prime-resynced")];
    }
    return [];
  }

  private mapSessionEvent(value: unknown): ControlEvent[] {
    if (!isRecord(value) || typeof value.type !== "string") {
      throw new PrimeEventMappingError("goal-invalid");
    }
    if (value.type === "goal_update") {
      return this.mapGoal(value.goal);
    }
    if (value.type === "auth_stale") {
      return [this.fault("prime-auth-stale", true)];
    }
    return [];
  }

  private mapGoal(value: unknown): ControlEvent[] {
    if (
      !isRecord(value) ||
      typeof value.status !== "string" ||
      !nonNegativeInteger(value.tokensUsed) ||
      value.tokensUsed < this.controllerTokens
    ) {
      throw new PrimeEventMappingError("goal-invalid");
    }
    const mapped = this.goalStatusFromPrime(value.status);
    if (mapped === undefined) {
      throw new PrimeEventMappingError("goal-invalid");
    }
    const events: ControlEvent[] = [];
    if (mapped !== this.goalStatus) {
      if (this.goalStatus === "paused" && mapped === "active") {
        this.sessionStatus = "running";
        events.push(this.reasonEvent("session.running", "prime-goal-resumed"));
      }
      events.push(this.goalEvent(mapped));
      this.goalStatus = mapped;
      if (mapped === "paused") {
        this.sessionStatus = "paused";
        events.push(this.reasonEvent("session.paused", "prime-goal-paused"));
      }
    }
    if (value.tokensUsed !== this.controllerTokens) {
      this.controllerTokens = value.tokensUsed;
      events.push(this.usageEvent(value.tokensUsed));
    }
    let terminal: readonly [
      "session.completed" | "session.failed" | "session.budget-limited",
      string,
    ] | undefined;
    if (mapped === "completed") {
      terminal = ["session.completed", "prime-goal-complete"];
    } else if (mapped === "failed") {
      terminal = [
        "session.failed",
        value.status === "idle"
          ? "prime-goal-unavailable"
          : "prime-goal-failed",
      ];
    } else if (mapped === "budget_limited") {
      terminal = ["session.budget-limited", "prime-goal-budget-limited"];
    }
    if (terminal !== undefined) {
      this.sessionStatus = "terminal";
      events.push(this.reasonEvent(terminal[0], terminal[1]));
    }
    return events;
  }

  private goalStatusFromPrime(status: string): GoalStatus | undefined {
    return {
      active: "active",
      paused: "paused",
      budget_limited: "budget_limited",
      complete: "completed",
      error: "failed",
      idle: "failed",
    }[status] as GoalStatus | undefined;
  }

  private recovery(faultCode: string, reasonCode: string): ControlEvent[] {
    if (this.sessionStatus === "recovery_required") {
      return [this.fault(faultCode, true)];
    }
    this.sessionStatus = "recovery_required";
    return [
      this.fault(faultCode, true),
      this.reasonEvent("session.recovery-required", reasonCode),
    ];
  }

  private goalEvent(status: GoalStatus): ControlEvent {
    return this.event("goal.updated", {
      goal_id: this.options.goalId,
      status,
    });
  }

  private usageEvent(tokens: number): ControlEvent {
    return this.event("budget.reported", {
      controller_tokens: tokens,
      application_tokens: 0,
      child_tokens: 0,
      aggregate_tokens: tokens,
      cost_micros: 0,
    });
  }

  private fault(code: string, recoverable: boolean): ControlEvent {
    return this.event("fault.raised", {
      code,
      recoverable,
      evidence_ref: null,
    });
  }

  private reasonEvent(
    type:
      | "session.running"
      | "session.paused"
      | "session.recovery-required"
      | "session.completed"
      | "session.failed"
      | "session.budget-limited",
    reasonCode: string,
  ): ControlEvent {
    return this.event(type, { reason_code: reasonCode });
  }

  private event(type: ControlEvent["type"], payload: object): ControlEvent {
    const identity = this.options.nextEventIdentity();
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
}
