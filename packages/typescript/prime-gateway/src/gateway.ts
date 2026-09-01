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
  GatewayContextModelBaseline,
  GatewayClientObservation,
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
  PrivateAttachmentMetadata,
  PrivateBoundAttachment,
  PrivateValueRef,
} from "./private-store.js";
import type { PrivateValueStore } from "./private-store.js";
import {
  PrimeClientObservationMapper,
  PrimeClientObservationError,
} from "./client-observation.js";
import type { PrimeClientObservation, PrimeClientObservationHealth } from "./client-observation.js";
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
  PrimeContextLabelResult,
  PrimeContextModelBaseline,
  PrimeContextModelBudget,
  PrimeContextCompactionResult,
  PrimeContextBranchSummaryResult,
  PrimeContextModelOutcome,
  PrimeContextStatus,
  PrimeContinuationDeleteResult,
  PrimeContinuationLocator,
  PrimeContinuationResumeResult,
  PrimeForkCloneResult,
  PrimeInputDelivery,
  PrimeInputAttachment,
  PrimeInputSubmission,
  PrimeSessionInitialBinding,
  PrimeTreeNavigationResult,
} from "./prime-session.js";
import {
  PrimePromptAdmissionUncertainError,
} from "./prime-session.js";
import type { PrimeSessionTreeProjection } from "./session-tree.js";
import type {
  GatewayEcosystemEffectResult,
  PrimeEcosystemAdapter,
} from "./ecosystem.js";

type CheckpointPayload = Extract<
  ControlEvent,
  { readonly type: "checkpoint.created" }
>["payload"];

/** Exact, body-free receipt contract emitted by the locked Prime client module. */
export const PRIME_CLIENT_RECEIPT_FORMAT = "asterion.prime-client-receipt/v1";
export const PRIME_CLIENT_ARTIFACT_LOCK_DIGEST =
  "34374afe3bbef57b6690764a174a22f2fbd3952e26cfac788c955a363a54274d";
export const PRIME_CLIENT_MODULE_LOCK_DIGEST =
  "577f5ea261d515223d578673f7431fd12d141fb5160c1611315ab015892485a8";
export const PRIME_CLIENT_BUNDLE_DIGEST =
  "5ada8386371b8b68bf2bf34b892fdee1b93ad936dfa906110901b14141b63e86";

/** Digests for the repository resource that gates real Prime operations. */
export const PRIME_OPERATIONAL_MODULE_LOCK_DIGEST =
  "51afa7c04e8dff80f72e6928df919a81e0c617d146549b34b54696cfb771cf9a";
export const PRIME_OPERATIONAL_BUNDLE_DIGEST =
  "6326ee8a6433f52c78210297c6bf499ab561d171ce1caaf51a107216392be041";

export interface PrimeClientReceipt {
  readonly artifact_lock_digest: string;
  readonly credential_reads: 0;
  readonly feature_count: number;
  readonly feature_ids: readonly string[];
  readonly module_digest: string;
  readonly module_lock_digest: string;
  readonly package: "core" | "protocols" | "interactive" | "export-share";
  readonly provider_operations: 0;
  readonly public_export_private_reads: 0;
  readonly retained_processes: 0;
  readonly scenario_count: number;
  readonly scenario_ids: readonly string[];
  readonly source_commit: "a18809e00ea30638584d87b3afea7285a9d7296c";
  readonly unauthorized_uploads: 0;
}

export interface PrimeGatewaySession {
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly continuationId: string;
  readonly supervisorGeneration: string;
  readonly lastAttachResponse: PrimeDaemonResponse | undefined;
  adoptRecovery(recovery: PrimeCheckpointRecovery): void;
  acknowledgeCheckpoint(checkpointId: string): boolean;
  isIdle?(): Promise<boolean>;
  subscribe(listener: PrimeDaemonListener): () => void;
  submitInput(
    inputId: string,
    delivery: PrimeInputDelivery,
    body: string,
    attachments?: readonly PrimeInputAttachment[],
  ): Promise<PrimeInputSubmission>;
  acknowledgeInput(inputId: string): boolean;
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
  setContextLabel(
    commandId: string,
    continuationId: string,
    entryId: string,
    label: string | null,
  ): Promise<PrimeContextLabelResult>;
  measureContextModelBaseline(
    commandId: string,
    continuationId: string,
    selectedEntryId?: string,
  ): Promise<PrimeContextModelBaseline>;
  compactContext(
    commandId: string,
    continuationId: string,
    instructions: string | null,
    budget: PrimeContextModelBudget,
    baseline: PrimeContextModelBaseline,
  ): Promise<PrimeContextModelOutcome<PrimeContextCompactionResult>>;
  summarizeContextBranch(
    commandId: string,
    continuationId: string,
    entryId: string,
    instructions: string | null,
    budget: PrimeContextModelBudget,
    baseline: PrimeContextModelBaseline,
  ): Promise<PrimeContextModelOutcome<PrimeContextBranchSummaryResult>>;
  abortContextModelOperation(
    commandId: string,
    operation: "session.branch.summarize" | "session.compact",
  ): Promise<void>;
  acknowledgeContext(commandId: string): boolean;
  acknowledgeLabel(commandId: string): boolean;
  acknowledgeContextModelOperation(
    commandId: string,
    operation: "session.branch.summarize" | "session.compact",
  ): boolean;
  resumeContinuation(
    commandId: string,
    target: PrimeContinuationLocator,
  ): Promise<PrimeContinuationResumeResult>;
  deleteContinuation(
    commandId: string,
    target: PrimeContinuationLocator,
  ): Promise<PrimeContinuationDeleteResult>;
  adoptContinuation(target: PrimeContinuationLocator): void;
  acknowledgeContinuation(
    commandId: string,
    operation: "session.continuation.delete" | "session.continuation.resume",
  ): boolean;
  readContextTree(
    commandId: string,
    continuationId: string,
  ): Promise<PrimeSessionTreeProjection>;
  navigateContextTree(
    commandId: string,
    continuationId: string,
    entryId: string,
    previousLeafId: string | null,
  ): Promise<PrimeTreeNavigationResult>;
  acknowledgeTreeMutation(commandId: string): boolean;
  forkContext(
    commandId: string,
    continuationId: string,
    entryId: string,
    position: "at" | "before",
  ): Promise<PrimeForkCloneResult>;
  cloneContext(
    commandId: string,
    continuationId: string,
    selectedLeafId: string,
  ): Promise<PrimeForkCloneResult>;
  acknowledgeForkClone(
    commandId: string,
    operation: "session.fork" | "session.clone",
  ): boolean;
}

export interface PrimeGatewayPrivateInputs {
  readInput(reference: string): Promise<string>;
  readBoundAttachment(
    sessionId: string,
    inputId: string,
    attachmentId: string,
  ): Promise<PrivateBoundAttachment>;
  readBoundAttachments(
    sessionId: string,
    inputId: string,
    expected: readonly PrivateAttachmentMetadata[],
  ): Promise<readonly PrivateBoundAttachment[]>;
  putContinuationLocator(
    locator: PrivateContinuationLocator,
  ): Promise<GatewayContextBinding>;
  readContinuationLocator(
    binding: GatewayContextBinding,
  ): Promise<PrivateContinuationLocator>;
  ensurePreparedContinuationLocator(
    binding: GatewayContextBinding,
  ): Promise<Readonly<{
    binding: GatewayContextBinding;
    locator: PrivateContinuationLocator;
  }>>;
  readPreparedContinuationLocator(
    binding: GatewayContextBinding,
    allowMissing: boolean,
  ): Promise<PrivateContinuationLocator>;
  rebindRecoveredContinuationLocator(
    binding: GatewayContextBinding,
    expected: Omit<PrivateContinuationLocator, "sessionPath">,
  ): Promise<GatewayContextBinding>;
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
  readonly clientObservationValues?: Pick<
    PrivateValueStore,
    "putClientValue" | "describeClientValue" | "deleteClientValue"
  >;
  readonly ecosystem?: Pick<PrimeEcosystemAdapter, "activate">;
  readonly createSession: (
    goal: string,
    bindIdentity: (identity: PrimeSessionInitialBinding) => Promise<void>,
    context: PrimeGatewayCreateContext,
  ) => Promise<PrimeGatewaySession>;
  readonly restoreSession?: (
    identity: PrimeIdentityBinding & Readonly<{
      continuationId: string;
      sessionPath: string;
      pendingResume?: Readonly<{
        commandId: string;
        target: PrimeContinuationLocator;
      }>;
      pendingForkClone?: Readonly<{
        commandId: string;
        operation: "session.fork" | "session.clone";
        selectedEntryId: string;
        position: "at" | "before";
      }>;
    }>,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void>,
  ) => Promise<PrimeGatewaySession>;
  readonly createCheckpoint: (
    checkpointId: string,
    coveredSequence: number,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void>,
    deadlineMs?: number,
    idleVerified?: boolean,
  ) => Promise<PrimeCheckpointCreated>;
  readonly sessionContext?: PrimeGatewaySessionContextExecutor;
  readonly onSessionReady?: (context: PrimeGatewayCreateContext) => void;
  readonly restoreExistingSession?: boolean;
  readonly now?: () => string;
}

export interface PrimeGatewaySessionContextResult {
  readonly receipt: SessionContextReceipt;
  readonly nextBinding: GatewayContextBinding | null;
  readonly sourceBinding?: GatewayContextBinding | null;
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
  deadlineMs: number;
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
  readonly command: SessionContextCommand;
  readonly promise: Promise<SessionContextReceipt>;
  settled: boolean;
}

interface ReservedEventIdentity {
  readonly eventId: string;
  readonly emittedAt: string;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const PRIME_IMAGE_MEDIA_TYPES = new Set([
  "image/gif",
  "image/jpeg",
  "image/png",
  "image/webp",
]);

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
  private readonly checkpointTasks = new Map<string, Promise<void>>();
  private readonly pendingCheckpointAcknowledgements = new Set<string>();
  private readonly pendingInputAcknowledgements = new Map<string, string>();
  private readonly inputClaims = new Map<string, string>();
  private readonly attachmentClaims = new Map<string, string>();
  private readonly commandExecutions = new Map<string, CommandExecution>();
  private readonly contextExecutions = new Map<string, ContextExecution>();
  private modelContextClaim: string | undefined;
  private readonly reservedEvents = new Map<number, ReservedEventIdentity>();
  private readonly now: () => string;
  private nextSequence: number;
  private lastAppendedSequence: number;
  private session: PrimeGatewaySession | undefined;
  private mapper: PrimeEventMapper | undefined;
  private clientObservationMapper: PrimeClientObservationMapper | undefined;
  private clientObservationHealthValue: PrimeClientObservationHealth = Object.freeze({
    status: "healthy", reason_code: null, observed_through_native_sequence: 0,
    first_missing_native_sequence: null, resync_required: false,
  });
  private readonly clientObservations: PrimeClientObservation[] = [];
  private unsubscribe: (() => void) | undefined;
  /** Monotonic source identity for callbacks from a daemon transport. */
  private transportEpoch = 0;
  private cancellationInProgress = false;
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
    try {
      this.clientObservations.push(
        ...options.store.clientObservations(options.generation) as readonly PrimeClientObservation[],
      );
      this.clientObservationHealthValue = options.store.clientObservationHealth(
        options.generation,
      );
    } catch {
      throw new PrimeGatewayError();
    }
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
          deadlineMs: event.payload.budget.deadline_ms,
        });
      } else if (event.type === "checkpoint.created") {
        this.checkpoints.add(event.payload.checkpoint_id);
      }
      this.updateSessionStatus(event);
    }
    for (const operation of options.store.contextOperations()) {
      this.contextExecutions.set(operation.command.command_id, {
        digest: sha256Hex(canonicalJsonBytes(operation.command)),
        command: operation.command,
        promise: Promise.resolve(operation.receipt),
        settled: true,
      });
    }
    const preparedModels = options.store.preparedContextModelOperations();
    if (preparedModels.length > 1) {
      throw new PrimeGatewayError();
    }
    this.modelContextClaim = preparedModels[0]?.command.command_id;
    for (const command of options.store.acceptedContextCommands()) {
      if (command.operation !== "session.attachment.bind") {
        continue;
      }
      const key = this.attachmentClaimKey(
        command.payload.input_id,
        command.payload.attachment_id,
      );
      const existing = this.attachmentClaims.get(key);
      if (existing !== undefined && existing !== command.command_id) {
        throw new PrimeGatewayError();
      }
      this.attachmentClaims.set(key, command.command_id);
    }
    const deliveryProtocolPosition = options.store.inputDeliveryProtocolPosition();
    const committedInputCommands = new Set(
      options.store.inputDeliveries().map(({ commandId }) => commandId),
    );
    for (const { command, position } of options.store.commands()) {
      if (command.type !== "input.submit") {
        continue;
      }
      const existing = this.inputClaims.get(command.payload.input_id);
      if (existing !== undefined && existing !== command.command_id) {
        throw new PrimeGatewayError();
      }
      this.inputClaims.set(command.payload.input_id, command.command_id);
      if (
        !committedInputCommands.has(command.command_id) &&
        (deliveryProtocolPosition === undefined ||
          position < deliveryProtocolPosition)
      ) {
        this.commandExecutions.set(command.command_id, {
          digest: sha256Hex(canonicalJsonBytes(command)),
          promise: Promise.resolve(),
        });
      }
    }
    for (const delivery of options.store.inputDeliveries()) {
      const command = options.store.commands().find(
        ({ command: candidate }) => candidate.command_id === delivery.commandId,
      )?.command;
      if (
        command?.type !== "input.submit" ||
        command.payload.input_id !== delivery.inputId ||
        sha256Hex(canonicalJsonBytes(
          this.committedAttachmentMetadata(delivery.inputId).map((metadata) => ({
            attachmentId: metadata.attachmentId,
            mediaType: metadata.mediaType,
            sha256: metadata.sha256,
            size: metadata.size,
          })),
        )) !== sha256Hex(canonicalJsonBytes(delivery.attachments))
      ) {
        throw new PrimeGatewayError();
      }
      this.commandExecutions.set(command.command_id, {
        digest: sha256Hex(canonicalJsonBytes(command)),
        promise: Promise.resolve(),
      });
      this.pendingInputAcknowledgements.set(
        delivery.commandId,
        delivery.inputId,
      );
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
      (options.ecosystem !== undefined &&
        typeof options.ecosystem.activate !== "function") ||
      options.store.snapshot().sessionId !== options.sessionId
    ) {
      throw new PrimeGatewayError();
    }
    const gateway = new PrimeGateway(options);
    await gateway.cleanupStagedClientObservationValues();
    await gateway.restoreClientObservationPrefix();
    await gateway.restoreActionCommands();
    if (options.restoreExistingSession !== false) {
      await gateway.restoreExistingSession();
    }
    gateway.retryInputAcknowledgements();
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

  async waitForActionProposalAvailability(): Promise<void> {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      await this.durableQueue;
      const durableSessionStatus = this.durableSessionStatus();
      if (durableSessionStatus === "running" && !this.closed && !this.terminal) {
        return;
      }
      if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
        const category = this.closed ? "closed" : this.terminal ? "terminal" : durableSessionStatus === undefined ? "prefix" : "state";
        process.stderr.write(`asterion-prime-rlm-ready:${category}\n`);
      }
      if (this.closed || this.terminal || this.sessionStatus === "paused" || this.sessionStatus === "recovery_required") {
        throw new PrimeGatewayError();
      }
      await new Promise<void>((resolve) => setTimeout(resolve, 10));
    }
    throw new PrimeGatewayError();
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

  clientObservationsAfterCursor(cursor: { readonly generation: number; readonly sequence: number }): readonly PrimeClientObservation[] {
    this.assertOpen();
    if (
      !Number.isSafeInteger(cursor.generation) || cursor.generation !== this.options.generation ||
      !Number.isSafeInteger(cursor.sequence) || cursor.sequence < 0 || cursor.sequence > this.clientObservations.length
    ) throw new PrimeGatewayError();
    return Object.freeze(this.clientObservations.slice(cursor.sequence));
  }

  clientObservationHealth(): PrimeClientObservationHealth {
    return this.clientObservationHealthValue;
  }

  async activateEcosystem(value: unknown): Promise<GatewayEcosystemEffectResult> {
    this.assertOpen();
    if (this.options.ecosystem === undefined) throw new PrimeGatewayError();
    try {
      return await this.options.ecosystem.activate(value);
    } catch {
      throw new PrimeGatewayError();
    }
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
    this.retryInputAcknowledgements();
    const digest = sha256Hex(canonicalJsonBytes(command));
    const existing = this.commandExecutions.get(command.command_id);
    if (existing !== undefined) {
      if (existing.digest !== digest) {
        throw new PrimeGatewayError();
      }
      return existing.promise;
    }
    if (command.type === "input.submit") {
      const claimedBy = this.inputClaims.get(command.payload.input_id);
      const committedAttachments = new Set(
        this.options.store.contextOperations().map(
          ({ command: accepted }) => accepted.command_id,
        ),
      );
      const hasPendingAttachment = [...this.attachmentClaims.entries()].some(
        ([key, attachmentCommandId]) =>
          key.startsWith(`${command.payload.input_id}\u0000`) &&
          !committedAttachments.has(attachmentCommandId),
      );
      if (
        (claimedBy !== undefined && claimedBy !== command.command_id) ||
        hasPendingAttachment
      ) {
        throw new PrimeGatewayError();
      }
      this.inputClaims.set(command.payload.input_id, command.command_id);
    }
    let promise: Promise<void>;
    promise = (command.type === "input.submit"
      ? this.enqueueDurable(() =>
          this.options.store.ensureInputDeliveryProtocol()
        ).then(() => this.persistAndHandle(command))
      : this.persistAndHandle(command)).catch((error) => {
      const current = this.commandExecutions.get(command.command_id);
      if (current?.promise === promise) {
        this.commandExecutions.delete(command.command_id);
      }
      if (
        command.type === "input.submit" &&
        !this.options.store.commands().some(
          ({ command: accepted }) => accepted.command_id === command.command_id,
        ) &&
        this.inputClaims.get(command.payload.input_id) === command.command_id
      ) {
        this.inputClaims.delete(command.payload.input_id);
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
      await this.reconcileCommittedContext(command, receipt);
      this.retryContextAcknowledgement(command);
      return receipt;
    }
    if (command.operation === "session.attachment.bind") {
      const claimKey = this.attachmentClaimKey(
        command.payload.input_id,
        command.payload.attachment_id,
      );
      const claimedBy = this.attachmentClaims.get(claimKey);
      if (
        !PRIME_IMAGE_MEDIA_TYPES.has(command.payload.media_type) ||
        command.payload.size <= 0 ||
        this.inputClaims.has(command.payload.input_id) ||
        (claimedBy !== undefined && claimedBy !== command.command_id)
      ) {
        throw new PrimeGatewayError();
      }
      this.attachmentClaims.set(claimKey, command.command_id);
    }
    if (
      command.operation === "session.compact" ||
      command.operation === "session.branch.summarize"
    ) {
      if (
        this.modelContextClaim !== undefined &&
        this.modelContextClaim !== command.command_id
      ) {
        throw new PrimeGatewayError();
      }
      this.modelContextClaim = command.command_id;
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
        if (this.modelContextClaim === command.command_id) {
          this.modelContextClaim = undefined;
        }
        return receipt;
      })
      .catch((error) => {
        if (this.contextExecutions.get(command.command_id) === execution) {
          this.contextExecutions.delete(command.command_id);
        }
        if (
          this.modelContextClaim === command.command_id &&
          this.options.store.preparedContextModelOperation(command.command_id) ===
            undefined
        ) {
          this.modelContextClaim = undefined;
        }
        throw error;
      });
    execution = { digest, command, promise, settled: false };
    this.contextExecutions.set(command.command_id, execution);
    return promise;
  }

  async cancelSessionContext(commandId: string): Promise<void> {
    this.assertOpen();
    const executor = this.options.sessionContext ?? this.nativeContextExecutor();
    const execution = this.contextExecutions.get(commandId);
    if (
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
    if (this.closed || this.terminal) {
      privateDiagnosticActionProposal("closed");
      throw new PrimeGatewayError();
    }
    if (
      event.type !== "action.proposed" ||
      event.session_id !== this.options.sessionId ||
      event.generation !== this.options.generation
    ) {
      privateDiagnosticActionProposal("identity");
      throw new PrimeGatewayError();
    }
    const durableSessionStatus = this.durableSessionStatus();
    if (
      durableSessionStatus !== "running" &&
      !(durableSessionStatus === "paused" && event.payload.kind === "checkpoint.create")
    ) {
      privateDiagnosticActionProposal("session");
      this.releaseReservedEvent(event);
      throw new PrimeGatewayError();
    }
    if (!this.matchesReservation(event)) {
      privateDiagnosticActionProposal("reservation");
      throw new PrimeGatewayError();
    }
    if (this.actions.has(event.payload.action_id)) {
      privateDiagnosticActionProposal("duplicate");
      this.releaseReservedEvent(event);
      throw new PrimeGatewayError();
    }
    try {
      await this.append(event);
    } catch {
      privateDiagnosticActionProposal("append");
      throw new PrimeGatewayError();
    }
    this.actions.set(event.payload.action_id, {
      status: "proposed",
      kind: event.payload.kind,
      targetId: this.actionTargetId(event),
      deadlineMs: event.payload.budget.deadline_ms,
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
    if (this.session !== undefined && this.sessionStatus !== "terminal") {
      await this.session.detach("asterion-detach");
    }
  }

  async settle(): Promise<void> {
    await this.eventQueue;
    await this.durableQueue;
    while (this.checkpointTasks.size > 0) {
      await Promise.all(this.checkpointTasks.values());
      await this.eventQueue;
      await this.durableQueue;
    }
  }

  async close(): Promise<void> {
    if (this.closed) {
      return;
    }
    await this.settle();
    this.closed = true;
    await this.clientObservationMapper?.close();
    this.unsubscribe?.();
    this.unsubscribe = undefined;
  }

  private async inputAttachments(
    inputId: string,
  ): Promise<readonly PrimeInputAttachment[]> {
    const expected = this.committedAttachmentMetadata(inputId);
    let bound: readonly PrivateBoundAttachment[];
    try {
      bound = await this.options.privateValues.readBoundAttachments(
        this.options.sessionId,
        inputId,
        expected,
      );
    } catch {
      throw new PrimeGatewayError();
    }
    if (bound.length !== expected.length) {
      throw new PrimeGatewayError();
    }
    const delivered = bound.map((attachment, index) => {
      const metadata = expected[index];
      if (
        metadata === undefined ||
        attachment.sessionId !== metadata.sessionId ||
        attachment.inputId !== metadata.inputId ||
        attachment.attachmentId !== metadata.attachmentId ||
        attachment.mediaType !== metadata.mediaType ||
        attachment.sha256 !== metadata.sha256 ||
        attachment.size !== metadata.size ||
        !(attachment.body instanceof Uint8Array)
      ) {
        throw new PrimeGatewayError();
      }
      return Object.freeze({
        attachmentId: attachment.attachmentId,
        mediaType: attachment.mediaType,
        sha256: attachment.sha256,
        size: attachment.size,
        body: Uint8Array.from(attachment.body),
      });
    });
    return Object.freeze(delivered);
  }

  private committedAttachmentMetadata(
    inputId: string,
  ): readonly PrivateAttachmentMetadata[] {
    const expected: PrivateAttachmentMetadata[] = [];
    for (const { command, receipt } of this.options.store.contextOperations()) {
      if (
        command.operation !== "session.attachment.bind" ||
        receipt.status !== "succeeded" ||
        command.payload.input_id !== inputId
      ) {
        continue;
      }
      const result = receipt.payload.result as Readonly<{
        input_id: string;
        attachment_id: string;
        media_type: string;
        sha256: string;
        size: number;
      }>;
      if (
        result.input_id !== command.payload.input_id ||
        result.attachment_id !== command.payload.attachment_id ||
        result.media_type !== command.payload.media_type ||
        result.sha256 !== command.payload.sha256 ||
        result.size !== command.payload.size ||
        !PRIME_IMAGE_MEDIA_TYPES.has(result.media_type)
      ) {
        throw new PrimeGatewayError();
      }
      expected.push(Object.freeze({
        sessionId: command.session_id,
        inputId: result.input_id,
        attachmentId: result.attachment_id,
        mediaType: result.media_type,
        sha256: result.sha256,
        size: result.size,
      }));
    }
    if (expected.some((metadata, index) => {
      const previous = expected[index - 1];
      return previous !== undefined &&
        previous.attachmentId >= metadata.attachmentId;
    })) {
      throw new PrimeGatewayError();
    }
    return Object.freeze(expected);
  }

  private retryInputAcknowledgements(): void {
    if (this.session === undefined) {
      return;
    }
    for (const [commandId, inputId] of this.pendingInputAcknowledgements) {
      try {
        if (this.session.acknowledgeInput(inputId)) {
          this.pendingInputAcknowledgements.delete(commandId);
        }
      } catch {
        // A later replay or restart retries the stable acknowledgement.
      }
    }
  }

  private attachmentClaimKey(inputId: string, attachmentId: string): string {
    return `${inputId}\u0000${attachmentId}`;
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
        const attachments = await this.inputAttachments(
          command.payload.input_id,
        );
        const deliveryMetadata = attachments.map(({ body: _body, ...metadata }) =>
          metadata
        );
        const submission = await this.requireSession().submitInput(
          command.payload.input_id,
          command.payload.delivery,
          await this.options.privateValues.readInput(command.payload.content_ref),
          attachments,
        );
        if (
          typeof submission !== "object" ||
          submission === null ||
          Object.keys(submission).length !== 1 ||
          typeof submission.acknowledge !== "function"
        ) {
          throw new PrimeGatewayError();
        }
        await this.enqueueDurable(() =>
          this.options.store.commitInputDelivery(
            command.command_id,
            deliveryMetadata,
          )
        );
        this.pendingInputAcknowledgements.set(
          command.command_id,
          command.payload.input_id,
        );
        try {
          if (submission.acknowledge()) {
            this.pendingInputAcknowledgements.delete(command.command_id);
          }
        } catch {
          // The body-free delivery commit wins; restart retries acknowledgement.
        }
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
      case "session.detach":
        if (this.sessionStatus === undefined || this.sessionStatus === "terminal") {
          throw new PrimeGatewayError();
        }
        await this.requireSession().detach(command.command_id);
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
          this.sessionStatus !== "paused" &&
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
            .join("\u0000") &&
          resultKeys !== ["nextBinding", "receipt", "sourceBinding"]
            .sort()
            .join("\u0000") &&
          resultKeys !== [
            "acknowledge",
            "nextBinding",
            "receipt",
            "sourceBinding",
          ]
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
      if (
        command.operation === "session.attachment.bind" &&
        receipt.status === "succeeded"
      ) {
        const attachmentResult = receipt.payload.result as Readonly<{
          input_id: string;
          attachment_id: string;
          media_type: string;
          sha256: string;
          size: number;
        }>;
        if (
          attachmentResult.input_id !== command.payload.input_id ||
          attachmentResult.attachment_id !== command.payload.attachment_id ||
          attachmentResult.media_type !== command.payload.media_type ||
          attachmentResult.sha256 !== command.payload.sha256 ||
          attachmentResult.size !== command.payload.size
        ) {
          throw new PrimeGatewayError();
        }
      }
      this.assertMonotonicContextReceipt(receipt);
      const committed = await this.enqueueDurable(
        () => this.options.store.commitContextOperation(
          receipt,
          result.nextBinding,
          result.sourceBinding ?? null,
        ),
      );
      await this.reconcileCommittedContext(command, committed.receipt);
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
        if (command.operation === "session.attachment.bind") {
          if (!PRIME_IMAGE_MEDIA_TYPES.has(command.payload.media_type)) {
            throw new PrimeGatewayError();
          }
          const bound = await this.options.privateValues.readBoundAttachment(
            command.session_id,
            command.payload.input_id,
            command.payload.attachment_id,
          );
          if (
            bound.sessionId !== command.session_id ||
            bound.inputId !== command.payload.input_id ||
            bound.attachmentId !== command.payload.attachment_id ||
            bound.mediaType !== command.payload.media_type ||
            bound.sha256 !== command.payload.sha256 ||
            bound.size !== command.payload.size
          ) {
            throw new PrimeGatewayError();
          }
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              input_id: bound.inputId,
              attachment_id: bound.attachmentId,
              media_type: bound.mediaType,
              sha256: bound.sha256,
              size: bound.size,
            }),
            nextBinding: null,
          });
        }
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
        if (command.operation === "session.label.set") {
          this.assertActiveContinuation(command.payload.continuation_id);
          const labelled = await session.setContextLabel(
            command.command_id,
            command.payload.continuation_id,
            command.payload.entry_id,
            command.payload.label_ref === null
              ? null
              : await this.options.privateValues.readInput(
                command.payload.label_ref,
              ),
          );
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: labelled.result.continuationId,
              entry_id: labelled.result.entryId,
              label_sha256: labelled.result.labelSha256,
            }),
            nextBinding: null,
            acknowledge: labelled.acknowledge,
          });
        }
        if (
          command.operation === "session.compact" ||
          command.operation === "session.branch.summarize"
        ) {
          this.assertActiveContinuation(command.payload.continuation_id);
          if (
            command.payload.budget.controller_tokens === 0 ||
            command.payload.budget.aggregate_tokens === 0
          ) {
            return Object.freeze({
              receipt: this.contextTerminalReceipt(
                command,
                "rejected",
                "provider-budget-unsupported",
              ),
              nextBinding: null,
            });
          }
          const baseline = await this.prepareContextModelBaseline(command);
          const instructions = command.payload.instructions_ref === null
            ? null
            : await this.options.privateValues.readInput(
              command.payload.instructions_ref,
            );
          if (command.operation === "session.compact") {
            const outcome = await session.compactContext(
              command.command_id,
              command.payload.continuation_id,
              instructions,
              command.payload.budget,
              baseline,
            );
            if (outcome.status !== "succeeded") {
              return Object.freeze({
                receipt: this.contextTerminalReceipt(
                  command,
                  outcome.status,
                  this.contextModelReasonCode(outcome.status),
                ),
                nextBinding: null,
                acknowledge: outcome.acknowledge,
              });
            }
            return Object.freeze({
              receipt: this.contextSuccessReceipt(command, {
                continuation_id: outcome.result.continuationId,
                covered_leaf_id: outcome.result.coveredLeafId,
                before_context_tokens: outcome.result.beforeContextTokens,
                after_context_tokens: outcome.result.afterContextTokens,
                summary_sha256: outcome.result.summarySha256,
                usage: outcome.result.usage,
              }),
              nextBinding: null,
              acknowledge: outcome.acknowledge,
            });
          }
          const outcome = await session.summarizeContextBranch(
            command.command_id,
            command.payload.continuation_id,
            command.payload.entry_id,
            instructions,
            command.payload.budget,
            baseline,
          );
          if (outcome.status !== "succeeded") {
            return Object.freeze({
              receipt: this.contextTerminalReceipt(
                command,
                outcome.status,
                this.contextModelReasonCode(outcome.status),
              ),
              nextBinding: null,
              acknowledge: outcome.acknowledge,
            });
          }
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: outcome.result.continuationId,
              previous_leaf_id: outcome.result.previousLeafId,
              current_leaf_id: outcome.result.currentLeafId,
              summary_sha256: outcome.result.summarySha256,
              usage: outcome.result.usage,
            }),
            nextBinding: null,
            acknowledge: outcome.acknowledge,
          });
        }
        if (command.operation === "session.tree.read") {
          this.assertActiveContinuation(command.payload.continuation_id);
          const tree = await session.readContextTree(
            command.command_id,
            command.payload.continuation_id,
          );
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: command.payload.continuation_id,
              nodes: tree.nodes,
              leaf_id: tree.leafId,
            }),
            nextBinding: null,
          });
        }
        if (command.operation === "session.tree.navigate") {
          const prepared = await this.prepareTreeMutation(command);
          const navigated = await session.navigateContextTree(
            command.command_id,
            command.payload.continuation_id,
            command.payload.entry_id,
            prepared.previousLeafId,
          );
          const nextBinding = await this.options.privateValues
            .putContinuationLocator(prepared.locator);
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: navigated.result.continuationId,
              previous_leaf_id: navigated.result.previousLeafId,
              current_leaf_id: navigated.result.currentLeafId,
              transition_sha256: navigated.result.transitionSha256,
            }),
            nextBinding,
            acknowledge: navigated.acknowledge,
          });
        }
        if (
          command.operation === "session.fork" ||
          command.operation === "session.clone"
        ) {
          const prepared = await this.prepareForkClone(command);
          const replaced = command.operation === "session.fork"
            ? await session.forkContext(
                command.command_id,
                command.payload.continuation_id,
                prepared.selectedEntryId,
                command.payload.position,
              )
            : await session.cloneContext(
                command.command_id,
                command.payload.continuation_id,
                prepared.selectedEntryId,
              );
          const sourceBinding = await this.refreshedPreparedContinuationBinding(
            prepared.binding,
          );
          const nextBinding = await this.options.privateValues
            .putContinuationLocator(replaced.locator);
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              source_continuation_id: replaced.result.sourceContinuationId,
              new_continuation_id: replaced.result.newContinuationId,
              active_leaf_id: replaced.result.activeLeafId,
              transition_sha256: replaced.result.transitionSha256,
            }),
            sourceBinding,
            nextBinding,
            acknowledge: replaced.acknowledge,
          });
        }
        if (command.operation === "session.continuation.resume") {
          const target = await this.prepareContinuationTarget(command);
          const sourceBinding = this.options.store.activeContextBinding();
          if (
            sourceBinding === undefined ||
            sourceBinding.continuationId === target.continuationId
          ) {
            throw new PrimeGatewayError();
          }
          const resumed = await session.resumeContinuation(
            command.command_id,
            target,
          );
          await this.refreshPreparedContinuationBinding(sourceBinding);
          const nextBinding = await this.options.privateValues
            .putContinuationLocator(resumed.locator);
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              previous_continuation_id: resumed.result.previousContinuationId,
              current_continuation_id: resumed.result.currentContinuationId,
              transition_sha256: resumed.result.transitionSha256,
            }),
            nextBinding,
            acknowledge: resumed.acknowledge,
          });
        }
        if (command.operation === "session.continuation.delete") {
          const target = await this.prepareContinuationTarget(command);
          const deleted = await session.deleteContinuation(
            command.command_id,
            target,
          );
          return Object.freeze({
            receipt: this.contextSuccessReceipt(command, {
              continuation_id: deleted.result.continuationId,
              deletion_sha256: deleted.result.deletionSha256,
            }),
            nextBinding: null,
            acknowledge: deleted.acknowledge,
          });
        }
        throw new PrimeGatewayError();
      },
      cancel: async (commandId: string) => {
        const execution = this.contextExecutions.get(commandId);
        if (
          execution === undefined ||
          (execution.command.operation !== "session.compact" &&
            execution.command.operation !== "session.branch.summarize")
        ) {
          throw new PrimeGatewayError();
        }
        await session.abortContextModelOperation(
          commandId,
          execution.command.operation,
        );
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

  private contextTerminalReceipt(
    command: SessionContextCommand,
    status: "cancelled" | "rejected" | "uncertain",
    reasonCode: string,
  ): SessionContextReceipt {
    return validateSessionContextReceipt({
      protocol: "asterion.session-context/v1",
      receipt_id: `context-${sha256Hex(
        canonicalJsonBytes({ command_id: command.command_id, status }),
      ).slice(0, 32)}`,
      command_id: command.command_id,
      session_id: command.session_id,
      generation: command.generation,
      operation: command.operation,
      status,
      reason_code: reasonCode,
      payload: { evidence_ref: null, result: null },
    });
  }

  private contextModelReasonCode(
    status: "cancelled" | "rejected" | "uncertain",
  ): string {
    if (status === "cancelled") {
      return "provider-cancelled";
    }
    return status === "uncertain"
      ? "provider-outcome-uncertain"
      : "provider-rejected";
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
    if (this.session === undefined) {
      return;
    }
    try {
      if (command.operation === "session.name.set") {
        this.session.acknowledgeContext(command.command_id);
      } else if (command.operation === "session.label.set") {
        this.session.acknowledgeLabel(command.command_id);
      } else if (
        command.operation === "session.compact" ||
        command.operation === "session.branch.summarize"
      ) {
        this.session.acknowledgeContextModelOperation(
          command.command_id,
          command.operation,
        );
      } else if (
        command.operation === "session.continuation.resume" ||
        command.operation === "session.continuation.delete"
      ) {
        this.session.acknowledgeContinuation(
          command.command_id,
          command.operation,
        );
      } else if (command.operation === "session.tree.navigate") {
        this.session.acknowledgeTreeMutation(command.command_id);
      } else if (
        command.operation === "session.fork" ||
        command.operation === "session.clone"
      ) {
        this.session.acknowledgeForkClone(
          command.command_id,
          command.operation,
        );
      }
    } catch {
      // A later replay retries the stable acknowledgement.
    }
  }

  private async prepareContinuationTarget(
    command: Extract<
      SessionContextCommand,
      {
        readonly operation:
          | "session.continuation.delete"
          | "session.continuation.resume";
      }
    >,
  ): Promise<PrimeContinuationLocator> {
    const targetId = command.payload.continuation_id;
    let binding = this.options.store.preparedContextBinding(command.command_id);
    if (binding === undefined) {
      binding = this.options.store.currentContextBinding(targetId);
      if (
        binding === undefined ||
        this.options.store.activeContextBinding()?.continuationId === targetId
      ) {
        throw new PrimeGatewayError();
      }
      if (command.operation === "session.continuation.resume") {
        const sourceBinding = this.options.store.activeContextBinding();
        if (sourceBinding === undefined) {
          throw new PrimeGatewayError();
        }
        await this.ensurePinnedContinuationBinding(sourceBinding);
      }
      let locator = await this.options.privateValues.readContinuationLocator(binding);
      this.assertContinuationTarget(locator, targetId, false);
      if (locator.supervisorGeneration !== this.requireSession().supervisorGeneration) {
        const replacement = await this.options.privateValues.putContinuationLocator({
          ...locator,
          supervisorGeneration: this.requireSession().supervisorGeneration,
        });
        await this.enqueueDurable(
          () => this.options.store.rebindContextBinding(replacement),
        );
        binding = replacement;
        locator = await this.options.privateValues.readContinuationLocator(binding);
        this.assertContinuationTarget(locator, targetId);
      } else {
        const prepared = await this.options.privateValues
          .ensurePreparedContinuationLocator(binding);
        if (!this.sameContextBinding(binding, prepared.binding)) {
          await this.enqueueDurable(
            () => this.options.store.rebindContextBinding(prepared.binding),
          );
        }
        binding = prepared.binding;
        locator = prepared.locator;
      }
      await this.enqueueDurable(
        () => this.options.store.prepareContextOperation(
          command.command_id,
          binding!,
        ),
      );
      if (!this.sameContextBinding(
        this.options.store.currentContextBinding(targetId),
        binding,
      )) {
        throw new PrimeGatewayError();
      }
      const revalidated = await this.options.privateValues
        .readContinuationLocator(binding);
      this.assertContinuationTarget(revalidated, targetId);
      return revalidated;
    }
    if (!this.sameContextBinding(
      this.options.store.currentContextBinding(targetId),
      binding,
    )) {
      throw new PrimeGatewayError();
    }
    const replay = await this.options.privateValues.readPreparedContinuationLocator(
      binding,
      command.operation === "session.continuation.delete",
    );
    this.assertContinuationTarget(replay, targetId);
    return replay;
  }

  private async prepareContextModelBaseline(
    command: Extract<
      SessionContextCommand,
      {
        readonly operation:
          | "session.branch.summarize"
          | "session.compact";
      }
    >,
  ): Promise<GatewayContextModelBaseline> {
    const existing = this.options.store.preparedContextModelOperation(
      command.command_id,
    );
    if (existing !== undefined) {
      if (
        existing.commandId !== command.command_id ||
        existing.continuationId !== command.payload.continuation_id
      ) {
        throw new PrimeGatewayError();
      }
      return existing;
    }
    const measured = await this.requireSession().measureContextModelBaseline(
      command.command_id,
      command.payload.continuation_id,
      command.operation === "session.branch.summarize"
        ? command.payload.entry_id
        : undefined,
    );
    await this.enqueueDurable(
      () => this.options.store.prepareContextModelOperation(
        command.command_id,
        measured,
      ),
    );
    const prepared = this.options.store.preparedContextModelOperation(
      command.command_id,
    );
    if (prepared === undefined) {
      throw new PrimeGatewayError();
    }
    return prepared;
  }

  private assertActiveContinuation(continuationId: string): void {
    const active = this.options.store.activeContextBinding();
    const session = this.requireSession();
    if (
      active === undefined ||
      active.continuationId !== continuationId ||
      session.continuationId !== continuationId
    ) {
      throw new PrimeGatewayError();
    }
  }

  private async prepareTreeMutation(
    command: Extract<
      SessionContextCommand,
      { readonly operation: "session.tree.navigate" }
    >,
  ): Promise<Readonly<{
    locator: PrivateContinuationLocator;
    previousLeafId: string | null;
  }>> {
    this.assertActiveContinuation(command.payload.continuation_id);
    let binding = this.options.store.preparedContextBinding(command.command_id);
    let state = this.options.store.preparedContextState(command.command_id);
    if (binding === undefined) {
      const active = this.options.store.activeContextBinding();
      if (active === undefined) {
        throw new PrimeGatewayError();
      }
      const pinned = await this.ensurePinnedContinuationBinding(active);
      binding = pinned.binding;
      const tree = await this.requireSession().readContextTree(
        `${command.command_id}-prepare`,
        command.payload.continuation_id,
      );
      if (!tree.nodes.some((node) => node.entry_id === command.payload.entry_id)) {
        throw new PrimeGatewayError();
      }
      state = Object.freeze({
        previousLeafId: tree.leafId,
        selectedEntryId: command.payload.entry_id,
      });
      await this.enqueueDurable(
        () => this.options.store.prepareContextOperation(
          command.command_id,
          binding!,
          state!,
        ),
      );
      if (!this.sameContextBinding(
        this.options.store.currentContextBinding(command.payload.continuation_id),
        binding,
      )) {
        throw new PrimeGatewayError();
      }
      const revalidated = await this.options.privateValues
        .readContinuationLocator(binding);
      this.assertContinuationTarget(
        revalidated,
        command.payload.continuation_id,
      );
      return Object.freeze({
        locator: revalidated,
        previousLeafId: state.previousLeafId,
      });
    }
    if (
      state === undefined ||
      state.selectedEntryId !== command.payload.entry_id ||
      !this.sameContextBinding(
        this.options.store.currentContextBinding(command.payload.continuation_id),
        binding,
      )
    ) {
      throw new PrimeGatewayError();
    }
    const locator = await this.options.privateValues
      .readPreparedContinuationLocator(binding, false);
    this.assertContinuationTarget(locator, command.payload.continuation_id, false);
    return Object.freeze({
      locator: Object.freeze({
        ...locator,
        supervisorGeneration: this.requireSession().supervisorGeneration,
      }),
      previousLeafId: state.previousLeafId,
    });
  }

  private async prepareForkClone(
    command: Extract<
      SessionContextCommand,
      { readonly operation: "session.fork" | "session.clone" }
    >,
  ): Promise<Readonly<{
    binding: GatewayContextBinding;
    locator: PrivateContinuationLocator;
    previousLeafId: string | null;
    selectedEntryId: string;
  }>> {
    let binding = this.options.store.preparedContextBinding(command.command_id);
    let state = this.options.store.preparedContextState(command.command_id);
    if (binding === undefined) {
      this.assertActiveContinuation(command.payload.continuation_id);
      const active = this.options.store.activeContextBinding();
      if (active === undefined) {
        throw new PrimeGatewayError();
      }
      const pinned = await this.ensurePinnedContinuationBinding(active);
      binding = pinned.binding;
      const tree = await this.requireSession().readContextTree(
        `${command.command_id}-prepare`,
        command.payload.continuation_id,
      );
      let selectedEntryId: string;
      if (command.operation === "session.fork") {
        const selected = tree.nodes.find(
          (node) => node.entry_id === command.payload.entry_id,
        );
        if (
          selected === undefined ||
          (command.payload.position === "before" && selected.kind !== "input")
        ) {
          throw new PrimeGatewayError();
        }
        selectedEntryId = command.payload.entry_id;
      } else {
        if (tree.leafId === null) {
          throw new PrimeGatewayError();
        }
        selectedEntryId = tree.leafId;
      }
      state = Object.freeze({
        previousLeafId: tree.leafId,
        selectedEntryId,
      });
      await this.enqueueDurable(
        () => this.options.store.prepareContextOperation(
          command.command_id,
          binding!,
          state!,
        ),
      );
      if (!this.sameContextBinding(
        this.options.store.currentContextBinding(command.payload.continuation_id),
        binding,
      )) {
        throw new PrimeGatewayError();
      }
      const revalidated = await this.options.privateValues
        .readContinuationLocator(binding);
      this.assertContinuationTarget(
        revalidated,
        command.payload.continuation_id,
      );
      return Object.freeze({
        binding,
        locator: revalidated,
        previousLeafId: state.previousLeafId,
        selectedEntryId: state.selectedEntryId!,
      });
    }
    const expectedEntryId = command.operation === "session.fork"
      ? command.payload.entry_id
      : state?.previousLeafId;
    if (
      state === undefined ||
      state.selectedEntryId === null ||
      state.selectedEntryId !== expectedEntryId ||
      !this.sameContextBinding(
        this.options.store.currentContextBinding(command.payload.continuation_id),
        binding,
      )
    ) {
      throw new PrimeGatewayError();
    }
    const locator = await this.options.privateValues
      .readPreparedContinuationLocator(binding, false);
    this.assertContinuationTarget(locator, command.payload.continuation_id, false);
    return Object.freeze({
      binding,
      locator,
      previousLeafId: state.previousLeafId,
      selectedEntryId: state.selectedEntryId,
    });
  }

  private async ensurePinnedContinuationBinding(
    binding: GatewayContextBinding,
  ): Promise<Readonly<{
    binding: GatewayContextBinding;
    locator: PrivateContinuationLocator;
  }>> {
    const prepared = await this.options.privateValues
      .ensurePreparedContinuationLocator(binding);
    if (!this.sameContextBinding(binding, prepared.binding)) {
      await this.enqueueDurable(
        () => this.options.store.rebindContextBinding(prepared.binding),
      );
    }
    return prepared;
  }

  private async refreshPreparedContinuationBinding(
    binding: GatewayContextBinding,
  ): Promise<GatewayContextBinding> {
    try {
      await this.options.privateValues.readContinuationLocator(binding);
      return binding;
    } catch {
      const locator = await this.options.privateValues
        .readPreparedContinuationLocator(binding, false);
      const replacement = await this.options.privateValues
        .putContinuationLocator(locator);
      await this.enqueueDurable(
        () => this.options.store.rebindContextBinding(replacement),
      );
      return replacement;
    }
  }

  private async refreshedPreparedContinuationBinding(
    binding: GatewayContextBinding,
  ): Promise<GatewayContextBinding> {
    let locator: PrivateContinuationLocator;
    try {
      locator = await this.options.privateValues.readContinuationLocator(binding);
      if (locator.supervisorGeneration === this.requireSession().supervisorGeneration) {
        return binding;
      }
    } catch {
      locator = await this.options.privateValues
        .readPreparedContinuationLocator(binding, false);
    }
    return this.options.privateValues.putContinuationLocator(Object.freeze({
      ...locator,
      supervisorGeneration: this.requireSession().supervisorGeneration,
    }));
  }

  private assertContinuationTarget(
    locator: PrivateContinuationLocator,
    continuationId: string,
    requireCurrentGeneration = true,
  ): void {
    const session = this.requireSession();
    if (
      locator.continuationId !== continuationId ||
      locator.activeSessionId !== session.activeSessionId ||
      (requireCurrentGeneration &&
        locator.supervisorGeneration !== session.supervisorGeneration)
    ) {
      throw new PrimeGatewayError();
    }
  }

  private sameContextBinding(
    left: GatewayContextBinding | undefined,
    right: GatewayContextBinding,
  ): boolean {
    return left !== undefined &&
      left.continuationId === right.continuationId &&
      left.privateRef === right.privateRef &&
      left.bindingDigest === right.bindingDigest;
  }

  private async reconcileCommittedContext(
    command: SessionContextCommand,
    receipt: SessionContextReceipt,
  ): Promise<void> {
    if (receipt.operation !== command.operation) {
      throw new PrimeGatewayError();
    }
    if (receipt.status !== "succeeded") {
      return;
    }
    if (
      command.operation === "session.continuation.resume" ||
      command.operation === "session.fork" ||
      command.operation === "session.clone"
    ) {
      const binding = this.options.store.activeContextBinding();
      const currentId = (receipt.payload.result as {
        readonly current_continuation_id?: string;
        readonly new_continuation_id?: string;
      }).current_continuation_id ?? (receipt.payload.result as {
        readonly new_continuation_id: string;
      }).new_continuation_id;
      if (binding === undefined) {
        throw new PrimeGatewayError();
      }
      if (binding.continuationId !== currentId) {
        return;
      }
      const locator = await this.options.privateValues.readContinuationLocator(binding);
      this.assertContinuationTarget(locator, currentId);
      const session = this.requireSession();
      session.adoptContinuation(locator);
      await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
        activeSessionId: locator.activeSessionId,
        transcriptSessionId: locator.transcriptSessionId,
        supervisorGeneration: locator.supervisorGeneration,
      }));
    } else if (
      command.operation === "session.continuation.delete" &&
      this.options.store.currentContextBinding(
        (receipt.payload.result as {
          readonly continuation_id: string;
        }).continuation_id,
      ) !== undefined
    ) {
      throw new PrimeGatewayError();
    } else if (command.operation === "session.tree.navigate") {
      const session = this.requireSession();
      await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
        activeSessionId: session.activeSessionId,
        transcriptSessionId: session.transcriptSessionId,
        supervisorGeneration: session.supervisorGeneration,
      }));
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
      privateDiagnosticContextRefresh("current");
      throw new PrimeGatewayError();
    }
    let locator: PrimeContinuationLocator;
    try {
      locator = await this.options.privateValues.readContinuationLocator(current);
    } catch {
      // A Prime checkpoint can append to the same trusted transcript while it
      // prepares the successor. Re-pin only the already durable binding; the
      // identity checks below still reject a substituted continuation.
      try {
        locator = await this.options.privateValues
          .readPreparedContinuationLocator(current, false);
      } catch {
        try {
          const rebound = await this.options.privateValues
            .rebindRecoveredContinuationLocator(current, {
              continuationId: session.continuationId,
              activeSessionId: session.activeSessionId,
              transcriptSessionId: session.transcriptSessionId,
              supervisorGeneration,
            });
          await this.enqueueDurable(
            () => this.options.store.rebindContextBinding(rebound),
          );
          locator = await this.options.privateValues.readContinuationLocator(rebound);
        } catch {
          privateDiagnosticContextRefresh("locator");
          throw new PrimeGatewayError();
        }
      }
    }
    if (
      locator.continuationId !== session.continuationId ||
      locator.activeSessionId !== session.activeSessionId ||
      locator.transcriptSessionId !== session.transcriptSessionId
    ) {
      privateDiagnosticContextRefresh("identity");
      throw new PrimeGatewayError();
    }
    if (locator.supervisorGeneration === supervisorGeneration) {
      privateDiagnosticContextRefresh("unchanged");
      return;
    }
    try {
      const replacement = await this.options.privateValues.putContinuationLocator({
        ...locator,
        supervisorGeneration,
      });
      await this.enqueueDurable(
        () => this.options.store.rebindContextBinding(replacement),
      );
    } catch {
      privateDiagnosticContextRefresh("write");
      throw new PrimeGatewayError();
    }
    privateDiagnosticContextRefresh("rebound");
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
    this.clientObservationMapper = this.newClientObservationMapper(
      session.activeSessionId,
    );
    await this.append(this.event("session.created", {
      goal_id: this.goalId,
      authority_id: this.options.authorityId,
      authority_revision: command.authority_revision,
    }));
    await this.append(this.reasonEvent("session.running", "prime-resident-started"));
    this.options.onSessionReady?.(createContext);
    this.subscribeToSession(session);
  }

  private async cancel(
    command: Extract<ControlCommand, { type: "session.cancel" }>,
  ): Promise<void> {
    this.cancellationInProgress = true;
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    try {
      await this.eventQueue;
      if (this.sessionStatus === undefined || this.sessionStatus === "terminal") {
        throw new PrimeGatewayError();
      }
      await this.requireSession().cancel(command.command_id);
      privateDiagnosticGatewayCancelStage("native-returned");
      const goalId = this.requireGoalId();
      await this.append(this.event("goal.updated", {
        goal_id: goalId,
        status: "cancelled",
      }));
      privateDiagnosticGatewayCancelStage("goal-updated");
      await this.append(this.reasonEvent("session.cancelled", command.payload.reason_code));
      privateDiagnosticGatewayCancelStage("terminal-appended");
      this.mapper?.noteExternalGoalStatus("cancelled");
      this.mapper?.noteExternalTerminal();
      this.terminal = true;
    } catch {
      if (!this.terminal && !this.closed) {
        this.cancellationInProgress = false;
        this.subscribeToSession(this.requireSession());
      }
      throw new PrimeGatewayError();
    }
  }

  private async checkpoint(checkpointId: string, deadlineMs?: number): Promise<void> {
    if (this.checkpoints.has(checkpointId)) {
      this.retryCheckpointAcknowledgements();
      return;
    }
    const session = this.requireSession();
    const deadlineAt = Date.now() + (deadlineMs ?? 120_000);
    // PrimeSession.pause() does not return until native `wait_for_idle`
    // succeeds.  A paused resident root can still report itself as active
    // because it exists, so probing it again here can turn that completed
    // quiescence barrier into a false checkpoint timeout.
    while (
      this.sessionStatus !== "paused" &&
      typeof session.isIdle === "function" &&
      !await session.isIdle()
    ) {
      const remainingMs = deadlineAt - Date.now();
      if (remainingMs <= 0) {
        throw new PrimeGatewayError();
      }
      await new Promise<void>((resolve) => setTimeout(resolve, Math.min(50, remainingMs)));
    }
    const remainingMs = deadlineAt - Date.now();
    if (remainingMs <= 0) {
      throw new PrimeGatewayError();
    }
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    try {
      await this.eventQueue;
      if (this.sessionStatus === "running" || this.sessionStatus === "paused") {
        await this.append(this.reasonEvent(
          "session.recovery-required",
          "prime-checkpoint-restart",
        ));
        this.mapper?.noteExternalRecoveryRequired();
      } else if (this.sessionStatus !== "recovery_required") {
        throw new PrimeGatewayError();
      }
    } catch {
      this.subscribeToSession(this.requireSession());
      throw new PrimeGatewayError();
    }

    // The queue above drains every event accepted before the checkpoint
    // boundary.  Callbacks retained by the retired transport can still fire
    // later, so invalidate only that source before the recovered mapper exists.
    this.transportEpoch += 1;

    const expectedRecoveryStatus = this.recoveryBaseStatus === "paused"
      ? "paused"
      : "running";
    const restoredEvent = this.reasonEvent(
      expectedRecoveryStatus === "paused" ? "session.paused" : "session.running",
      "prime-checkpoint-restored",
    );
    const coveredSequence = restoredEvent.sequence;
    let recovered: PrimeCheckpointRecovery | undefined;
    let adopted = false;
    let created: PrimeCheckpointCreated;
    try {
      created = await this.options.createCheckpoint(
        checkpointId,
        coveredSequence,
        async (recovery) => {
          if (recovered !== undefined) {
            privateDiagnosticCheckpointRecovery("duplicate");
            throw new PrimeGatewayError();
          }
          if (this.sessionStatus !== "recovery_required") {
            privateDiagnosticCheckpointRecovery("state");
            throw new PrimeGatewayError();
          }
          if (!this.validRecovery(recovery)) {
            privateDiagnosticCheckpointRecovery("invalid");
            throw new PrimeGatewayError();
          }
          // Prime reports a resident root's goal as active after reattach even
          // when the operator had already paused Asterion at the checkpoint
          // boundary. Preserve that external pause; a running Asterion session
          // still requires a running native recovery.
          if (
            expectedRecoveryStatus === "running" &&
            recovery.sessionStatus !== "running"
          ) {
            privateDiagnosticCheckpointRecovery("status");
            throw new PrimeGatewayError();
          }
          privateDiagnosticCheckpointRecovery("validated");
          const session = this.requireSession();
          const identity = this.options.store.snapshot().primeIdentity;
          if (
            identity === undefined ||
            session.activeSessionId !== identity.activeSessionId ||
            session.transcriptSessionId !== identity.transcriptSessionId ||
            session.supervisorGeneration !== identity.supervisorGeneration ||
            recovery.transcriptSessionId !== identity.transcriptSessionId
          ) {
            privateDiagnosticCheckpointRecovery("identity");
            throw new PrimeGatewayError();
          }
          session.adoptRecovery(recovery);
          if (session.supervisorGeneration !== recovery.supervisorGeneration) {
            privateDiagnosticCheckpointRecovery("adopt");
            throw new PrimeGatewayError();
          }
          adopted = true;
          privateDiagnosticCheckpointRecovery("adopted");
          try {
            await this.refreshContextBinding(
              session,
              recovery.supervisorGeneration,
            );
          } catch {
            privateDiagnosticCheckpointRecovery("context-failed");
            throw new PrimeGatewayError();
          }
          privateDiagnosticCheckpointRecovery("context");
          await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
            activeSessionId: session.activeSessionId,
            transcriptSessionId: recovery.transcriptSessionId,
            supervisorGeneration: recovery.supervisorGeneration,
          }));
          await this.enqueueDurable(
            () => this.options.store.recordPrimeCursor(recovery.primeCursor),
          );
          privateDiagnosticCheckpointRecovery("cursor");
          this.mapper = this.recoveredMapper(recovery.primeCursor);
          await this.append(restoredEvent);
          privateDiagnosticCheckpointRecovery("event");
          this.mapper.noteExternalSessionStatus(expectedRecoveryStatus);
          recovered = recovery;
          privateDiagnosticCheckpointRecovery("complete");
        },
        remainingMs,
        this.sessionStatus === "paused",
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
        this.releaseReservedEvent(restoredEvent);
      }
      if (recovered !== undefined || adopted) {
        this.subscribeToSession(this.requireSession());
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
      this.subscribeToSession(this.requireSession());
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

  private newClientObservationMapper(
    activeSessionId: string,
  ): PrimeClientObservationMapper | undefined {
    const values = this.options.clientObservationValues;
    if (values === undefined) {
      return undefined;
    }
    const progress = this.options.store.clientObservationProgress(
      this.options.generation,
    );
    // A persisted sequence gap cannot be healed by replaying arbitrary live
    // events. Keep the projection closed until an explicit resync protocol is
    // implemented; callers receive the durable degraded health instead.
    if (this.options.store.clientObservationHealth(this.options.generation).status !== "healthy") {
      return undefined;
    }
    return new PrimeClientObservationMapper({
      sessionId: this.options.sessionId,
      generation: this.options.generation,
      activeSessionId,
      privateValues: values,
      initialNativeSequence: progress.nativeSequence,
      initialObservationSequence: progress.observationSequence,
      commit: async (nativeSequence, observation, stage) => {
        await this.options.store.recordClientObservationProgress(
          this.options.generation,
          nativeSequence,
          observation,
          stage ?? null,
        );
      },
      stage: async (stage) => {
        await this.options.store.stageClientObservationValue(stage);
      },
      now: this.now,
    });
  }

  private async cleanupStagedClientObservationValues(): Promise<void> {
    const stages = this.options.store.stagedClientObservationValues(
      this.options.generation,
    );
    if (stages.length === 0) return;
    const values = this.options.clientObservationValues;
    if (values === undefined) throw new PrimeGatewayError();
    try {
      for (const stage of stages) {
        await values.deleteClientValue(stage.reference, this.options.sessionId);
      }
    } catch {
      throw new PrimeGatewayError();
    }
  }

  private async restoreClientObservationPrefix(): Promise<void> {
    if (this.clientObservations.length === 0) {
      return;
    }
    const values = this.options.clientObservationValues;
    if (values === undefined) {
      throw new PrimeGatewayError();
    }
    try {
      for (const observation of this.clientObservations) {
        const payload = observation.payload;
        const verify = async (
          reference: unknown,
          kind: string,
          mediaType: string,
          digest?: unknown,
          size?: unknown,
        ): Promise<void> => {
          if (typeof reference !== "string") {
            throw new PrimeGatewayError();
          }
          const descriptor = await values.describeClientValue(
            reference,
            this.options.sessionId,
          );
          if (
            descriptor.kind !== kind ||
            descriptor.mediaType !== mediaType ||
            (digest !== undefined && descriptor.sha256 !== digest) ||
            (size !== undefined && descriptor.size !== size)
          ) {
            throw new PrimeGatewayError();
          }
        };
        if (observation.kind === "message.available") {
          await verify(payload.content_ref, "message", String(payload.media_type), payload.sha256, payload.size);
        } else if (observation.kind === "tool.started") {
          await verify(payload.arguments_ref, "tool-arguments", "application/json", payload.sha256, payload.size);
        } else if (observation.kind === "tool.completed") {
          await verify(payload.result_ref, "tool-result", String(payload.media_type), payload.sha256, payload.size);
        } else if (observation.kind === "artifact.available") {
          await verify(payload.artifact_ref, "artifact", String(payload.media_type), payload.sha256, payload.size);
        } else if (observation.kind === "extension-ui.requested") {
          await verify(payload.payload_ref, "extension-ui", "application/json");
        }
      }
    } catch {
      throw new PrimeGatewayError();
    }
  }

  private async restoreExistingSession(): Promise<void> {
    if (this.sessionStatus === undefined || this.sessionStatus === "terminal") {
      return;
    }
    let identity = this.options.store.snapshot().primeIdentity;
    let contextBinding = this.options.store.activeContextBinding();
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
      const preparedOperations = this.options.store.preparedContextOperations();
      if (preparedOperations.length > 1) {
        throw new PrimeGatewayError();
      }
      const preparedResume = preparedOperations[0]?.command.operation ===
          "session.continuation.resume"
        ? preparedOperations[0]
        : undefined;
      const preparedActiveMutation = preparedOperations[0] !== undefined &&
          (preparedOperations[0].command.operation === "session.tree.navigate" ||
            preparedOperations[0].command.operation === "session.fork" ||
            preparedOperations[0].command.operation === "session.clone") &&
          this.sameContextBinding(
            contextBinding,
            preparedOperations[0].binding,
          )
        ? preparedOperations[0]
        : undefined;
      let locator: PrivateContinuationLocator;
      try {
        const pinned = await this.ensurePinnedContinuationBinding(contextBinding);
        contextBinding = pinned.binding;
        locator = pinned.locator;
      } catch {
        if (preparedResume === undefined && preparedActiveMutation === undefined) {
          throw new PrimeGatewayError();
        }
        const mutableSource = await this.options.privateValues
          .readPreparedContinuationLocator(contextBinding, false);
        if (preparedActiveMutation !== undefined) {
          locator = mutableSource;
        } else {
          const replacement = await this.options.privateValues
            .putContinuationLocator(mutableSource);
          await this.enqueueDurable(
            () => this.options.store.rebindContextBinding(replacement),
          );
          contextBinding = replacement;
          locator = await this.options.privateValues.readContinuationLocator(
            contextBinding,
          );
        }
      }
      if (
        locator.continuationId !== contextBinding.continuationId ||
        locator.supervisorGeneration !== identity.supervisorGeneration
      ) {
        throw new PrimeGatewayError();
      }
      if (
        locator.activeSessionId !== identity.activeSessionId ||
        locator.transcriptSessionId !== identity.transcriptSessionId
      ) {
        identity = Object.freeze({
          activeSessionId: locator.activeSessionId,
          transcriptSessionId: locator.transcriptSessionId,
          supervisorGeneration: locator.supervisorGeneration,
        });
        await this.enqueueDurable(
          () => this.options.store.bindPrimeIdentity(identity!),
        );
      }
      const restoredIdentity = identity;
      let pendingResume: Readonly<{
        commandId: string;
        target: PrimeContinuationLocator;
      }> | undefined;
      let pendingForkClone: Readonly<{
        commandId: string;
        operation: "session.fork" | "session.clone";
        selectedEntryId: string;
        position: "at" | "before";
      }> | undefined;
      if (preparedResume !== undefined) {
        const target = await this.options.privateValues
          .readPreparedContinuationLocator(preparedResume.binding, false);
        const preparedTargetId = (preparedResume.command.payload as {
          readonly continuation_id: string;
        }).continuation_id;
        if (
          target.activeSessionId !== restoredIdentity.activeSessionId ||
          target.supervisorGeneration !== restoredIdentity.supervisorGeneration ||
          target.continuationId !== preparedTargetId
        ) {
          throw new PrimeGatewayError();
        }
        pendingResume = Object.freeze({
          commandId: preparedResume.command.command_id,
          target,
        });
      }
      if (
        preparedActiveMutation !== undefined &&
        (preparedActiveMutation.command.operation === "session.fork" ||
          preparedActiveMutation.command.operation === "session.clone")
      ) {
        if (preparedActiveMutation.selectedEntryId === null) {
          throw new PrimeGatewayError();
        }
        pendingForkClone = Object.freeze({
          commandId: preparedActiveMutation.command.command_id,
          operation: preparedActiveMutation.command.operation,
          selectedEntryId: preparedActiveMutation.selectedEntryId,
          position: preparedActiveMutation.command.operation === "session.fork"
            ? preparedActiveMutation.command.payload.position
            : "at",
        });
      }
      const sourceIdentity = Object.freeze({
        ...restoredIdentity,
        continuationId: locator.continuationId,
        sessionPath: locator.sessionPath,
      });
      const expectedIdentity = pendingResume?.target ?? sourceIdentity;
      const session = await this.options.restoreSession(Object.freeze({
        ...restoredIdentity,
        continuationId: locator.continuationId,
        sessionPath: locator.sessionPath,
        ...(pendingResume === undefined ? {} : { pendingResume }),
        ...(pendingForkClone === undefined ? {} : { pendingForkClone }),
      }), async (recovery) => {
        if (
          recovered !== undefined ||
          this.sessionStatus !== "recovery_required" ||
          !this.validRecovery(recovery) ||
          (pendingForkClone === undefined &&
            recovery.transcriptSessionId !== expectedIdentity.transcriptSessionId)
        ) {
          throw new PrimeGatewayError();
        }
        recovered = recovery;
      });
      if (
        recovered === undefined ||
        session.activeSessionId !== expectedIdentity.activeSessionId ||
        (pendingForkClone === undefined &&
          (session.transcriptSessionId !== expectedIdentity.transcriptSessionId ||
            session.continuationId !== expectedIdentity.continuationId)) ||
        (pendingForkClone !== undefined &&
          (session.transcriptSessionId !== recovered.transcriptSessionId ||
            session.transcriptSessionId === sourceIdentity.transcriptSessionId ||
            session.continuationId === sourceIdentity.continuationId)) ||
        typeof session.adoptRecovery !== "function" ||
        typeof session.subscribe !== "function"
      ) {
        throw new PrimeGatewayError();
      }
      session.adoptRecovery(recovered);
      if (session.supervisorGeneration !== recovered.supervisorGeneration) {
        throw new PrimeGatewayError();
      }
      if (
        pendingResume === undefined &&
        pendingForkClone === undefined &&
        preparedActiveMutation === undefined
      ) {
        await this.refreshContextBinding(
          session,
          recovered.supervisorGeneration,
        );
        await this.enqueueDurable(() => this.options.store.bindPrimeIdentity({
          activeSessionId: restoredIdentity.activeSessionId,
          transcriptSessionId: restoredIdentity.transcriptSessionId,
          supervisorGeneration: recovered!.supervisorGeneration,
        }));
      }
      await this.enqueueDurable(
        () => this.options.store.recordPrimeCursor(recovered!.primeCursor),
      );
      this.session = session;
      await this.recoverPreparedContextOperations();
      this.mapper = this.recoveredMapper(recovered.primeCursor);
      this.clientObservationMapper = this.newClientObservationMapper(
        session.activeSessionId,
      );
      const restoredStatus = previousStatus === "paused"
        ? "paused"
        : recovered.sessionStatus;
      restoredEvent = this.reasonEvent(
        restoredStatus === "running" ? "session.running" : "session.paused",
        "prime-gateway-restored",
      );
      await this.append(restoredEvent);
      this.mapper.noteExternalSessionStatus(restoredStatus);
      this.subscribeToSession(session);
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

  private async recoverPreparedContextOperations(): Promise<void> {
    const prepared = this.options.store.preparedContextOperations();
    if (prepared.length > 1) {
      throw new PrimeGatewayError();
    }
    for (const { command } of prepared) {
      const receipt = await this.persistAndExecuteSessionContext(
        command,
        this.nativeContextExecutor(),
        async () => undefined,
      );
      this.contextExecutions.set(command.command_id, {
        digest: sha256Hex(canonicalJsonBytes(command)),
        command,
        promise: Promise.resolve(receipt),
        settled: true,
      });
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
    if (resolution === "succeeded" && action.kind === "checkpoint.create") {
      this.scheduleCheckpoint(action.targetId, action.deadlineMs);
    }
  }

  private scheduleCheckpoint(checkpointId: string, deadlineMs: number): void {
    if (this.checkpoints.has(checkpointId) || this.checkpointTasks.has(checkpointId)) {
      return;
    }
    privateDiagnosticCheckpointStage("scheduled");
    const task = new Promise<void>((resolve) => setTimeout(resolve, 0))
      .then(() => {
        privateDiagnosticCheckpointStage("started");
        return this.checkpoint(checkpointId, deadlineMs);
      })
      .catch(async () => {
        privateDiagnosticCheckpointStage("failed");
        await this.append(this.event("fault.raised", {
          code: "prime-checkpoint-failed",
          recoverable: true,
          evidence_ref: null,
        }));
      })
      .finally(() => {
        this.checkpointTasks.delete(checkpointId);
      });
    this.checkpointTasks.set(checkpointId, task);
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

  private subscribeToSession(session: PrimeGatewaySession): void {
    this.unsubscribe?.();
    const epoch = this.transportEpoch + 1;
    this.transportEpoch = epoch;
    this.unsubscribe = session.subscribe((outbound) => this.enqueue(outbound, epoch));
  }

  private enqueue(outbound: PrimeDaemonOutbound, epoch = this.transportEpoch): void {
    if (this.cancellationInProgress) {
      return;
    }
    this.eventQueue = this.eventQueue
      .then(() => epoch === this.transportEpoch
        ? this.handlePrimeOutbound(outbound)
        : undefined)
      .catch((error: unknown) => this.raiseMappingFault(error));
  }

  private async handlePrimeOutbound(outbound: PrimeDaemonOutbound): Promise<void> {
    if (this.mapper === undefined || this.terminal) {
      return;
    }
    let observations: readonly PrimeClientObservation[] = [];
    if (this.clientObservationMapper !== undefined) {
      try {
        observations = await this.clientObservationMapper.map(outbound);
        this.clientObservationHealthValue = this.clientObservationMapper.health;
        await this.enqueueDurable(() => this.options.store.recordClientObservationHealth(
          this.options.generation, this.clientObservationHealthValue,
        ));
      } catch (error) {
        // Client observations are an optional, private projection. A malformed
        // projection must not fence the canonical control event stream.
        this.clientObservationHealthValue = this.clientObservationMapper.health;
        await this.enqueueDurable(() => this.options.store.recordClientObservationHealth(
          this.options.generation, this.clientObservationHealthValue,
        ));
        this.clientObservationMapper = undefined;
        if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
          const category = error instanceof PrimeClientObservationError
            ? error.kind
            : "gateway";
          process.stderr.write(`asterion-prime-client-observation-disabled:${category}\n`);
        }
      }
    }
    for (const observation of observations) {
      if (observation.source_sequence !== this.clientObservations.length + 1) {
        throw new PrimeGatewayError();
      }
      this.clientObservations.push(observation);
    }
    const events = this.mapper.map(outbound);
    await Promise.all(events.map((event) => this.append(event)));
    if (this.mapper.primeCursor !== undefined) {
      await this.enqueueDurable(
        () => this.options.store.recordPrimeCursor(this.mapper!.primeCursor!),
      );
    }
  }

  private async raiseMappingFault(error: unknown): Promise<void> {
    if (this.terminal || this.closed || this.sessionStatus === "recovery_required") {
      return;
    }
    if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
      const category = error instanceof PrimeEventMappingError
        ? `mapping-${error.kind}`
        : error instanceof PrimeClientObservationError
        ? `client-observation-${error.kind}`
        : "gateway";
      process.stderr.write(`asterion-prime-event-processing:${category}\n`);
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

  private durableSessionStatus(): GatewaySessionStatus | undefined {
    let status: GatewaySessionStatus | undefined;
    for (const { event } of this.options.store.eventsAfter(0)) {
      if (event.generation !== this.options.generation) {
        continue;
      }
      if (event.type === "session.created") {
        status ??= "created";
      } else if (event.type === "session.running") {
        status = "running";
      } else if (event.type === "session.paused") {
        status = "paused";
      } else if (event.type === "session.recovery-required") {
        status = "recovery_required";
      } else if ([
        "session.budget-limited",
        "session.cancelled",
        "session.completed",
        "session.failed",
      ].includes(event.type)) {
        status = "terminal";
      }
    }
    return status;
  }

  private updateSessionStatus(event: ControlEvent): void {
    if (event.type === "session.created") {
      // Native subscription delivery can repeat its creation observation
      // after the durable running prefix is established. A repeated creation
      // must never regress the canonical session state.
      this.sessionStatus ??= "created";
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

function privateDiagnosticGatewayCancelStage(
  stage: "native-returned" | "goal-updated" | "terminal-appended",
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
    process.stderr.write(`asterion-prime-gateway-cancel-stage:${stage}\n`);
  }
}

function privateDiagnosticActionProposal(
  stage: "closed" | "identity" | "session" | "reservation" | "duplicate" | "append",
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
    process.stderr.write(`asterion-prime-action-proposal:${stage}\n`);
  }
}

function privateDiagnosticCheckpointStage(
  stage: "scheduled" | "started" | "failed",
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
    process.stderr.write(`asterion-prime-gateway-checkpoint-stage:${stage}\n`);
  }
}

function privateDiagnosticCheckpointRecovery(
  stage: "duplicate" | "state" | "invalid" | "status" | "validated" | "identity" | "adopt" | "adopted" | "context" | "context-failed" | "cursor" | "event" | "complete",
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
    process.stderr.write(`asterion-prime-gateway-checkpoint-recovery:${stage}\n`);
  }
}

function privateDiagnosticContextRefresh(
  stage: "current" | "locator" | "identity" | "unchanged" | "write" | "rebound",
): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS === "1") {
    process.stderr.write(`asterion-prime-context-refresh:${stage}\n`);
  }
}
