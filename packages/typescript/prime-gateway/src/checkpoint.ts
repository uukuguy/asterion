import { isAbsolute, normalize } from "node:path";

import type { PrimeArtifactEvidence } from "./artifact-lock.js";
import type { PrimeDaemonDeferredResponse } from "./daemon-client.js";
import type {
  PrimeDaemonCursor,
  PrimeDaemonHello,
  PrimeDaemonResponse,
} from "./daemon-wire.js";
import { canonicalJsonBytes, sha256Hex } from "./durable-store.js";
import type { PrivateValueRef, PrivateValueStore } from "./private-store.js";
import type {
  PrimeDaemonTransport,
  PrimeSessionRecovery,
} from "./prime-session.js";

const CAPSULE_FORMAT = "asterion.prime-capsule/v1";
const CHECKPOINT_VERSION = "1.0.0";
const CONTROL_PLANE_ID = "prime.gateway";
const CONTROL_PLANE_VERSION = "0.1.0";
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
const MAX_MANIFEST_SESSIONS = 10_000;

export interface PrimeCapsuleV1 {
  readonly format: typeof CAPSULE_FORMAT;
  readonly artifactDigest: string;
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly primeCursor: PrimeDaemonCursor;
  readonly asterionGeneration: number;
  readonly asterionSequence: number;
  readonly updateManifest: unknown;
}

export interface PrimeCheckpointCreated {
  readonly checkpointId: string;
  readonly capsuleId: string;
  readonly capsuleDigest: string;
  readonly controlPlaneId: typeof CONTROL_PLANE_ID;
  readonly controlPlaneVersion: typeof CONTROL_PLANE_VERSION;
  readonly checkpointVersion: typeof CHECKPOINT_VERSION;
  readonly coveredSequence: number;
  readonly storageRef: PrivateValueRef;
  /** Private gateway state; omitted from the public checkpoint event. */
  readonly primeCursor: PrimeDaemonCursor;
  /** Private gateway state; omitted from the public checkpoint event. */
  readonly supervisorGeneration: string;
  /** Acknowledges Prime only after the caller commits the public checkpoint. */
  acknowledge(): boolean;
}

export type PrimeCheckpointRecovery = PrimeSessionRecovery;

export interface PrimeCheckpointRuntime {
  stop(): Promise<void>;
  relaunch(): Promise<PrimeDaemonTransport>;
}

export interface PrimeCheckpointManagerOptions {
  readonly sessionId: string;
  readonly asterionGeneration: number;
  readonly activeSessionId: string;
  readonly transcriptSessionId?: string;
  readonly artifactEvidence: PrimeArtifactEvidence;
  readonly expectedRuntimeBuildId: string;
  readonly privateValues: PrivateValueStore;
  readonly transport: PrimeDaemonTransport;
  readonly runtime: PrimeCheckpointRuntime;
  readonly primeCursor: PrimeDaemonCursor;
}

interface ManifestSession {
  readonly activeSessionId: string;
  readonly sessionId: string;
  readonly sessionFile: string;
  readonly runtimeMetadata?: Readonly<Record<string, unknown>>;
}

interface ValidatedManifest {
  readonly formatVersion: 1;
  readonly createdAt: string;
  readonly sessions: readonly ManifestSession[];
  readonly discardedActiveSessionIds: readonly string[];
  readonly value: Readonly<Record<string, unknown>>;
}

interface CheckpointExecution {
  readonly coveredSequence: number;
  readonly promise: Promise<PrimeCheckpointCreated>;
}

export class PrimeCheckpointError extends Error {
  constructor() {
    super("Prime checkpoint operation failed");
    this.name = "PrimeCheckpointError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length && actual.every((key, index) => key === wanted[index]);
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function validOpaqueId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID.test(value);
}

function validCursor(value: unknown): value is PrimeDaemonCursor {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["generation", "sequence"]) &&
    validOpaqueId(value.generation) &&
    nonNegativeInteger(value.sequence)
  );
}

function validateArtifactEvidence(value: unknown): PrimeArtifactEvidence {
  if (!isRecord(value)) {
    throw new PrimeCheckpointError();
  }
  const files = value.fileDigests;
  if (
    !hasExactKeys(value, [
      "commit",
      "packageName",
      "packageVersion",
      "protocolVersion",
      "schemaRevision",
      "schemaId",
      "fileDigests",
    ]) ||
    typeof value.commit !== "string" ||
    !/^[0-9a-f]{40}$/u.test(value.commit) ||
    typeof value.packageName !== "string" ||
    value.packageName.length === 0 ||
    typeof value.packageVersion !== "string" ||
    value.packageVersion.length === 0 ||
    !positiveInteger(value.protocolVersion) ||
    !positiveInteger(value.schemaRevision) ||
    typeof value.schemaId !== "string" ||
    value.schemaId.length === 0 ||
    !isRecord(files) ||
    Object.keys(files).length === 0 ||
    Object.entries(files).some(
      ([path, digest]) =>
        path.length === 0 ||
        typeof digest !== "string" ||
        !SHA256.test(digest),
    )
  ) {
    throw new PrimeCheckpointError();
  }
  return value as unknown as PrimeArtifactEvidence;
}

function validateHello(
  hello: PrimeDaemonHello | undefined,
  evidence: PrimeArtifactEvidence,
  expectedRuntimeBuildId: string,
): void {
  if (
    hello === undefined ||
    hello.protocolVersion !== evidence.protocolVersion ||
    hello.schemaRevision !== evidence.schemaRevision ||
    hello.schemaId !== evidence.schemaId ||
    hello.appVersion !== evidence.packageVersion ||
    hello.runtimeBuildId !== expectedRuntimeBuildId ||
    !validOpaqueId(hello.supervisorGeneration)
  ) {
    throw new PrimeCheckpointError();
  }
}

function validateManifest(
  value: unknown,
  activeSessionId: string,
  transcriptSessionId: string,
): ValidatedManifest {
  if (
    !isRecord(value) ||
    value.formatVersion !== 1 ||
    typeof value.createdAt !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/u.test(value.createdAt) ||
    new Date(value.createdAt).toISOString() !== value.createdAt ||
    !Array.isArray(value.sessions) ||
    value.sessions.length === 0 ||
    value.sessions.length > MAX_MANIFEST_SESSIONS ||
    (value.discardedActiveSessionIds !== undefined &&
      !Array.isArray(value.discardedActiveSessionIds))
  ) {
    throw new PrimeCheckpointError();
  }

  const sessions: ManifestSession[] = [];
  const activeIds = new Set<string>();
  const transcriptIds = new Set<string>();
  const sessionFiles = new Set<string>();
  const discarded: string[] = [];
  for (const discardedId of value.discardedActiveSessionIds ?? []) {
    if (!validOpaqueId(discardedId) || activeIds.has(discardedId)) {
      throw new PrimeCheckpointError();
    }
    activeIds.add(discardedId);
    discarded.push(discardedId);
  }
  for (const candidate of value.sessions) {
    if (
      !isRecord(candidate) ||
      !validOpaqueId(candidate.activeSessionId) ||
      !validOpaqueId(candidate.sessionId) ||
      typeof candidate.sessionFile !== "string" ||
      !isAbsolute(candidate.sessionFile) ||
      (candidate.runtimeMetadata !== undefined && !isRecord(candidate.runtimeMetadata)) ||
      activeIds.has(candidate.activeSessionId) ||
      transcriptIds.has(candidate.sessionId) ||
      sessionFiles.has(normalize(candidate.sessionFile))
    ) {
      throw new PrimeCheckpointError();
    }
    activeIds.add(candidate.activeSessionId);
    transcriptIds.add(candidate.sessionId);
    sessionFiles.add(normalize(candidate.sessionFile));
    sessions.push(Object.freeze({
      activeSessionId: candidate.activeSessionId,
      sessionId: candidate.sessionId,
      sessionFile: candidate.sessionFile,
      ...(candidate.runtimeMetadata === undefined
        ? {}
        : { runtimeMetadata: Object.freeze({ ...candidate.runtimeMetadata }) }),
    }));
  }

  const roots = sessions.filter((session) => session.activeSessionId === activeSessionId);
  if (
    roots.length !== 1 ||
    roots[0]?.sessionId !== transcriptSessionId ||
    discarded.includes(activeSessionId) ||
    (roots[0].runtimeMetadata !== undefined &&
      roots[0].runtimeMetadata.kind !== "top-level")
  ) {
    throw new PrimeCheckpointError();
  }

  const byActiveId = new Map(sessions.map((session) => [session.activeSessionId, session]));
  for (const session of sessions) {
    if (session.activeSessionId === activeSessionId) {
      continue;
    }
    if (
      session.runtimeMetadata?.kind !== "subagent" ||
      !validOpaqueId(session.runtimeMetadata.parentActiveSessionId)
    ) {
      throw new PrimeCheckpointError();
    }
    const seen = new Set<string>([session.activeSessionId]);
    let parentId = session.runtimeMetadata.parentActiveSessionId;
    while (parentId !== activeSessionId) {
      if (seen.has(parentId)) {
        throw new PrimeCheckpointError();
      }
      seen.add(parentId);
      const parent = byActiveId.get(parentId);
      if (
        parent?.runtimeMetadata?.kind !== "subagent" ||
        !validOpaqueId(parent.runtimeMetadata.parentActiveSessionId)
      ) {
        throw new PrimeCheckpointError();
      }
      parentId = parent.runtimeMetadata.parentActiveSessionId;
    }
  }

  let canonicalValue: Readonly<Record<string, unknown>>;
  try {
    canonicalValue = JSON.parse(canonicalJsonBytes(value).toString("utf8")) as Readonly<Record<string, unknown>>;
  } catch {
    throw new PrimeCheckpointError();
  }
  return Object.freeze({
    formatVersion: 1,
    createdAt: value.createdAt,
    sessions: Object.freeze(sessions),
    discardedActiveSessionIds: Object.freeze(discarded),
    value: canonicalValue,
  });
}

function requireSuccessful(
  response: PrimeDaemonResponse,
  command: string,
): PrimeDaemonResponse & { readonly success: true } {
  if (!response.success || response.command !== command) {
    throw new PrimeCheckpointError();
  }
  return response;
}

function recoveryFromAttach(
  response: PrimeDaemonResponse,
  activeSessionId: string,
  transcriptSessionId: string,
  fallback: PrimeDaemonCursor,
): Readonly<{
  primeCursor: PrimeDaemonCursor;
  sessionStatus: "running" | "paused";
}> {
  const successful = requireSuccessful(response, "attach");
  const data = successful.data;
  if (!isRecord(data) || data.activeSessionId !== activeSessionId) {
    throw new PrimeCheckpointError();
  }
  const replay = data.replay;
  const snapshot = data.snapshot;
  if (
    !isRecord(data.protocol) ||
    data.protocol.name !== "prime-agent.daemon" ||
    data.protocol.version !== 7 ||
    !isRecord(replay) ||
    (replay.status !== "complete" && replay.status !== "unavailable") ||
    !nonNegativeInteger(replay.toSequence) ||
    !isRecord(snapshot) ||
    snapshot.activeSessionId !== activeSessionId ||
    !nonNegativeInteger(snapshot.lastEventSequence) ||
    !nonNegativeInteger(data.lastEventSequence) ||
    snapshot.lastEventSequence !== data.lastEventSequence ||
    replay.toSequence !== data.lastEventSequence ||
    !isRecord(snapshot.summary) ||
    snapshot.summary.sessionId !== transcriptSessionId ||
    (snapshot.summary.activeSessionId !== undefined &&
      snapshot.summary.activeSessionId !== activeSessionId) ||
    !isRecord(snapshot.state) ||
    !isRecord(snapshot.state.goal) ||
    (snapshot.state.goal.status !== "active" &&
      snapshot.state.goal.status !== "paused")
  ) {
    throw new PrimeCheckpointError();
  }
  const selected = validCursor(data.lastEventCursor)
    ? data.lastEventCursor
    : validCursor(snapshot.lastEventCursor)
      ? snapshot.lastEventCursor
      : fallback;
  if (
    (validCursor(data.lastEventCursor) &&
      validCursor(snapshot.lastEventCursor) &&
      (data.lastEventCursor.generation !== snapshot.lastEventCursor.generation ||
        data.lastEventCursor.sequence !== snapshot.lastEventCursor.sequence)) ||
    selected.sequence !== data.lastEventSequence ||
    (replay.status === "unavailable" && !validCursor(snapshot.lastEventCursor))
  ) {
    throw new PrimeCheckpointError();
  }
  return Object.freeze({
    primeCursor: Object.freeze({
      generation: selected.generation,
      sequence: selected.sequence,
    }),
    sessionStatus: snapshot.state.goal.status === "active" ? "running" : "paused",
  });
}

function parseCapsule(
  bytes: Buffer,
  expectedDigest: string,
  artifactDigest: string,
  options: Pick<
    PrimeCheckpointManagerOptions,
    "activeSessionId" | "transcriptSessionId" | "asterionGeneration"
  >,
): PrimeCapsuleV1 {
  if (
    typeof expectedDigest !== "string" ||
    !SHA256.test(expectedDigest) ||
    sha256Hex(bytes) !== expectedDigest
  ) {
    throw new PrimeCheckpointError();
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new PrimeCheckpointError();
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "format",
      "artifactDigest",
      "activeSessionId",
      "transcriptSessionId",
      "primeCursor",
      "asterionGeneration",
      "asterionSequence",
      "updateManifest",
    ]) ||
    !canonicalJsonBytes(value).equals(bytes) ||
    value.format !== CAPSULE_FORMAT ||
    value.artifactDigest !== artifactDigest ||
    value.activeSessionId !== options.activeSessionId ||
    !validOpaqueId(value.transcriptSessionId) ||
    (options.transcriptSessionId !== undefined &&
      value.transcriptSessionId !== options.transcriptSessionId) ||
    value.asterionGeneration !== options.asterionGeneration ||
    !positiveInteger(value.asterionSequence) ||
    !validCursor(value.primeCursor)
  ) {
    throw new PrimeCheckpointError();
  }
  validateManifest(value.updateManifest, options.activeSessionId, value.transcriptSessionId);
  return Object.freeze({
    format: CAPSULE_FORMAT,
    artifactDigest,
    activeSessionId: options.activeSessionId,
    transcriptSessionId: value.transcriptSessionId,
    primeCursor: Object.freeze({
      generation: value.primeCursor.generation,
      sequence: value.primeCursor.sequence,
    }),
    asterionGeneration: options.asterionGeneration,
    asterionSequence: value.asterionSequence,
    updateManifest: value.updateManifest,
  });
}

export class PrimeCheckpointManager {
  private readonly executions = new Map<string, CheckpointExecution>();
  private readonly artifactEvidence: PrimeArtifactEvidence;
  private readonly artifactDigest: string;
  private transport: PrimeDaemonTransport;
  private primeCursor: PrimeDaemonCursor;
  private transcriptSessionId: string | undefined;

  private constructor(private readonly options: PrimeCheckpointManagerOptions) {
    this.artifactEvidence = validateArtifactEvidence(options.artifactEvidence);
    this.artifactDigest = sha256Hex(canonicalJsonBytes(this.artifactEvidence));
    this.transport = options.transport;
    this.primeCursor = Object.freeze({ ...options.primeCursor });
    this.transcriptSessionId = options.transcriptSessionId;
  }

  static async open(options: PrimeCheckpointManagerOptions): Promise<PrimeCheckpointManager> {
    try {
      if (
        !validOpaqueId(options.sessionId) ||
        !positiveInteger(options.asterionGeneration) ||
        !validOpaqueId(options.activeSessionId) ||
        (options.transcriptSessionId !== undefined &&
          !validOpaqueId(options.transcriptSessionId)) ||
        !validOpaqueId(options.expectedRuntimeBuildId) ||
        !validCursor(options.primeCursor) ||
        typeof options.runtime?.stop !== "function" ||
        typeof options.runtime?.relaunch !== "function"
      ) {
        throw new PrimeCheckpointError();
      }
      const manager = new PrimeCheckpointManager(options);
      validateHello(
        options.transport.hello,
        manager.artifactEvidence,
        options.expectedRuntimeBuildId,
      );
      return manager;
    } catch (error) {
      if (error instanceof PrimeCheckpointError) {
        throw error;
      }
      throw new PrimeCheckpointError();
    }
  }

  create(
    checkpointId: string,
    coveredSequence: number,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void> = async () => undefined,
  ): Promise<PrimeCheckpointCreated> {
    if (
      !validOpaqueId(checkpointId) ||
      !positiveInteger(coveredSequence) ||
      typeof onRecovered !== "function"
    ) {
      return Promise.reject(new PrimeCheckpointError());
    }
    const existing = this.executions.get(checkpointId);
    if (existing !== undefined) {
      return existing.coveredSequence === coveredSequence
        ? existing.promise
        : Promise.reject(new PrimeCheckpointError());
    }
    const promise = this.createOnce(checkpointId, coveredSequence, onRecovered)
      .catch(() => {
        throw new PrimeCheckpointError();
      });
    this.executions.set(checkpointId, { coveredSequence, promise });
    return promise;
  }

  async restore(
    capsuleRef: PrivateValueRef,
    expectedDigest: string,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void> = async () => undefined,
  ): Promise<PrimeCheckpointCreated> {
    try {
      if (typeof onRecovered !== "function") {
        throw new PrimeCheckpointError();
      }
      const bytes = await this.options.privateValues.readCapsule(capsuleRef);
      const capsule = parseCapsule(
        bytes,
        expectedDigest,
        this.artifactDigest,
        this.options,
      );
      this.transcriptSessionId = capsule.transcriptSessionId;
      await this.options.runtime.stop();
      this.transport = await this.options.runtime.relaunch();
      validateHello(
        this.transport.hello,
        this.artifactEvidence,
        this.options.expectedRuntimeBuildId,
      );
      const restored = await this.attachAndValidate(capsule.primeCursor, "restore");
      this.primeCursor = restored.primeCursor;
      const recovery = this.recovery(restored);
      await onRecovered(recovery);
      return this.created(
        `restored-${expectedDigest.slice(0, 24)}`,
        capsule.asterionSequence,
        capsuleRef,
        expectedDigest,
        restored.primeCursor,
        () => true,
      );
    } catch (error) {
      if (error instanceof PrimeCheckpointError) {
        throw error;
      }
      throw new PrimeCheckpointError();
    }
  }

  toString(): string {
    return "[Asterion Prime checkpoint manager]";
  }

  toJSON(): Readonly<Record<string, string | number>> {
    return Object.freeze({
      kind: "prime-checkpoint-manager",
      session_id: this.options.sessionId,
      generation: this.options.asterionGeneration,
    });
  }

  private async createOnce(
    checkpointId: string,
    coveredSequence: number,
    onRecovered: (recovery: PrimeCheckpointRecovery) => Promise<void>,
  ): Promise<PrimeCheckpointCreated> {
    validateHello(
      this.transport.hello,
      this.artifactEvidence,
      this.options.expectedRuntimeBuildId,
    );
    requireSuccessful(
      await this.transport.request(
        { type: "wait_for_idle", activeSessionId: this.options.activeSessionId },
        `${this.options.sessionId}-checkpoint-${checkpointId}-idle`,
        120_000,
      ),
      "wait_for_idle",
    );
    const prepareCommandId =
      `${this.options.sessionId}-checkpoint-${checkpointId}-prepare`;
    const deferred = await this.transport.requestDeferred(
      { type: "prepare_update_restart" },
      prepareCommandId,
      120_000,
    );
    const manifest = this.manifestFromDeferred(deferred);

    await this.options.runtime.stop();
    this.transport = await this.options.runtime.relaunch();
    validateHello(
      this.transport.hello,
      this.artifactEvidence,
      this.options.expectedRuntimeBuildId,
    );
    const restored = await this.attachAndValidate(
      this.primeCursor,
      `checkpoint-${checkpointId}`,
    );
    this.primeCursor = restored.primeCursor;
    const acknowledgementTransport = this.transport;
    const recovery = this.recovery(restored);
    await onRecovered(recovery);

    const capsule: PrimeCapsuleV1 = Object.freeze({
      format: CAPSULE_FORMAT,
      artifactDigest: this.artifactDigest,
      activeSessionId: this.options.activeSessionId,
      transcriptSessionId: this.requireTranscriptSessionId(),
      primeCursor: restored.primeCursor,
      asterionGeneration: this.options.asterionGeneration,
      asterionSequence: coveredSequence,
      updateManifest: manifest.value,
    });
    const capsuleBytes = canonicalJsonBytes(capsule);
    const capsuleDigest = sha256Hex(capsuleBytes);
    const storageRef = await this.options.privateValues.putCapsule(capsuleBytes);
    return this.created(
      checkpointId,
      coveredSequence,
      storageRef,
      capsuleDigest,
      restored.primeCursor,
      () => {
        try {
          return acknowledgementTransport.acknowledgeResult(prepareCommandId);
        } catch {
          return false;
        }
      },
    );
  }

  private manifestFromDeferred(deferred: PrimeDaemonDeferredResponse): ValidatedManifest {
    const response = requireSuccessful(deferred.response, "prepare_update_restart");
    return validateManifest(
      response.data,
      this.options.activeSessionId,
      this.requireTranscriptSessionId(),
    );
  }

  private async attachAndValidate(
    cursor: PrimeDaemonCursor,
    purpose: string,
  ): Promise<Readonly<{
    primeCursor: PrimeDaemonCursor;
    sessionStatus: "running" | "paused";
  }>> {
    const response = await this.transport.request(
      {
        type: "attach",
        activeSessionId: this.options.activeSessionId,
        supportsExtensionUi: false,
        clientId: `asterion-${this.options.sessionId}`,
        capabilities: ["attach_snapshot", "event_sequence", "slim_attach"],
        resumeCursor: cursor,
        telemetryDisabled: true,
      },
      `${this.options.sessionId}-${purpose}-attach`,
      120_000,
    );
    return recoveryFromAttach(
      response,
      this.options.activeSessionId,
      this.requireTranscriptSessionId(),
      cursor,
    );
  }

  private created(
    checkpointId: string,
    coveredSequence: number,
    storageRef: PrivateValueRef,
    capsuleDigest: string,
    restoredCursor: PrimeDaemonCursor,
    acknowledge: () => boolean,
  ): PrimeCheckpointCreated {
    const capsuleId = `prime-capsule-${sha256Hex(Buffer.from(checkpointId)).slice(0, 24)}`;
    return Object.freeze({
      checkpointId,
      capsuleId,
      capsuleDigest,
      controlPlaneId: CONTROL_PLANE_ID,
      controlPlaneVersion: CONTROL_PLANE_VERSION,
      checkpointVersion: CHECKPOINT_VERSION,
      coveredSequence,
      storageRef,
      primeCursor: restoredCursor,
      supervisorGeneration: this.requireSupervisorGeneration(),
      acknowledge,
    });
  }

  private recovery(
    restored: Readonly<{
      primeCursor: PrimeDaemonCursor;
      sessionStatus: "running" | "paused";
    }>,
  ): PrimeCheckpointRecovery {
    return Object.freeze({
      transport: this.transport,
      primeCursor: restored.primeCursor,
      transcriptSessionId: this.requireTranscriptSessionId(),
      supervisorGeneration: this.requireSupervisorGeneration(),
      sessionStatus: restored.sessionStatus,
    });
  }

  private requireSupervisorGeneration(): string {
    const generation = this.transport.hello?.supervisorGeneration;
    if (!validOpaqueId(generation)) {
      throw new PrimeCheckpointError();
    }
    return generation;
  }

  private requireTranscriptSessionId(): string {
    if (!validOpaqueId(this.transcriptSessionId)) {
      throw new PrimeCheckpointError();
    }
    return this.transcriptSessionId;
  }
}
