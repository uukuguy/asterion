import { randomUUID, createHash } from "node:crypto";
import { constants } from "node:fs";
import {
  lstat,
  link,
  mkdir,
  open,
  readdir,
  unlink,
} from "node:fs/promises";
import { join } from "node:path";

import {
  validateControlCommand,
  validateControlEvent,
  validateSessionContextCommand,
  validateSessionContextReceipt,
} from "@dci/agent-runtime";
import type {
  ControlCommand,
  ControlEvent,
  SessionContextCommand,
  SessionContextReceipt,
} from "@dci/agent-runtime";

import type { PrimeDaemonCursor } from "./daemon-wire.js";

export const MAX_PUBLIC_EVENTS_PER_GENERATION = 100_000;
export const MAX_PUBLIC_RECORD_BYTES = 1024 * 1024;

const STORE_FORMAT = "asterion.prime-gateway-store/v1";
const RECORD_FORMAT = "asterion.prime-gateway-record/v1";
const SESSION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const RECORD_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/u;
const RECORD_NAME_PATTERN = /^(?<position>[0-9]{12})\.json$/u;
const ATOMIC_TEMP_PATTERN = /^\.asterion-[0-9a-f-]{36}\.tmp$/u;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/u;
const PRIVATE_REF_PATTERN = /^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const RECORD_KINDS = new Set([
  "command.accepted",
  "context.binding.initialized",
  "context.binding.rebound",
  "context.command.accepted",
  "context.operation.committed",
  "event.accepted",
  "prime.identity",
  "prime.cursor",
]);

export type StorageFaultStage =
  | "before_write"
  | "after_write"
  | "before_rename"
  | "after_rename"
  | "before_directory_fsync"
  | "after_directory_fsync";

export type StorageFaultInjector = (
  stage: StorageFaultStage,
) => void | Promise<void>;

export interface GatewayDurableStoreOptions {
  readonly faultInjector?: StorageFaultInjector;
}

export interface PrimeIdentityBinding {
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly supervisorGeneration: string;
}

export interface GatewayRecordReceipt {
  readonly position: number;
  readonly digest: string;
}

export interface GatewayEventReceipt extends GatewayRecordReceipt {
  readonly event: ControlEvent;
}

export interface GatewayCommandReceipt extends GatewayRecordReceipt {
  readonly command: ControlCommand;
}

export interface GatewayContextBinding {
  readonly continuationId: string;
  readonly privateRef: string;
  readonly bindingDigest: string;
}

export interface GatewayContextOperation {
  readonly command: SessionContextCommand;
  readonly receipt: SessionContextReceipt;
  readonly nextBinding: GatewayContextBinding | null;
}

export interface GatewayContextCommitReceipt extends GatewayRecordReceipt {
  readonly receipt: SessionContextReceipt;
  readonly nextBinding: GatewayContextBinding | null;
}

export interface GatewayDurableSnapshot {
  readonly sessionId: string;
  readonly position: number;
  readonly headDigest: string | null;
  readonly commandCount: number;
  readonly eventCount: number;
  readonly contextCommandCount?: number;
  readonly contextCommitCount?: number;
  readonly primeIdentity?: PrimeIdentityBinding;
  readonly primeCursor?: PrimeDaemonCursor;
}

export interface GatewayEventCursor {
  readonly generation: number;
  readonly sequence: number;
}

interface StoredRecordBody {
  readonly format: typeof RECORD_FORMAT;
  readonly position: number;
  readonly previous_digest: string | null;
  readonly kind: string;
  readonly record_id: string;
  readonly payload: Record<string, unknown>;
  readonly payload_digest: string;
}

interface StoredRecord extends StoredRecordBody {
  readonly digest: string;
}

interface LoadedRecord {
  readonly stored: StoredRecord;
  readonly payload: Record<string, unknown>;
}

export class GatewayStoreConflictError extends Error {
  constructor() {
    super("Prime gateway durable record conflicts");
    this.name = "GatewayStoreConflictError";
  }
}

export class GatewayStoreCorruptionError extends Error {
  constructor() {
    super("Prime gateway durable store is corrupt");
    this.name = "GatewayStoreCorruptionError";
  }
}

export class GatewayStoreWriteError extends Error {
  constructor() {
    super("Prime gateway durable write failed");
    this.name = "GatewayStoreWriteError";
  }
}

export class AtomicTargetExistsError extends Error {
  constructor() {
    super("Prime gateway durable target already exists");
    this.name = "AtomicTargetExistsError";
  }
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

function nonEmptyIdentifier(value: unknown): value is string {
  return typeof value === "string" && SESSION_ID_PATTERN.test(value);
}

function nonEmptyRecordId(value: unknown): value is string {
  return typeof value === "string" && RECORD_ID_PATTERN.test(value);
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
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

function canonicalJsonValue(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJsonValue(item)).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value)
      .sort()
      .map(
        (key) =>
          `${JSON.stringify(key)}:${canonicalJsonValue(value[key])}`,
      )
      .join(",")}}`;
  }
  throw new GatewayStoreConflictError();
}

export function canonicalJsonBytes(value: unknown): Buffer {
  return Buffer.from(canonicalJsonValue(value), "utf8");
}

export function sha256Hex(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (
      isRecord(error) &&
      "code" in error &&
      error.code === "ENOENT"
    ) {
      return false;
    }
    throw error;
  }
}

export async function ensurePrivateDirectory(path: string): Promise<void> {
  await mkdir(path, { recursive: true, mode: 0o700 });
  const metadata = await lstat(path);
  if (
    metadata.isSymbolicLink() ||
    !metadata.isDirectory() ||
    (metadata.mode & 0o777) !== 0o700
  ) {
    throw new GatewayStoreCorruptionError();
  }
}

async function syncDirectory(path: string): Promise<void> {
  const descriptor = await open(path, constants.O_RDONLY);
  try {
    await descriptor.sync();
  } finally {
    await descriptor.close();
  }
}

export async function syncPrivateDirectory(
  path: string,
  faultInjector?: StorageFaultInjector,
): Promise<void> {
  await faultInjector?.("before_directory_fsync");
  await syncDirectory(path);
  await faultInjector?.("after_directory_fsync");
}

export async function atomicWriteFile(
  directory: string,
  targetName: string,
  bytes: Uint8Array,
  faultInjector?: StorageFaultInjector,
): Promise<void> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(targetName)) {
    throw new GatewayStoreWriteError();
  }
  const target = join(directory, targetName);
  if (await pathExists(target)) {
    throw new AtomicTargetExistsError();
  }
  const temporary = join(directory, `.asterion-${randomUUID()}.tmp`);
  const descriptor = await open(
    temporary,
    constants.O_CREAT |
      constants.O_EXCL |
      constants.O_WRONLY |
      constants.O_NOFOLLOW,
    0o600,
  );
  let closed = false;
  try {
    await descriptor.chmod(0o600);
    await faultInjector?.("before_write");
    let offset = 0;
    while (offset < bytes.byteLength) {
      const result = await descriptor.write(
        bytes,
        offset,
        bytes.byteLength - offset,
        offset,
      );
      if (result.bytesWritten <= 0) {
        throw new GatewayStoreWriteError();
      }
      offset += result.bytesWritten;
    }
    await descriptor.datasync();
    await faultInjector?.("after_write");
    await descriptor.close();
    closed = true;
    await faultInjector?.("before_rename");
    try {
      await link(temporary, target);
    } catch (error) {
      if (isRecord(error) && "code" in error && error.code === "EEXIST") {
        throw new AtomicTargetExistsError();
      }
      throw error;
    }
    await unlink(temporary);
    await faultInjector?.("after_rename");
    await syncPrivateDirectory(directory, faultInjector);
  } finally {
    if (!closed) {
      await descriptor.close().catch(() => undefined);
    }
  }
}

export async function readPrivateRegularFile(
  path: string,
  maxBytes: number,
): Promise<Buffer> {
  const descriptor = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const metadata = await descriptor.stat();
    if (
      !metadata.isFile() ||
      (metadata.mode & 0o777) !== 0o600 ||
      metadata.size < 1 ||
      metadata.size > maxBytes
    ) {
      throw new GatewayStoreCorruptionError();
    }
    return await descriptor.readFile();
  } finally {
    await descriptor.close();
  }
}

function parseJsonLine(bytes: Buffer): unknown {
  if (
    bytes.byteLength > MAX_PUBLIC_RECORD_BYTES ||
    bytes[bytes.byteLength - 1] !== 0x0a
  ) {
    throw new GatewayStoreCorruptionError();
  }
  const body = bytes.subarray(0, bytes.byteLength - 1).toString("utf8");
  if (body.includes("\n") || body.includes("\r")) {
    throw new GatewayStoreCorruptionError();
  }
  try {
    const parsed: unknown = JSON.parse(body);
    if (!canonicalJsonBytes(parsed).equals(bytes.subarray(0, bytes.byteLength - 1))) {
      throw new GatewayStoreCorruptionError();
    }
    return parsed;
  } catch {
    throw new GatewayStoreCorruptionError();
  }
}

function payloadDigest(
  kind: string,
  recordId: string,
  payload: Record<string, unknown>,
): string {
  return sha256Hex(canonicalJsonBytes({ kind, record_id: recordId, payload }));
}

function recordDigest(body: StoredRecordBody): string {
  return sha256Hex(canonicalJsonBytes(body));
}

function recordName(position: number): string {
  return `${String(position).padStart(12, "0")}.json`;
}

function validateIdentityPayload(value: unknown): PrimeIdentityBinding {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "activeSessionId",
      "transcriptSessionId",
      "supervisorGeneration",
    ]) ||
    !nonEmptyIdentifier(value.activeSessionId) ||
    !nonEmptyIdentifier(value.transcriptSessionId) ||
    !nonEmptyIdentifier(value.supervisorGeneration)
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    activeSessionId: value.activeSessionId,
    transcriptSessionId: value.transcriptSessionId,
    supervisorGeneration: value.supervisorGeneration,
  });
}

function validateCursorPayload(value: unknown): PrimeDaemonCursor {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["generation", "sequence"]) ||
    !nonEmptyIdentifier(value.generation) ||
    !nonNegativeInteger(value.sequence)
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({ generation: value.generation, sequence: value.sequence });
}

function validateContextBinding(value: unknown): GatewayContextBinding {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "bindingDigest",
      "continuationId",
      "privateRef",
    ]) ||
    !nonEmptyIdentifier(value.continuationId) ||
    typeof value.privateRef !== "string" ||
    !PRIVATE_REF_PATTERN.test(value.privateRef) ||
    typeof value.bindingDigest !== "string" ||
    !DIGEST_PATTERN.test(value.bindingDigest)
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    continuationId: value.continuationId,
    privateRef: value.privateRef,
    bindingDigest: value.bindingDigest,
  });
}

function validateContextCommitPayload(
  value: unknown,
  command: SessionContextCommand,
): Readonly<{
  receipt: SessionContextReceipt;
  nextBinding: GatewayContextBinding | null;
}> {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["nextBinding", "receipt"])
  ) {
    throw new GatewayStoreConflictError();
  }
  let receipt: SessionContextReceipt;
  try {
    receipt = validateSessionContextReceipt(value.receipt);
  } catch {
    throw new GatewayStoreConflictError();
  }
  if (
    receipt.command_id !== command.command_id ||
    receipt.session_id !== command.session_id ||
    receipt.generation !== command.generation ||
    receipt.operation !== command.operation
  ) {
    throw new GatewayStoreConflictError();
  }
  const nextBinding = value.nextBinding === null
    ? null
    : validateContextBinding(value.nextBinding);
  if (nextBinding !== null) {
    if (receipt.status !== "succeeded" || receipt.payload.result === null) {
      throw new GatewayStoreConflictError();
    }
    const result = receipt.payload.result as Record<string, unknown>;
    const continuationIds = [
      result.continuation_id,
      result.current_continuation_id,
      result.new_continuation_id,
    ].filter((item): item is string => typeof item === "string");
    if (!continuationIds.includes(nextBinding.continuationId)) {
      throw new GatewayStoreConflictError();
    }
  }
  return Object.freeze({ receipt, nextBinding });
}

export class GatewayDurableStore {
  private readonly records: LoadedRecord[] = [];
  private readonly recordsById = new Map<string, LoadedRecord>();
  private readonly eventCounts = new Map<number, number>();
  private readonly knownEventGenerations = new Set<number>();
  private readonly contextCommands = new Map<string, SessionContextCommand>();
  private readonly contextIdempotency = new Map<string, string>();
  private readonly contextCommits = new Map<
    string,
    Readonly<{
      receipt: SessionContextReceipt;
      nextBinding: GatewayContextBinding | null;
    }>
  >();
  private readonly currentContextBindings = new Map<
    string,
    GatewayContextBinding
  >();
  private initialContextBindingValue?: GatewayContextBinding;
  private readonly faultInjector: StorageFaultInjector | undefined;
  private failed = false;
  private commandCount = 0;
  private eventCount = 0;
  private contextCommandCount = 0;
  private contextCommitCount = 0;
  private primeIdentity?: PrimeIdentityBinding;
  private primeCursor?: PrimeDaemonCursor;

  private constructor(
    private readonly root: string,
    private readonly recordsRoot: string,
    private readonly sessionId: string,
    options: GatewayDurableStoreOptions,
  ) {
    this.faultInjector = options.faultInjector;
  }

  static async open(
    root: string,
    sessionId: string,
    options: GatewayDurableStoreOptions = {},
  ): Promise<GatewayDurableStore> {
    if (!nonEmptyIdentifier(sessionId)) {
      throw new GatewayStoreConflictError();
    }
    const publicRoot = join(root, "public");
    const recordsRoot = join(publicRoot, "records");
    try {
      await ensurePrivateDirectory(root);
      await ensurePrivateDirectory(publicRoot);
      await ensurePrivateDirectory(recordsRoot);
      const headerPath = join(publicRoot, "session.json");
      if (!(await pathExists(headerPath))) {
        const headerBytes = Buffer.concat([
          canonicalJsonBytes({ format: STORE_FORMAT, session_id: sessionId }),
          Buffer.from("\n"),
        ]);
        await atomicWriteFile(
          publicRoot,
          "session.json",
          headerBytes,
          options.faultInjector,
        );
      }
      const header = parseJsonLine(
        await readPrivateRegularFile(headerPath, 4096),
      );
      if (
        !isRecord(header) ||
        !hasExactKeys(header, ["format", "session_id"]) ||
        header.format !== STORE_FORMAT ||
        header.session_id !== sessionId
      ) {
        throw new GatewayStoreCorruptionError();
      }
      const store = new GatewayDurableStore(root, recordsRoot, sessionId, options);
      await store.loadRecords();
      return store;
    } catch (error) {
      if (
        error instanceof GatewayStoreConflictError ||
        error instanceof GatewayStoreCorruptionError ||
        error instanceof GatewayStoreWriteError
      ) {
        throw error;
      }
      throw new GatewayStoreCorruptionError();
    }
  }

  async acceptCommand(command: unknown): Promise<GatewayRecordReceipt> {
    let validated: ControlCommand;
    try {
      validated = validateControlCommand(command);
    } catch {
      throw new GatewayStoreConflictError();
    }
    if (validated.session_id !== this.sessionId) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "command.accepted",
      `command:${validated.command_id}`,
      { command: validated },
    );
  }

  async acceptContextCommand(command: unknown): Promise<GatewayRecordReceipt> {
    let validated: SessionContextCommand;
    try {
      validated = validateSessionContextCommand(command);
    } catch {
      throw new GatewayStoreConflictError();
    }
    if (validated.session_id !== this.sessionId) {
      throw new GatewayStoreConflictError();
    }
    const idempotentCommandId = this.contextIdempotency.get(
      validated.idempotency_key,
    );
    if (
      idempotentCommandId !== undefined &&
      idempotentCommandId !== validated.command_id
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "context.command.accepted",
      `context-command:${validated.command_id}`,
      { command: validated },
    );
  }

  async initializeContextBinding(
    binding: GatewayContextBinding,
  ): Promise<GatewayRecordReceipt> {
    const validated = validateContextBinding(binding);
    return this.appendRecord(
      "context.binding.initialized",
      "context-binding:initial",
      validated as unknown as Record<string, unknown>,
    );
  }

  async rebindContextBinding(
    binding: GatewayContextBinding,
  ): Promise<GatewayRecordReceipt> {
    const validated = validateContextBinding(binding);
    if (!this.currentContextBindings.has(validated.continuationId)) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "context.binding.rebound",
      `context-binding:${validated.continuationId}:${validated.bindingDigest}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async commitContextOperation(
    receipt: unknown,
    nextBinding: GatewayContextBinding | null,
  ): Promise<GatewayContextCommitReceipt> {
    let commandId: string;
    try {
      if (!isRecord(receipt) || typeof receipt.command_id !== "string") {
        throw new GatewayStoreConflictError();
      }
      commandId = receipt.command_id;
      const command = this.contextCommands.get(commandId);
      if (command === undefined) {
        throw new GatewayStoreConflictError();
      }
      const payload = validateContextCommitPayload(
        { receipt, nextBinding },
        command,
      );
      const committed = await this.appendRecord(
        "context.operation.committed",
        `context-commit:${commandId}`,
        {
          receipt: payload.receipt,
          nextBinding: payload.nextBinding,
        },
      );
      const stored = this.contextCommits.get(commandId);
      if (stored === undefined) {
        throw new GatewayStoreConflictError();
      }
      return Object.freeze({
        ...committed,
        receipt: stored.receipt,
        nextBinding: stored.nextBinding,
      });
    } catch (error) {
      if (
        error instanceof GatewayStoreWriteError ||
        error instanceof GatewayStoreConflictError
      ) {
        throw error;
      }
      throw new GatewayStoreConflictError();
    }
  }

  contextOperations(): readonly GatewayContextOperation[] {
    return Object.freeze(
      [...this.contextCommits.entries()].map(([commandId, committed]) => {
        const command = this.contextCommands.get(commandId);
        if (command === undefined) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({
          command,
          receipt: committed.receipt,
          nextBinding: committed.nextBinding,
        });
      }),
    );
  }

  currentContextBinding(
    continuationId: string,
  ): GatewayContextBinding | undefined {
    if (!nonEmptyIdentifier(continuationId)) {
      throw new GatewayStoreConflictError();
    }
    return this.currentContextBindings.get(continuationId);
  }

  initialContextBinding(): GatewayContextBinding | undefined {
    return this.initialContextBindingValue;
  }

  async appendEvent(event: unknown): Promise<GatewayEventReceipt> {
    let validated: ControlEvent;
    try {
      validated = validateControlEvent(event);
    } catch {
      throw new GatewayStoreConflictError();
    }
    if (validated.session_id !== this.sessionId) {
      throw new GatewayStoreConflictError();
    }
    const generationCount = this.eventCounts.get(validated.generation) ?? 0;
    if (generationCount >= MAX_PUBLIC_EVENTS_PER_GENERATION) {
      throw new GatewayStoreConflictError();
    }
    const receipt = await this.appendRecord(
      "event.accepted",
      `event:${validated.event_id}`,
      { event: validated },
    );
    return Object.freeze({ ...receipt, event: validated });
  }

  registerEventGeneration(generation: number): void {
    if (!positiveInteger(generation)) {
      throw new GatewayStoreConflictError();
    }
    this.knownEventGenerations.add(generation);
  }

  async bindPrimeIdentity(identity: PrimeIdentityBinding): Promise<GatewayRecordReceipt> {
    const validated = validateIdentityPayload(identity);
    return this.appendRecord(
      "prime.identity",
      `prime-identity:${validated.supervisorGeneration}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async recordPrimeCursor(cursor: PrimeDaemonCursor): Promise<GatewayRecordReceipt> {
    const validated = validateCursorPayload(cursor);
    if (
      this.primeCursor?.generation === validated.generation &&
      validated.sequence < this.primeCursor.sequence
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "prime.cursor",
      `prime-cursor:${validated.generation}:${validated.sequence}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  eventsAfter(position: number): readonly GatewayEventReceipt[] {
    if (!nonNegativeInteger(position) || position > this.records.length) {
      throw new GatewayStoreConflictError();
    }
    return Object.freeze(
      this.records
        .slice(position)
        .filter((record) => record.stored.kind === "event.accepted")
        .map((record) => {
          const event = record.payload.event as ControlEvent;
          return Object.freeze({
            position: record.stored.position,
            digest: record.stored.digest,
            event,
          });
        }),
    );
  }

  commands(): readonly GatewayCommandReceipt[] {
    return Object.freeze(
      this.records
        .filter((record) => record.stored.kind === "command.accepted")
        .map((record) => Object.freeze({
          position: record.stored.position,
          digest: record.stored.digest,
          command: record.payload.command as ControlCommand,
        })),
    );
  }

  eventsAfterCursor(cursor: GatewayEventCursor): readonly GatewayEventReceipt[] {
    if (
      !isRecord(cursor) ||
      !positiveInteger(cursor.generation) ||
      !nonNegativeInteger(cursor.sequence)
    ) {
      throw new GatewayStoreConflictError();
    }
    const generationEvents = this.records
      .filter((record) => record.stored.kind === "event.accepted")
      .map((record) => {
        const event = record.payload.event as ControlEvent;
        return { record, event };
      })
      .filter(({ event }) => event.generation === cursor.generation);
    if (!this.knownEventGenerations.has(cursor.generation)) {
      throw new GatewayStoreConflictError();
    }
    for (const [index, { event }] of generationEvents.entries()) {
      const expectedSequence = index + 1;
      if (
        event.session_id !== this.sessionId ||
        event.sequence !== expectedSequence
      ) {
        throw new GatewayStoreCorruptionError();
      }
    }
    if (
      cursor.sequence > generationEvents.length ||
      (generationEvents.length === 0 && cursor.sequence !== 0)
    ) {
      throw new GatewayStoreConflictError();
    }
    return Object.freeze(
      generationEvents
        .filter(({ event }) => event.sequence > cursor.sequence)
        .map(({ record, event }) =>
          Object.freeze({
            position: record.stored.position,
            digest: record.stored.digest,
            event,
          }),
        ),
    );
  }

  snapshot(): GatewayDurableSnapshot {
    const head = this.records.at(-1)?.stored.digest ?? null;
    return Object.freeze({
      sessionId: this.sessionId,
      position: this.records.length,
      headDigest: head,
      commandCount: this.commandCount,
      eventCount: this.eventCount,
      ...(this.contextCommandCount === 0
        ? {}
        : { contextCommandCount: this.contextCommandCount }),
      ...(this.contextCommitCount === 0
        ? {}
        : { contextCommitCount: this.contextCommitCount }),
      ...(this.primeIdentity === undefined
        ? {}
        : { primeIdentity: this.primeIdentity }),
      ...(this.primeCursor === undefined ? {} : { primeCursor: this.primeCursor }),
    });
  }

  private async loadRecords(): Promise<void> {
    try {
      const names = await readdir(this.recordsRoot);
      const recordNames = names.filter((name) => RECORD_NAME_PATTERN.test(name)).sort();
      const unexpected = names.filter(
        (name) =>
          !RECORD_NAME_PATTERN.test(name) && !ATOMIC_TEMP_PATTERN.test(name),
      );
      if (unexpected.length > 0) {
        throw new GatewayStoreCorruptionError();
      }
      let previousDigest: string | null = null;
      for (const [index, name] of recordNames.entries()) {
        const match = RECORD_NAME_PATTERN.exec(name);
        const expectedPosition = index + 1;
        if (match?.groups?.position !== String(expectedPosition).padStart(12, "0")) {
          throw new GatewayStoreCorruptionError();
        }
        const value = parseJsonLine(
          await readPrivateRegularFile(
            join(this.recordsRoot, name),
            MAX_PUBLIC_RECORD_BYTES,
          ),
        );
        const loaded = this.validateStoredRecord(
          value,
          expectedPosition,
          previousDigest,
        );
        this.applyLoadedRecord(loaded);
        previousDigest = loaded.stored.digest;
      }
    } catch (error) {
      if (error instanceof GatewayStoreCorruptionError) {
        throw error;
      }
      throw new GatewayStoreCorruptionError();
    }
  }

  private validateStoredRecord(
    value: unknown,
    expectedPosition: number,
    previousDigest: string | null,
  ): LoadedRecord {
    if (
      !isRecord(value) ||
      !hasExactKeys(value, [
        "format",
        "position",
        "previous_digest",
        "kind",
        "record_id",
        "payload",
        "payload_digest",
        "digest",
      ]) ||
      value.format !== RECORD_FORMAT ||
      value.position !== expectedPosition ||
      value.previous_digest !== previousDigest ||
      typeof value.kind !== "string" ||
      !RECORD_KINDS.has(value.kind) ||
      !nonEmptyRecordId(value.record_id) ||
      !isRecord(value.payload) ||
      typeof value.payload_digest !== "string" ||
      !DIGEST_PATTERN.test(value.payload_digest) ||
      typeof value.digest !== "string" ||
      !DIGEST_PATTERN.test(value.digest)
    ) {
      throw new GatewayStoreCorruptionError();
    }
    if (
      payloadDigest(value.kind, value.record_id, value.payload) !==
      value.payload_digest
    ) {
      throw new GatewayStoreCorruptionError();
    }
    const body: StoredRecordBody = {
      format: RECORD_FORMAT,
      position: expectedPosition,
      previous_digest: previousDigest,
      kind: value.kind,
      record_id: value.record_id,
      payload: value.payload,
      payload_digest: value.payload_digest,
    };
    if (recordDigest(body) !== value.digest) {
      throw new GatewayStoreCorruptionError();
    }
    const payload = this.validateLoadedPayload(value.kind, value.record_id, value.payload);
    return Object.freeze({
      stored: deepFreeze({ ...body, digest: value.digest }),
      payload,
    });
  }

  private validateLoadedPayload(
    kind: string,
    recordId: string,
    payload: Record<string, unknown>,
  ): Record<string, unknown> {
    try {
      if (kind === "command.accepted") {
        if (!hasExactKeys(payload, ["command"])) {
          throw new GatewayStoreCorruptionError();
        }
        const command = validateControlCommand(payload.command);
        if (
          command.session_id !== this.sessionId ||
          recordId !== `command:${command.command_id}`
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({ command });
      }
      if (kind === "event.accepted") {
        if (!hasExactKeys(payload, ["event"])) {
          throw new GatewayStoreCorruptionError();
        }
        const event = validateControlEvent(payload.event);
        if (
          event.session_id !== this.sessionId ||
          recordId !== `event:${event.event_id}`
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({ event });
      }
      if (kind === "context.command.accepted") {
        if (!hasExactKeys(payload, ["command"])) {
          throw new GatewayStoreCorruptionError();
        }
        const command = validateSessionContextCommand(payload.command);
        if (
          command.session_id !== this.sessionId ||
          recordId !== `context-command:${command.command_id}`
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({ command });
      }
      if (kind === "context.binding.initialized") {
        const binding = validateContextBinding(payload);
        if (recordId !== "context-binding:initial") {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "context.binding.rebound") {
        const binding = validateContextBinding(payload);
        if (
          recordId !==
            `context-binding:${binding.continuationId}:${binding.bindingDigest}` ||
          !this.currentContextBindings.has(binding.continuationId)
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "context.operation.committed") {
        const commandId = recordId.startsWith("context-commit:")
          ? recordId.slice("context-commit:".length)
          : "";
        const command = this.contextCommands.get(commandId);
        if (command === undefined || recordId !== `context-commit:${command.command_id}`) {
          throw new GatewayStoreCorruptionError();
        }
        const committed = validateContextCommitPayload(payload, command);
        return Object.freeze({
          receipt: committed.receipt,
          nextBinding: committed.nextBinding,
        });
      }
      if (kind === "prime.identity") {
        const identity = validateIdentityPayload(payload);
        if (recordId !== `prime-identity:${identity.supervisorGeneration}`) {
          throw new GatewayStoreCorruptionError();
        }
        return identity as unknown as Record<string, unknown>;
      }
      const cursor = validateCursorPayload(payload);
      if (recordId !== `prime-cursor:${cursor.generation}:${cursor.sequence}`) {
        throw new GatewayStoreCorruptionError();
      }
      return cursor as unknown as Record<string, unknown>;
    } catch {
      throw new GatewayStoreCorruptionError();
    }
  }

  private applyLoadedRecord(record: LoadedRecord): void {
    if (this.recordsById.has(record.stored.record_id)) {
      throw new GatewayStoreCorruptionError();
    }
    this.records.push(record);
    this.recordsById.set(record.stored.record_id, record);
    if (record.stored.kind === "command.accepted") {
      this.commandCount += 1;
    } else if (record.stored.kind === "context.binding.initialized") {
      const binding = record.payload as unknown as GatewayContextBinding;
      if (
        this.currentContextBindings.size !== 0 ||
        this.initialContextBindingValue !== undefined
      ) {
        throw new GatewayStoreCorruptionError();
      }
      this.initialContextBindingValue = binding;
      this.currentContextBindings.set(binding.continuationId, binding);
    } else if (record.stored.kind === "context.binding.rebound") {
      const binding = record.payload as unknown as GatewayContextBinding;
      const existing = this.currentContextBindings.get(binding.continuationId);
      if (existing === undefined) {
        throw new GatewayStoreCorruptionError();
      }
      this.currentContextBindings.set(binding.continuationId, binding);
      if (this.initialContextBindingValue?.continuationId === binding.continuationId) {
        this.initialContextBindingValue = binding;
      }
    } else if (record.stored.kind === "context.command.accepted") {
      const command = record.payload.command as SessionContextCommand;
      const existingId = this.contextIdempotency.get(command.idempotency_key);
      if (existingId !== undefined && existingId !== command.command_id) {
        throw new GatewayStoreCorruptionError();
      }
      this.contextCommands.set(command.command_id, command);
      this.contextIdempotency.set(command.idempotency_key, command.command_id);
      this.contextCommandCount += 1;
    } else if (record.stored.kind === "context.operation.committed") {
      const receipt = record.payload.receipt as SessionContextReceipt;
      const nextBinding = record.payload.nextBinding as GatewayContextBinding | null;
      if (
        this.contextCommits.has(receipt.command_id) ||
        !this.contextCommands.has(receipt.command_id)
      ) {
        throw new GatewayStoreCorruptionError();
      }
      const committed = Object.freeze({ receipt, nextBinding });
      this.contextCommits.set(receipt.command_id, committed);
      if (nextBinding !== null) {
        this.currentContextBindings.set(
          nextBinding.continuationId,
          nextBinding,
        );
      }
      this.contextCommitCount += 1;
    } else if (record.stored.kind === "event.accepted") {
      this.eventCount += 1;
      const event = record.payload.event as ControlEvent;
      this.knownEventGenerations.add(event.generation);
      const count = (this.eventCounts.get(event.generation) ?? 0) + 1;
      if (count > MAX_PUBLIC_EVENTS_PER_GENERATION) {
        throw new GatewayStoreCorruptionError();
      }
      this.eventCounts.set(event.generation, count);
    } else if (record.stored.kind === "prime.identity") {
      this.primeIdentity = record.payload as unknown as PrimeIdentityBinding;
    } else if (record.stored.kind === "prime.cursor") {
      const cursor = record.payload as unknown as PrimeDaemonCursor;
      if (
        this.primeCursor?.generation === cursor.generation &&
        cursor.sequence < this.primeCursor.sequence
      ) {
        throw new GatewayStoreCorruptionError();
      }
      this.primeCursor = cursor;
    }
  }

  private async appendRecord(
    kind: string,
    recordId: string,
    payload: Record<string, unknown>,
  ): Promise<GatewayRecordReceipt> {
    if (this.failed) {
      throw new GatewayStoreWriteError();
    }
    const candidatePayloadDigest = payloadDigest(kind, recordId, payload);
    const existing = this.recordsById.get(recordId);
    if (existing !== undefined) {
      if (existing.stored.payload_digest !== candidatePayloadDigest) {
        throw new GatewayStoreConflictError();
      }
      return Object.freeze({
        position: existing.stored.position,
        digest: existing.stored.digest,
      });
    }
    const position = this.records.length + 1;
    const body: StoredRecordBody = {
      format: RECORD_FORMAT,
      position,
      previous_digest: this.records.at(-1)?.stored.digest ?? null,
      kind,
      record_id: recordId,
      payload,
      payload_digest: candidatePayloadDigest,
    };
    const stored = deepFreeze({ ...body, digest: recordDigest(body) });
    const bytes = Buffer.concat([
      canonicalJsonBytes(stored),
      Buffer.from("\n"),
    ]);
    if (bytes.byteLength > MAX_PUBLIC_RECORD_BYTES) {
      throw new GatewayStoreConflictError();
    }
    try {
      await atomicWriteFile(
        this.recordsRoot,
        recordName(position),
        bytes,
        this.faultInjector,
      );
    } catch {
      this.failed = true;
      throw new GatewayStoreWriteError();
    }
    const loaded: LoadedRecord = Object.freeze({ stored, payload: deepFreeze(payload) });
    this.applyLoadedRecord(loaded);
    return Object.freeze({ position, digest: stored.digest });
  }
}
