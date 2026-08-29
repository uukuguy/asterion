import { createHash, randomUUID } from "node:crypto";
import { constants } from "node:fs";
import { lstat, open, readdir, realpath, unlink } from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { TextDecoder } from "node:util";

import {
  AtomicTargetExistsError,
  GatewayStoreCorruptionError,
  atomicWriteFile,
  canonicalJsonBytes,
  ensurePrivateDirectory,
  readPrivateRegularFile,
  syncPrivateDirectory,
} from "./durable-store.js";
import type {
  StorageFaultInjector,
} from "./durable-store.js";

export type PrivateValueRef = `private:${string}`;

export interface PrivateResultProjection {
  readonly receiptRef: string;
  readonly artifactIds: readonly string[];
  readonly mediaTypes: readonly string[];
}

export interface PrivateValueStoreOptions {
  readonly faultInjector?: StorageFaultInjector;
  readonly continuationRoot?: string;
}

export interface PrivateAttachmentMetadata {
  readonly sessionId: string;
  readonly inputId: string;
  readonly attachmentId: string;
  readonly mediaType: string;
  readonly sha256: string;
  readonly size: number;
}

export interface PrivateBoundAttachment extends PrivateAttachmentMetadata {
  readonly privateRef: PrivateValueRef;
  readonly body: Buffer;
}

export interface PrivateContinuationLocator {
  readonly continuationId: string;
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly supervisorGeneration: string;
  readonly sessionPath: string;
}

export interface PrivateContinuationBinding {
  readonly continuationId: string;
  readonly privateRef: PrivateValueRef;
  readonly bindingDigest: string;
}

export interface PrivateClientValueDescriptor {
  readonly reference: PrivateValueRef;
  readonly kind: string;
  readonly mediaType: string;
  readonly size: number;
  readonly sha256: string;
}

const PRIVATE_VALUE_FORMAT = "asterion.prime-private-value/v1";
const PRIVATE_INPUT_BINDING_FORMAT = "asterion.prime-private-input-binding/v1";
const PRIVATE_ATTACHMENT_BINDING_FORMAT = "asterion.prime-private-attachment-binding/v1";
const PRIVATE_CONTINUATION_FORMAT_V1 = "asterion.prime-private-continuation/v1";
const PRIVATE_CONTINUATION_FORMAT_V2 = "asterion.prime-private-continuation/v2";
const PRIVATE_REF_PATTERN = /^private:(?<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/u;
const OPAQUE_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/u;
const HEADER_LIMIT_BYTES = 1024;
const BINDING_LIMIT_BYTES = 4096;
const INPUT_LIMIT_BYTES = 1024 * 1024;
const RESULT_LIMIT_BYTES = 64 * 1024;
const CAPSULE_LIMIT_BYTES = 8 * 1024 * 1024;
const ATTACHMENT_LIMIT_BYTES = 8 * 1024 * 1024;
const CLIENT_VALUE_LIMIT_BYTES = 700 * 1024;
const CONTINUATION_LIMIT_BYTES = 16 * 1024;
const TRANSCRIPT_LIMIT_BYTES = 64 * 1024 * 1024;
const CONTINUATION_READY_ATTEMPTS = 40;
const CONTINUATION_READY_DELAY_MS = 25;
const UTF8_DECODER = new TextDecoder("utf-8", { fatal: true });

type PrivateValueKind = "input" | "result" | "capsule" | "attachment" | "continuation" | "client";

interface PrivateValueHeader {
  readonly format: typeof PRIVATE_VALUE_FORMAT;
  readonly reference: PrivateValueRef;
  readonly kind: PrivateValueKind;
  readonly size: number;
  readonly digest: string;
  readonly clientKind?: string;
  readonly mediaType?: string;
  readonly sessionId?: string;
}

interface PrivateInputBinding {
  readonly format: typeof PRIVATE_INPUT_BINDING_FORMAT;
  readonly commandId: string | null;
  readonly sourceRef: string;
  readonly valueDigest: string;
  readonly privateRef: PrivateValueRef;
}

interface PrivateAttachmentBinding extends PrivateAttachmentMetadata {
  readonly format: typeof PRIVATE_ATTACHMENT_BINDING_FORMAT;
  readonly privateRef: PrivateValueRef;
}

interface StoredContinuationLocator {
  readonly format:
    | typeof PRIVATE_CONTINUATION_FORMAT_V1
    | typeof PRIVATE_CONTINUATION_FORMAT_V2;
  readonly continuationId: string;
  readonly activeSessionId: string;
  readonly transcriptSessionId: string;
  readonly supervisorGeneration: string;
  readonly sessionFileName: string;
  readonly transcriptDevice: number | null;
  readonly transcriptInode: number | null;
  readonly transcriptSize: number;
  readonly transcriptSha256: string;
}

interface ContinuationRootIdentity {
  readonly path: string;
  readonly realPath: string;
  readonly device: number;
  readonly inode: number;
}

export class PrivateValueInvalidError extends Error {
  constructor() {
    super("Prime private value is invalid");
    this.name = "PrivateValueInvalidError";
  }
}

export class PrivateValueWriteError extends Error {
  constructor() {
    super("Prime private value write failed");
    this.name = "PrivateValueWriteError";
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

function isSortedUnique(values: readonly string[]): boolean {
  return values.every(
    (value, index) => index === 0 || String(values[index - 1]) < value,
  );
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

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function limitForKind(kind: PrivateValueKind): number {
  if (kind === "input") {
    return INPUT_LIMIT_BYTES;
  }
  if (kind === "result") {
    return RESULT_LIMIT_BYTES;
  }
  if (kind === "attachment") {
    return ATTACHMENT_LIMIT_BYTES;
  }
  if (kind === "continuation") {
    return CONTINUATION_LIMIT_BYTES;
  }
  if (kind === "client") {
    return CLIENT_VALUE_LIMIT_BYTES;
  }
  return CAPSULE_LIMIT_BYTES;
}

function parseReference(reference: string): string {
  const match = PRIVATE_REF_PATTERN.exec(reference);
  if (match?.groups?.id === undefined) {
    throw new PrivateValueInvalidError();
  }
  return match.groups.id;
}

function validateProjection(value: unknown): PrivateResultProjection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["receiptRef", "artifactIds", "mediaTypes"]) ||
    typeof value.receiptRef !== "string" ||
    !OPAQUE_ID_PATTERN.test(value.receiptRef) ||
    !Array.isArray(value.artifactIds) ||
    value.artifactIds.some(
      (item) => typeof item !== "string" || !OPAQUE_ID_PATTERN.test(item),
    ) ||
    !isSortedUnique(value.artifactIds as string[]) ||
    !Array.isArray(value.mediaTypes) ||
    value.mediaTypes.some(
      (item) => typeof item !== "string" || !MEDIA_TYPE_PATTERN.test(item),
    ) ||
    !isSortedUnique(value.mediaTypes as string[])
  ) {
    throw new PrivateValueInvalidError();
  }
  return deepFreeze({
    receiptRef: value.receiptRef,
    artifactIds: [...(value.artifactIds as string[])],
    mediaTypes: [...(value.mediaTypes as string[])],
  });
}

function validInputValue(value: unknown): value is string {
  return typeof value === "string" && Buffer.byteLength(value, "utf8") <= INPUT_LIMIT_BYTES;
}

function validateBindingKey(value: unknown): string {
  if (typeof value !== "string" || !OPAQUE_ID_PATTERN.test(value)) {
    throw new PrivateValueInvalidError();
  }
  return value;
}

function bindingDigest(
  kind: "attachment" | "command" | "public" | "result-command",
  values: readonly string[],
): string {
  return sha256(canonicalJsonBytes({ kind, values: [...values] }));
}

function attachmentBindingName(
  sessionId: string,
  inputId: string,
  attachmentId: string,
): string {
  return `attachment-${bindingDigest("attachment", [
    sessionId,
    inputId,
    attachmentId,
  ])}.json`;
}

function commandBindingName(commandId: string, sourceRef: string): string {
  return `command-${bindingDigest("command", [commandId, sourceRef])}.json`;
}

function publicBindingName(sourceRef: string): string {
  return `public-${bindingDigest("public", [sourceRef])}.json`;
}

function resultBindingName(
  commandId: string,
  actionId: string,
  sourceRef: string,
): string {
  return `result-${bindingDigest("result-command", [commandId, actionId, sourceRef])}.json`;
}

function parseBinding(bytes: Buffer): PrivateInputBinding {
  if (bytes.byteLength > BINDING_LIMIT_BYTES || bytes.at(-1) !== 0x0a) {
    throw new PrivateValueInvalidError();
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.subarray(0, -1).toString("utf8"));
  } catch {
    throw new PrivateValueInvalidError();
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "commandId",
      "format",
      "privateRef",
      "sourceRef",
      "valueDigest",
    ]) ||
    value.format !== PRIVATE_INPUT_BINDING_FORMAT ||
    (value.commandId !== null &&
      (typeof value.commandId !== "string" ||
        !OPAQUE_ID_PATTERN.test(value.commandId))) ||
    typeof value.sourceRef !== "string" ||
    !OPAQUE_ID_PATTERN.test(value.sourceRef) ||
    typeof value.valueDigest !== "string" ||
    !DIGEST_PATTERN.test(value.valueDigest) ||
    typeof value.privateRef !== "string" ||
    !PRIVATE_REF_PATTERN.test(value.privateRef)
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    format: PRIVATE_INPUT_BINDING_FORMAT,
    commandId: value.commandId,
    sourceRef: value.sourceRef,
    valueDigest: value.valueDigest,
    privateRef: value.privateRef as PrivateValueRef,
  });
}

function validateAttachmentMetadata(value: unknown): PrivateAttachmentMetadata {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "attachmentId",
      "inputId",
      "mediaType",
      "sessionId",
      "sha256",
      "size",
    ]) ||
    ![value.sessionId, value.inputId, value.attachmentId].every(
      (item) => typeof item === "string" && OPAQUE_ID_PATTERN.test(item),
    ) ||
    typeof value.mediaType !== "string" ||
    !MEDIA_TYPE_PATTERN.test(value.mediaType) ||
    typeof value.sha256 !== "string" ||
    !DIGEST_PATTERN.test(value.sha256) ||
    !Number.isSafeInteger(value.size) ||
    Number(value.size) < 0 ||
    Number(value.size) > ATTACHMENT_LIMIT_BYTES
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    sessionId: String(value.sessionId),
    inputId: String(value.inputId),
    attachmentId: String(value.attachmentId),
    mediaType: value.mediaType,
    sha256: value.sha256,
    size: Number(value.size),
  });
}

function parseAttachmentBinding(bytes: Buffer): PrivateAttachmentBinding {
  if (bytes.byteLength > BINDING_LIMIT_BYTES || bytes.at(-1) !== 0x0a) {
    throw new PrivateValueInvalidError();
  }
  let value: unknown;
  try {
    value = JSON.parse(bytes.subarray(0, -1).toString("utf8"));
  } catch {
    throw new PrivateValueInvalidError();
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "attachmentId",
      "format",
      "inputId",
      "mediaType",
      "privateRef",
      "sessionId",
      "sha256",
      "size",
    ]) ||
    value.format !== PRIVATE_ATTACHMENT_BINDING_FORMAT ||
    typeof value.privateRef !== "string" ||
    !PRIVATE_REF_PATTERN.test(value.privateRef)
  ) {
    throw new PrivateValueInvalidError();
  }
  const metadata = validateAttachmentMetadata({
    sessionId: value.sessionId,
    inputId: value.inputId,
    attachmentId: value.attachmentId,
    mediaType: value.mediaType,
    sha256: value.sha256,
    size: value.size,
  });
  return Object.freeze({
    format: PRIVATE_ATTACHMENT_BINDING_FORMAT,
    ...metadata,
    privateRef: value.privateRef as PrivateValueRef,
  });
}

function validateContinuationLocator(
  value: unknown,
): Omit<PrivateContinuationLocator, "sessionPath"> & { readonly sessionPath: string } {
  if (
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
    ].every((item) => typeof item === "string" && OPAQUE_ID_PATTERN.test(item)) ||
    typeof value.sessionPath !== "string" ||
    value.sessionPath.length === 0
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    continuationId: String(value.continuationId),
    activeSessionId: String(value.activeSessionId),
    transcriptSessionId: String(value.transcriptSessionId),
    supervisorGeneration: String(value.supervisorGeneration),
    sessionPath: value.sessionPath,
  });
}

async function regularPathExists(path: string): Promise<boolean> {
  try {
    await lstat(path);
    return true;
  } catch (error) {
    if (isRecord(error) && "code" in error && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
}

function parseHeader(value: unknown, reference: PrivateValueRef): PrivateValueHeader {
  const client = isRecord(value) && value.kind === "client";
  if (
    !isRecord(value) ||
    !hasExactKeys(value, client
      ? ["format", "reference", "kind", "size", "digest", "clientKind", "mediaType", "sessionId"]
      : ["format", "reference", "kind", "size", "digest"]) ||
    value.format !== PRIVATE_VALUE_FORMAT ||
    value.reference !== reference ||
    typeof value.kind !== "string" ||
    ![
      "attachment",
      "capsule",
      "continuation",
      "client",
      "input",
      "result",
    ].includes(String(value.kind)) ||
    !Number.isSafeInteger(value.size) ||
    Number(value.size) < 0 ||
    typeof value.digest !== "string" ||
    !DIGEST_PATTERN.test(value.digest)
    || (client && (
      typeof value.clientKind !== "string" || !OPAQUE_ID_PATTERN.test(value.clientKind) ||
      typeof value.mediaType !== "string" || !MEDIA_TYPE_PATTERN.test(value.mediaType) ||
      typeof value.sessionId !== "string" || !OPAQUE_ID_PATTERN.test(value.sessionId)
    ))
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    format: PRIVATE_VALUE_FORMAT,
    reference,
    kind: value.kind as PrivateValueKind,
    size: Number(value.size),
    digest: value.digest,
    ...(client ? {
      clientKind: value.clientKind as string,
      mediaType: value.mediaType as string,
      sessionId: value.sessionId as string,
    } : {}),
  });
}

async function validateContinuationRoot(
  path: string,
): Promise<ContinuationRootIdentity> {
  if (typeof path !== "string" || path.length === 0) {
    throw new PrivateValueInvalidError();
  }
  const normalized = resolve(path);
  const metadata = await lstat(normalized);
  if (
    metadata.isSymbolicLink() ||
    !metadata.isDirectory() ||
    (metadata.mode & 0o777) !== 0o700
  ) {
    throw new PrivateValueInvalidError();
  }
  return Object.freeze({
    path: normalized,
    realPath: await realpath(normalized),
    device: metadata.dev,
    inode: metadata.ino,
  });
}

export class PrivateValueStore {
  private readonly faultInjector: StorageFaultInjector | undefined;
  private bindingQueue: Promise<void> = Promise.resolve();

  private constructor(
    private readonly root: string,
    private readonly privateRoot: string,
    private readonly valuesRoot: string,
    private readonly bindingsRoot: string,
    private readonly continuationRoot: ContinuationRootIdentity | undefined,
    options: PrivateValueStoreOptions,
  ) {
    this.faultInjector = options.faultInjector;
  }

  static async open(
    root: string,
    options: PrivateValueStoreOptions = {},
  ): Promise<PrivateValueStore> {
    const privateRoot = join(root, "private");
    const valuesRoot = join(privateRoot, "values");
    const bindingsRoot = join(privateRoot, "input-bindings");
    try {
      await ensurePrivateDirectory(root);
      await ensurePrivateDirectory(privateRoot);
      await ensurePrivateDirectory(valuesRoot);
      await ensurePrivateDirectory(bindingsRoot);
      const continuationRoot = options.continuationRoot === undefined
        ? undefined
        : await validateContinuationRoot(options.continuationRoot);
      return new PrivateValueStore(
        root,
        privateRoot,
        valuesRoot,
        bindingsRoot,
        continuationRoot,
        options,
      );
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  async putInput(value: string): Promise<PrivateValueRef> {
    if (!validInputValue(value)) {
      throw new PrivateValueInvalidError();
    }
    return this.put("input", Buffer.from(value, "utf8"));
  }

  async readInput(reference: PrivateValueRef): Promise<string> {
    const bytes = await this.read(reference, "input");
    try {
      return UTF8_DECODER.decode(bytes);
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  async bindInputReference(
    commandId: string,
    sourceRef: string,
    value: string,
  ): Promise<PrivateValueRef> {
    return this.serializeBinding(async () => {
      const commandKey = validateBindingKey(commandId);
      const publicKey = validateBindingKey(sourceRef);
      if (!validInputValue(value)) {
        throw new PrivateValueInvalidError();
      }
      const valueDigest = sha256(Buffer.from(value, "utf8"));
      const publicBinding = await this.readBinding(publicBindingName(publicKey));
      if (publicBinding !== undefined) {
        this.assertBinding(publicBinding, {
          commandId: null,
          sourceRef,
          valueDigest,
        });
        await this.syncBindingsRootForAcknowledgement();
        await this.bindCommandReference(
          commandKey,
          sourceRef,
          valueDigest,
          publicBinding.privateRef,
        );
        return publicBinding.privateRef;
      }
      const privateRef = await this.putInput(value);
      await this.writeBinding(publicBindingName(publicKey), {
        format: PRIVATE_INPUT_BINDING_FORMAT,
        commandId: null,
        sourceRef,
        valueDigest,
        privateRef,
      });
      await this.bindCommandReference(commandKey, sourceRef, valueDigest, privateRef);
      return privateRef;
    });
  }

  async readBoundInputReference(sourceRef: string): Promise<string> {
    const publicKey = validateBindingKey(sourceRef);
    const binding = await this.readBinding(publicBindingName(publicKey));
    if (binding === undefined) {
      throw new PrivateValueInvalidError();
    }
    return this.readInput(binding.privateRef);
  }

  async bindResultReference(
    commandId: string,
    actionId: string,
    sourceRef: string,
    value: PrivateResultProjection,
  ): Promise<PrivateValueRef> {
    return this.serializeBinding(async () => {
      const commandKey = validateBindingKey(commandId);
      const actionKey = validateBindingKey(actionId);
      const publicKey = validateBindingKey(sourceRef);
      const projection = validateProjection(value);
      if (projection.receiptRef !== publicKey) {
        throw new PrivateValueInvalidError();
      }
      const valueDigest = sha256(canonicalJsonBytes(projection));
      const targetName = resultBindingName(commandKey, actionKey, publicKey);
      const existing = await this.readBinding(targetName);
      if (existing !== undefined) {
        this.assertBinding(existing, {
          commandId: commandKey,
          sourceRef: publicKey,
          valueDigest,
        });
        await this.syncBindingsRootForAcknowledgement();
        return existing.privateRef;
      }
      const privateRef = await this.putResult(projection);
      await this.writeBinding(targetName, {
        format: PRIVATE_INPUT_BINDING_FORMAT,
        commandId: commandKey,
        sourceRef: publicKey,
        valueDigest,
        privateRef,
      });
      return privateRef;
    });
  }

  async readBoundResultReference(
    commandId: string,
    actionId: string,
    sourceRef: string,
  ): Promise<PrivateValueRef> {
    const commandKey = validateBindingKey(commandId);
    const actionKey = validateBindingKey(actionId);
    const publicKey = validateBindingKey(sourceRef);
    const binding = await this.readBinding(
      resultBindingName(commandKey, actionKey, publicKey),
    );
    if (binding === undefined) {
      throw new PrivateValueInvalidError();
    }
    const projection = await this.readResult(binding.privateRef);
    if (projection.receiptRef !== publicKey) {
      throw new PrivateValueInvalidError();
    }
    const valueDigest = sha256(canonicalJsonBytes(projection));
    this.assertBinding(binding, {
      commandId: commandKey,
      sourceRef: publicKey,
      valueDigest,
    });
    await this.syncBindingsRootForAcknowledgement();
    return binding.privateRef;
  }

  async bindAttachment(
    metadataValue: PrivateAttachmentMetadata,
    value: Uint8Array,
  ): Promise<PrivateValueRef> {
    return this.serializeBinding(async () => {
      const metadata = validateAttachmentMetadata(metadataValue);
      if (
        !(value instanceof Uint8Array) ||
        value.byteLength !== metadata.size ||
        value.byteLength > ATTACHMENT_LIMIT_BYTES ||
        sha256(value) !== metadata.sha256
      ) {
        throw new PrivateValueInvalidError();
      }
      const targetName = attachmentBindingName(
        metadata.sessionId,
        metadata.inputId,
        metadata.attachmentId,
      );
      const existing = await this.readAttachmentBinding(targetName);
      if (existing !== undefined) {
        this.assertAttachmentBinding(existing, metadata);
        const body = await this.read(existing.privateRef, "attachment");
        if (body.byteLength !== metadata.size || sha256(body) !== metadata.sha256) {
          throw new PrivateValueInvalidError();
        }
        await this.syncBindingsRootForAcknowledgement();
        return existing.privateRef;
      }
      const privateRef = await this.put("attachment", Buffer.from(value));
      await this.writeAttachmentBinding(targetName, {
        format: PRIVATE_ATTACHMENT_BINDING_FORMAT,
        ...metadata,
        privateRef,
      });
      return privateRef;
    });
  }

  async readBoundAttachment(
    sessionId: string,
    inputId: string,
    attachmentId: string,
  ): Promise<PrivateBoundAttachment> {
    const sessionKey = validateBindingKey(sessionId);
    const inputKey = validateBindingKey(inputId);
    const attachmentKey = validateBindingKey(attachmentId);
    const binding = await this.readAttachmentBinding(
      attachmentBindingName(
        sessionKey,
        inputKey,
        attachmentKey,
      ),
    );
    if (binding === undefined) {
      throw new PrivateValueInvalidError();
    }
    const body = Buffer.from(await this.read(binding.privateRef, "attachment"));
    if (body.byteLength !== binding.size || sha256(body) !== binding.sha256) {
      throw new PrivateValueInvalidError();
    }
    return Object.freeze({
      sessionId: binding.sessionId,
      inputId: binding.inputId,
      attachmentId: binding.attachmentId,
      mediaType: binding.mediaType,
      sha256: binding.sha256,
      size: binding.size,
      privateRef: binding.privateRef,
      body,
    });
  }

  async readBoundAttachments(
    sessionId: string,
    inputId: string,
    expectedValue: readonly PrivateAttachmentMetadata[],
  ): Promise<readonly PrivateBoundAttachment[]> {
    const sessionKey = validateBindingKey(sessionId);
    const inputKey = validateBindingKey(inputId);
    if (!Array.isArray(expectedValue)) {
      throw new PrivateValueInvalidError();
    }
    const expected = expectedValue.map((value) => validateAttachmentMetadata(value));
    if (expected.some((metadata, index) => {
      const previous = expected[index - 1];
      return metadata.sessionId !== sessionKey ||
        metadata.inputId !== inputKey ||
        (previous !== undefined &&
          previous.attachmentId >= metadata.attachmentId);
    })) {
      throw new PrivateValueInvalidError();
    }
    try {
      await this.ensureBindingsRoot();
      const actual = new Map<string, PrivateAttachmentBinding>();
      for (const name of await readdir(this.bindingsRoot)) {
        if (!name.startsWith("attachment-") || !name.endsWith(".json")) {
          continue;
        }
        const binding = await this.readAttachmentBinding(name);
        if (binding === undefined) {
          throw new PrivateValueInvalidError();
        }
        if (binding.sessionId !== sessionKey || binding.inputId !== inputKey) {
          continue;
        }
        if (actual.has(binding.attachmentId)) {
          throw new PrivateValueInvalidError();
        }
        actual.set(binding.attachmentId, binding);
      }
      if (
        actual.size !== expected.length ||
        expected.some((metadata) => {
          const binding = actual.get(metadata.attachmentId);
          if (binding === undefined) {
            return true;
          }
          try {
            this.assertAttachmentBinding(binding, metadata);
            return false;
          } catch {
            return true;
          }
        })
      ) {
        throw new PrivateValueInvalidError();
      }
      const delivered = await Promise.all(expected.map((metadata) =>
        this.readBoundAttachment(
          metadata.sessionId,
          metadata.inputId,
          metadata.attachmentId,
        )
      ));
      return Object.freeze(delivered);
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  async putContinuationLocator(
    value: PrivateContinuationLocator,
  ): Promise<PrivateContinuationBinding> {
    const locator = validateContinuationLocator(value);
    const transcript = await this.inspectReadyContinuation(locator.sessionPath);
    const stored: StoredContinuationLocator = {
      format: PRIVATE_CONTINUATION_FORMAT_V2,
      continuationId: locator.continuationId,
      activeSessionId: locator.activeSessionId,
      transcriptSessionId: locator.transcriptSessionId,
      supervisorGeneration: locator.supervisorGeneration,
      sessionFileName: transcript.fileName,
      transcriptDevice: transcript.device,
      transcriptInode: transcript.inode,
      transcriptSize: transcript.size,
      transcriptSha256: transcript.digest,
    };
    const body = canonicalJsonBytes(stored);
    const privateRef = await this.put("continuation", body);
    return Object.freeze({
      continuationId: locator.continuationId,
      privateRef,
      bindingDigest: sha256(body),
    });
  }

  private async inspectReadyContinuation(
    sessionPath: string,
  ): Promise<Readonly<{
    fileName: string;
    device: number;
    inode: number;
    size: number;
    digest: string;
  }>> {
    for (let attempt = 0; attempt < CONTINUATION_READY_ATTEMPTS; attempt += 1) {
      try {
        return await this.inspectContinuation(sessionPath);
      } catch (error) {
        if (
          !(error instanceof PrivateValueInvalidError) ||
          attempt + 1 === CONTINUATION_READY_ATTEMPTS
        ) {
          throw error;
        }
        await new Promise<void>((resolveDelay) => {
          setTimeout(resolveDelay, CONTINUATION_READY_DELAY_MS);
        });
      }
    }
    throw new PrivateValueInvalidError();
  }

  async ensurePreparedContinuationLocator(
    bindingValue: PrivateContinuationBinding,
  ): Promise<Readonly<{
    binding: PrivateContinuationBinding;
    locator: PrivateContinuationLocator;
  }>> {
    const locator = await this.readContinuationLocator(bindingValue);
    const { stored } = await this.readStoredContinuation(bindingValue);
    if (stored.format === PRIVATE_CONTINUATION_FORMAT_V2) {
      return Object.freeze({ binding: bindingValue, locator });
    }
    const binding = await this.putContinuationLocator(locator);
    return Object.freeze({ binding, locator });
  }

  async readContinuationLocator(
    bindingValue: PrivateContinuationBinding,
  ): Promise<PrivateContinuationLocator> {
    const { stored, sessionPath } = await this.readStoredContinuation(
      bindingValue,
    );
    const transcript = await this.inspectContinuation(sessionPath);
    if (
      (stored.format === PRIVATE_CONTINUATION_FORMAT_V2 &&
        (transcript.device !== stored.transcriptDevice ||
          transcript.inode !== stored.transcriptInode)) ||
      transcript.size !== stored.transcriptSize ||
      transcript.digest !== stored.transcriptSha256
    ) {
      throw new PrivateValueInvalidError();
    }
    return this.projectContinuationLocator(stored, sessionPath);
  }

  async readPreparedContinuationLocator(
    bindingValue: PrivateContinuationBinding,
    allowMissing: boolean,
  ): Promise<PrivateContinuationLocator> {
    if (typeof allowMissing !== "boolean") {
      throw new PrivateValueInvalidError();
    }
    const { stored, sessionPath } = await this.readStoredContinuation(
      bindingValue,
    );
    if (
      stored.transcriptDevice === null ||
      stored.transcriptInode === null
    ) {
      throw new PrivateValueInvalidError();
    }
    try {
      const transcript = await this.inspectContinuation(sessionPath);
      if (
        transcript.device !== stored.transcriptDevice ||
        transcript.inode !== stored.transcriptInode
      ) {
        throw new PrivateValueInvalidError();
      }
    } catch {
      if (!allowMissing) {
        throw new PrivateValueInvalidError();
      }
      await this.assertContinuationRootIdentity();
      if (await regularPathExists(sessionPath)) {
        throw new PrivateValueInvalidError();
      }
    }
    return this.projectContinuationLocator(stored, sessionPath);
  }

  /**
   * Re-pin a transcript only after a caller has independently authenticated a
   * Prime recovery. This is deliberately separate from ordinary reads: it
   * accepts a replaced inode, but never a different bound continuation.
   */
  async rebindRecoveredContinuationLocator(
    bindingValue: PrivateContinuationBinding,
    expected: Omit<PrivateContinuationLocator, "sessionPath">,
  ): Promise<PrivateContinuationBinding> {
    const { stored, sessionPath } = await this.readStoredContinuation(bindingValue);
    const pinned = this.projectContinuationLocator(stored, sessionPath);
    if (
      pinned.continuationId !== expected.continuationId ||
      pinned.activeSessionId !== expected.activeSessionId ||
      pinned.transcriptSessionId !== expected.transcriptSessionId
    ) {
      throw new PrivateValueInvalidError();
    }
    return this.putContinuationLocator({ ...expected, sessionPath: pinned.sessionPath });
  }

  private async readStoredContinuation(
    bindingValue: PrivateContinuationBinding,
  ): Promise<Readonly<{
    stored: StoredContinuationLocator;
    sessionPath: string;
  }>> {
    if (
      !isRecord(bindingValue) ||
      !hasExactKeys(bindingValue, [
        "bindingDigest",
        "continuationId",
        "privateRef",
      ]) ||
      typeof bindingValue.continuationId !== "string" ||
      !OPAQUE_ID_PATTERN.test(bindingValue.continuationId) ||
      typeof bindingValue.privateRef !== "string" ||
      !PRIVATE_REF_PATTERN.test(bindingValue.privateRef) ||
      typeof bindingValue.bindingDigest !== "string" ||
      !DIGEST_PATTERN.test(bindingValue.bindingDigest) ||
      this.continuationRoot === undefined
    ) {
      throw new PrivateValueInvalidError();
    }
    const body = await this.read(
      bindingValue.privateRef as PrivateValueRef,
      "continuation",
    );
    if (sha256(body) !== bindingValue.bindingDigest) {
      throw new PrivateValueInvalidError();
    }
    let stored: unknown;
    try {
      stored = JSON.parse(UTF8_DECODER.decode(body));
    } catch {
      throw new PrivateValueInvalidError();
    }
    if (!canonicalJsonBytes(stored).equals(body)) {
      throw new PrivateValueInvalidError();
    }
    if (
      !isRecord(stored) ||
      !(
        (stored.format === PRIVATE_CONTINUATION_FORMAT_V1 &&
          hasExactKeys(stored, [
            "activeSessionId",
            "continuationId",
            "format",
            "sessionFileName",
            "supervisorGeneration",
            "transcriptSessionId",
            "transcriptSha256",
            "transcriptSize",
          ])) ||
        (stored.format === PRIVATE_CONTINUATION_FORMAT_V2 &&
          hasExactKeys(stored, [
            "activeSessionId",
            "continuationId",
            "format",
            "sessionFileName",
            "supervisorGeneration",
            "transcriptDevice",
            "transcriptInode",
            "transcriptSessionId",
            "transcriptSha256",
            "transcriptSize",
          ]))
      ) ||
      stored.continuationId !== bindingValue.continuationId ||
      ![
        stored.activeSessionId,
        stored.continuationId,
        stored.supervisorGeneration,
        stored.transcriptSessionId,
      ].every((item) => typeof item === "string" && OPAQUE_ID_PATTERN.test(item)) ||
      typeof stored.sessionFileName !== "string" ||
      basename(stored.sessionFileName) !== stored.sessionFileName ||
      (stored.format === PRIVATE_CONTINUATION_FORMAT_V2 &&
        (!Number.isSafeInteger(stored.transcriptDevice) ||
          Number(stored.transcriptDevice) < 0 ||
          !Number.isSafeInteger(stored.transcriptInode) ||
          Number(stored.transcriptInode) < 0)) ||
      typeof stored.transcriptSha256 !== "string" ||
      !DIGEST_PATTERN.test(stored.transcriptSha256) ||
      !Number.isSafeInteger(stored.transcriptSize) ||
      Number(stored.transcriptSize) < 1
    ) {
      throw new PrivateValueInvalidError();
    }
    const sessionPath = join(this.continuationRoot.path, stored.sessionFileName);
    return Object.freeze({
      stored: Object.freeze({
        format: stored.format,
        continuationId: String(stored.continuationId),
        activeSessionId: String(stored.activeSessionId),
        transcriptSessionId: String(stored.transcriptSessionId),
        supervisorGeneration: String(stored.supervisorGeneration),
        sessionFileName: stored.sessionFileName,
        transcriptDevice: stored.format === PRIVATE_CONTINUATION_FORMAT_V2
          ? Number(stored.transcriptDevice)
          : null,
        transcriptInode: stored.format === PRIVATE_CONTINUATION_FORMAT_V2
          ? Number(stored.transcriptInode)
          : null,
        transcriptSize: Number(stored.transcriptSize),
        transcriptSha256: stored.transcriptSha256,
      }),
      sessionPath,
    });
  }

  private projectContinuationLocator(
    stored: StoredContinuationLocator,
    sessionPath: string,
  ): PrivateContinuationLocator {
    return Object.freeze({
      continuationId: String(stored.continuationId),
      activeSessionId: String(stored.activeSessionId),
      transcriptSessionId: String(stored.transcriptSessionId),
      supervisorGeneration: String(stored.supervisorGeneration),
      sessionPath,
    });
  }

  async putResult(value: PrivateResultProjection): Promise<PrivateValueRef> {
    const projection = validateProjection(value);
    return this.put("result", canonicalJsonBytes(projection));
  }

  async readResult(reference: PrivateValueRef): Promise<PrivateResultProjection> {
    const bytes = await this.read(reference, "result");
    try {
      return validateProjection(JSON.parse(UTF8_DECODER.decode(bytes)));
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    }
  }

  async putCapsule(value: Uint8Array): Promise<PrivateValueRef> {
    if (!(value instanceof Uint8Array)) {
      throw new PrivateValueInvalidError();
    }
    return this.put("capsule", Buffer.from(value));
  }

  async putClientValue(
    sessionId: string,
    kind: string,
    mediaType: string,
    value: Uint8Array,
    reference?: PrivateValueRef,
  ): Promise<PrivateClientValueDescriptor> {
    if (
      !OPAQUE_ID_PATTERN.test(sessionId) ||
      !OPAQUE_ID_PATTERN.test(kind) ||
      !MEDIA_TYPE_PATTERN.test(mediaType) ||
      !(value instanceof Uint8Array)
    ) {
      throw new PrivateValueInvalidError();
    }
    if (reference !== undefined && typeof reference !== "string") {
      throw new PrivateValueInvalidError();
    }
    const expectedDigest = sha256(value);
    if (reference !== undefined) {
      try {
        const existing = await this.describeClientValue(reference, sessionId);
        if (existing.kind !== kind || existing.mediaType !== mediaType || existing.size !== value.byteLength || existing.sha256 !== expectedDigest) {
          throw new PrivateValueInvalidError();
        }
        return existing;
      } catch (error) {
        if (!(error instanceof PrivateValueInvalidError)) throw error;
      }
    }
    const written = await this.put("client", Buffer.from(value), {
      clientKind: kind,
      mediaType,
      sessionId,
    }, reference);
    return this.describeClientValue(written, sessionId);
  }

  async describeClientValue(
    reference: string,
    sessionId?: string,
  ): Promise<PrivateClientValueDescriptor> {
    const header = await this.clientHeader(reference, sessionId);
    return Object.freeze({
      reference: header.reference,
      kind: header.clientKind!,
      mediaType: header.mediaType!,
      size: header.size,
      sha256: header.digest,
    });
  }

  async readClientValue(
    reference: string,
    maxBytes: number,
    sessionId?: string,
  ): Promise<Buffer> {
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) {
      throw new PrivateValueInvalidError();
    }
    const header = await this.clientHeader(reference, sessionId);
    if (header.size > maxBytes) {
      throw new PrivateValueInvalidError();
    }
    return this.read(header.reference, "client");
  }

  async deleteClientValue(reference: string, sessionId: string): Promise<void> {
    try {
      const identifier = parseReference(reference);
      const path = join(this.valuesRoot, `${identifier}.value`);
      const metadata = await lstat(path);
      const header = await this.clientHeader(reference, sessionId);
      if (metadata.isSymbolicLink() || !metadata.isFile()) {
        throw new PrivateValueInvalidError();
      }
      await unlink(path);
      await syncPrivateDirectory(this.valuesRoot);
    } catch (error) {
      if (isRecord(error) && "code" in error && error.code === "ENOENT") {
        return;
      }
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    }
  }

  async readCapsule(reference: PrivateValueRef): Promise<Buffer> {
    return Buffer.from(await this.read(reference, "capsule"));
  }

  toString(): string {
    return "[Prime private value store]";
  }

  private async put(
    kind: PrivateValueKind,
    body: Buffer,
    client?: Readonly<{ readonly clientKind: string; readonly mediaType: string; readonly sessionId: string }>,
    requestedReference?: PrivateValueRef,
  ): Promise<PrivateValueRef> {
    if (body.byteLength > limitForKind(kind)) {
      throw new PrivateValueInvalidError();
    }
    const reference = requestedReference ?? `private:${randomUUID()}` as PrivateValueRef;
    parseReference(reference);
    const header: PrivateValueHeader = {
      format: PRIVATE_VALUE_FORMAT,
      reference,
      kind,
      size: body.byteLength,
      digest: sha256(body),
      ...(kind === "client" && client !== undefined ? client : {}),
    };
    const bytes = Buffer.concat([
      canonicalJsonBytes(header),
      Buffer.from("\n"),
      body,
    ]);
    try {
      await this.ensureRoots();
      await atomicWriteFile(
        this.valuesRoot,
        `${parseReference(reference)}.value`,
        bytes,
        this.faultInjector,
      );
      return reference;
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueWriteError();
    }
  }

  private async bindCommandReference(
    commandKey: string,
    sourceRef: string,
    valueDigest: string,
    privateRef: PrivateValueRef,
  ): Promise<void> {
    const targetName = commandBindingName(commandKey, sourceRef);
    const binding = await this.readBinding(targetName);
    if (binding !== undefined) {
      this.assertBinding(binding, {
        commandId: commandKey,
        sourceRef,
        valueDigest,
      });
      if (binding.privateRef !== privateRef) {
        throw new PrivateValueInvalidError();
      }
      await this.syncBindingsRootForAcknowledgement();
      return;
    }
    await this.writeBinding(targetName, {
      format: PRIVATE_INPUT_BINDING_FORMAT,
      commandId: commandKey,
      sourceRef,
      valueDigest,
      privateRef,
    });
  }

  private assertBinding(
    binding: PrivateInputBinding,
    expected: {
      readonly commandId: string | null;
      readonly sourceRef: string;
      readonly valueDigest: string;
    },
  ): void {
    if (
      binding.commandId !== expected.commandId ||
      binding.sourceRef !== expected.sourceRef ||
      binding.valueDigest !== expected.valueDigest
    ) {
      throw new PrivateValueInvalidError();
    }
  }

  private async readBinding(targetName: string): Promise<PrivateInputBinding | undefined> {
    try {
      await this.ensureBindingsRoot();
      const path = join(this.bindingsRoot, targetName);
      if (!(await regularPathExists(path))) {
        return undefined;
      }
      const bytes = await readPrivateRegularFile(
        path,
        BINDING_LIMIT_BYTES,
      );
      return parseBinding(bytes);
    } catch (error) {
      throw new PrivateValueInvalidError();
    }
  }

  private async readAttachmentBinding(
    targetName: string,
  ): Promise<PrivateAttachmentBinding | undefined> {
    try {
      await this.ensureBindingsRoot();
      const path = join(this.bindingsRoot, targetName);
      if (!(await regularPathExists(path))) {
        return undefined;
      }
      return parseAttachmentBinding(
        await readPrivateRegularFile(path, BINDING_LIMIT_BYTES),
      );
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  private assertAttachmentBinding(
    binding: PrivateAttachmentBinding,
    expected: PrivateAttachmentMetadata,
  ): void {
    if (
      binding.sessionId !== expected.sessionId ||
      binding.inputId !== expected.inputId ||
      binding.attachmentId !== expected.attachmentId ||
      binding.mediaType !== expected.mediaType ||
      binding.sha256 !== expected.sha256 ||
      binding.size !== expected.size
    ) {
      throw new PrivateValueInvalidError();
    }
  }

  private async writeAttachmentBinding(
    targetName: string,
    binding: PrivateAttachmentBinding,
  ): Promise<void> {
    try {
      await this.ensureBindingsRoot();
      await atomicWriteFile(
        this.bindingsRoot,
        targetName,
        Buffer.concat([canonicalJsonBytes(binding), Buffer.from("\n")]),
        this.faultInjector,
      );
      await this.ensureBindingsRoot();
    } catch (error) {
      if (!(error instanceof AtomicTargetExistsError)) {
        throw new PrivateValueWriteError();
      }
      const existing = await this.readAttachmentBinding(targetName);
      if (existing === undefined) {
        throw new PrivateValueWriteError();
      }
      this.assertAttachmentBinding(existing, binding);
      if (existing.privateRef !== binding.privateRef) {
        throw new PrivateValueInvalidError();
      }
      await this.syncBindingsRootForAcknowledgement();
    }
  }

  private async writeBinding(
    targetName: string,
    binding: PrivateInputBinding,
  ): Promise<void> {
    try {
      await this.ensureBindingsRoot();
      await atomicWriteFile(
        this.bindingsRoot,
        targetName,
        Buffer.concat([canonicalJsonBytes(binding), Buffer.from("\n")]),
        this.faultInjector,
      );
      await this.ensureBindingsRoot();
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      if (!(error instanceof AtomicTargetExistsError)) {
        throw new PrivateValueWriteError();
      }
      const existing = await this.readBinding(targetName);
      if (existing === undefined) {
        throw new PrivateValueWriteError();
      }
      this.assertBinding(existing, binding);
      if (existing.privateRef !== binding.privateRef) {
        throw new PrivateValueInvalidError();
      }
      await this.syncBindingsRootForAcknowledgement();
    }
  }

  private async read(
    reference: PrivateValueRef,
    expectedKind: PrivateValueKind,
  ): Promise<Buffer> {
    try {
      const identifier = parseReference(reference);
      await this.ensureRoots();
      const path = join(this.valuesRoot, `${identifier}.value`);
      const metadata = await lstat(path);
      if (metadata.isSymbolicLink() || !metadata.isFile()) {
        throw new PrivateValueInvalidError();
      }
      const bytes = await readPrivateRegularFile(
        path,
        HEADER_LIMIT_BYTES + limitForKind(expectedKind) + 1,
      );
      const newline = bytes.indexOf(0x0a);
      if (newline < 1 || newline > HEADER_LIMIT_BYTES) {
        throw new PrivateValueInvalidError();
      }
      let headerValue: unknown;
      try {
        headerValue = JSON.parse(bytes.subarray(0, newline).toString("utf8"));
      } catch {
        throw new PrivateValueInvalidError();
      }
      if (!canonicalJsonBytes(headerValue).equals(bytes.subarray(0, newline))) {
        throw new PrivateValueInvalidError();
      }
      const header = parseHeader(headerValue, reference);
      const body = bytes.subarray(newline + 1);
      if (
        header.kind !== expectedKind ||
        header.size !== body.byteLength ||
        body.byteLength > limitForKind(expectedKind) ||
        sha256(body) !== header.digest
      ) {
        throw new PrivateValueInvalidError();
      }
      return Buffer.from(body);
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    }
  }

  private async clientHeader(
    reference: string,
    sessionId?: string,
  ): Promise<PrivateValueHeader> {
    try {
      if (typeof reference !== "string" || (sessionId !== undefined && !OPAQUE_ID_PATTERN.test(sessionId))) {
        throw new PrivateValueInvalidError();
      }
      const identifier = parseReference(reference);
      await this.ensureRoots();
      const path = join(this.valuesRoot, `${identifier}.value`);
      const bytes = await readPrivateRegularFile(
        path,
        HEADER_LIMIT_BYTES + limitForKind("client") + 1,
      );
      const newline = bytes.indexOf(0x0a);
      if (newline < 1 || newline > HEADER_LIMIT_BYTES) throw new PrivateValueInvalidError();
      const headerValue = JSON.parse(bytes.subarray(0, newline).toString("utf8"));
      if (!canonicalJsonBytes(headerValue).equals(bytes.subarray(0, newline))) throw new PrivateValueInvalidError();
      const header = parseHeader(headerValue, reference as PrivateValueRef);
      if (header.kind !== "client" || (sessionId !== undefined && header.sessionId !== sessionId)) {
        throw new PrivateValueInvalidError();
      }
      return header;
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  private async inspectContinuation(
    sessionPath: string,
  ): Promise<Readonly<{
    fileName: string;
    device: number;
    inode: number;
    size: number;
    digest: string;
  }>> {
    if (
      this.continuationRoot === undefined ||
      resolve(sessionPath) !== sessionPath ||
      dirname(sessionPath) !== this.continuationRoot.path ||
      basename(sessionPath) !== basename(resolve(sessionPath))
    ) {
      throw new PrivateValueInvalidError();
    }
    let descriptor: Awaited<ReturnType<typeof open>> | undefined;
    try {
      await this.assertContinuationRootIdentity();
      descriptor = await open(
        sessionPath,
        constants.O_RDONLY | constants.O_NOFOLLOW,
      );
      // Prime materializes a newly created transcript with the process default
      // mode.  The private store owns the pinned continuation and tightens that
      // already-open, no-follow file descriptor before accepting its identity.
      await descriptor.chmod(0o600);
      const metadata = await descriptor.stat();
      if (
        !metadata.isFile() ||
        (metadata.mode & 0o777) !== 0o600 ||
        metadata.size < 1 ||
        metadata.size > TRANSCRIPT_LIMIT_BYTES
      ) {
        throw new PrivateValueInvalidError();
      }
      const body = await descriptor.readFile();
      if (body.byteLength !== metadata.size) {
        throw new PrivateValueInvalidError();
      }
      return Object.freeze({
        fileName: basename(sessionPath),
        device: metadata.dev,
        inode: metadata.ino,
        size: body.byteLength,
        digest: sha256(body),
      });
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueInvalidError();
    } finally {
      await descriptor?.close().catch(() => undefined);
    }
  }

  private async assertContinuationRootIdentity(): Promise<void> {
    if (this.continuationRoot === undefined) {
      throw new PrivateValueInvalidError();
    }
    try {
      const rootMetadata = await lstat(this.continuationRoot.path);
      if (
        rootMetadata.isSymbolicLink() ||
        !rootMetadata.isDirectory() ||
        (rootMetadata.mode & 0o777) !== 0o700 ||
        rootMetadata.dev !== this.continuationRoot.device ||
        rootMetadata.ino !== this.continuationRoot.inode ||
        await realpath(this.continuationRoot.path) !==
          this.continuationRoot.realPath
      ) {
        throw new PrivateValueInvalidError();
      }
    } catch {
      throw new PrivateValueInvalidError();
    }
  }

  private async ensureRoots(): Promise<void> {
    try {
      await ensurePrivateDirectory(this.root);
      await ensurePrivateDirectory(this.privateRoot);
      await ensurePrivateDirectory(this.valuesRoot);
      await ensurePrivateDirectory(this.bindingsRoot);
    } catch (error) {
      if (error instanceof GatewayStoreCorruptionError) {
        throw new PrivateValueInvalidError();
      }
      throw error;
    }
  }

  private async serializeBinding<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.bindingQueue.then(operation);
    this.bindingQueue = result.then(
      () => undefined,
      () => undefined,
    );
    return result;
  }

  private async ensureBindingsRoot(): Promise<void> {
    try {
      await this.ensureRoots();
      await ensurePrivateDirectory(this.bindingsRoot);
    } catch (error) {
      if (error instanceof GatewayStoreCorruptionError) {
        throw new PrivateValueInvalidError();
      }
      throw error;
    }
  }

  private async syncBindingsRootForAcknowledgement(): Promise<void> {
    try {
      await this.ensureBindingsRoot();
      await syncPrivateDirectory(this.bindingsRoot, this.faultInjector);
      await this.ensureBindingsRoot();
    } catch (error) {
      if (error instanceof PrivateValueInvalidError) {
        throw error;
      }
      throw new PrivateValueWriteError();
    }
  }
}
