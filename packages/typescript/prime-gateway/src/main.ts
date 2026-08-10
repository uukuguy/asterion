import { constants, readFileSync } from "node:fs";
import {
  open,
  rename,
  rm,
  unlink,
} from "node:fs/promises";
import { randomUUID } from "node:crypto";
import process from "node:process";
import { join } from "node:path";
import readline from "node:readline/promises";
import { pathToFileURL } from "node:url";

import {
  validateControlCommand,
  validateControlEvent,
} from "@dci/agent-runtime";
import type {
  ControlCommand,
  ControlEvent,
} from "@dci/agent-runtime";

import {
  loadPrimeArtifactLock,
  verifyPrimeArtifact,
} from "./artifact-lock.js";
import {
  PrimeCheckpointManager,
  recoveryFromAttach,
} from "./checkpoint.js";
import {
  PrimeDaemonClient,
} from "./daemon-client.js";
import {
  canonicalJsonBytes,
  ensurePrivateDirectory,
  GatewayDurableStore,
  syncPrivateDirectory,
} from "./durable-store.js";
import {
  PrimeGateway,
  PrimeGatewayError,
} from "./gateway.js";
import type {
  PrimeGatewayPrivateInputs,
} from "./gateway.js";
import {
  PrimeSession,
} from "./prime-session.js";
import {
  PrivateValueStore,
} from "./private-store.js";
import type {
  PrivateResultProjection,
} from "./private-store.js";
import {
  AsterionSkillBridge,
  generateSkillBridgeToken,
} from "./skill-bridge.js";
import type {
  SkillApplicationTarget,
  SkillBudget,
} from "./skill-bridge.js";

export const PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1";
export const PRIME_GATEWAY_SKILL_DISCOVERY = "asterion.skill-control-discovery/v1";
export const PRIME_GATEWAY_SKILL_DISCOVERY_FILE = "asterion-control.json";

type SidecarEnvelopeType =
  | "authority.update"
  | "command.accept"
  | "events.stream"
  | "private.read";

export interface PrimeGatewaySidecarOptions {
  readonly currentGeneration: number;
  readonly gateway: {
    accept(command: ControlCommand): Promise<void>;
    updateRemainingBudget(budget: SkillBudget): void;
    eventsAfterCursor(cursor: { readonly generation: number; readonly sequence: number }): readonly ControlEvent[];
    close(): Promise<void>;
  };
  readonly privateValues: Pick<
    PrivateValueStore,
    | "bindInputReference"
    | "bindResultReference"
    | "readInput"
    | "readBoundInputReference"
    | "readBoundResultReference"
  >;
}

interface PrimeSidecarDescriptor {
  readonly agentDir: string;
  readonly artifactLockPath: string;
  readonly authorityId: string;
  readonly authorityRevision: number;
  readonly expectedRuntimeBuildId: string;
  readonly gatewayRoot: string;
  readonly generation: number;
  readonly maxContinuations: number;
  readonly maxControllerTokens: number;
  readonly maxTurns: number;
  readonly model: string;
  readonly portfolio: readonly SkillApplicationTarget[];
  readonly primeSocketPath: string;
  readonly primeSourceRoot: string;
  readonly provider: string;
  readonly remainingBudget: SkillBudget;
  readonly sessionDir: string;
  readonly sessionId: string;
  readonly skillPath: string;
  readonly timeoutMs: number;
  readonly workspace: string;
}

interface SidecarEnvelope {
  readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
  readonly id: string;
  readonly type: SidecarEnvelopeType;
  readonly command?: unknown;
  readonly private?: unknown;
  readonly cursor?: unknown;
  readonly reference?: unknown;
  readonly budget?: unknown;
}

type SidecarResponse =
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "authority.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "command.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "events.batch";
    readonly events: readonly ControlEvent[];
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "private.value";
    readonly text: string;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "error";
    readonly code: "prime-gateway-sidecar-failed";
  };

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MAX_PRIVATE_TEXT_BYTES = 1024 * 1024;
const IDENTIFIER_PATTERN = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/u;
const VERSION_PATTERN = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/u;
const TOKEN_PATTERN = /^[0-9a-f]{64}$/u;
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
const BUDGET_KEYS = Object.freeze([
  "aggregate_tokens",
  "application_tokens",
  "child_tokens",
  "controller_tokens",
  "cost_micros",
  "deadline_ms",
]);

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

function validPrivateText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    Buffer.byteLength(value, "utf8") <= MAX_PRIVATE_TEXT_BYTES
  );
}

function validText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function validateBudget(value: unknown, allowZeroDeadline = false): SkillBudget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, BUDGET_KEYS) ||
    !nonNegativeInteger(value.aggregate_tokens) ||
    !nonNegativeInteger(value.application_tokens) ||
    !nonNegativeInteger(value.child_tokens) ||
    !nonNegativeInteger(value.controller_tokens) ||
    !nonNegativeInteger(value.cost_micros) ||
    !(
      allowZeroDeadline
        ? nonNegativeInteger(value.deadline_ms)
        : positiveInteger(value.deadline_ms)
    )
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    aggregate_tokens: value.aggregate_tokens,
    application_tokens: value.application_tokens,
    child_tokens: value.child_tokens,
    controller_tokens: value.controller_tokens,
    cost_micros: value.cost_micros,
    deadline_ms: Number(value.deadline_ms),
  });
}

function validateTarget(value: unknown): SkillApplicationTarget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "application_id",
      "kind",
      "provider_id",
      "runtime_id",
      "version",
    ]) ||
    value.kind !== "application" ||
    typeof value.application_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.application_id) ||
    typeof value.provider_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.provider_id) ||
    typeof value.runtime_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.runtime_id) ||
    typeof value.version !== "string" ||
    !VERSION_PATTERN.test(value.version)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    application_id: value.application_id,
    kind: "application",
    provider_id: value.provider_id,
    runtime_id: value.runtime_id,
    version: value.version,
  });
}

function validatePortfolio(value: unknown): readonly SkillApplicationTarget[] {
  if (!Array.isArray(value)) {
    throw new PrimeGatewayError();
  }
  const targets = value.map(validateTarget);
  if (targets.length === 0) {
    throw new PrimeGatewayError();
  }
  let previousKey: string | undefined;
  for (const target of targets) {
    const key = [
      target.kind,
      target.provider_id,
      target.application_id,
      target.version,
      target.runtime_id,
    ].join("\u0000");
    if (previousKey !== undefined && previousKey >= key) {
      throw new PrimeGatewayError();
    }
    previousKey = key;
  }
  return Object.freeze(targets);
}

function validateDescriptor(value: unknown): PrimeSidecarDescriptor {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "agentDir",
      "artifactLockPath",
      "authorityId",
      "authorityRevision",
      "expectedRuntimeBuildId",
      "gatewayRoot",
      "generation",
      "maxContinuations",
      "maxControllerTokens",
      "maxTurns",
      "model",
      "portfolio",
      "primeSocketPath",
      "primeSourceRoot",
      "provider",
      "remainingBudget",
      "sessionDir",
      "sessionId",
      "skillPath",
      "timeoutMs",
      "workspace",
    ]) ||
    ![
      value.agentDir,
      value.artifactLockPath,
      value.authorityId,
      value.expectedRuntimeBuildId,
      value.gatewayRoot,
      value.model,
      value.primeSocketPath,
      value.primeSourceRoot,
      value.provider,
      value.sessionDir,
      value.sessionId,
      value.skillPath,
      value.workspace,
    ].every(validText) ||
    !positiveInteger(value.generation) ||
    !positiveInteger(value.authorityRevision) ||
    !positiveInteger(value.maxContinuations) ||
    !positiveInteger(value.maxControllerTokens) ||
    !positiveInteger(value.maxTurns) ||
    !positiveInteger(value.timeoutMs)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    ...(value as unknown as PrimeSidecarDescriptor),
    authorityRevision: Number(value.authorityRevision),
    generation: Number(value.generation),
    maxContinuations: Number(value.maxContinuations),
    maxControllerTokens: Number(value.maxControllerTokens),
    maxTurns: Number(value.maxTurns),
    portfolio: validatePortfolio(value.portfolio),
    remainingBudget: validateBudget(value.remainingBudget),
    timeoutMs: Number(value.timeoutMs),
  });
}

function validateEnvelope(value: unknown): SidecarEnvelope {
  if (
    !isRecord(value) ||
    value.protocol !== PRIME_GATEWAY_IPC_PROTOCOL ||
    typeof value.id !== "string" ||
    !REQUEST_ID.test(value.id) ||
    (
      value.type !== "command.accept" &&
      value.type !== "events.stream" &&
      value.type !== "private.read" &&
      value.type !== "authority.update"
    )
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "authority.update" &&
    !hasExactKeys(value, ["protocol", "id", "type", "budget"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "command.accept" &&
    !hasExactKeys(value, ["protocol", "id", "type", "command", "private"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "events.stream" &&
    !hasExactKeys(value, ["protocol", "id", "type", "cursor"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "private.read" &&
    !hasExactKeys(value, ["protocol", "id", "type", "reference"])
  ) {
    throw new PrimeGatewayError();
  }
  return value as unknown as SidecarEnvelope;
}

function sortedUniqueStrings(
  value: unknown,
  pattern: RegExp,
): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || !pattern.test(item)) ||
    value.some((item, index) => index > 0 && String(value[index - 1]) >= item)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze([...(value as string[])]);
}

function validateResultProjection(
  value: unknown,
  sourceReceiptRef: string,
): PrivateResultProjection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["artifact_ids", "media_types", "receipt_ref"]) ||
    value.receipt_ref !== sourceReceiptRef
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    receiptRef: sourceReceiptRef,
    artifactIds: sortedUniqueStrings(value.artifact_ids, REQUEST_ID),
    mediaTypes: sortedUniqueStrings(value.media_types, MEDIA_TYPE_PATTERN),
  });
}

function validateCursor(value: unknown): Readonly<{ generation: number; sequence: number }> | null {
  if (value === null) {
    return null;
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["generation", "sequence"]) ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 1 ||
    !Number.isSafeInteger(value.sequence) ||
    Number(value.sequence) < 0
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    generation: Number(value.generation),
    sequence: Number(value.sequence),
  });
}

export class PrimeGatewaySidecar {
  constructor(private readonly options: PrimeGatewaySidecarOptions) {}

  async handleEnvelope(value: unknown): Promise<SidecarResponse> {
    let envelope: SidecarEnvelope;
    try {
      envelope = validateEnvelope(value);
      if (envelope.type === "authority.update") {
        this.options.gateway.updateRemainingBudget(
          validateBudget(envelope.budget, true),
        );
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "authority.accepted",
        });
      }
      if (envelope.type === "command.accept") {
        await this.accept(envelope);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "command.accepted",
        });
      }
      if (envelope.type === "private.read") {
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "private.value",
          text: await this.readPrivate(envelope),
        });
      }
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: envelope.id,
        type: "events.batch",
        events: this.events(envelope),
      });
    } catch {
      const id = isRecord(value) && typeof value.id === "string" && REQUEST_ID.test(value.id)
        ? value.id
        : "request-invalid";
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id,
        type: "error",
        code: "prime-gateway-sidecar-failed",
      });
    }
  }

  async close(): Promise<void> {
    await this.options.gateway.close();
  }

  private async accept(envelope: SidecarEnvelope): Promise<void> {
    let command = validateControlCommand(envelope.command);
    const privateValues = envelope.private;
    if (!isRecord(privateValues)) {
      throw new PrimeGatewayError();
    }
    if (command.type === "session.create") {
      if (!hasExactKeys(privateValues, ["goal"]) || !validPrivateText(privateValues.goal)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.goal_ref,
        privateValues.goal,
      );
    } else if (command.type === "input.submit") {
      if (!hasExactKeys(privateValues, ["content"]) || !validPrivateText(privateValues.content)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.content_ref,
        privateValues.content,
      );
    } else if (
      command.type === "action.resolve" &&
      command.payload.resolution === "succeeded"
    ) {
      if (!hasExactKeys(privateValues, ["result"])) {
        throw new PrimeGatewayError();
      }
      const sourceReceiptRef = command.payload.receipt_ref;
      const actionId = command.payload.action_id;
      if (
        typeof sourceReceiptRef !== "string" ||
        !REQUEST_ID.test(sourceReceiptRef) ||
        typeof actionId !== "string" ||
        !REQUEST_ID.test(actionId)
      ) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindResultReference(
        command.command_id,
        actionId,
        sourceReceiptRef,
        validateResultProjection(privateValues.result, sourceReceiptRef),
      );
    } else if (!hasExactKeys(privateValues, [])) {
      throw new PrimeGatewayError();
    }
    await this.options.gateway.accept(command);
  }

  private events(envelope: SidecarEnvelope): readonly ControlEvent[] {
    const cursor = validateCursor(envelope.cursor);
    const replayCursor = cursor ?? {
      generation: this.options.currentGeneration,
      sequence: 0,
    };
    const events = this.options.gateway.eventsAfterCursor(
      replayCursor,
    ).map((event) => {
      const validated = validateControlEvent(event);
      if (validated.generation !== replayCursor.generation) {
        throw new PrimeGatewayError();
      }
      return validated;
    });
    return Object.freeze(events);
  }

  private async readPrivate(envelope: SidecarEnvelope): Promise<string> {
    const reference = envelope.reference;
    if (
      typeof reference !== "string" ||
      !/^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u
        .test(reference)
    ) {
      throw new PrimeGatewayError();
    }
    return this.options.privateValues.readInput(reference as `private:${string}`);
  }
}

export class PrimeBoundPrivateInputs implements PrimeGatewayPrivateInputs {
  constructor(private readonly privateValues: PrivateValueStore) {}

  async readInput(reference: string): Promise<string> {
    return this.privateValues.readBoundInputReference(reference);
  }
}

function encodeResponse(value: SidecarResponse): string {
  return `${JSON.stringify(value)}\n`;
}

function readPrivateDescriptor(): PrimeSidecarDescriptor {
  const fd = Number(process.env.ASTERION_PRIME_PRIVATE_FD);
  if (!Number.isSafeInteger(fd) || fd < 3) {
    throw new PrimeGatewayError();
  }
  try {
    return validateDescriptor(JSON.parse(readFileSync(fd, { encoding: "utf8" })));
  } catch {
    throw new PrimeGatewayError();
  }
}

async function writeSkillDiscovery(
  descriptor: PrimeSidecarDescriptor,
  bridge: AsterionSkillBridge,
  token: string,
): Promise<void> {
  if (!TOKEN_PATTERN.test(token)) {
    throw new PrimeGatewayError();
  }
  await ensurePrivateDirectory(descriptor.agentDir);
  const record = {
    protocol: PRIME_GATEWAY_SKILL_DISCOVERY,
    socket_path: bridge.socketPath,
    token,
    session_id: descriptor.sessionId,
  };
  await atomicReplacePrivateFile(
    descriptor.agentDir,
    PRIME_GATEWAY_SKILL_DISCOVERY_FILE,
    Buffer.concat([canonicalJsonBytes(record), Buffer.from("\n")]),
  );
}

async function atomicReplacePrivateFile(
  directory: string,
  targetName: string,
  bytes: Uint8Array,
): Promise<void> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(targetName)) {
    throw new PrimeGatewayError();
  }
  const temporary = join(directory, `.asterion-${randomUUID()}.tmp`);
  const descriptor = await open(
    temporary,
    constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW,
    0o600,
  );
  let closed = false;
  let renamed = false;
  try {
    await descriptor.chmod(0o600);
    await descriptor.writeFile(bytes);
    await descriptor.datasync();
    await descriptor.close();
    closed = true;
    await rename(temporary, join(directory, targetName));
    renamed = true;
    await syncPrivateDirectory(directory);
  } finally {
    if (!closed) {
      await descriptor.close().catch(() => undefined);
    }
    if (!renamed) {
      await unlink(temporary).catch(() => undefined);
    }
  }
}

async function removeSkillDiscovery(descriptor: PrimeSidecarDescriptor): Promise<void> {
  await unlink(join(descriptor.agentDir, PRIME_GATEWAY_SKILL_DISCOVERY_FILE))
    .catch(() => undefined);
  await syncPrivateDirectory(descriptor.agentDir).catch(() => undefined);
}

function restoredBridgeContext(
  store: GatewayDurableStore,
  generation: number,
  descriptor: PrimeSidecarDescriptor,
): Readonly<{
  goalId: string;
  authorityRevision: number;
  causalParentIds: readonly string[];
}> | undefined {
  let created:
    | Extract<ControlEvent, { readonly type: "session.created" }>
    | undefined;
  let terminal = false;
  for (const receipt of store.eventsAfter(0)) {
    const event = receipt.event;
    if (event.generation !== generation) {
      continue;
    }
    if (event.type === "session.created") {
      created = event;
    }
    if ([
      "session.budget-limited",
      "session.cancelled",
      "session.completed",
      "session.failed",
    ].includes(event.type)) {
      terminal = true;
    }
  }
  if (created === undefined || terminal || store.snapshot().primeIdentity === undefined) {
    return undefined;
  }
  if (
    created.payload.authority_id !== descriptor.authorityId ||
    created.payload.authority_revision !== descriptor.authorityRevision
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    goalId: created.payload.goal_id,
    authorityRevision: created.payload.authority_revision,
    causalParentIds: Object.freeze([created.payload.goal_id]),
  });
}

async function createSidecarFromDescriptor(
  descriptor: PrimeSidecarDescriptor,
): Promise<PrimeGatewaySidecar> {
  const transport = new PrimeDaemonClient({
    clientId: `asterion-${descriptor.sessionId}`,
    connectTimeoutMs: descriptor.timeoutMs,
    requestTimeoutMs: descriptor.timeoutMs,
  });
  await transport.connect(descriptor.primeSocketPath);
  const store = await GatewayDurableStore.open(
    descriptor.gatewayRoot,
    descriptor.sessionId,
  );
  store.registerEventGeneration(descriptor.generation);
  const privateValues = await PrivateValueStore.open(descriptor.gatewayRoot);
  const boundPrivateInputs = new PrimeBoundPrivateInputs(privateValues);
  const lock = await loadPrimeArtifactLock(pathToFileURL(descriptor.artifactLockPath));
  const artifactEvidence = await verifyPrimeArtifact(descriptor.primeSourceRoot, lock);
  let checkpointManager: PrimeCheckpointManager | undefined;
  let gateway: PrimeGateway;
  let skillBridge: AsterionSkillBridge | undefined;
  let skillBridgeRoot: string | undefined;
  let sessionReady: (() => void) | undefined;
  let currentRemainingBudget = descriptor.remainingBudget;

  const closeSkillBridge = async () => {
    const current = skillBridge;
    skillBridge = undefined;
    if (current !== undefined) {
      await current.close();
    }
    if (skillBridgeRoot !== undefined) {
      await rm(skillBridgeRoot, { force: true, recursive: true }).catch(() => undefined);
      skillBridgeRoot = undefined;
    }
    await removeSkillDiscovery(descriptor);
  };

  const startSkillBridge = async (
    context: Readonly<{
      goalId: string;
      authorityRevision: number;
      causalParentIds: readonly string[];
    }>,
    ready: Promise<void>,
  ) => {
    await closeSkillBridge();
    const token = generateSkillBridgeToken();
    skillBridgeRoot = join(
      descriptor.agentDir,
      `b${process.pid}-${randomUUID().slice(0, 8)}`,
    );
    skillBridge = await AsterionSkillBridge.listen({
      root: skillBridgeRoot,
      sessionId: descriptor.sessionId,
      authorityRevision: context.authorityRevision,
      generation: descriptor.generation,
      goalId: context.goalId,
      causalParentIds: context.causalParentIds,
      token,
      portfolio: descriptor.portfolio,
      remainingBudget: currentRemainingBudget,
      privateValues,
      beforeEffect: () => ready,
      nextEventIdentity: () => gateway.nextEventIdentity(),
      emitActionProposal: async (event) => {
        await ready;
        await gateway.emitActionProposal(event);
      },
      waitForAdmission: (actionId) => gateway.waitForAdmission(actionId),
      waitForTerminal: (actionId) => gateway.waitForTerminal(actionId),
      actionStatus: (actionId) => gateway.actionStatus(actionId),
    });
    await writeSkillDiscovery(descriptor, skillBridge, token);
  };

  gateway = await PrimeGateway.open({
    sessionId: descriptor.sessionId,
    generation: descriptor.generation,
    authorityId: descriptor.authorityId,
    store,
    privateValues: boundPrivateInputs,
    privateResults: privateValues,
    async createSession(goal, bindIdentity, context) {
      const ready = new Promise<void>((resolve) => {
        sessionReady = resolve;
      });
      await startSkillBridge(context, ready);
      try {
        return await PrimeSession.create({
          transport,
          sessionId: descriptor.sessionId,
          privateConfig: {
            workspace: descriptor.workspace,
            agentDir: descriptor.agentDir,
            sessionDir: descriptor.sessionDir,
            provider: descriptor.provider,
            model: descriptor.model,
            skillPath: descriptor.skillPath,
            goal,
            maxContinuations: descriptor.maxContinuations,
            maxTurns: descriptor.maxTurns,
            maxControllerTokens: descriptor.maxControllerTokens,
            timeoutMs: descriptor.timeoutMs,
          },
          bindIdentity,
        });
      } catch (error) {
        sessionReady = undefined;
        await closeSkillBridge();
        throw error;
      }
    },
    restoreSession(identity, onRecovered) {
      const session = PrimeSession.restore({
        transport,
        sessionId: descriptor.sessionId,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
      });
      return (async () => {
        const cursor = store.snapshot().primeCursor;
        if (cursor === undefined) {
          throw new PrimeGatewayError();
        }
        const attachResponse = await session.attach("restore-attach", cursor);
        const recovery = recoveryFromAttach(
          attachResponse,
          identity.activeSessionId,
          identity.transcriptSessionId,
          cursor,
        );
        await onRecovered({
          transport,
          primeCursor: recovery.primeCursor,
          transcriptSessionId: identity.transcriptSessionId,
          supervisorGeneration: transport.hello?.supervisorGeneration ?? identity.supervisorGeneration,
          sessionStatus: recovery.sessionStatus,
        });
        return session;
      })();
    },
    async createCheckpoint(checkpointId, coveredSequence, onRecovered) {
      const identity = store.snapshot().primeIdentity;
      const cursor = store.snapshot().primeCursor;
      if (identity === undefined || cursor === undefined) {
        throw new PrimeGatewayError();
      }
      checkpointManager ??= await PrimeCheckpointManager.open({
        sessionId: descriptor.sessionId,
        asterionGeneration: descriptor.generation,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
        artifactEvidence,
        expectedRuntimeBuildId: descriptor.expectedRuntimeBuildId,
        privateValues,
        transport,
        runtime: {
          async stop() {
            transport.close();
          },
          async relaunch() {
            const relaunched = new PrimeDaemonClient({
              clientId: `asterion-${descriptor.sessionId}-checkpoint`,
              connectTimeoutMs: descriptor.timeoutMs,
              requestTimeoutMs: descriptor.timeoutMs,
            });
            await relaunched.connect(descriptor.primeSocketPath);
            return relaunched;
          },
        },
        primeCursor: cursor,
      });
      return checkpointManager.create(checkpointId, coveredSequence, onRecovered);
    },
    onSessionReady() {
      sessionReady?.();
      sessionReady = undefined;
    },
  });
  const recoveredContext = restoredBridgeContext(store, descriptor.generation, descriptor);
  if (recoveredContext !== undefined) {
    await startSkillBridge(recoveredContext, Promise.resolve());
  }

  return new PrimeGatewaySidecar({
    currentGeneration: descriptor.generation,
    privateValues,
    gateway: {
      accept: (command) => gateway.accept(command),
      updateRemainingBudget: (budget) => {
        currentRemainingBudget = budget;
        skillBridge?.updateRemainingBudget(budget);
      },
      eventsAfterCursor: (cursor) =>
        store.eventsAfterCursor(cursor).map((receipt) => receipt.event),
      close: async () => {
        let failed = false;
        try {
          await closeSkillBridge();
        } catch {
          failed = true;
        }
        try {
          await gateway.detach();
        } catch {
          failed = true;
        }
        try {
          await gateway.close();
        } catch {
          failed = true;
        }
        try {
          transport.close();
        } catch {
          failed = true;
        }
        if (failed) {
          throw new PrimeGatewayError();
        }
      },
    },
  });
}

async function run(): Promise<void> {
  const descriptor = readPrivateDescriptor();
  const sidecar = await createSidecarFromDescriptor(descriptor);
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });
  try {
    for await (const line of rl) {
      let parsed: unknown;
      try {
        parsed = JSON.parse(line);
      } catch {
        parsed = {};
      }
      process.stdout.write(encodeResponse(await sidecar.handleEnvelope(parsed)));
    }
  } finally {
    await sidecar.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run()
    .catch(() => {
      process.exitCode = 1;
    });
}
