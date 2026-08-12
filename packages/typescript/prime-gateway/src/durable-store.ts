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
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
const PRIVATE_REF_PATTERN = /^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const RECORD_KINDS = new Set([
  "command.accepted",
  "context.binding.initialized",
  "context.binding.rebound",
  "context.command.accepted",
  "context.operation.committed",
  "context.model.prepared",
  "context.operation.prepared",
  "event.accepted",
  "input.delivery.committed",
  "input.delivery.protocol",
  "prime.identity",
  "prime.identity.rebound",
  "prime.cursor",
  "rlm.binding",
  "rlm.lifecycle",
  "rlm.message.binding",
  "rlm.message.delivered",
]);

export interface GatewayRlmBinding {
  readonly action_id: string;
  readonly child_id: string;
  readonly authority_revision: number;
  readonly depth: number;
  readonly model_selector_digest: string;
}

export interface GatewayRlmMessageBinding {
  readonly action_id: string;
  readonly message_id: string;
  readonly sender_id: string;
  readonly recipient_id: string;
  readonly authority_revision: number;
  readonly body_digest: string;
}

export type GatewayRlmLifecycleObservation =
  | Readonly<{
      readonly type: "rlm.child.started";
      readonly child_id: string;
      readonly native_identity_digest: string;
    }>
  | Readonly<{
      readonly type: "rlm.child.terminal";
      readonly child_id: string;
      readonly status: "completed" | "failed" | "cancelled";
    }>;

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

export interface GatewayInputAttachment {
  readonly attachmentId: string;
  readonly mediaType: string;
  readonly sha256: string;
  readonly size: number;
}

export interface GatewayInputDelivery {
  readonly commandId: string;
  readonly inputId: string;
  readonly attachments: readonly GatewayInputAttachment[];
  readonly deliveryDigest: string;
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

export interface GatewayContextModelBaseline {
  readonly commandId: string;
  readonly continuationId: string;
  readonly leafId: string | null;
  readonly contextTokens: number;
  readonly controllerTokens: number;
  readonly costMicros: number;
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

function nullableIdentifier(value: unknown): value is string | null {
  return value === null || nonEmptyIdentifier(value);
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

function validateRlmLifecycleObservation(
  value: unknown,
): GatewayRlmLifecycleObservation {
  if (!isRecord(value) || !nonEmptyIdentifier(value.child_id)) {
    throw new GatewayStoreConflictError();
  }
  if (
    value.type === "rlm.child.started" &&
    hasExactKeys(value, ["child_id", "native_identity_digest", "type"]) &&
    typeof value.native_identity_digest === "string" &&
    DIGEST_PATTERN.test(value.native_identity_digest)
  ) {
    return Object.freeze({ type: value.type, child_id: value.child_id, native_identity_digest: value.native_identity_digest });
  }
  if (
    value.type === "rlm.child.terminal" &&
    hasExactKeys(value, ["child_id", "status", "type"]) &&
    (value.status === "completed" ||
      value.status === "failed" ||
      value.status === "cancelled")
  ) {
    return Object.freeze({
      type: value.type,
      child_id: value.child_id,
      status: value.status,
    });
  }
  throw new GatewayStoreConflictError();
}

function validateRlmBinding(value: unknown): GatewayRlmBinding {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "action_id",
      "authority_revision",
      "child_id",
      "depth",
      "model_selector_digest",
    ]) ||
    !nonEmptyIdentifier(value.action_id) ||
    !nonEmptyIdentifier(value.child_id) ||
    !positiveInteger(value.authority_revision) ||
    !nonNegativeInteger(value.depth) ||
    !DIGEST_PATTERN.test(String(value.model_selector_digest))
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    action_id: value.action_id,
    child_id: value.child_id,
    authority_revision: value.authority_revision,
    depth: value.depth,
    model_selector_digest: value.model_selector_digest as string,
  });
}

function validateRlmMessageBinding(value: unknown): GatewayRlmMessageBinding {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "action_id",
      "authority_revision",
      "body_digest",
      "message_id",
      "recipient_id",
      "sender_id",
    ]) ||
    !nonEmptyIdentifier(value.action_id) ||
    !nonEmptyIdentifier(value.message_id) ||
    !nonEmptyIdentifier(value.sender_id) ||
    !nonEmptyIdentifier(value.recipient_id) ||
    value.sender_id === value.recipient_id ||
    !positiveInteger(value.authority_revision) ||
    !DIGEST_PATTERN.test(String(value.body_digest))
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    action_id: value.action_id,
    message_id: value.message_id,
    sender_id: value.sender_id,
    recipient_id: value.recipient_id,
    authority_revision: value.authority_revision,
    body_digest: value.body_digest as string,
  });
}

function validateInputDeliveryPayload(
  value: unknown,
  command: ControlCommand | undefined,
): GatewayInputDelivery {
  if (
    command?.type !== "input.submit" ||
    !isRecord(value) ||
    !hasExactKeys(value, [
      "attachments",
      "commandId",
      "deliveryDigest",
      "inputId",
    ]) ||
    value.commandId !== command.command_id ||
    value.inputId !== command.payload.input_id ||
    typeof value.deliveryDigest !== "string" ||
    !DIGEST_PATTERN.test(value.deliveryDigest) ||
    !Array.isArray(value.attachments)
  ) {
    throw new GatewayStoreConflictError();
  }
  const attachmentValues = value.attachments as unknown[];
  const attachments = attachmentValues.map((attachment, index) => {
    if (
      !isRecord(attachment) ||
      !hasExactKeys(attachment, [
        "attachmentId",
        "mediaType",
        "sha256",
        "size",
      ]) ||
      !nonEmptyIdentifier(attachment.attachmentId) ||
      typeof attachment.mediaType !== "string" ||
      !MEDIA_TYPE_PATTERN.test(attachment.mediaType) ||
      typeof attachment.sha256 !== "string" ||
      !DIGEST_PATTERN.test(attachment.sha256) ||
      !nonNegativeInteger(attachment.size)
    ) {
      throw new GatewayStoreConflictError();
    }
    const previous = attachmentValues[index - 1];
    if (
      isRecord(previous) &&
      typeof previous.attachmentId === "string" &&
      previous.attachmentId >= attachment.attachmentId
    ) {
      throw new GatewayStoreConflictError();
    }
    return Object.freeze({
      attachmentId: attachment.attachmentId,
      mediaType: attachment.mediaType,
      sha256: attachment.sha256,
      size: attachment.size,
    });
  });
  const deliveryDigest = sha256Hex(canonicalJsonBytes({
    command,
    attachments,
  }));
  if (value.deliveryDigest !== deliveryDigest) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    commandId: command.command_id,
    inputId: command.payload.input_id,
    attachments: Object.freeze(attachments),
    deliveryDigest,
  });
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

function sameContextBinding(
  left: GatewayContextBinding | undefined,
  right: GatewayContextBinding,
): boolean {
  return left !== undefined &&
    left.continuationId === right.continuationId &&
    left.privateRef === right.privateRef &&
    left.bindingDigest === right.bindingDigest;
}

interface GatewayContextPreparation {
  readonly binding: GatewayContextBinding;
  readonly previousLeafId: string | null;
  readonly selectedEntryId: string | null;
}

function validateContextModelBaseline(
  value: unknown,
): GatewayContextModelBaseline {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "commandId",
      "contextTokens",
      "continuationId",
      "controllerTokens",
      "costMicros",
      "leafId",
    ]) ||
    !nonEmptyIdentifier(value.commandId) ||
    !nonEmptyIdentifier(value.continuationId) ||
    !nullableIdentifier(value.leafId) ||
    !nonNegativeInteger(value.contextTokens) ||
    !nonNegativeInteger(value.controllerTokens) ||
    !nonNegativeInteger(value.costMicros)
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    commandId: value.commandId,
    continuationId: value.continuationId,
    leafId: value.leafId,
    contextTokens: value.contextTokens,
    controllerTokens: value.controllerTokens,
    costMicros: value.costMicros,
  });
}

function validContextModelPreparation(
  command: SessionContextCommand | undefined,
  baseline: GatewayContextModelBaseline,
  activeBinding: GatewayContextBinding | undefined,
): boolean {
  return command !== undefined &&
    (command.operation === "session.compact" ||
      command.operation === "session.branch.summarize") &&
    baseline.commandId === command.command_id &&
    baseline.continuationId === command.payload.continuation_id &&
    activeBinding?.continuationId === baseline.continuationId &&
    (command.operation !== "session.compact" || baseline.leafId !== null);
}

function validContextModelCommit(
  command: SessionContextCommand,
  baseline: GatewayContextModelBaseline | undefined,
  payload: ValidatedContextCommit,
): boolean {
  if (
    (command.operation !== "session.compact" &&
      command.operation !== "session.branch.summarize") ||
    baseline === undefined ||
    payload.nextBinding !== null ||
    payload.sourceBinding !== null ||
    payload.receipt.status !== "succeeded" ||
    payload.receipt.payload.result === null
  ) {
    return false;
  }
  const result = payload.receipt.payload.result as Record<string, unknown>;
  const usage = result.usage;
  const budget = command.payload.budget;
  if (!isRecord(usage) || !isRecord(budget)) {
    return false;
  }
  const fields = [
    "controller_tokens",
    "application_tokens",
    "child_tokens",
    "aggregate_tokens",
    "cost_micros",
  ] as const;
  if (fields.some((field) =>
    !nonNegativeInteger(usage[field]) ||
    !nonNegativeInteger(budget[field]) ||
    Number(usage[field]) > Number(budget[field])
  )) {
    return false;
  }
  if (
    Number(usage.aggregate_tokens) !==
      Number(usage.controller_tokens) +
        Number(usage.application_tokens) +
        Number(usage.child_tokens) ||
    result.continuation_id !== baseline.continuationId
  ) {
    return false;
  }
  if (command.operation === "session.compact") {
    return result.covered_leaf_id === baseline.leafId &&
      result.before_context_tokens === baseline.contextTokens &&
      typeof result.after_context_tokens === "number" &&
      result.after_context_tokens <= baseline.contextTokens;
  }
  return command.operation === "session.branch.summarize" &&
    result.previous_leaf_id === baseline.leafId;
}

function validateContextPreparationPayload(
  value: unknown,
): GatewayContextPreparation {
  if (isRecord(value) && hasExactKeys(value, [
    "bindingDigest",
    "continuationId",
    "privateRef",
  ])) {
    return Object.freeze({
      binding: validateContextBinding(value),
      previousLeafId: null,
      selectedEntryId: null,
    });
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["binding", "previousLeafId", "selectedEntryId"]) ||
    !nullableIdentifier(value.previousLeafId) ||
    !nullableIdentifier(value.selectedEntryId)
  ) {
    throw new GatewayStoreConflictError();
  }
  return Object.freeze({
    binding: validateContextBinding(value.binding),
    previousLeafId: value.previousLeafId,
    selectedEntryId: value.selectedEntryId,
  });
}

function validContextPreparation(
  command: SessionContextCommand | undefined,
  preparation: GatewayContextPreparation,
  currentBinding: GatewayContextBinding | undefined,
  activeBinding: GatewayContextBinding | undefined,
): boolean {
  if (command === undefined) {
    return false;
  }
  let continuationId: string;
  if (
    command.operation === "session.continuation.resume" ||
    command.operation === "session.continuation.delete" ||
    command.operation === "session.tree.navigate" ||
    command.operation === "session.fork" ||
    command.operation === "session.clone"
  ) {
    continuationId = command.payload.continuation_id;
  } else {
    return false;
  }
  if (
    !sameContextBinding(currentBinding, preparation.binding) ||
    continuationId !== preparation.binding.continuationId
  ) {
    return false;
  }
  if (
    command.operation === "session.continuation.resume" ||
    command.operation === "session.continuation.delete"
  ) {
    return preparation.previousLeafId === null &&
      preparation.selectedEntryId === null &&
      activeBinding?.continuationId !== preparation.binding.continuationId;
  }
  if (activeBinding?.continuationId !== preparation.binding.continuationId) {
    return false;
  }
  if (
    command.operation === "session.tree.navigate" ||
    command.operation === "session.fork"
  ) {
    return preparation.selectedEntryId === command.payload.entry_id;
  }
  if (command.operation === "session.clone") {
    return preparation.previousLeafId !== null &&
      preparation.selectedEntryId === preparation.previousLeafId;
  }
  return false;
}

function validateContextCommitPayload(
  value: unknown,
  command: SessionContextCommand,
): Readonly<{
  receipt: SessionContextReceipt;
  nextBinding: GatewayContextBinding | null;
  sourceBinding: GatewayContextBinding | null;
}> {
  if (
    !isRecord(value) ||
    (!hasExactKeys(value, ["nextBinding", "receipt"]) &&
      !hasExactKeys(value, ["nextBinding", "receipt", "sourceBinding"]))
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
  const sourceBinding = !Object.hasOwn(value, "sourceBinding") ||
      value.sourceBinding === null
    ? null
    : validateContextBinding(value.sourceBinding);
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
  if (sourceBinding !== null) {
    if (receipt.status !== "succeeded" || receipt.payload.result === null) {
      throw new GatewayStoreConflictError();
    }
    const result = receipt.payload.result as Record<string, unknown>;
    const sourceIds = [
      result.continuation_id,
      result.previous_continuation_id,
      result.source_continuation_id,
    ].filter((item): item is string => typeof item === "string");
    if (!sourceIds.includes(sourceBinding.continuationId)) {
      throw new GatewayStoreConflictError();
    }
  }
  return Object.freeze({ receipt, nextBinding, sourceBinding });
}

type ValidatedContextCommit = ReturnType<typeof validateContextCommitPayload>;

function validPreparedContextCommit(
  command: SessionContextCommand,
  preparation: GatewayContextPreparation | undefined,
  payload: ValidatedContextCommit,
  currentBinding: GatewayContextBinding | undefined,
  activeBinding: GatewayContextBinding | undefined,
): boolean {
  if (
    preparation === undefined ||
    !sameContextBinding(currentBinding, preparation.binding)
  ) {
    return false;
  }
  if (command.operation === "session.continuation.resume") {
    return payload.sourceBinding === null &&
      payload.nextBinding !== null &&
      payload.nextBinding.continuationId === command.payload.continuation_id;
  }
  if (command.operation === "session.continuation.delete") {
    return payload.sourceBinding === null &&
      payload.nextBinding === null &&
      (payload.receipt.payload.result as {
        readonly continuation_id: string;
      }).continuation_id === command.payload.continuation_id &&
      activeBinding?.continuationId !== command.payload.continuation_id;
  }
  if (command.operation === "session.tree.navigate") {
    const result = payload.receipt.payload.result as {
      readonly continuation_id: string;
      readonly previous_leaf_id: string | null;
    };
    return payload.sourceBinding === null &&
      payload.nextBinding !== null &&
      payload.nextBinding.continuationId === command.payload.continuation_id &&
      result.continuation_id === command.payload.continuation_id &&
      result.previous_leaf_id === preparation.previousLeafId &&
      preparation.selectedEntryId === command.payload.entry_id;
  }
  if (
    command.operation === "session.fork" ||
    command.operation === "session.clone"
  ) {
    const result = payload.receipt.payload.result as {
      readonly source_continuation_id: string;
      readonly new_continuation_id: string;
    };
    return payload.sourceBinding !== null &&
      payload.sourceBinding.continuationId === command.payload.continuation_id &&
      payload.nextBinding !== null &&
      payload.nextBinding.continuationId === result.new_continuation_id &&
      result.source_continuation_id === command.payload.continuation_id &&
      result.new_continuation_id !== command.payload.continuation_id;
  }
  return false;
}

function validLegacyContextMutationCommit(
  command: SessionContextCommand,
  payload: ValidatedContextCommit,
  currentBinding: GatewayContextBinding | undefined,
  activeBinding: GatewayContextBinding | undefined,
): boolean {
  if (
    command.operation !== "session.tree.navigate" &&
    command.operation !== "session.fork" &&
    command.operation !== "session.clone"
  ) {
    return false;
  }
  const continuationId = command.payload.continuation_id;
  if (
    payload.sourceBinding !== null ||
    currentBinding === undefined ||
    activeBinding?.continuationId !== continuationId
  ) {
    return false;
  }
  if (command.operation === "session.tree.navigate") {
    const result = payload.receipt.payload.result as {
      readonly continuation_id: string;
    };
    return result.continuation_id === continuationId &&
      (payload.nextBinding === null ||
        payload.nextBinding.continuationId === continuationId);
  }
  if (command.operation === "session.fork" || command.operation === "session.clone") {
    const result = payload.receipt.payload.result as {
      readonly source_continuation_id: string;
      readonly new_continuation_id: string;
    };
    return payload.nextBinding !== null &&
      result.source_continuation_id === continuationId &&
      result.new_continuation_id !== continuationId &&
      payload.nextBinding.continuationId === result.new_continuation_id;
  }
  return false;
}

export class GatewayDurableStore {
  private readonly records: LoadedRecord[] = [];
  private readonly recordsById = new Map<string, LoadedRecord>();
  private readonly eventCounts = new Map<number, number>();
  private readonly knownEventGenerations = new Set<number>();
  private readonly contextCommands = new Map<string, SessionContextCommand>();
  private readonly controlCommands = new Map<string, ControlCommand>();
  private readonly inputDeliveryValues = new Map<string, GatewayInputDelivery>();
  private readonly contextIdempotency = new Map<string, string>();
  private readonly contextCommits = new Map<
    string,
    Readonly<{
      receipt: SessionContextReceipt;
      nextBinding: GatewayContextBinding | null;
      sourceBinding: GatewayContextBinding | null;
    }>
  >();
  private readonly currentContextBindings = new Map<
    string,
    GatewayContextBinding
  >();
  private readonly tombstonedContextIds = new Set<string>();
  private initialContextBindingValue?: GatewayContextBinding;
  private activeContextBindingValue?: GatewayContextBinding;
  private readonly preparedContextBindings = new Map<
    string,
    GatewayContextBinding
  >();
  private readonly preparedContextStates = new Map<
    string,
    Readonly<{
      previousLeafId: string | null;
      selectedEntryId: string | null;
    }>
  >();
  private readonly preparedContextModelBaselines = new Map<
    string,
    GatewayContextModelBaseline
  >();
  private readonly faultInjector: StorageFaultInjector | undefined;
  private failed = false;
  private commandCount = 0;
  private eventCount = 0;
  private contextCommandCount = 0;
  private contextCommitCount = 0;
  private inputDeliveryProtocolRecordPosition?: number;
  private primeIdentity?: PrimeIdentityBinding;
  private primeCursor?: PrimeDaemonCursor;
  private readonly rlmLifecycleValues: GatewayRlmLifecycleObservation[] = [];
  private readonly rlmBindings = new Map<string, GatewayRlmBinding>();
  private readonly rlmMessageBindings = new Map<string, GatewayRlmMessageBinding>();
  private readonly rlmMessageActionsById = new Map<string, string>();
  private readonly deliveredRlmMessageIds = new Set<string>();
  private readonly activeRlmChildIds = new Set<string>();
  private readonly closedRlmChildIds = new Set<string>();

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

  async ensureInputDeliveryProtocol(): Promise<GatewayRecordReceipt> {
    return this.appendRecord(
      "input.delivery.protocol",
      "input-delivery-protocol:v1",
      { version: 1 },
    );
  }

  inputDeliveryProtocolPosition(): number | undefined {
    return this.inputDeliveryProtocolRecordPosition;
  }

  async commitInputDelivery(
    commandId: string,
    attachments: readonly GatewayInputAttachment[],
  ): Promise<GatewayRecordReceipt> {
    const command = this.controlCommands.get(commandId);
    const commandPosition = this.recordsById.get(
      `command:${commandId}`,
    )?.stored.position;
    if (
      this.inputDeliveryProtocolRecordPosition === undefined ||
      commandPosition === undefined ||
      commandPosition <= this.inputDeliveryProtocolRecordPosition
    ) {
      throw new GatewayStoreConflictError();
    }
    const deliveryDigest = sha256Hex(canonicalJsonBytes({ command, attachments }));
    const delivery = validateInputDeliveryPayload(
      {
        commandId,
        inputId: command?.type === "input.submit"
          ? command.payload.input_id
          : undefined,
        attachments,
        deliveryDigest,
      },
      command,
    );
    return this.appendRecord(
      "input.delivery.committed",
      `input-delivery:${delivery.commandId}`,
      delivery as unknown as Record<string, unknown>,
    );
  }

  async initializeContextBinding(
    binding: GatewayContextBinding,
  ): Promise<GatewayRecordReceipt> {
    const validated = validateContextBinding(binding);
    if (this.tombstonedContextIds.has(validated.continuationId)) {
      throw new GatewayStoreConflictError();
    }
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
    if (
      this.tombstonedContextIds.has(validated.continuationId) ||
      !this.currentContextBindings.has(validated.continuationId)
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "context.binding.rebound",
      `context-binding:${validated.continuationId}:${validated.bindingDigest}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async prepareContextOperation(
    commandId: string,
    binding: GatewayContextBinding,
    state: Readonly<{
      previousLeafId: string | null;
      selectedEntryId: string | null;
    }> = Object.freeze({ previousLeafId: null, selectedEntryId: null }),
  ): Promise<GatewayRecordReceipt> {
    const command = this.contextCommands.get(commandId);
    const preparation = validateContextPreparationPayload({
      binding,
      previousLeafId: state.previousLeafId,
      selectedEntryId: state.selectedEntryId,
    });
    const validated = preparation.binding;
    if (
      this.tombstonedContextIds.has(validated.continuationId) ||
      (this.preparedContextBindings.size !== 0 &&
        !this.preparedContextBindings.has(commandId)) ||
      !validContextPreparation(
        command,
        preparation,
        this.currentContextBindings.get(validated.continuationId),
        this.activeContextBindingValue,
      )
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "context.operation.prepared",
      `context-prepare:${commandId}`,
      preparation as unknown as Record<string, unknown>,
    );
  }

  async prepareContextModelOperation(
    commandId: string,
    baselineValue: GatewayContextModelBaseline,
  ): Promise<GatewayRecordReceipt> {
    const baseline = validateContextModelBaseline(baselineValue);
    const command = this.contextCommands.get(commandId);
    if (
      baseline.commandId !== commandId ||
      this.contextCommits.has(commandId) ||
      (this.preparedContextModelBaselines.size !== 0 &&
        !this.preparedContextModelBaselines.has(commandId)) ||
      !validContextModelPreparation(
        command,
        baseline,
        this.activeContextBindingValue,
      )
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "context.model.prepared",
      `context-model-prepare:${commandId}`,
      baseline as unknown as Record<string, unknown>,
    );
  }

  async commitContextOperation(
    receipt: unknown,
    nextBinding: GatewayContextBinding | null,
    sourceBinding: GatewayContextBinding | null = null,
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
        { receipt, nextBinding, sourceBinding },
        command,
      );
      if (
        (payload.nextBinding !== null &&
          this.tombstonedContextIds.has(payload.nextBinding.continuationId)) ||
        (payload.sourceBinding !== null &&
          this.tombstonedContextIds.has(payload.sourceBinding.continuationId))
      ) {
        throw new GatewayStoreConflictError();
      }
      if (
        payload.receipt.status === "succeeded" &&
        (command.operation === "session.continuation.resume" ||
          command.operation === "session.continuation.delete" ||
          command.operation === "session.tree.navigate" ||
          command.operation === "session.fork" ||
          command.operation === "session.clone")
      ) {
        const preparedBinding = this.preparedContextBindings.get(commandId);
        const preparedState = this.preparedContextStates.get(commandId);
        const preparation = preparedBinding === undefined || preparedState === undefined
          ? undefined
          : Object.freeze({ binding: preparedBinding, ...preparedState });
        if (
          !validPreparedContextCommit(
            command,
            preparation,
            payload,
            preparation === undefined
              ? undefined
              : this.currentContextBindings.get(
                preparation.binding.continuationId,
              ),
            this.activeContextBindingValue,
          )
        ) {
          throw new GatewayStoreConflictError();
        }
      }
      if (
        payload.receipt.status === "succeeded" &&
        (command.operation === "session.compact" ||
          command.operation === "session.branch.summarize") &&
        !validContextModelCommit(
          command,
          this.preparedContextModelBaselines.get(commandId),
          payload,
        )
      ) {
        throw new GatewayStoreConflictError();
      }
      const committed = await this.appendRecord(
        "context.operation.committed",
        `context-commit:${commandId}`,
        {
          receipt: payload.receipt,
          nextBinding: payload.nextBinding,
          sourceBinding: payload.sourceBinding,
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

  activeContextBinding(): GatewayContextBinding | undefined {
    return this.activeContextBindingValue;
  }

  preparedContextBinding(
    commandId: string,
  ): GatewayContextBinding | undefined {
    if (!nonEmptyIdentifier(commandId)) {
      throw new GatewayStoreConflictError();
    }
    return this.preparedContextBindings.get(commandId);
  }

  preparedContextState(commandId: string): Readonly<{
    previousLeafId: string | null;
    selectedEntryId: string | null;
  }> | undefined {
    if (!nonEmptyIdentifier(commandId)) {
      throw new GatewayStoreConflictError();
    }
    return this.preparedContextStates.get(commandId);
  }

  preparedContextOperations(): readonly Readonly<{
    command: SessionContextCommand;
    binding: GatewayContextBinding;
    previousLeafId: string | null;
    selectedEntryId: string | null;
  }>[] {
    return Object.freeze(
      [...this.preparedContextBindings.entries()].map(([commandId, binding]) => {
        const command = this.contextCommands.get(commandId);
        if (command === undefined || this.contextCommits.has(commandId)) {
          throw new GatewayStoreCorruptionError();
        }
        const state = this.preparedContextStates.get(commandId);
        if (state === undefined) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({ command, binding, ...state });
      }),
    );
  }

  preparedContextModelOperation(
    commandId: string,
  ): GatewayContextModelBaseline | undefined {
    if (!nonEmptyIdentifier(commandId)) {
      throw new GatewayStoreConflictError();
    }
    return this.preparedContextModelBaselines.get(commandId);
  }

  preparedContextModelOperations(): readonly Readonly<{
    command: SessionContextCommand;
    baseline: GatewayContextModelBaseline;
  }>[] {
    return Object.freeze(
      [...this.preparedContextModelBaselines.entries()].map(
        ([commandId, baseline]) => {
          const command = this.contextCommands.get(commandId);
          if (command === undefined || this.contextCommits.has(commandId)) {
            throw new GatewayStoreCorruptionError();
          }
          return Object.freeze({ command, baseline });
        },
      ),
    );
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
    const rebound = this.primeIdentity?.supervisorGeneration ===
        validated.supervisorGeneration &&
      (this.primeIdentity.activeSessionId !== validated.activeSessionId ||
        this.primeIdentity.transcriptSessionId !== validated.transcriptSessionId);
    return this.appendRecord(
      rebound ? "prime.identity.rebound" : "prime.identity",
      rebound
        ? `prime-identity:${validated.supervisorGeneration}:${sha256Hex(
          canonicalJsonBytes(validated),
        )}`
        : `prime-identity:${validated.supervisorGeneration}`,
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

  async recordRlmLifecycle(
    observation: GatewayRlmLifecycleObservation,
  ): Promise<GatewayRecordReceipt> {
    const validated = validateRlmLifecycleObservation(observation);
    if (
      (validated.type === "rlm.child.started" &&
        (this.activeRlmChildIds.has(validated.child_id) ||
          this.closedRlmChildIds.has(validated.child_id))) ||
      (validated.type === "rlm.child.terminal" &&
        !this.activeRlmChildIds.has(validated.child_id))
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "rlm.lifecycle",
      `rlm-lifecycle:${this.rlmLifecycleValues.length}:${validated.child_id}:${validated.type}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async recordRlmBinding(binding: GatewayRlmBinding): Promise<GatewayRecordReceipt> {
    const validated = validateRlmBinding(binding);
    return this.appendRecord(
      "rlm.binding",
      `rlm-binding:${validated.action_id}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async recordRlmMessageBinding(
    binding: GatewayRlmMessageBinding,
  ): Promise<GatewayRecordReceipt> {
    const validated = validateRlmMessageBinding(binding);
    const existingAction = this.rlmMessageActionsById.get(validated.message_id);
    if (existingAction !== undefined && existingAction !== validated.action_id) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "rlm.message.binding",
      `rlm-message-binding:${validated.action_id}`,
      validated as unknown as Record<string, unknown>,
    );
  }

  async recordRlmMessageDelivered(messageId: string): Promise<GatewayRecordReceipt> {
    if (
      !nonEmptyIdentifier(messageId) ||
      !this.rlmMessageActionsById.has(messageId) ||
      this.deliveredRlmMessageIds.has(messageId)
    ) {
      throw new GatewayStoreConflictError();
    }
    return this.appendRecord(
      "rlm.message.delivered",
      `rlm-message-delivered:${messageId}`,
      { message_id: messageId },
    );
  }

  rlmBinding(actionId: string): GatewayRlmBinding | undefined {
    if (!nonEmptyIdentifier(actionId)) {
      throw new GatewayStoreConflictError();
    }
    return this.rlmBindings.get(actionId);
  }

  rlmMessageBinding(actionId: string): GatewayRlmMessageBinding | undefined {
    if (!nonEmptyIdentifier(actionId)) {
      throw new GatewayStoreConflictError();
    }
    return this.rlmMessageBindings.get(actionId);
  }

  rlmMessageDelivered(): readonly string[] {
    return Object.freeze([...this.deliveredRlmMessageIds].sort());
  }

  rlmLifecycle(): readonly GatewayRlmLifecycleObservation[] {
    return Object.freeze([...this.rlmLifecycleValues]);
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

  inputDeliveries(): readonly GatewayInputDelivery[] {
    return Object.freeze([...this.inputDeliveryValues.values()]);
  }

  acceptedContextCommands(): readonly SessionContextCommand[] {
    return Object.freeze([...this.contextCommands.values()]);
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
      if (kind === "input.delivery.committed") {
        if (this.inputDeliveryProtocolRecordPosition === undefined) {
          throw new GatewayStoreCorruptionError();
        }
        const commandId = recordId.slice("input-delivery:".length);
        const delivery = validateInputDeliveryPayload(
          payload,
          this.controlCommands.get(commandId),
        );
        if (recordId !== `input-delivery:${delivery.commandId}`) {
          throw new GatewayStoreCorruptionError();
        }
        return delivery as unknown as Record<string, unknown>;
      }
      if (kind === "input.delivery.protocol") {
        if (
          recordId !== "input-delivery-protocol:v1" ||
          !hasExactKeys(payload, ["version"]) ||
          payload.version !== 1 ||
          this.inputDeliveryProtocolRecordPosition !== undefined
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({ version: 1 });
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
        if (
          recordId !== "context-binding:initial" ||
          this.tombstonedContextIds.has(binding.continuationId)
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "context.binding.rebound") {
        const binding = validateContextBinding(payload);
        if (
          recordId !==
            `context-binding:${binding.continuationId}:${binding.bindingDigest}` ||
          this.tombstonedContextIds.has(binding.continuationId) ||
          !this.currentContextBindings.has(binding.continuationId)
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "context.operation.prepared") {
        const commandId = recordId.startsWith("context-prepare:")
          ? recordId.slice("context-prepare:".length)
          : "";
        const command = this.contextCommands.get(commandId);
        const preparation = validateContextPreparationPayload(payload);
        const binding = preparation.binding;
        if (
          command === undefined ||
          recordId !== `context-prepare:${command.command_id}` ||
          this.tombstonedContextIds.has(binding.continuationId) ||
          (this.preparedContextBindings.size !== 0 &&
            !this.preparedContextBindings.has(commandId)) ||
          !validContextPreparation(
            command,
            preparation,
            this.currentContextBindings.get(binding.continuationId),
            this.activeContextBindingValue,
          )
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return preparation as unknown as Record<string, unknown>;
      }
      if (kind === "context.model.prepared") {
        const commandId = recordId.startsWith("context-model-prepare:")
          ? recordId.slice("context-model-prepare:".length)
          : "";
        const baseline = validateContextModelBaseline(payload);
        if (
          recordId !== `context-model-prepare:${commandId}` ||
          baseline.commandId !== commandId ||
          (this.preparedContextModelBaselines.size !== 0 &&
            !this.preparedContextModelBaselines.has(commandId)) ||
          !validContextModelPreparation(
            this.contextCommands.get(commandId),
            baseline,
            this.activeContextBindingValue,
          )
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return baseline as unknown as Record<string, unknown>;
      }
      if (kind === "context.operation.committed") {
        const commandId = recordId.startsWith("context-commit:")
          ? recordId.slice("context-commit:".length)
          : "";
        const command = this.contextCommands.get(commandId);
        if (command === undefined || recordId !== `context-commit:${command.command_id}`) {
          throw new GatewayStoreCorruptionError();
        }
        const legacyCommitShape = hasExactKeys(payload, ["nextBinding", "receipt"]);
        const committed = validateContextCommitPayload(payload, command);
        if (
          (committed.nextBinding !== null &&
            this.tombstonedContextIds.has(committed.nextBinding.continuationId)) ||
          (committed.sourceBinding !== null &&
            this.tombstonedContextIds.has(committed.sourceBinding.continuationId))
        ) {
          throw new GatewayStoreCorruptionError();
        }
        if (
          committed.receipt.status === "succeeded" &&
          (command.operation === "session.continuation.resume" ||
            command.operation === "session.continuation.delete" ||
            command.operation === "session.tree.navigate" ||
            command.operation === "session.fork" ||
            command.operation === "session.clone")
        ) {
          const preparedBinding = this.preparedContextBindings.get(commandId);
          const preparedState = this.preparedContextStates.get(commandId);
          const preparation = preparedBinding === undefined || preparedState === undefined
            ? undefined
            : Object.freeze({ binding: preparedBinding, ...preparedState });
          const validPrepared = validPreparedContextCommit(
              command,
              preparation,
              committed,
              preparation === undefined
                ? undefined
                : this.currentContextBindings.get(
                  preparation.binding.continuationId,
                ),
              this.activeContextBindingValue,
            );
          const validLegacy = preparation === undefined &&
            legacyCommitShape &&
            validLegacyContextMutationCommit(
              command,
              committed,
              this.currentContextBindings.get(command.payload.continuation_id),
              this.activeContextBindingValue,
            );
          if (!validPrepared && !validLegacy) {
            throw new GatewayStoreCorruptionError();
          }
        }
        if (
          committed.receipt.status === "succeeded" &&
          (command.operation === "session.compact" ||
            command.operation === "session.branch.summarize") &&
          !validContextModelCommit(
            command,
            this.preparedContextModelBaselines.get(commandId),
            committed,
          )
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return Object.freeze({
          receipt: committed.receipt,
          nextBinding: committed.nextBinding,
          sourceBinding: committed.sourceBinding,
        });
      }
      if (kind === "prime.identity") {
        const identity = validateIdentityPayload(payload);
        if (recordId !== `prime-identity:${identity.supervisorGeneration}`) {
          throw new GatewayStoreCorruptionError();
        }
        return identity as unknown as Record<string, unknown>;
      }
      if (kind === "prime.identity.rebound") {
        const identity = validateIdentityPayload(payload);
        if (
          this.primeIdentity?.supervisorGeneration !==
            identity.supervisorGeneration ||
          recordId !==
            `prime-identity:${identity.supervisorGeneration}:${sha256Hex(
              canonicalJsonBytes(identity),
            )}`
        ) {
          throw new GatewayStoreCorruptionError();
        }
        return identity as unknown as Record<string, unknown>;
      }
      if (kind === "rlm.lifecycle") {
        const observation = validateRlmLifecycleObservation(payload);
        const expectedRecordId = `rlm-lifecycle:${this.rlmLifecycleValues.length}:${observation.child_id}:${observation.type}`;
        if (recordId !== expectedRecordId) {
          throw new GatewayStoreCorruptionError();
        }
        return observation as unknown as Record<string, unknown>;
      }
      if (kind === "rlm.binding") {
        const binding = validateRlmBinding(payload);
        if (recordId !== `rlm-binding:${binding.action_id}`) {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "rlm.message.binding") {
        const binding = validateRlmMessageBinding(payload);
        if (recordId !== `rlm-message-binding:${binding.action_id}`) {
          throw new GatewayStoreCorruptionError();
        }
        return binding as unknown as Record<string, unknown>;
      }
      if (kind === "rlm.message.delivered") {
        if (!hasExactKeys(payload, ["message_id"]) || !nonEmptyIdentifier(payload.message_id)) {
          throw new GatewayStoreCorruptionError();
        }
        if (recordId !== `rlm-message-delivered:${payload.message_id}`) {
          throw new GatewayStoreCorruptionError();
        }
        return { message_id: payload.message_id };
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
      const command = record.payload.command as ControlCommand;
      if (this.controlCommands.has(command.command_id)) {
        throw new GatewayStoreCorruptionError();
      }
      this.controlCommands.set(command.command_id, command);
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
      this.activeContextBindingValue = binding;
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
      if (this.activeContextBindingValue?.continuationId === binding.continuationId) {
        this.activeContextBindingValue = binding;
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
    } else if (record.stored.kind === "context.operation.prepared") {
      const commandId = record.stored.record_id.slice("context-prepare:".length);
      if (this.preparedContextBindings.has(commandId)) {
        throw new GatewayStoreCorruptionError();
      }
      const preparation = record.payload as unknown as GatewayContextPreparation;
      this.preparedContextBindings.set(
        commandId,
        preparation.binding,
      );
      this.preparedContextStates.set(commandId, Object.freeze({
        previousLeafId: preparation.previousLeafId,
        selectedEntryId: preparation.selectedEntryId,
      }));
    } else if (record.stored.kind === "context.model.prepared") {
      const baseline = record.payload as unknown as GatewayContextModelBaseline;
      if (
        this.preparedContextModelBaselines.has(baseline.commandId) ||
        this.contextCommits.has(baseline.commandId)
      ) {
        throw new GatewayStoreCorruptionError();
      }
      this.preparedContextModelBaselines.set(baseline.commandId, baseline);
    } else if (record.stored.kind === "context.operation.committed") {
      const receipt = record.payload.receipt as SessionContextReceipt;
      const nextBinding = record.payload.nextBinding as GatewayContextBinding | null;
      const sourceBinding = record.payload.sourceBinding as
        | GatewayContextBinding
        | null;
      if (
        this.contextCommits.has(receipt.command_id) ||
        !this.contextCommands.has(receipt.command_id)
      ) {
        throw new GatewayStoreCorruptionError();
      }
      const committed = Object.freeze({ receipt, nextBinding, sourceBinding });
      this.contextCommits.set(receipt.command_id, committed);
      if (sourceBinding !== null) {
        if (
          this.tombstonedContextIds.has(sourceBinding.continuationId) ||
          !this.currentContextBindings.has(sourceBinding.continuationId)
        ) {
          throw new GatewayStoreCorruptionError();
        }
        this.currentContextBindings.set(
          sourceBinding.continuationId,
          sourceBinding,
        );
        if (
          this.initialContextBindingValue?.continuationId ===
            sourceBinding.continuationId
        ) {
          this.initialContextBindingValue = sourceBinding;
        }
        if (
          this.activeContextBindingValue?.continuationId ===
            sourceBinding.continuationId
        ) {
          this.activeContextBindingValue = sourceBinding;
        }
      }
      if (nextBinding !== null) {
        if (this.tombstonedContextIds.has(nextBinding.continuationId)) {
          throw new GatewayStoreCorruptionError();
        }
        this.currentContextBindings.set(
          nextBinding.continuationId,
          nextBinding,
        );
        this.activeContextBindingValue = nextBinding;
      } else if (
        receipt.status === "succeeded" &&
        receipt.operation === "session.continuation.delete"
      ) {
        const deleted = receipt.payload.result.continuation_id;
        if (this.activeContextBindingValue?.continuationId === deleted) {
          throw new GatewayStoreCorruptionError();
        }
        this.currentContextBindings.delete(deleted);
        this.tombstonedContextIds.add(deleted);
      }
      this.preparedContextBindings.delete(receipt.command_id);
      this.preparedContextStates.delete(receipt.command_id);
      this.preparedContextModelBaselines.delete(receipt.command_id);
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
    } else if (record.stored.kind === "input.delivery.committed") {
      const delivery = record.payload as unknown as GatewayInputDelivery;
      if (this.inputDeliveryValues.has(delivery.commandId)) {
        throw new GatewayStoreCorruptionError();
      }
      this.inputDeliveryValues.set(delivery.commandId, delivery);
    } else if (record.stored.kind === "input.delivery.protocol") {
      if (this.inputDeliveryProtocolRecordPosition !== undefined) {
        throw new GatewayStoreCorruptionError();
      }
      this.inputDeliveryProtocolRecordPosition = record.stored.position;
    } else if (
      record.stored.kind === "prime.identity" ||
      record.stored.kind === "prime.identity.rebound"
    ) {
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
    } else if (record.stored.kind === "rlm.lifecycle") {
      const observation = validateRlmLifecycleObservation(record.payload);
      if (observation.type === "rlm.child.started") {
        if (this.activeRlmChildIds.has(observation.child_id)) {
          throw new GatewayStoreCorruptionError();
        }
        if (this.closedRlmChildIds.has(observation.child_id)) {
          throw new GatewayStoreCorruptionError();
        }
        this.activeRlmChildIds.add(observation.child_id);
      } else if (!this.activeRlmChildIds.delete(observation.child_id)) {
        throw new GatewayStoreCorruptionError();
      } else {
        this.closedRlmChildIds.add(observation.child_id);
      }
      this.rlmLifecycleValues.push(observation);
    } else if (record.stored.kind === "rlm.binding") {
      const binding = validateRlmBinding(record.payload);
      const existing = this.rlmBindings.get(binding.action_id);
      if (existing !== undefined && canonicalJsonBytes(existing).compare(canonicalJsonBytes(binding)) !== 0) {
        throw new GatewayStoreCorruptionError();
      }
      if (existing === undefined) {
        this.rlmBindings.set(binding.action_id, binding);
      }
    } else if (record.stored.kind === "rlm.message.binding") {
      const binding = validateRlmMessageBinding(record.payload);
      const existing = this.rlmMessageBindings.get(binding.action_id);
      const existingAction = this.rlmMessageActionsById.get(binding.message_id);
      if (
        (existing !== undefined && canonicalJsonBytes(existing).compare(canonicalJsonBytes(binding)) !== 0) ||
        (existingAction !== undefined && existingAction !== binding.action_id)
      ) {
        throw new GatewayStoreCorruptionError();
      }
      if (existing === undefined) {
        this.rlmMessageBindings.set(binding.action_id, binding);
        this.rlmMessageActionsById.set(binding.message_id, binding.action_id);
      }
    } else if (record.stored.kind === "rlm.message.delivered") {
      const messageId = record.payload.message_id;
      if (
        !nonEmptyIdentifier(messageId) ||
        !this.rlmMessageActionsById.has(messageId) ||
        this.deliveredRlmMessageIds.has(messageId)
      ) {
        throw new GatewayStoreCorruptionError();
      }
      this.deliveredRlmMessageIds.add(messageId);
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
